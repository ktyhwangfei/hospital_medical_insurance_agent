"""
医保政策问答RAG系统 - SSE流式API端点

端点: POST /api/v1/medical-insurance-ai-agent/policy-qa/stream
      GET  /api/v1/medical-insurance-ai-agent/policy-qa/history
"""

from __future__ import annotations

import json
import logging
import time as _time
from collections.abc import AsyncGenerator
from typing import Any

import asyncio
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.model_service.gateway import ModelGateway
from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
from src.runtime.policy_qa.models import PolicyQARequest, PolicyQAResponse
from src.runtime.policy_qa.runtime_bridge import get_runtime_bridge
from src.runtime.policy_qa.settlement_data_provider import (
    SettlementNotFoundError,
    create_settlement_data_provider,
)
from src.runtime.policy_qa.structured_policy_retriever import (
    retrieve_policy_evidence,
)
from src.config.production import MILVUS_HOST, MILVUS_PORT
from src.skill_infra.skill_router import route_question, get_assembler, get_skill_manifest
from src.runtime.policy_qa.persistence import (
    ensure_session_and_workflow,
    record_qa_task,
    record_step_task,
    finalize_workflow,
)
from src.runtime.infra_event.context import set_infra_context

logger = logging.getLogger(__name__)

router = APIRouter()

# 搜索引擎初始化超时（秒）：PolicyRulesSearchEngine 构造会加载 sentence-transformer
# embedding 模型（本地约 19-32s，含首次下载），超时需能容纳该加载；Milvus 未就绪时
# 快速降级不阻塞流式响应。失败后进入 120s 冷却，避免每轮重复等待。
# （注：_init_search_engine 已随旧编排器退役删除；结构化政策检索走 skill 查询计划，
#  由 structured_policy_retriever 直接连 Milvus，不加载 embedding 模型。）


def _sse_event(event_type: str, data: dict | str) -> str:
    """格式化SSE事件
    v2: 包含 public_message / detail / dual-view
    """
    if isinstance(data, dict):
        data_str = json.dumps(data, ensure_ascii=False)
    else:
        data_str = data
    return f'event: {event_type}\ndata: {data_str}\n\n'


# ── 防泄漏：禁止返回前端的字段 ────────────────────────────────────
_FORBIDDEN_KEYS = frozenset({
    "reasoning", "reasoning_content", "chain_of_thought", "thought",
    "scratchpad", "debug", "internal", "prompt", "messages",
    "raw_response", "tool_calls", "agent_trace",
})


def _sanitize(obj: dict) -> dict:
    """递归删除禁止字段，将内部数据写入日志"""
    result = {}
    for key, value in obj.items():
        key_lower = key.lower()
        if any(forbidden in key_lower for forbidden in _FORBIDDEN_KEYS):
            # 内部数据写入日志，不返回前端
            logger.debug(f'[SANITIZE] 已过滤字段: {key}')
            continue
        if isinstance(value, dict):
            result[key] = _sanitize(value)
        elif isinstance(value, list):
            result[key] = [
                _sanitize(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


async def _policy_qa_stream(
    request: PolicyQARequest,
) -> AsyncGenerator[str, None]:
    """
    政策问答SSE流式处理

    Args:
        request: 政策问答请求

    Yields:
        SSE事件字符串
    """
    print(f'[POLICY-QA] 开始处理请求: question={request.question[:30]}..., settlement_id={request.settlement_id}', flush=True)

    # ── 持久化：创建 session + workflow（失败不影响流式响应）──
    start_time = _time.time()
    user_id = request.user_id or "demo"
    role = request.role or "cashier"
    session_id = request.session_id or f"sess-{id(request)}"
    workflow_id = f"wf-{id(request)}"
    try:
        session_id, workflow_id = ensure_session_and_workflow(
            session_id=session_id,
            user_id=user_id,
            role=role,
            question=request.question,
            settlement_id=request.settlement_id,
        )
        logger.info(f"[PERSIST] 持久化完成: session_id={session_id}, workflow_id={workflow_id}")
    except Exception as e:
        logger.warning(f"Session/workflow creation failed (non-blocking): {e}")

    # 设置基础设施事件上下文（供 ModelGateway/McpTransport/SQLDataFetcher 使用）
    set_infra_context(
        session_id=session_id,
        workflow_id=workflow_id,
        user_id=user_id,
        role=role,
    )

    # ── Runtime 增强：上下文规划（Memory/Planner/Reasoning，失败降级不阻塞）──
    runtime_bridge = get_runtime_bridge()
    context_need = runtime_bridge.prepare_turn(
        session_id=session_id,
        question=request.question,
        settlement_id=request.settlement_id,
        user_id=user_id,
        role=role,
    )
    if context_need:
        yield _sse_event("context_need", _sanitize(context_need))

    # 累积结果用于 task 记录
    accumulated_steps: list[dict] = []
    
    try:
        # ── Skill 驱动：结算数据 provider（真实 SQL）+ 模型网关（来源标注）──
        # 旧编排器（PolicyQAOrchestrator）已退役：政策检索/计算/回答统一走 skill 策略引擎。
        provider = create_settlement_data_provider()
        model_gateway = None
        try:
            model_gateway = ModelGateway()
        except Exception as e:
            logger.warning(f'Model gateway init failed: {e}')
        explanation_generator = ExplanationGenerator(model_gateway=model_gateway)

        # 处理请求并 yield SSE 事件（Skill 驱动：五步流程）
        step_count = 0
        public_steps: list[dict] = []          # 累积公开步骤
        result_patient_view = ""               # 最终结果：患者视角
        result_office_view = ""                # 最终结果：院端视角
        result_policy_evidence: list[dict] = [] # 最终结果：政策依据（RAG）
        result_settlement_evidence: list[dict] = []  # 最终结果：结算数据溯源证据
        result_calculation_steps: list[dict] = []    # 最终结果：分段计算步骤
        import asyncio

        # v2 trace result tracking
        trace_run_id: str = ""
        trace_can_answer: bool = False
        trace_partial_answer: bool = False
        trace_can_answer_reason: str = ""
        trace_events_list: list[dict] = []
        trace_selected_skill_id: str = ""

        _loop = asyncio.get_event_loop()

        async def _yield_step(
            step_name: str,
            status: str,
            public_message: str = "",
            step_number: int = 0,
        ) -> AsyncGenerator[str, None]:
            """发送 step + trace_event（前端执行链路展示）。"""
            step_evt: dict[str, Any] = {"step": step_name, "status": status}
            if public_message:
                step_evt["public_message"] = public_message
            public_steps.append(step_evt)
            accumulated_steps.append(step_evt)
            yield _sse_event("step", _sanitize(step_evt))
            await asyncio.sleep(0)
            yield _sse_event("trace_event", _sanitize({
                "step_id": step_name,
                "step_name": step_name,
                "step_number": step_number,
                "status": status,
            }))
            await asyncio.sleep(0)

        # ═══ Step 1: intent_detection（关键词 → 目标费用项）═══
        _fee_item_keywords = [
            ("deductible", ["起付线", "起付标准", "门槛费"]),
            ("large_amount_self_pay", ["大额自付", "大额互助"]),
            ("pooling_payment", ["统筹支付", "统筹报销"]),
            ("personal_total_pay", ["个人总支付", "个人负担"]),
            ("pooling_self_pay", ["统筹自付", "基本统筹自付", "统筹段个人承担"]),
        ]
        target_fee_item = "pooling_self_pay"
        for _fi, _kws in _fee_item_keywords:
            if any(_kw in (request.question or "") for _kw in _kws):
                target_fee_item = _fi
                break
        async for _ev in _yield_step("intent_detection", "running", "识别问题意图…", 1):
            yield _ev
        async for _ev in _yield_step("intent_detection", "done", f"识别为「{target_fee_item}」费用解释", 1):
            yield _ev

        # ═══ Step 2: skill_routing（SkillRouter 路由到技能）═══
        skill_id = route_question(request.question) or "settlement_explain_skill"
        assembler = get_assembler(skill_id)
        if assembler is None:
            raise RuntimeError(f"Skill '{skill_id}' 未加载")
        trace_selected_skill_id = skill_id
        async for _ev in _yield_step("skill_routing", "running", "匹配技能…", 2):
            yield _ev
        async for _ev in _yield_step("skill_routing", "done", f"匹配技能: {skill_id}", 2):
            yield _ev

        # ═══ Step 3: settlement_query（真实结算数据）═══
        async for _ev in _yield_step("settlement_query", "running", "查询真实结算数据…", 3):
            yield _ev
        settlement_context = await provider.get_settlement_context(request.settlement_id)
        for _evt_type, _evt_payload in runtime_bridge.record_step(
            session_id=session_id,
            step="settlement_query",
            detail={
                "settlement_id": request.settlement_id,
                "total_fee": settlement_context.total_amount,
                "deductible": settlement_context.deductible,
                "basic_pooling_self_pay": settlement_context.basic_pooling_self_pay,
            },
            settlement_id=request.settlement_id,
        ):
            yield _sse_event(_evt_type, _sanitize(_evt_payload))
            await asyncio.sleep(0)
        async for _ev in _yield_step("settlement_query", "done", "结算数据获取完成", 3):
            yield _ev

        # ═══ Step 4: policy_rule_search（skill 查询计划 + 结构化检索）═══
        async for _ev in _yield_step("policy_rule_search", "running", "检索政策规则…", 4):
            yield _ev
        _normalized_ctx: dict[str, Any] = {
            "settlement_id": settlement_context.settlement_id,
            "insu_type": _normalize_insu_type(settlement_context.insurance_type or "城镇职工"),
            "med_type": _normalize_med_type(settlement_context.service_type or "普通住院"),
            "hosp_lv": settlement_context.hospital_level or "三级医院",
            "psn_type": settlement_context.person_type or "退休人员",
            "target_field": assembler._get_fee_field(target_fee_item),
            "target_amount": assembler._get_fee_amount(settlement_context, target_fee_item),
        }
        _custom_queries = assembler.build_policy_queries(target_fee_item)
        _retrieval_result = await _loop.run_in_executor(
            None,
            lambda: retrieve_policy_evidence(
                settlement_context=_normalized_ctx,
                host=MILVUS_HOST,
                port=str(MILVUS_PORT),
                custom_queries=_custom_queries,
            ),
        )
        policy_evidence: list[dict] = []
        for _ev in _retrieval_result.selected_evidence:
            policy_evidence.append({
                "title": _ev.source_text[:80] + "..." if len(_ev.source_text) > 80 else _ev.source_text,
                "clause": _ev.source_text,
                "evidence_text": _ev.source_text,
                "matched_reason": _ev.applied_reason or f"匹配规则类型: {_ev.rule_type}",
                "rule_type": _ev.rule_type,
                "score": _ev.score,
                "source_text": _ev.source_text,
                "payment_ratio": _ev.payment_ratio,
                "amount_band": _ev.amount_band,
                "rule_value": _ev.rule_value,
            })
        policy_status = "no_policy_matched"
        if not _retrieval_result.missing_required_rules and len(policy_evidence) >= 2:
            policy_status = "full_policy_matched"
        elif len(policy_evidence) > 0:
            policy_status = "partial_policy_matched"
        for _evt_type, _evt_payload in runtime_bridge.record_step(
            session_id=session_id,
            step="policy_rule_search",
            detail={"rules_count": len(policy_evidence), "policy_filters": []},
        ):
            yield _sse_event(_evt_type, _sanitize(_evt_payload))
            await asyncio.sleep(0)
        async for _ev in _yield_step(
            "policy_rule_search", "done",
            f"检索到 {len(policy_evidence)} 条政策规则" if policy_evidence else "未检索到匹配的政策规则",
            4,
        ):
            yield _ev

        # ═══ Step 5: skill_execution（skill 策略引擎执行）═══
        async for _ev in _yield_step("skill_execution", "running", "生成费用解释…", 5):
            yield _ev
        skill_result = await _loop.run_in_executor(
            None,
            lambda: assembler.execute(
                settlement_context=settlement_context,
                policy_evidence=policy_evidence,
                policy_status=policy_status,
                target_fee_item=target_fee_item,
            ),
        )
        for _evt_type, _evt_payload in runtime_bridge.record_step(
            session_id=session_id, step="answer_assembly", detail={},
        ):
            yield _sse_event(_evt_type, _sanitize(_evt_payload))
            await asyncio.sleep(0)
        async for _ev in _yield_step("skill_execution", "done", "费用解释生成完成", 5):
            yield _ev

        # ── 结果捕获（供 result 事件组装）──
        result_patient_view = skill_result.patient_answer or ""
        result_office_view = skill_result.office_answer or ""
        result_policy_evidence = policy_evidence
        result_settlement_evidence = []
        result_calculation_steps = []
        trace_can_answer = bool(result_patient_view)
        trace_partial_answer = False
        trace_can_answer_reason = skill_result.policy_status_message

        # ── 所有步骤完成：发送合并结果 ──
        logger.info(f'[POLICY-QA] 处理完成，发送 result 事件（共 {len(public_steps)} 个步骤）')

        # v2: 根据可回答性门控患者/院端视角
        if trace_can_answer or trace_partial_answer:
            result_views = {
                "patient_view": result_patient_view,
                "office_view": result_office_view,
            }
        else:
            result_views = {
                "patient_view": "",
                "office_view": "",
            }

        consolidated_result = _sanitize({
            "public_steps": public_steps,
            "result": {
                **result_views,
                "policy_evidence": result_policy_evidence,
                "settlement_evidence": result_settlement_evidence,
                "calculation_steps": result_calculation_steps,
                "can_answer": trace_can_answer,
                "partial_answer": trace_partial_answer,
                "can_answer_reason": trace_can_answer_reason,
                "trace_events": trace_events_list,
                "run_id": trace_run_id,
                "selected_skill_id": trace_selected_skill_id,
                # 回答来源（前端据此标注真实性）：llm（模型生成）/ dummy（降级模板）/ fallback
                "answer_mode": getattr(explanation_generator, "mode", "fallback"),
            },
        })
        # ── Runtime 增强：推理链与记忆计数附加到 result（在 _sanitize 之后，
        #    避免 reasoning_* 键被防泄漏过滤；该数据为策划后的公开契约）──
        runtime_extra = runtime_bridge.finalize_turn(
            session_id=session_id, question=request.question,
        )
        if runtime_extra and isinstance(consolidated_result.get("result"), dict):
            consolidated_result["result"].update(runtime_extra)
        yield _sse_event("result", consolidated_result)

        # ── 持久化：记录 task 并完成 workflow ──
        duration_ms = int((_time.time() - start_time) * 1000)
        try:
            record_qa_task(
                workflow_id=workflow_id,
                session_id=session_id,
                user_id=user_id,
                role=role,
                question=request.question,
                settlement_id=request.settlement_id,
                status="completed",
                output_data={
                    "can_answer": trace_can_answer,
                    "partial_answer": trace_partial_answer,
                    "patient_view": result_patient_view[:500] if result_patient_view else "",
                    "office_view": result_office_view[:500] if result_office_view else "",
                    "policy_evidence_count": len(result_policy_evidence),
                    "steps_count": len(public_steps),
                    "selected_skill_id": trace_selected_skill_id,
                    "run_id": trace_run_id,
                },
                duration_ms=duration_ms,
            )
            finalize_workflow(workflow_id, "completed", accumulated_steps or public_steps)
        except Exception as e:
            logger.warning(f"Failed to persist QA result: {e}")

        yield _sse_event("done", {"can_answer": trace_can_answer})

    except Exception as e:
        print(f'[POLICY-QA] 处理异常: {e}', flush=True)
        logger.exception("Policy QA stream failed")

        # ── 持久化：记录失败 ──
        try:
            duration_ms = int((_time.time() - start_time) * 1000)
            record_qa_task(
                workflow_id=workflow_id,
                session_id=session_id,
                user_id=user_id,
                role=role,
                question=request.question,
                settlement_id=request.settlement_id,
                status="failed",
                output_data={},
                error_message=str(e),
                duration_ms=duration_ms,
            )
            finalize_workflow(workflow_id, "failed", accumulated_steps)
        except Exception as pe:
            logger.warning(f"Failed to persist error state: {pe}")

        yield _sse_event("error", {"message": str(e)})
        yield _sse_event("done", {})


@router.post("/stream")
async def policy_qa_stream(request: PolicyQARequest) -> StreamingResponse:
    """
    政策问答SSE流式端点

    Args:
        request: 政策问答请求

    Returns:
        StreamingResponse: SSE流式响应
    """
    # 验证请求
    if not request.question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    if not request.settlement_id:
        raise HTTPException(status_code=400, detail="结算ID不能为空")

    # 返回SSE流式响应
    return StreamingResponse(
        _policy_qa_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/test")
async def policy_qa_test(request: PolicyQARequest) -> dict:
    """
    政策问答测试端点 (非流式)

    Args:
        request: 政策问答请求

    Returns:
        dict: 测试结果
    """
    # 验证请求
    if not request.question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    if not request.settlement_id:
        raise HTTPException(status_code=400, detail="结算ID不能为空")

    # 返回测试结果
    return {
        "status": "ok",
        "message": "政策问答测试端点",
        "request": {
            "question": request.question,
            "settlement_id": request.settlement_id,
            "session_id": request.session_id,
        },
    }


# ── 调试端点：结构化政策规则检索 ──────────────────────────────────

@router.get("/debug/structured-policy-search")
async def debug_structured_policy_search(
    settlement_id: str,
    target_field: str = "统筹自付",
) -> dict:
    """
    调试端点：展示结构化政策规则检索的完整过程。

    返回：
    - settlement_context: 真实结算数据上下文
    - normalized_policy_context: 标准化后的政策查询上下文
    - planned_queries: 规划的各组查询
    - structured_hits: 各组查询的命中结果
    - vector_fallback_hits: 向量兜底结果（当前未使用）
    - selected_policy_evidence: 最终选中的政策证据
    - missing_required_rules: 缺失的必需规则
    - dedupe_info: 去重信息
    """
    if not settlement_id:
        raise HTTPException(status_code=400, detail="settlement_id is required")

    try:
        provider = create_settlement_data_provider()
        context = await provider.get_settlement_context(settlement_id)

        # 构建标准化上下文
        normalized_ctx = {
            "settlement_id": context.settlement_id,
            "insu_type": _normalize_insu_type(context.insurance_type or "城镇职工"),
            "med_type": _normalize_med_type(context.service_type or "普通住院"),
            "hosp_lv": context.hospital_level or "三级医院",
            "psn_type": context.person_type or "退休人员",
            "target_field": target_field,
            "target_amount": context.basic_pooling_self_pay,
        }

        # 执行结构化检索
        retrieval_result = retrieve_policy_evidence(
            settlement_context=normalized_ctx,
            host=MILVUS_HOST,
            port=str(MILVUS_PORT),
        )

        # 序列化 selected_evidence
        selected_evidence = []
        for ev in retrieval_result.selected_evidence:
            selected_evidence.append({
                "evidence_id": ev.evidence_id,
                "source": ev.source,
                "query_name": ev.query_name,
                "policy_id": ev.policy_id,
                "clause_id": ev.clause_id,
                "rule_type": ev.rule_type,
                "insu_type": ev.insu_type,
                "med_type": ev.med_type,
                "hosp_lv": ev.hosp_lv,
                "psn_type": ev.psn_type,
                "source_text": ev.source_text,
                "rule_value": ev.rule_value,
                "payment_ratio": ev.payment_ratio,
                "amount_band": ev.amount_band,
                "rule_id": ev.rule_id,
                "rule_instance_key": ev.rule_instance_key,
                "applied_reason": ev.applied_reason,
                "score": ev.score,
            })

        return {
            "settlement_context": {
                "settlement_id": context.settlement_id,
                "insurance_type": context.insurance_type,
                "service_type": context.service_type,
                "hospital_level": context.hospital_level,
                "person_type": context.person_type,
                "basic_pooling_self_pay": context.basic_pooling_self_pay,
                "deductible": context.deductible,
                "yearly_cycle_count": context.yearly_cycle_count,
                "tables_queried": context.tables_queried,
                "query_profile": context.query_profile,
            },
            "normalized_policy_context": normalized_ctx,
            "planned_queries": retrieval_result.planned_queries,
            "structured_hits": retrieval_result.query_results,
            "vector_fallback_hits": [],
            "selected_policy_evidence": selected_evidence,
            "missing_required_rules": retrieval_result.missing_required_rules,
            "dedupe_info": retrieval_result.dedupe_info,
        }

    except SettlementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Debug structured policy search failed")
        raise HTTPException(status_code=503, detail=f'检索失败: {str(e)}')


# ── 解释生成辅助函数（从结算上下文构建双视角文本和计算链路）──

# ★ Milvus 字段标准化映射
# SQL CASE WHEN 返回的简称 vs Milvus 存储的全称
_INSURANCE_TYPE_EXPAND: dict[str, str] = {
    "城镇职工": "城镇职工基本医疗保险",
    "城乡居民": "城乡居民基本医疗保险",
    "工伤保险": "工伤保险",
    "离休统筹": "离休统筹",
    "公疗医照": "公疗医照",
}
_MEDICAL_TYPE_PREFIX: dict[str, str] = {
    "普通门诊": "门诊-普通门诊",
    "急诊": "门诊-急诊",
    "普通住院": "住院-普通住院",
    "单病种住院": "住院-单病种住院",
    "日间手术": "住院-日间手术",
    "生育住院": "住院-生育住院",
    "生育门诊": "门诊-生育门诊",
    "家庭病床": "住院-家庭病床",
    "药店购药": "药店购药",
}


def _normalize_insu_type(raw: str) -> str:
    """将 SQL 返回的险种简称映射到 Milvus 存储的全称。"""
    for short, full in _INSURANCE_TYPE_EXPAND.items():
        if short in raw:
            return full
    return raw


def _normalize_med_type(raw: str) -> str:
    """将 SQL 返回的医疗类别映射到 Milvus 存储格式 '住院-普通住院'。"""
    if raw in _MEDICAL_TYPE_PREFIX:
        return _MEDICAL_TYPE_PREFIX[raw]
    if raw.startswith("住院-") or raw.startswith("门诊-"):
        return raw
    return f'住院-{raw}'


# ── 解释生成 ──────────────────────────────────────────────────

def _fmt_money(value) -> str:
    """安全格式化金额：null/0/空 → '未获取'，否则千分位两位小数。"""
    if value is None or value == '' or (isinstance(value, (int, float)) and value == 0):
        return '未获取'
    try:
        return f'{float(value):,.2f}'
    except (ValueError, TypeError):
        return '未获取'


def _fmt_label(value, label: str) -> str:
    """格式化带标签的值，如 format_label(650, '元') → '650.00 元'，空值 → '未获取'。"""
    v = _fmt_money(value)
    if v == '未获取':
        return f'{label}：未获取'
    return f'{label} {v} 元'


def _clean_policy_excerpt(text: str) -> str:
    """清洗政策原文：移除 JSON 块（如 {"ratio": 0.85}）和多余空白，只保留可读文本。"""
    import re
    # 移除 JSON 块，如 {"ratio": 0.85} 或 {"expression": "...", "multiplier": 0.6}
    cleaned = re.sub(r'\n?\{[^}]*\}[\s\S]*$', '', text).strip()
    # 移除连续空行
    cleaned = re.sub(r'\n{2,}', '\n', cleaned)
    # 移除行首多余空白
    cleaned = '\n'.join(line.strip() for line in cleaned.split('\n') if line.strip())
    return cleaned

# ── 以下函数已迁移到 src/skills/benefit_pooling_self_pay/assembler.py ──
# _build_patient_answer, _build_office_answer, _extract_segment_ratios,
# _build_ratio_explanation, _build_explanation_completeness,
# _build_calculation_trace, _build_warnings
# 产品层不再包含统筹自付专属解释逻辑。


async def _process_single_settlement(settlement_id: str, question: str = "") -> dict:
    """提取单个结算单的完整处理流程，返回结果字典。

    同时用于单结算单模式和对比模式，保持两种模式的输出一致性。

    Returns:
        与 get_settlement_explanation 单结算单模式完全相同的返回结构

    Raises:
        HTTPException: settlement_id 不存在、skill 未匹配等
        SettlementNotFoundError: 结算数据在数据库中不存在
    """
    provider = create_settlement_data_provider()
    context = await provider.get_settlement_context(settlement_id)

    # ★ Skill 驱动架构：通过 SkillRouter 路由到对应 skill
    skill_id = route_question(question or "统筹自付")
    if skill_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"问题 '{question}' 未匹配到解释技能",
        )

    # 加载 skill assembler（通过动态加载器）
    assembler = get_assembler(skill_id)
    if assembler is None:
        raise HTTPException(status_code=500, detail=f"Skill '{skill_id}' not loaded")

    # ★ 推断目标费用项（关键词 → fee_item）
    _fee_item_keywords = [
        ("deductible", ["起付线", "起付标准", "门槛费"]),
        ("large_amount_self_pay", ["大额自付", "大额互助"]),
        ("pooling_payment", ["统筹支付", "统筹报销"]),
        ("personal_total_pay", ["个人总支付", "个人负担"]),
        ("pooling_self_pay", ["统筹自付", "基本统筹自付", "统筹段个人承担"]),
    ]
    target_fee_item = "pooling_self_pay"  # default
    for fee_item, keywords in _fee_item_keywords:
        if any(kw in (question or "") for kw in keywords):
            target_fee_item = fee_item
            break

    # ★ 结构化政策规则检索（使用 skill 定义的查询计划）
    policy_evidence: list[dict] = []
    policy_status = "no_policy_matched"
    try:
        # 构建标准化上下文 → 映射 SettlementContext 字段到 Milvus 字段名
        normalized_ctx: dict[str, Any] = {
            "settlement_id": context.settlement_id,
            "insu_type": _normalize_insu_type(context.insurance_type or "城镇职工"),
            "med_type": _normalize_med_type(context.service_type or "普通住院"),
            "hosp_lv": context.hospital_level or "三级医院",
            "psn_type": context.person_type or "退休人员",
            "target_field": assembler._get_fee_field(target_fee_item),
            "target_amount": assembler._get_fee_amount(context, target_fee_item),
        }
        logger.info(f'[settlement-explanation] Structured retrieval with: {normalized_ctx}')

        # 使用 skill 配置的查询计划（根据 target_fee_item 选择对应 Strategy）
        custom_queries = assembler.build_policy_queries(target_fee_item)

        retrieval_result = retrieve_policy_evidence(
            settlement_context=normalized_ctx,
            host=MILVUS_HOST,
            port=str(MILVUS_PORT),
            custom_queries=custom_queries,
        )

        # 组装 policy_evidence
        for ev in retrieval_result.selected_evidence:
            policy_evidence.append({
                "policy_title": ev.source_text[:80] + "..." if len(ev.source_text) > 80 else ev.source_text,
                "clause_text": ev.source_text,
                "source_text": ev.source_text,
                "rule_tags": [
                    ev.rule_type,
                    ev.insu_type,
                    ev.med_type,
                    ev.hosp_lv,
                    ev.psn_type,
                ],
                "matched_query": ev.query_name,
                "score": ev.score,
                "applied_reason": ev.applied_reason,
                "rule_id": ev.rule_id,
                "rule_type": ev.rule_type,
                "payment_ratio": ev.payment_ratio,
                "amount_band": ev.amount_band,
                "rule_value": ev.rule_value,
                "psn_type": ev.psn_type,
                "insu_type": ev.insu_type,
                "med_type": ev.med_type,
                "hosp_lv": ev.hosp_lv,
            })

        # 判断匹配状态（基于检索结果，不依赖硬编码解析逻辑）
        if not retrieval_result.missing_required_rules and len(policy_evidence) >= 2:
            policy_status = "full_policy_matched"
        elif len(policy_evidence) > 0:
            policy_status = "partial_policy_matched"

        logger.info(
            f'[settlement-explanation] Policy retrieval: {len(policy_evidence)} evidence, '
            f'status={policy_status}, missing={retrieval_result.missing_required_rules}, '
            f'dedup={retrieval_result.dedupe_info}'
        )

    except Exception as e:
        logger.exception(f'[settlement-explanation] Structured retrieval failed: {e}')
        policy_status = "no_policy_matched"

    # ★ Skill 驱动：通过 assembler 生成所有解释输出（统一处理所有费用类型）
    # A-重：语义层数据路径（开关 USE_SEMANTIC_LAYER_PATH=1 启用）
    # 把 SettlementContext 经 BusinessFactsBuilder（已发布版本锁定）转为 facts，
    # 再走 execute_via_registry；默认关闭，沿用 SQL 直连路径。
    import os
    if os.environ.get("USE_SEMANTIC_LAYER_PATH") == "1":
        from src.semantic_layer.settlement_bridge import build_settlement_facts
        facts = build_settlement_facts(context)
        skill_result = assembler.execute_via_registry(
            facts, question, target_fee_item=target_fee_item,
            policy_evidence=policy_evidence, policy_status=policy_status,
        )
    else:
        skill_result = assembler.execute(
            settlement_context=context,
            policy_evidence=policy_evidence,
            policy_status=policy_status,
            target_fee_item=target_fee_item,
        )

    # ★ 从 Manifest 读取前端展示配置，构建 profile / output_groups / display_config
    manifest = get_skill_manifest(skill_id) or {}
    display_config = manifest.get("display", {})

    profile = {}
    if "profile" in display_config:
        profile["title"] = display_config["profile"].get("title", "")
        profile["items"] = []
        for item in display_config["profile"].get("items", []):
            field = item.get("field", "")
            # field 为 SQL 列名（如 zyjyxx.rylb），需映射到 SettlementContext 属性名
            attr = assembler._FACT_FIELD_MAP.get(field, field)
            value = getattr(context, attr, "") or ""
            profile["items"].append({
                "label": item.get("label", field),
                "field": field,
                "value": value,
            })

    output_groups = []
    for group_def in display_config.get("output", []):
        group_entry = {"group": group_def.get("group", ""), "items": []}
        for item_def in group_def.get("items", []):
            field = item_def.get("field", "")
            # field 为 SQL 列名（如 zyfdxx.bdtczf），需映射到 SettlementContext 属性名
            attr = assembler._FACT_FIELD_MAP.get(field, field)
            value = getattr(context, attr, 0) or 0
            entry = {
                "label": item_def.get("label", field),
                "field": field,
                "value": value,
            }
            if "format" in item_def:
                entry["format"] = item_def["format"]
            if "hint" in item_def:
                entry["hint"] = item_def["hint"]
            if "highlight" in item_def:
                entry["highlight"] = item_def["highlight"]
            group_entry["items"].append(entry)
        output_groups.append(group_entry)

    return {
        "question": question or f'{assembler._get_fee_label(target_fee_item)}为什么是{_fmt_money(assembler._get_fee_amount(context, target_fee_item))}？',
        "answer_type": "benefit_calculation_explanation",
        "target_fee_item": target_fee_item,
        "target_field": assembler._get_fee_field(target_fee_item),
        "target_amount": assembler._get_fee_amount(context, target_fee_item),
        "data_source": "REAL_DB",
        "mock_used": False,
        "query_trace": {
            "settlement_id": context.settlement_id,
            "tables": context.tables_queried,
            "sql_profile": context.query_profile,
        },
        "definition": skill_result.definition,
        "case_context": {
            "person_type": context.person_type,
            "insurance_type": context.insurance_type,
            "service_type": context.service_type,
            "hospital_level": context.hospital_level,
            "deductible": context.deductible,
            "yearly_cycle_count": context.yearly_cycle_count,
            "basic_pooling_payment": context.basic_pooling_payment,
            "basic_pooling_self_pay": context.basic_pooling_self_pay,
            "large_amount_payment": context.large_amount_payment,
            "large_amount_self_pay": context.large_amount_self_pay,
            "personal_total_pay": context.personal_total_pay,
        },
        "policy_evidence": policy_evidence,
        "policy_status": skill_result.policy_status,
        "policy_warning": skill_result.policy_status_message,
        "calculation_trace": skill_result.calculation_trace,
        "patient_answer": skill_result.patient_answer,
        "office_answer": skill_result.office_answer,
        "ratio_explanation": skill_result.ratio_explanation,
        "explanation_completeness": skill_result.explanation_completeness,
        "warnings": skill_result.warnings,
        "mode": "single",
        "profile": profile,
        "output_groups": output_groups,
        "display_config": display_config,
    }


@router.get("/settlement-explanation")
async def get_settlement_explanation(
    settlement_id: str,
    question: str = "",
    compare_with: str = "",
) -> dict:
    """
    GET settlement explanation from REAL DATABASE.

    Query real SQL Server for settlement context using the existing
    settlement_context SQL.  Never uses mock data — errors propagate clearly.

    When `compare_with` is provided, returns a comparison between two
    settlement explanations side by side.

    Args:
        settlement_id: 登记号 from the settlement system (required)
        question: optional user question for additional context
        compare_with: 对比结算单号 — when provided, returns comparison mode

    Returns:
        Structured explanation result with:
          - data_source: always "REAL_DB"
          - mock_used: always False
          - query_trace: settlement_id, tables queried, SQL profile name
          - case_context: all normalized settlement fields
          - policy_evidence: (empty, for future RAG integration)
          - calculation_trace: (empty, for future calculation steps)
          - patient_answer / office_answer: (empty, for future LLM generation)
          - warnings: data quality notes
          When compare_with is set:
          - mode: "compare"
          - comparison: { primary: {...}, secondary: {...} }

    Raises:
        HTTPException 400: missing settlement_id or compare_with equals settlement_id
        HTTPException 404: settlement_id / compare_with not found in DB
        HTTPException 503: DB connection/query failure
    """
    if not settlement_id:
        raise HTTPException(status_code=400, detail="settlement_id is required")

    if compare_with and compare_with == settlement_id:
        raise HTTPException(
            status_code=400,
            detail="对比结算单号不能与主结算单号相同",
        )

    try:
        # ── Single settlement mode (original behavior) ──
        if not compare_with:
            return await _process_single_settlement(settlement_id, question)

        # ── Comparison mode ──
        primary = await _process_single_settlement(settlement_id, question)
        secondary = await _process_single_settlement(compare_with, question)

        return {
            **primary,
            "mode": "compare",
            "comparison": {
                "primary": primary,
                "secondary": secondary,
            },
        }

    except SettlementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        # Raised when DATA_SOURCE_MODE != "real_db"
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Settlement explanation query failed")
        raise HTTPException(status_code=503, detail=f'真实数据库查询失败: {str(e)}')


# ── 问答历史端点 ──────────────────────────────────────────────

@router.get("/history")
async def get_qa_history(
    user_id: str | None = Query(None, description="按用户ID过滤（不传则返回全部）"),
    limit: int = Query(50, ge=1, le=500, description="每页条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
) -> dict:
    """
    获取政策问答历史记录（含全量 session、workflow、task 数据）。

    默认返回全部用户的记录。
    """
    from src.runtime.policy_qa.history_service import get_qa_history as _get_history
    try:
        return _get_history(user_id=user_id, limit=limit, offset=offset)
    except Exception as e:
        logger.exception("Failed to get QA history")
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}")

