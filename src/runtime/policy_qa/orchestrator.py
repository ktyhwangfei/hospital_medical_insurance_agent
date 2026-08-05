"""
医保政策问答RAG系统 - 编排器（适配器驱动）

串联6个步骤（通过 adapter + skill 配置路由）:
0. 意图识别 (LLM, 非流式)
1. SQL 查询 via adapter (MCP类型)
2. 政策检索 via adapter (KNOWLEDGE类型)
3. 计算 via config.yaml 路由 (SKILL类型)
4. 单答案解释生成
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import yaml

# 加载 skill 包
_skill_dir = Path(__file__).parent.parent.parent.parent / "skills"
if str(_skill_dir) not in sys.path:
    sys.path.insert(0, str(_skill_dir))

from src.model_service.gateway import ModelGateway
from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
from src.runtime.policy_qa.intent_detector import IntentDetector
from src.runtime.policy_qa.fee_item_detector import FeeItemDetector
from src.runtime.policy_qa.models import (
    EvidenceItem,
    ExplanationContext,
    FeeCategory,
    FeeDecomposition,
    FeeDecompositionResult,
    PolicyQAIntent,
    PolicyQAIntentResult,
    PolicyQARequest,
    PolicyQAResponse,
    PolicyRule,
    RewrittenQuestion,
    SegmentCalculationResult,
    SegmentInfo,
    SQLQueryResult,
    TreatmentDecomposition,
    TreatmentItem,
)
from src.runtime.policy_qa.question_rewriter import QuestionRewriter
from src.runtime.policy_qa.sql_data_fetcher import SQLDataFetcher

# v2: TraceEventBuilder, SkillRouter, 新模型
from settlement_explain_skill.scripts.build_trace_event import TraceEventBuilder
from src.skill_infra.skill_router import route_question

from src.runtime.policy_qa.models import (
    AnswerabilityResult,
    PolicyQARunStatus,
    PolicyQATraceResponse,
    TraceEvent,

    make_answerability,
    make_trace_event,
)

logger = logging.getLogger(__name__)


def _load_skill_config() -> dict:
    """从 skill 包加载费用路由配置"""
    config_path = _skill_dir / "settlement_explain_skill" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_calculators() -> dict:
    """从 skill 包加载计算器注册表"""
    from settlement_explain_skill.calculator import CALCULATOR_REGISTRY
    return CALCULATOR_REGISTRY


def _build_decomposition_from_dict(data: dict) -> "FeeDecompositionResult":
    """从计算器返回的 dict 构建 FeeDecompositionResult（供 generate_answer 使用）。"""
    treatment_data = data.get("treatment", {})
    treatment = TreatmentDecomposition(
        total_fee=TreatmentItem(value=float(treatment_data.get("total_fee", 0))),
        in_scope=TreatmentItem(value=float(treatment_data.get("in_scope", 0))),
        deductible=TreatmentItem(value=float(treatment_data.get("deductible", 0))),
        pooling_self_pay=TreatmentItem(value=float(treatment_data.get("pooling_self_pay", 0))),
        pooling_payment=TreatmentItem(value=float(treatment_data.get("pooling_payment", 0))),
        major_payment=TreatmentItem(value=float(treatment_data.get("major_payment", 0))),
        major_self_pay=TreatmentItem(value=float(treatment_data.get("major_self_pay", 0))),
        personal_liability=TreatmentItem(value=float(treatment_data.get("personal_liability", 0))),
        out_of_scope=TreatmentItem(value=float(treatment_data.get("out_of_scope", 0))),
    )

    fees_data = data.get("fees", {})
    categories = [
        FeeCategory(
            category=str(cat.get("category", "")),
            total_amount=float(cat.get("total_amount", 0)),
            in_scope_amount=float(cat.get("in_scope_amount", 0)),
            out_of_scope_amount=float(cat.get("out_of_scope_amount", 0)),
        )
        for cat in fees_data.get("categories", [])
    ]
    fees = FeeDecomposition(
        total_amount=float(fees_data.get("total_amount", 0)),
        in_scope_total=float(fees_data.get("in_scope_total", 0)),
        out_of_scope_total=float(fees_data.get("out_of_scope_total", 0)),
        categories=categories,
    )

    segments_data = data.get("segments", {})
    segment_infos = [
        SegmentInfo(
            lower=float(seg.get("lower", 0)),
            upper=float(seg.get("upper", 0)),
            amount=float(seg.get("amount", 0)),
            base_ratio=float(seg.get("base_ratio", 0)),
            person_ratio=float(seg.get("person_ratio", 0)),
            actual_ratio=float(seg.get("actual_ratio", 0)),
            pay=float(seg.get("pay", 0)),
            calculation=str(seg.get("calculation", "")),
            rule_id=str(seg.get("rule_id", "")),
            policy_source=str(seg.get("policy_source", "")),
        )
        for seg in segments_data.get("segments", [])
    ]
    segments = SegmentCalculationResult(
        segments=segment_infos,
        total_pay=float(segments_data.get("total_pay", 0)),
        authoritative_amount=segments_data.get("authoritative_amount"),
        reconciliation_difference=segments_data.get("reconciliation_difference"),
        reconciliation_tolerance=float(segments_data.get("reconciliation_tolerance", 0.01)),
        reconciliation_matched=segments_data.get("reconciliation_matched"),
        reconciliation_message=str(segments_data.get("reconciliation_message", "")),
        warnings=list(segments_data.get("warnings", [])),
    )

    evidence_items = data.get("evidence", []) or []
    evidence = [
        EvidenceItem(
            item=str(e.get("item", "")),
            value=float(e.get("value", 0)),
            source_table=str(e.get("source_table", "")),
            source_field=str(e.get("source_field", "")),
            policy_rule=e.get("policy_rule", {}),
            calculation=e.get("calculation", {}),
        )
        for e in evidence_items
    ]

    return FeeDecompositionResult(
        treatment=treatment,
        fees=fees,
        segments=segments,
        evidence=evidence,
    )


class PolicyQAOrchestrator:
    """
    政策问答编排器

    串联6个步骤，yield SSE事件
    """

    def __init__(
        self,
        model_gateway: ModelGateway,
        sql_fetcher: SQLDataFetcher | None = None,
        question_rewriter: QuestionRewriter | None = None,
        search_engine: Any | None = None,  # MilvusPolicyRetriever
        fee_skill: FeeDecompositionSkill | None = None,
        explanation_generator: ExplanationGenerator | None = None,
    ):
        self.model_gateway = model_gateway
        self.sql_fetcher = sql_fetcher
        self.question_rewriter = question_rewriter
        self.search_engine = search_engine
        self.fee_skill = fee_skill
        self.explanation_generator = explanation_generator
        # 意图识别器（使用模型网关）
        self.intent_detector = IntentDetector(model_gateway=model_gateway)

        # ★ 新增：加载 skill 配置和计算器
        self.skill_config = _load_skill_config()
        self.calculators = _load_calculators()

        # ★ 新增：初始化适配器
        from src.runtime.policy_qa.tool_adapters import (
            SqlQueryAdapter, PolicySearchAdapter, LlmExplainAdapter,
        )
        self.adapters = {
            "sql": SqlQueryAdapter(sql_fetcher),
            "policy": PolicySearchAdapter(search_engine),
            "llm": LlmExplainAdapter(explanation_generator),
        }

    # ── v2: 可回答性判断 ──────────────────────────────────────────

    @staticmethod
    def build_answerability(
        sql_data: Any,
        skill_policy_rules: list[Any],
        intent_result: PolicyQAIntentResult,
    ) -> AnswerabilityResult:
        """
        可回答性判断

        检查以下维度:
        - has_real_settlement_data: 有真实结算数据（total_fee > 0）
        - has_basic_pooling_self_pay: 有统筹自付金额
        - has_basic_pooling_payment: 有统筹支付金额
        - has_deductible: 有起付线金额
        - has_large_amount_self_pay: 有大额自付金额
        - has_policy_rules_for_segment_ratios: 有分段/支付比例政策规则
        - has_retiree_factor: 有退休人员优惠因子

        Returns:
            AnswerabilityResult: 可回答性判断结果
        """
        treatment = getattr(sql_data, 'treatment', {}) or {}

        has_real_settlement_data = bool(treatment.get('total_fee', 0) > 0)
        has_basic_pooling_self_pay = treatment.get('pooling_self_pay') is not None
        has_basic_pooling_payment = treatment.get('pooling_payment') is not None
        has_deductible = treatment.get('deductible') is not None
        has_large_amount_self_pay = treatment.get('major_self_pay') is not None

        has_policy_rules_for_segment_ratios = any(
            '分段' in (getattr(r, 'rule_type', '') or '')
            or '支付比例' in (getattr(r, 'rule_type', '') or '')
            for r in (skill_policy_rules or [])
        )
        has_retiree_factor = any(
            '退休' in (getattr(r, 'matched_reason', '') or '')
            for r in (skill_policy_rules or [])
        )

        checks: dict[str, bool] = {
            "has_real_settlement_data": has_real_settlement_data,
            "has_basic_pooling_self_pay": has_basic_pooling_self_pay,
            "has_basic_pooling_payment": has_basic_pooling_payment,
            "has_deductible": has_deductible,
            "has_large_amount_self_pay": has_large_amount_self_pay,
            "has_policy_rules_for_segment_ratios": has_policy_rules_for_segment_ratios,
            "has_retiree_factor": has_retiree_factor,
        }

        missing_items = [k for k, v in checks.items() if not v]

        if not has_real_settlement_data:
            return make_answerability(
                can_answer=False,
                partial_answer=False,
                reason="缺少真实结算数据，无法回答",
                missing_items=missing_items,
                checks=checks,
            )

        if len(missing_items) == 0:
            return make_answerability(
                can_answer=True,
                partial_answer=False,
                reason="所有必要数据完整，可以完整回答",
                missing_items=[],
                checks=checks,
            )
        elif len(missing_items) <= 3:
            return make_answerability(
                can_answer=True,
                partial_answer=True,
                reason=f"部分数据缺失（{len(missing_items)}项），可以部分回答",
                missing_items=missing_items,
                checks=checks,
            )
        else:
            return make_answerability(
                can_answer=False,
                partial_answer=True,
                reason=f"重要数据缺失（{len(missing_items)}项），无法完整回答",
                missing_items=missing_items,
                checks=checks,
            )

    # ── v2: 政策证据完整性判断 ────────────────────────────────────

    @staticmethod
    def build_evidence_completeness(
        sql_data: Any,
        skill_policy_rules: list[Any],
    ) -> dict[str, Any]:
        """
        政策证据完整性判断

        检查:
        - has_segment_ratio: 政策规则包含分段/支付比例规则
        - has_retiree_factor: 政策包含退休人员优惠因子
        - has_segment_amount_detail: 结算数据包含分段金额详情

        Returns:
            dict: { level, has_segment_ratio, has_retiree_factor, has_segment_amount_detail, checks_passed, total_checks }
        """
        has_segment_ratio = False
        has_retiree_factor = False

        for rule in (skill_policy_rules or []):
            rule_type = getattr(rule, 'rule_type', '') or ''
            matched_reason = getattr(rule, 'matched_reason', '') or ''

            if '分段' in rule_type or '支付比例' in rule_type:
                has_segment_ratio = True
            if '退休' in matched_reason or '退休' in rule_type:
                has_retiree_factor = True

        has_segment_amount_detail = False
        if hasattr(sql_data, 'treatment') and sql_data.treatment:
            treatment = sql_data.treatment
            if treatment.get('pooling_self_pay') or treatment.get('pooling_payment'):
                has_segment_amount_detail = True

        checks_passed = sum([has_segment_ratio, has_retiree_factor, has_segment_amount_detail])
        if checks_passed == 3:
            level = "full"
        elif checks_passed >= 1:
            level = "partial"
        else:
            level = "none"

        return {
            "level": level,
            "has_segment_ratio": has_segment_ratio,
            "has_retiree_factor": has_retiree_factor,
            "has_segment_amount_detail": has_segment_amount_detail,
            "checks_passed": checks_passed,
            "total_checks": 3,
        }

    # ── v2: 输出校验 ──────────────────────────────────────────────

    @staticmethod
    def _validate_output(
        answer: str,
        policy_rules: list[Any],
    ) -> dict[str, Any]:
        """
        校验单答案的禁止内容，以及政策引用或不确定性声明。
        """
        import re
        errors: list[str] = []
        warnings_list: list[str] = []
        text = answer or ""

        if not text.strip():
            errors.append("答案为空")

        # 禁止内容：模拟数据、原始 JSON、未替换模板和无效字面量。
        mock_indicators = ["模拟数据", "mock", "示例数据", "仅供演示"]
        has_mock = any(i in text for i in mock_indicators)
        if has_mock:
            errors.append("输出包含模拟数据标记")

        stripped = text.strip()
        json_like_chars = sum(1 for c in stripped[:300] if c in ('"', "'", ":", ","))
        has_raw_json = stripped.startswith("{") and json_like_chars > 25
        if has_raw_json:
            errors.append("输出疑似包含原始 JSON 数据")

        template_patterns = re.findall(r'\$\{[^}]+\}|{{[^}]+}}', text)
        has_template_leak = len(template_patterns) > 0
        if has_template_leak:
            errors.append(f"输出包含 {len(template_patterns)} 个未替换模板变量")

        undefined_patterns = re.findall(r'\b(undefined|null|NaN)\b', text, re.IGNORECASE)
        has_undefined = len(undefined_patterns) > 0
        if has_undefined:
            errors.append("输出包含 undefined/null/NaN")

        policy_evidence_used = len(policy_rules or []) > 0
        has_policy_reference = any(
            getattr(rule, "source_text", "") or getattr(rule, "evidence_text", "")
            for rule in (policy_rules or [])
        )
        uncertainty_keywords = [
            "不确定性",
            "未检索到",
            "无法可靠确认",
            "无法基于",
            "建议核对",
            "建议咨询",
            "仅供参考，不作为",
        ]
        has_uncertainty = any(kw in text for kw in uncertainty_keywords)
        if text and not (has_policy_reference or has_uncertainty):
            errors.append("答案缺少可核验政策来源或明确不确定性声明")

        if policy_evidence_used and not has_policy_reference:
            warnings_list.append("政策规则缺少来源文本")

        fatal = len(errors) > 0
        passed = not fatal

        return {
            "passed": passed,
            "fatal": fatal,
            "errors": errors,
            "warnings": warnings_list,
            "warning_count": len(warnings_list),
            "policy_evidence_used": policy_evidence_used,
            "has_mock_data": has_mock,
            "has_template_leak": has_template_leak,
            "has_undefined": has_undefined,
            "no_raw_json": not has_raw_json,
            "answer_has_policy_reference": has_policy_reference,
            "answer_has_uncertainty": has_uncertainty,
        }

    # ── v2: TraceEvent 转换 ───────────────────────────────────────

    @staticmethod
    def _convert_trace_events(events: list[dict[str, Any]]) -> list[TraceEvent]:
        """将 TraceEventBuilder 导出的 dict 列表转为模型 TraceEvent 列表。"""
        result: list[TraceEvent] = []
        for e in events:
            status = e.get("status", "pending")
            # builder 的 'done' → 模型的 'success'（除非外部已覆盖为 warning）
            if status == "done":
                status = "success"
            result.append(make_trace_event(
                step_id=e.get("step_id", ""),
                step_name=e.get("step_name", ""),
                status=status,
                summary=e.get("detail", ""),
                details=e.get("data", {}),
                duration_ms=e.get("duration_ms", 0.0),
                error=e.get("error"),
            ))
        return result

    async def process(
        self,
        request: PolicyQARequest,
    ) -> AsyncGenerator[PolicyQAResponse, None]:
        """
        处理政策问答请求，yield SSE事件（v2: 8步骤 + TraceEventBuilder + answerability 门控）

        Args:
            request: 政策问答请求

        Yields:
            PolicyQAResponse: SSE事件
        """
        builder = TraceEventBuilder()
        # 跨步骤共享的状态
        intent_result: PolicyQAIntentResult | None = None
        skill_id: str = ""
        sql_data: Any = None
        skill_policy_rules: list[Any] = []
        route_config: dict[str, Any] = {}
        policy_filters: list[str] = []
        answer: str = ""
        answer_status: str = "unavailable"
        answerability: AnswerabilityResult | None = None
        sub_flow: str = ""

        try:
            # ═══════════════════════════════════════════════════════════
            # Step 1: intent_detection（意图识别）
            # ═══════════════════════════════════════════════════════════
            _evt = builder.start("intent_detection", "意图识别")
            yield PolicyQAResponse(
                step="intent_detection", status="running",
                public_message="正在识别问题意图",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": "running"},
            )

            intent_result = await self._detect_intent(request)

            # ★ 置信度门控：LLM 失败时降级到关键词的结果 confidence ≤ 0.6
            # 记录警告到 trace_event，但不阻断流程（关键词匹配是合法的降级路径）
            intent_from_fallback = intent_result.confidence <= 0.6

            # ★ 用 FeeItemDetector 补充识别 target_fee_item（当 LLM/关键词未设置时）
            fee_info = FeeItemDetector.detect(request.question)
            if fee_info and not intent_result.target_fee_item:
                intent_result.target_fee_item = fee_info["target_field"]
                intent_result.target_fee_label = fee_info["target_fee_item"]
            # 根据 target_field 决定子流程
            target_field = intent_result.target_fee_item or ""
            sub_flow_map = {
                "pooling_self_pay": "pooling_self_pay_flow",
                "deductible": "deductible_flow",
                "large_amount_self_pay": "large_amount_self_pay_flow",
                "personal_total_pay": "personal_total_pay_flow",
            }
            sub_flow = sub_flow_map.get(target_field, "generic_fee_flow")

            _evt = builder.done(
                detail=f"识别为「{intent_result.query_type or '费用分解'}」问题"
                       f"{'（关键词降级）' if intent_from_fallback else ''}",
                data={
                    "intent": intent_result.intent.value,
                    "settlement_id": intent_result.settlement_id,
                    "confidence": intent_result.confidence,
                    "query_type": intent_result.query_type,
                    "llm_failed": intent_from_fallback,
                    "fallback_used": intent_from_fallback,
                },
            )
            yield PolicyQAResponse(
                step="intent_detection", status="done",
                detail={
                    "intent": intent_result.intent.value,
                    "settlement_id": intent_result.settlement_id,
                    "confidence": intent_result.confidence,
                    "query_type": intent_result.query_type,
                    "target_fee_item": intent_result.target_fee_item,
                    "target_fee_label": intent_result.target_fee_label,
                    "sub_flow": sub_flow,
                },
                public_detail={
                    "summary": f"识别为「{intent_result.query_type or '费用分解'}」问题",
                    "confidence": intent_result.confidence,
                },
                public_message=f"检测到「{intent_result.query_type or '费用分解'}」问题",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": _evt.status, "duration_ms": _evt.duration_ms, "detail": _evt.detail},
            )

            # ═══════════════════════════════════════════════════════════
            # Step 2: skill_routing（Skill 匹配）
            # ═══════════════════════════════════════════════════════════
            _evt = builder.start("skill_routing", "Skill 匹配")
            yield PolicyQAResponse(
                step="skill_routing", status="running",
                public_message="正在匹配技能",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": "running"},
            )

            skill_id = route_question(request.question) or "settlement_explain_skill"

            _evt = builder.done(
                detail=f"命中医保费用解释 Skill：{skill_id}",
                data={
                    "selected_skill_id": skill_id,
                    "skill_path": f"skills/{skill_id}/SKILL.md",
                    "matched_fee_item": intent_result.target_fee_label or "统筹自付",
                    "target_field": intent_result.target_fee_item or "basic_pooling_self_pay",
                    "skill_flow": [
                        "费用字段识别",
                        "结算数据查询",
                        "政策查询计划",
                        "结构化政策查询",
                        "证据完整性判断",
                        "可回答性判断",
                        "单答案解释生成",
                        "输出校验",
                    ],
                },
            )
            yield PolicyQAResponse(
                step="skill_routing", status="done",
                detail={"skill_id": skill_id, "matched": skill_id != ""},
                public_detail={"skill_id": skill_id, "summary": f"匹配到「{skill_id}」技能"},
                public_message=f"已匹配技能: {skill_id}",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": _evt.status, "duration_ms": _evt.duration_ms, "detail": _evt.detail},
            )

            # ═══════════════════════════════════════════════════════════
            # Step 3: settlement_query（真实结算数据查询）
            # ═══════════════════════════════════════════════════════════
            _evt = builder.start("query_sql_data", "真实结算数据查询")
            yield PolicyQAResponse(
                step="settlement_query", status="running",
                public_message="正在查询患者结算数据",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": "running"},
            )

            sql_data = await self.adapters["sql"].query(intent_result.settlement_id)

            # 从 sql_data 提取关键字段
            treatment = getattr(sql_data, 'treatment', {}) or {}
            key_fields = {
                "deductible": treatment.get("deductible", 0),
                "basic_pooling_payment": treatment.get("pooling_payment", 0),
                "basic_pooling_self_pay": treatment.get("pooling_self_pay", 0),
                "large_amount_self_pay": treatment.get("major_self_pay", 0),
                "personal_total_pay": treatment.get("personal_liability", 0),
            }

            _evt = builder.done(
                detail=f"已从真实数据库查询5张表，获取统筹自付等关键字段",
                data={
                    "data_source": "REAL_DB",
                    "mock_used": False,
                    "settlement_id": intent_result.settlement_id,
                    "table_count": 5,
                    "tables": [
                        "yb_zyfdxx",
                        "yb_dyxxzy",
                        "yb_dyxxnd",
                        "yb_brdjxx",
                        "yb_zyjyxx",
                    ],
                    "key_fields": key_fields,
                },
            )
            yield PolicyQAResponse(
                step="settlement_query", status="done",
                detail={
                    "settlement_id": intent_result.settlement_id,
                    "tables": ["yb_zyfdxx", "yb_zyfymx", "yb_dyxxnd", "yb_dyxxzy", "yb_brdjxx"],
                },
                public_detail={"summary": "已查询患者结算数据与费用明细"},
                public_message="已获取结算数据与费用明细",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": _evt.status, "duration_ms": _evt.duration_ms, "detail": _evt.detail},
            )

            # ═══════════════════════════════════════════════════════════
            # Step 4: policy_rule_search（结构化政策规则查询）
            # ═══════════════════════════════════════════════════════════
            _evt = builder.start("structured_policy_query", "结构化政策规则查询")
            yield PolicyQAResponse(
                step="policy_rule_search", status="running",
                public_message="正在检索相关政策规则",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": "running"},
            )

            fee_item = intent_result.target_fee_item
            routes = self.skill_config.get("fee_explanation_routes", {})
            route_config = routes.get(fee_item) or self.skill_config.get("default_route", {})
            policy_filters = route_config.get("policy_filters", [])

            skill_policy_rules = await self.adapters["policy"].search(
                query=request.question,
                filters=policy_filters,
                top_k=10,
                patient_info={
                    "fund_type": sql_data.patient_info.get("fund_type", ""),
                    "person_type": sql_data.patient_info.get("person_type", ""),
                    "medical_type": sql_data.patient_info.get("medical_type", ""),
                } if hasattr(sql_data, 'patient_info') else None,
            )

            # 构建选用规则摘要（规则类型 + 支付比例信息）
            selected_summary = []
            for r in (skill_policy_rules or [])[:5]:
                rule_type = getattr(r, 'rule_type', '') or ''
                ratio = getattr(r, 'payment_ratio', '') or ''
                title = getattr(r, 'title', '') or ''
                source = getattr(r, 'source_text', '') or ''
                text = title or source
                if ratio:
                    text = f"{text}（{ratio}）" if text else ratio
                if text and len(text) > 80:
                    text = text[:80] + "…"
                if text:
                    selected_summary.append(text)

            _evt = builder.done(
                detail=f"检索到 {len(skill_policy_rules)} 条候选政策规则，最终选用 {len(selected_summary)} 条核心证据",
                data={
                    "candidate_count": len(skill_policy_rules),
                    "selected_evidence_count": len(selected_summary),
                    "selected_policy_summary": selected_summary,
                },
            )
            yield PolicyQAResponse(
                step="policy_rule_search", status="done",
                detail={"rules_count": len(skill_policy_rules)},
                public_detail={
                    "summary": f"已检索到 {len(skill_policy_rules)} 条相关政策规则",
                    "rules_count": len(skill_policy_rules),
                    "rag_miss": len(skill_policy_rules) == 0,
                    "policy_filters": policy_filters,
                },
                public_message=f"检索到 {len(skill_policy_rules)} 条政策规则" if skill_policy_rules else "未检索到匹配的政策规则，将基于结算数据解释",
                policy_cards=[
                    {
                        "title": r.title or f"[{r.rule_type}] {r.clause}",
                        "clause": r.clause or "",
                        "evidence_text": r.evidence_text or "",
                        "matched_reason": r.matched_reason or f"匹配规则类型: {r.rule_type}",
                        "rule_type": r.rule_type,
                        "score": r.score,
                    }
                    for r in skill_policy_rules
                ],
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": _evt.status, "duration_ms": _evt.duration_ms, "detail": _evt.detail},
            )

            # ═══════════════════════════════════════════════════════════
            # Step 5: evidence_completeness_check（政策证据完整性判断）
            # ═══════════════════════════════════════════════════════════
            _evt = builder.start("completeness_judgment", "政策证据完整性判断")
            yield PolicyQAResponse(
                step="evidence_completeness_check", status="running",
                public_message="正在判断证据完整性",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": "running"},
            )

            completeness = self.build_evidence_completeness(sql_data, skill_policy_rules)

            policy_core_matched = completeness["checks_passed"] >= 1
            recalculation_ready = completeness["level"] == "full"

            _evt = builder.done(
                detail="核心政策规则已匹配" if policy_core_matched else "政策规则匹配不完整",
                data={
                    "policy_core_rules_matched": policy_core_matched,
                    "has_segment_ratio_policy": completeness["has_segment_ratio"],
                    "has_retiree_factor_policy": completeness["has_retiree_factor"],
                    "has_segment_amount_detail": completeness["has_segment_amount_detail"],
                    "policy_explanation_level": "policy_core_rules_matched" if policy_core_matched else "insufficient_policy",
                    "recalculation_level": "fully_recalculated" if recalculation_ready else "not_fully_recalculated",
                    "message": (
                        "已具备政策口径解释和逐段复算能力"
                        if recalculation_ready
                        else "已具备政策口径解释能力；如需逐段复算，还需要分段进入金额明细。"
                    ),
                },
            )
            yield PolicyQAResponse(
                step="evidence_completeness_check", status="done",
                detail=completeness,
                public_detail={
                    "summary": f"证据完整性评估: {completeness['level']}",
                    "level": completeness['level'],
                    "has_segment_ratio": completeness['has_segment_ratio'],
                    "has_retiree_factor": completeness['has_retiree_factor'],
                    "has_segment_amount_detail": completeness['has_segment_amount_detail'],
                },
                public_message=f"证据完整性: {completeness['level']}",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": _evt.status, "duration_ms": _evt.duration_ms, "detail": _evt.detail},
            )

            # ═══════════════════════════════════════════════════════════
            # Step 6: answerability_check（可回答性判断）
            # ═══════════════════════════════════════════════════════════
            _evt = builder.start("answerability_judgment", "可回答性判断")
            yield PolicyQAResponse(
                step="answerability_check", status="running",
                public_message="正在判断可回答性",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": "running"},
            )

            answerability = self.build_answerability(sql_data, skill_policy_rules, intent_result)

            _evt = builder.done(
                detail="可以回答政策口径和结算字段来源" if answerability.can_answer else "暂不能完整回答",
                data={
                    "can_answer": answerability.can_answer,
                    "partial_answer": answerability.partial_answer,
                    "can_explain_policy_basis": answerability.checks.get("has_policy_rules_for_segment_ratios", False) or answerability.checks.get("has_retiree_factor", False),
                    "can_trace_real_settlement_field": answerability.checks.get("has_real_settlement_data", False),
                    "can_fully_recalculate_amount": answerability.checks.get("has_policy_rules_for_segment_ratios", False) and completeness.get("has_segment_amount_detail", False),
                    "reason": answerability.reason,
                    "missing_items": answerability.missing_items,
                    "checks": answerability.checks,
                },
            )
            yield PolicyQAResponse(
                step="answerability_check", status="done",
                detail={
                    "can_answer": answerability.can_answer,
                    "partial_answer": answerability.partial_answer,
                    "reason": answerability.reason,
                    "missing_items": answerability.missing_items,
                    "checks": answerability.checks,
                },
                public_detail={
                    "summary": f"可回答性: {'可回答' if answerability.can_answer else '无法回答'}",
                    "can_answer": answerability.can_answer,
                    "partial_answer": answerability.partial_answer,
                },
                public_message=(
                    "可以为您解答此问题" if answerability.can_answer
                    else "暂无法完整回答此问题"
                ),
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": _evt.status, "duration_ms": _evt.duration_ms, "detail": _evt.detail},
            )

            # ═══════════════════════════════════════════════════════════
            # Step 7: answer_generation（解释生成 — 受 answerability 门控）
            # ═══════════════════════════════════════════════════════════
            should_generate = answerability.can_answer or answerability.partial_answer

            if should_generate:
                _evt = builder.start("answer_generation", "答案生成")
                yield PolicyQAResponse(
                    step="answer_generation", status="running",
                    public_message="正在生成政策解释",
                    trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": "running"},
                )

                # 计算费用分解
                calculator_name = route_config.get("calculator", "FeeDecompositionCalculator")
                CalculatorClass = self.calculators.get(calculator_name)
                if CalculatorClass:
                    calculator = CalculatorClass()
                    calculation_result = calculator.calculate(sql_data, skill_policy_rules)
                else:
                    logger.warning(f"Calculator {calculator_name} not found in registry, using empty result")
                    calculation_result = {"error": f"Calculator {calculator_name} not found"}

                # ★ 子流程路由：根据 target_field 选择不同的解释生成方式
                target_field = intent_result.target_fee_item or ""
                if target_field == "deductible":
                    answer = self._build_deductible_answer(
                        sql_data, skill_policy_rules, intent_result
                    )
                elif target_field == "large_amount_self_pay":
                    # 大额自付子流程（占位，后续可扩展）
                    answer = self._build_generic_answer(
                        sql_data, skill_policy_rules, intent_result, "large_amount_self_pay"
                    )
                elif target_field == "personal_total_pay":
                    # 个人总支付子流程（占位，后续可扩展）
                    answer = self._build_generic_answer(
                        sql_data, skill_policy_rules, intent_result, "personal_total_pay"
                    )
                else:
                    # 默认：统筹自付等 → 使用 LLM 生成单一解释
                    explain_ctx = ExplanationContext(
                        question=request.question,
                        intent=intent_result,
                        user_role="患者",
                        rag_miss=len(skill_policy_rules) == 0,
                    )
                    explain_ctx.policy_rules = skill_policy_rules
                    if calculation_result is not None and isinstance(calculation_result, dict) and "treatment" in calculation_result:
                        explain_ctx.decomposition = _build_decomposition_from_dict(calculation_result)

                    if self.explanation_generator:
                        answer = await self.explanation_generator.generate_answer(explain_ctx)
                    else:
                        answer = self._generate_placeholder_explanation(explain_ctx)

                answer_status = (
                    "unavailable"
                    if answer.startswith("当前无法基于已有结算数据")
                    else "complete"
                )

            else:
                # 无法可靠回答：不生成猜测性内容，直接给出引导（用户咨询医保办/医保局）
                answer = ExplanationGenerator._refusal_reply()

            # 安全校验必须发生在任何携带 answer 的响应对外发送之前。
            validation_result = self._validate_output(answer, skill_policy_rules)
            if should_generate and validation_result["passed"] and answer_status == "complete":
                _answer_evt = builder.done(
                    detail="已生成政策解释",
                    data={
                        "answer_ready": True,
                        "answer_length": len(answer),
                        "answer_status": answer_status,
                    },
                )
                answer_event_status = "done"
                answer_message = "政策解释生成完成"
                answer_detail: dict[str, Any] = {}
            elif should_generate:
                if not validation_result["passed"]:
                    answer = ExplanationGenerator._refusal_reply()
                answer_status = "unavailable"
                _answer_evt = builder.error(
                    detail="答案因来源校验失败或不可用，已替换为安全提示"
                )
                answer_event_status = "skipped"
                answer_message = "无法生成可核验的政策解释"
                answer_detail = {
                    "reason": "source_validation_failed",
                    "can_answer": False,
                    "validation_errors": validation_result["errors"],
                }
            else:
                _answer_evt = builder.skip(
                    "answer_generation", "答案生成", reason=answerability.reason
                )
                answer_event_status = "skipped"
                answer_message = f"无法回答: {answerability.reason}"
                answer_detail = {
                    "reason": answerability.reason,
                    "can_answer": False,
                    "missing_items": answerability.missing_items,
                }

            yield PolicyQAResponse(
                step="answer_generation",
                status=answer_event_status,
                public_message=answer_message,
                detail=answer_detail,
                public_detail={
                    "summary": answer_message,
                    "can_answer": answer_status == "complete",
                },
                answer=answer,
                answer_status=answer_status,
                trace_event={
                    "step_id": _answer_evt.step_id,
                    "step_name": _answer_evt.step_name,
                    "step_number": _answer_evt.step_number,
                    "status": _answer_evt.status,
                    "duration_ms": _answer_evt.duration_ms,
                    "detail": _answer_evt.detail,
                },
            )

            # ═══════════════════════════════════════════════════════════
            # Step 8: output_validation（输出校验）
            # ═══════════════════════════════════════════════════════════
            _evt = builder.start("output_validation", "输出校验")
            yield PolicyQAResponse(
                step="output_validation", status="running",
                public_message="正在校验输出",
                trace_event={"step_id": _evt.step_id, "step_name": _evt.step_name, "step_number": _evt.step_number, "status": "running"},
            )

            has_warnings = len(validation_result.get("warnings", [])) > 0

            if not validation_result["passed"]:
                # 存在致命错误 → failed
                _evt = builder.error(
                    detail=f"输出校验失败: {validation_result['errors']}",
                )
                output_status = "failed"
                output_summary = "输出校验失败"
            elif has_warnings:
                # 有警告但可接受 → warning
                _evt = builder.done(
                    detail=f"输出校验完成，但存在 {len(validation_result['warnings'])} 项警告",
                    data=validation_result,
                )
                output_status = "warning"
                output_summary = f"输出校验完成，但存在 {len(validation_result['warnings'])} 项警告"
            else:
                _evt = builder.done(
                    detail="输出校验通过",
                    data=validation_result,
                )
                output_status = "success"
                output_summary = "输出校验通过"

            yield PolicyQAResponse(
                step="output_validation", status="done",
                detail=validation_result,
                public_detail={
                    "summary": output_summary,
                    "passed": validation_result["passed"],
                    "warnings": validation_result.get("warnings", []),
                },
                public_message=output_summary,
                trace_event={
                    "step_id": _evt.step_id,
                    "step_name": _evt.step_name,
                    "step_number": _evt.step_number,
                    "status": output_status,
                    "duration_ms": _evt.duration_ms,
                    "detail": _evt.detail,
                },
            )

            # ═══════════════════════════════════════════════════════════
            # Final: yield trace_result（完整链路结果）
            # ═══════════════════════════════════════════════════════════
            answerability = answerability or make_answerability(can_answer=False, reason="未执行可回答性判断")
            answer_succeeded = answer_status == "complete" and validation_result["passed"]
            trace_events = self._convert_trace_events(builder.to_list())
            trace_response = PolicyQATraceResponse(
                status=(
                    PolicyQARunStatus.SUCCESS.value
                    if answer_succeeded
                    else PolicyQARunStatus.FAILED.value
                ),
                can_answer=answerability.can_answer and answer_succeeded,
                partial_answer=answerability.partial_answer and answer_succeeded,
                selected_skill_id=skill_id or "",
                trace_events=trace_events,
                result={
                    "answer": answer,
                    "answer_status": answer_status,
                },
            )
            yield PolicyQAResponse(
                step="trace_result", status="done",
                detail={
                    "run_id": trace_response.run_id,
                    "status": trace_response.status,
                    "can_answer": trace_response.can_answer,
                    "partial_answer": trace_response.partial_answer,
                    "selected_skill_id": trace_response.selected_skill_id,
                    "target_fee_item": intent_result.target_fee_label or "",
                    "target_field": intent_result.target_fee_item or "",
                    "sub_flow": sub_flow,
                    "trace_events": [e.__dict__ for e in trace_response.trace_events],
                },
                public_detail={
                    "summary": "问答流程完成" if trace_response.can_answer else "无法回答此问题",
                    "can_answer": trace_response.can_answer,
                    "partial_answer": trace_response.partial_answer,
                },
                public_message="问答完成" if trace_response.can_answer else "无法回答此问题",
                answer=answer,
                answer_status=answer_status,
            )

        except Exception as e:
            logger.exception("PolicyQA processing failed")
            # 如果 builder 有当前事件，标记为 error
            try:
                builder.error(detail=str(e))
            except Exception:
                pass
            yield PolicyQAResponse(
                step="error",
                status="error",
                error=str(e),
            )

    async def _detect_intent(self, request: PolicyQARequest) -> PolicyQAIntentResult:
        """
        意图识别

        使用LLM识别用户意图，降级到关键词匹配
        """
        try:
            result = await self.intent_detector.detect(request.question)
            # 设置settlement_id
            result.settlement_id = request.settlement_id
            return result
        except Exception as e:
            logger.warning(f"Intent detection failed, using default: {e}")
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.FEE_DECOMPOSITION,
                settlement_id=request.settlement_id,
                need_patient_data=True,
                query_type="费用分解",
                confidence=0.6,
            )

    async def _fetch_sql_data(self, settlement_id: str) -> SQLQueryResult:
        """
        SQL Server数据获取

        查询所有相关表：待遇分解、费用明细、年度累计、住院信息、患者登记
        """
        if self.sql_fetcher is None:
            logger.warning("SQL fetcher not configured, returning empty result")
            return SQLQueryResult()

        try:
            # 调用SQL数据获取器查询所有表
            result = await self.sql_fetcher.fetch_all_tables(settlement_id)
            logger.info(
                f"Fetched SQL data for settlement_id={settlement_id}: "
                f"treatment={bool(result.yb_zyfdxx)}, "
                f"fees={len(result.yb_zyfymx)}, "
                f"patient={bool(result.yb_brdjxx)}"
            )
            return result
        except Exception as e:
            logger.exception(f"Failed to fetch SQL data for settlement_id={settlement_id}")
            return SQLQueryResult()

    async def _rewrite_question(
        self,
        question: str,
        sql_result: SQLQueryResult,
        intent=None,
        target_fee_item: str | None = None,
    ) -> RewrittenQuestion:
        """
        问题重写

        基于SQL结果+意图重写问题，注入患者上下文并生成精准检索查询。
        """
        print(f"\n[REWRITE] ====== 问题重写 ======", flush=True)
        print(f"[REWRITE] 原始问题: {question}", flush=True)
        print(f"[REWRITE] 意图: {intent.value if intent else 'None'}", flush=True)
        print(f"[REWRITE] SQL结果: yb_brdjxx={sql_result.yb_brdjxx}", flush=True)
        print(f"[REWRITE] SQL结果: yb_dyxxzy={sql_result.yb_dyxxzy}", flush=True)
        
        if self.question_rewriter is None:
            print(f"[REWRITE] 问题重写器未配置，返回原始问题", flush=True)
            return RewrittenQuestion(original=question, rewritten=question)

        try:
            # 调用问题重写器，基于SQL结果+意图+目标费用项重写问题
            result = await self.question_rewriter.rewrite(
                question,
                sql_result,
                intent=intent,
                target_fee_item=target_fee_item,
            )
            print(f"[REWRITE] 重写结果:", flush=True)
            print(f"[REWRITE]   original: {result.original}", flush=True)
            print(f"[REWRITE]   rewritten: {result.rewritten}", flush=True)
            print(f"[REWRITE]   semantic_mappings: {result.semantic_mappings}", flush=True)
            print(f"[REWRITE] ====== 问题重写完成 ======\n", flush=True)
            return result
        except Exception as e:
            print(f"[REWRITE] 重写失败: {e}", flush=True)
            logger.exception("Failed to rewrite question")
            return RewrittenQuestion(original=question, rewritten=question)

    async def _search_policy_rules(
        self,
        question: str,
        sql_result: SQLQueryResult,
        intent=None,
        target_fee_item: str | None = None,
    ) -> list[PolicyRule]:
        """
        RAG检索

        Milvus向量+高级搜索，使用重写后的问题进行检索
        使用SQL结果中的标准化后的insu_type、psn_type等参数进行过滤
        根据意图定向检索特定类型的规则
        """
        print(f"\n[SEARCH] ====== 政策规则检索 ======", flush=True)
        print(f"[SEARCH] 搜索问题: {question[:100]}...", flush=True)
        print(f"[SEARCH] 意图: {intent.value if intent else 'None'}", flush=True)
        
        if self.search_engine is None:
            print(f"[SEARCH] 搜索引擎未配置，返回空", flush=True)
            return []

        try:
            # 从 SQL 结果提取过滤参数（已标准化）
            insu_type = sql_result.yb_brdjxx.get("fund_type", "")
            psn_type = sql_result.yb_brdjxx.get("PER_TYPE", "")
            med_type = sql_result.yb_brdjxx.get("yllb", "")
            
            print(f"[SEARCH] 过滤参数 (已标准化):", flush=True)
            print(f"[SEARCH]   insu_type: {insu_type} (原始: {sql_result.yb_brdjxx.get('fund_type_raw', '')})", flush=True)
            print(f"[SEARCH]   psn_type: {psn_type} (原始: {sql_result.yb_brdjxx.get('PER_TYPE_raw', '')})", flush=True)
            print(f"[SEARCH]   med_type: {med_type} (原始: {sql_result.yb_brdjxx.get('yllb_raw', '')})", flush=True)

            # 调用搜索引擎
            print(f"[SEARCH] 使用 PolicyRulesSearchEngine.search()", flush=True)
            
            # 构建过滤表达式（使用标准化后的值）
            expr_parts = []
            if insu_type:
                expr_parts.append(f'insu_type == "{insu_type}"')
            if psn_type:
                # 人群标签：匹配具体类型或"全部"
                expr_parts.append(f'(psn_type == "{psn_type}" or psn_type == "全部")')
            
            # 根据目标费用项或意图添加 rule_type 过滤
            if target_fee_item == "pooling_self_pay":
                expr_parts.append(
                    '('
                    'rule_type == "统筹分段" or '
                    'rule_type == "支付比例" or '
                    'rule_type == "退休优惠" or '
                    'rule_type == "人员系数"'
                    ')'
                )
            elif intent:
                from src.runtime.policy_qa.models import PolicyQAIntent
                if intent == PolicyQAIntent.DEDUCTIBLE:
                    expr_parts.append('(rule_type == "起付线" or rule_type == "起付线标准")')
                elif intent == PolicyQAIntent.PAYMENT_RATIO:
                    expr_parts.append('(rule_type == "统筹分段" or rule_type == "支付比例")')
                elif intent == PolicyQAIntent.CAP_AMOUNT:
                    expr_parts.append('(rule_type == "封顶线" or rule_type == "最高支付限额")')
            
            expr = " and ".join(expr_parts) if expr_parts else None
            print(f"[SEARCH] 过滤表达式: {expr}", flush=True)
            
            search_results = self.search_engine.search(
                question=question,
                top_k=10,
                expr=expr,
            )
            
            # 如果过滤后没有结果，尝试放宽条件（只按 psn_type 过滤）
            if len(search_results) == 0 and insu_type:
                print(f"[SEARCH] 过滤后无结果，放宽 insu_type 过滤条件", flush=True)
                expr_parts = []
                if psn_type:
                    expr_parts.append(f'(psn_type == "{psn_type}" or psn_type == "全部")')
                expr = " and ".join(expr_parts) if expr_parts else None
                print(f"[SEARCH] 放宽后过滤表达式: {expr}", flush=True)
                
                search_results = self.search_engine.search(
                    question=question,
                    top_k=10,
                    expr=expr,
                )

            print(f"[SEARCH] 原始搜索结果: {len(search_results)} 条", flush=True)
            
            # 打印前3条搜索结果
            for i, hit in enumerate(search_results[:3]):
                if hasattr(hit, 'entity'):
                    entity = hit.entity or {}
                    score = hit.score or 0.0
                else:
                    entity = hit
                    score = entity.get("score", 0.0)
                print(f"[SEARCH]   [{i}] rule_type={entity.get('rule_type', entity.get('fact_type', ''))}, insu_type={entity.get('insu_type', '')}, psn_type={entity.get('psn_type', '')}, score={score:.4f}", flush=True)

            # 转换为 PolicyRule
            policy_rules = []
            for hit in search_results:
                # 处理 SearchHit 对象或 dict
                if hasattr(hit, 'entity'):
                    entity = hit.entity or {}
                    score = hit.score or 0.0
                else:
                    entity = hit
                    score = entity.get("score", 0.0)
                
                rule = PolicyRule(
                    rule_id=entity.get("rule_id", entity.get("fact_id", "")),
                    fact_id=entity.get("fact_id", ""),
                    policy_id=entity.get("policy_id", ""),
                    clause_id=entity.get("clause_id", ""),
                    source_text=entity.get("source_text", entity.get("evidence_text", "")),
                    insu_type=entity.get("insu_type", entity.get("insurance_type", "")),
                    med_type=entity.get("med_type", entity.get("service_type", "")),
                    hosp_lv=entity.get("hosp_lv", entity.get("hospital_level", "")),
                    psn_type=entity.get("psn_type", entity.get("population", "")),
                    payment_ratio=str(entity.get("payment_ratio", entity.get("ratio", ""))),
                    deductible_amount=str(entity.get("deductible_amount", "")),
                    cap_amount=str(entity.get("cap_amount", "")),
                    amount_band=str(entity.get("amount_band", entity.get("amount", ""))),
                    rule_type=entity.get("rule_type", entity.get("fact_type", "")),
                    rule_value=entity.get("rule_value", ""),
                    score=score,
                    # ★ 新增：RAG 政策卡片展示字段
                    title=entity.get("title", ""),
                    clause=entity.get("clause", ""),
                    evidence_text=entity.get("evidence_text", entity.get("source_text", "")),
                    matched_reason=self._build_matched_reason(entity),
                )
                policy_rules.append(rule)

            print(f"[SEARCH] 转换后 PolicyRule: {len(policy_rules)} 条", flush=True)
            
            # 打印转换后的规则摘要
            for i, rule in enumerate(policy_rules[:3]):
                print(f"[SEARCH]   [{i}] rule_id={rule.rule_id}, rule_type={rule.rule_type}, insu_type={rule.insu_type}, psn_type={rule.psn_type}, payment_ratio={rule.payment_ratio}", flush=True)
            
            print(f"[SEARCH] ====== 检索完成 ======\n", flush=True)
            return policy_rules

        except Exception as e:
            print(f"[SEARCH] 检索失败: {e}", flush=True)
            logger.exception("Failed to search policy rules")
            return []

    async def _calculate_decomposition(
        self,
        sql_result: SQLQueryResult,
        policy_rules: list[PolicyRule],
    ) -> FeeDecompositionResult:
        """
        费用拆分计算Skill

        待遇分解 + 费用分解 + 溯源证据
        """
        print(f"\n[DECOMPOSE] ====== 费用分解 ======", flush=True)
        print(f"[DECOMPOSE] SQL结果: yb_zyfdxx={sql_result.yb_zyfdxx}", flush=True)
        print(f"[DECOMPOSE] 政策规则数量: {len(policy_rules)}", flush=True)
        
        if self.fee_skill is None:
            print(f"[DECOMPOSE] 费用分解技能未配置，返回空", flush=True)
            return FeeDecompositionResult()

        try:
            # 调用费用分解技能
            result = self.fee_skill.decompose(
                sql_results=sql_result,
                policy_rules=policy_rules,
            )
            print(f"[DECOMPOSE] 分解结果:", flush=True)
            print(f"[DECOMPOSE]   总费用: {result.treatment.total_fee.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   医保内: {result.treatment.in_scope.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   起付线: {result.treatment.deductible.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   统筹支付: {result.treatment.pooling_payment.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   统筹自付: {result.treatment.pooling_self_pay.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   大额支付: {result.treatment.major_payment.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   大额自付: {result.treatment.major_self_pay.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   个人应负: {result.treatment.personal_liability.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   医保外: {result.treatment.out_of_scope.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   溯源证据: {len(result.evidence)} 条", flush=True)
            print(f"[DECOMPOSE] ====== 分解完成 ======\n", flush=True)
            return result

        except Exception as e:
            print(f"[DECOMPOSE] 分解失败: {e}", flush=True)
            logger.exception("Failed to calculate decomposition")
            return FeeDecompositionResult()

    async def _generate_explanation(
        self, context: ExplanationContext
    ):
        """
        解释生成

        大模型基于角色润色，流式输出
        """
        if self.explanation_generator is None:
            logger.warning("Explanation generator not configured, yielding placeholder")
            yield self._generate_placeholder_explanation(context)
            return

        try:
            # 调用解释生成器（流式）
            async for chunk in self.explanation_generator.generate(context):
                yield chunk

        except Exception as e:
            logger.exception("Explanation generation failed")
            yield f"生成解释时出错: {str(e)}"

    def _generate_placeholder_explanation(self, context: ExplanationContext) -> str:
        """
        生成占位符解释（当解释生成器不可用时）

        Args:
            context: 解释上下文

        Returns:
            占位符文本
        """
        decomposition = context.decomposition
        lines = []
        lines.append(f"您的总费用为{decomposition.treatment.total_fee.value:,.2f}元。")
        lines.append(f"其中医保内费用{decomposition.treatment.in_scope.value:,.2f}元，")
        lines.append(f"医保报销{decomposition.treatment.pooling_payment.value:,.2f}元，")
        lines.append(f"个人需要支付{decomposition.treatment.personal_liability.value:,.2f}元。")
        lines.append("")
        lines.append("具体费用构成:")
        lines.append(f"- 起付线: {decomposition.treatment.deductible.value:,.2f}元")
        lines.append(f"- 统筹支付: {decomposition.treatment.pooling_payment.value:,.2f}元")
        lines.append(f"- 统筹自付: {decomposition.treatment.pooling_self_pay.value:,.2f}元")
        lines.append(f"- 大额支付: {decomposition.treatment.major_payment.value:,.2f}元")
        lines.append(f"- 大额自付: {decomposition.treatment.major_self_pay.value:,.2f}元")
        lines.append(f"- 医保外: {decomposition.treatment.out_of_scope.value:,.2f}元")
        return "\n".join(lines)

    def _serialize_decomposition(
        self, decomposition: FeeDecompositionResult
    ) -> dict[str, Any]:
        """序列化费用分解结果为JSON"""
        return {
            "treatment": {
                "total_fee": decomposition.treatment.total_fee.value,
                "in_scope": decomposition.treatment.in_scope.value,
                "deductible": decomposition.treatment.deductible.value,
                "pooling_self_pay": decomposition.treatment.pooling_self_pay.value,
                "pooling_payment": decomposition.treatment.pooling_payment.value,
                "major_payment": decomposition.treatment.major_payment.value,
                "major_self_pay": decomposition.treatment.major_self_pay.value,
                "personal_liability": decomposition.treatment.personal_liability.value,
                "out_of_scope": decomposition.treatment.out_of_scope.value,
            },
            "fees": {
                "total_amount": decomposition.fees.total_amount,
                "in_scope_total": decomposition.fees.in_scope_total,
                "out_of_scope_total": decomposition.fees.out_of_scope_total,
                "categories": [
                    {
                        "category": cat.category,
                        "total_amount": cat.total_amount,
                        "in_scope_amount": cat.in_scope_amount,
                        "out_of_scope_amount": cat.out_of_scope_amount,
                    }
                    for cat in decomposition.fees.categories
                ],
            },
            "segments": {
                "total_pay": decomposition.segments.total_pay,
                "warnings": decomposition.segments.warnings,
                "reconciliation": {
                    "authoritative_amount": decomposition.segments.authoritative_amount,
                    "calculated_amount": decomposition.segments.total_pay,
                    "difference": decomposition.segments.reconciliation_difference,
                    "tolerance": decomposition.segments.reconciliation_tolerance,
                    "matched": decomposition.segments.reconciliation_matched,
                    "message": decomposition.segments.reconciliation_message,
                },
                "segments": [
                    {
                        "lower": seg.lower,
                        "upper": seg.upper,
                        "amount": seg.amount,
                        "base_ratio": seg.base_ratio,
                        "person_ratio": seg.person_ratio,
                        "actual_ratio": seg.actual_ratio,
                        "pay": seg.pay,
                        "calculation": seg.calculation,
                        "rule_id": seg.rule_id,
                        "policy_source": seg.policy_source,
                    }
                    for seg in decomposition.segments.segments
                ],
            },
            "evidence_count": len(decomposition.evidence),
        }

    # ── 起付线子流程：模板化单答案解释 ────────────────────────────

    def _build_deductible_answer(
        self,
        sql_data: Any,
        skill_policy_rules: list[Any],
        intent_result: PolicyQAIntentResult,
    ) -> str:
        """生成起付线解释（基于真实结算数据 + 政策规则）。"""
        treatment = getattr(sql_data, 'treatment', {}) or {}
        patient_info = getattr(sql_data, 'patient_info', {}) or {}
        admission = getattr(sql_data, 'admission', {}) or {}

        deductible_amount = treatment.get("deductible", 0)
        total_fee = treatment.get("total_fee", 0)
        in_scope = treatment.get("in_scope", 0)
        pooling_payment = treatment.get("pooling_payment", 0)
        major_payment = treatment.get("major_payment", 0)
        major_self_pay = treatment.get("major_self_pay", 0)
        personal_liability = treatment.get("personal_liability", 0)

        fund_type = patient_info.get("fund_type", "城镇职工")
        person_type = patient_info.get("person_type", "在职")
        medical_type = patient_info.get("medical_type", "普通住院")

        # 从政策规则中提取起付线相关规则
        deductible_rules = []
        for r in (skill_policy_rules or []):
            rule_type = getattr(r, 'rule_type', '') or ''
            title = getattr(r, 'title', '') or ''
            evidence = getattr(r, 'evidence_text', '') or ''
            if '起付' in rule_type or '起付' in title:
                deductible_rules.append({
                    "rule_type": rule_type,
                    "title": title,
                    "evidence": evidence[:200] if evidence else "",
                })

        lines = []
        lines.append("## 起付线说明")
        lines.append("")
        lines.append(f"本次住院起付线金额为 **{deductible_amount:,.2f}** 元。")
        lines.append("")
        lines.append("### 什么是起付线？")
        lines.append('起付线（又称"门槛费"）是指医保报销的起始标准。住院费用中，')
        lines.append("超过起付线的医保内费用部分才纳入统筹报销计算。")
        lines.append(f"本次总费用为 {total_fee:,.2f} 元，其中医保内费用 {in_scope:,.2f} 元。")
        lines.append(f"起付线 {deductible_amount:,.2f} 元需由个人先行承担。")
        lines.append("")
        lines.append("### 本次费用构成")
        lines.append(f"- 起付线（自付）: **{deductible_amount:,.2f}** 元")
        lines.append(f"- 统筹支付: {pooling_payment:,.2f} 元")
        lines.append(f"- 大额支付: {major_payment:,.2f} 元")
        lines.append(f"- 大额自付: {major_self_pay:,.2f} 元")
        lines.append(f"- 个人应负合计: {personal_liability:,.2f} 元")
        lines.append("")
        lines.append("### 起付线由谁决定？")
        lines.append("起付线标准由医保政策根据以下因素确定：")
        lines.append(f"- 险种: {fund_type}")
        lines.append(f"- 人员类型: {person_type}")
        lines.append(f"- 医疗类别: {medical_type}")
        lines.append(f"- 医院级别: {admission.get('hosp_lv', '未获取')}")
        lines.append("")

        if deductible_rules:
            lines.append("### 政策依据")
            for rule in deductible_rules[:3]:
                title = rule["title"] or f"[{rule['rule_type']}]"
                lines.append(f"- {title}")
                if rule["evidence"]:
                    lines.append(f"  {rule['evidence']}")
        elif skill_policy_rules:
            # 即使没有专门起付线规则，也展示通用政策
            lines.append("### 相关政策规则")
            for r in skill_policy_rules[:3]:
                title = getattr(r, 'title', '') or getattr(r, 'rule_type', '')
                if title:
                    lines.append(f"- {title}")

        lines.append("")
        lines.append('> 起付线不同于统筹自付。起付线是进入统筹报销前的"门槛"，超过起付线后的合规费用才按比例报销。')

        return "\n".join(lines)

    def _build_generic_answer(
        self,
        sql_data: Any,
        skill_policy_rules: list[Any],
        intent_result: PolicyQAIntentResult,
        target_field: str,
    ) -> str:
        """生成通用费用解释（用于尚未定义专属子流程的费用类型）"""
        treatment = getattr(sql_data, 'treatment', {}) or {}
        patient_info = getattr(sql_data, 'patient_info', {}) or {}

        amount_labels = {
            "large_amount_self_pay": ("大额自付", "bddegwyzf"),
            "personal_total_pay": ("个人总支付", "bdgryf"),
        }
        label, field = amount_labels.get(target_field, (target_field, target_field))
        amount = treatment.get(target_field, 0)

        lines = []
        lines.append(f"## {label}说明")
        lines.append("")
        lines.append(f"本次住院**{label}**金额为 **{amount:,.2f}** 元。")
        lines.append("")
        lines.append("### 费用构成概览")
        lines.append(f"- 总费用: {treatment.get('total_fee', 0):,.2f} 元")
        lines.append(f"- 医保内: {treatment.get('in_scope', 0):,.2f} 元")
        lines.append(f"- 统筹支付: {treatment.get('pooling_payment', 0):,.2f} 元")
        lines.append(f"- 统筹自付: {treatment.get('pooling_self_pay', 0):,.2f} 元")
        lines.append(f"- 起付线: {treatment.get('deductible', 0):,.2f} 元")
        lines.append(f"- 个人应负: {treatment.get('personal_liability', 0):,.2f} 元")
        lines.append("")
        lines.append("### 数据来源")
        lines.append("- 数据表: yb_zyfdxx（待遇分解表）")
        lines.append(f"- 数据字段: {field}")
        lines.append(f"- 险种: {patient_info.get('fund_type', '未获取')}")
        lines.append(f"- 人员: {patient_info.get('person_type', '未获取')}")
        lines.append("")
        if skill_policy_rules:
            lines.append("### 相关政策规则")
            for r in skill_policy_rules[:3]:
                title = getattr(r, 'title', '') or getattr(r, 'rule_type', '')
                if title:
                    lines.append(f"- {title}")

        return "\n".join(lines)

    @staticmethod
    def _build_matched_reason(entity: dict) -> str:
        """构建匹配原因说明（RAG 政策卡片展示用）。

        Args:
            entity: Milvus 搜索结果的实体字段 dict

        Returns:
            人性化匹配原因字符串，如 "险种=城镇职工, 人员类别=退休, 规则类型=统筹分段"
        """
        parts = []
        if entity.get("insu_type"):
            parts.append(f"险种={entity['insu_type']}")
        if entity.get("psn_type"):
            parts.append(f"人群={entity['psn_type']}")
        if entity.get("med_type"):
            parts.append(f"医疗={entity['med_type']}")
        if entity.get("rule_type"):
            parts.append(f"类型={entity['rule_type']}")
        if entity.get("payment_ratio"):
            parts.append(f"比例={entity['payment_ratio']}")
        return "、".join(parts) if parts else "政策规则匹配"
