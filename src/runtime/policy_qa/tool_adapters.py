"""工具适配器 — 把 Agent 已有的基础设施适配到 skill 声明的工具接口。

每个适配器实现了 skill 包 tool_interfaces.py 中定义的 Protocol。
skill 计算器只依赖接口，不依赖此处的具体实现。
"""

import sys
from pathlib import Path
from collections.abc import AsyncIterator

# 确保 skills 目录在 Python path 中
_skill_dir = Path(__file__).parent.parent.parent.parent / "skills"
if str(_skill_dir) not in sys.path:
    sys.path.insert(0, str(_skill_dir))

from policy_fee_explanation.tool_interfaces import (
    SqlQueryTool,
    PolicySearchTool,
    LlmExplainTool,
    PatientSettlementData,
    PolicyRule as SkillPolicyRule,
)

from src.runtime.policy_qa.sql_data_fetcher import SQLDataFetcher
from src.runtime.policy_qa.policy_rules_search import PolicyRulesSearchEngine
from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
from src.runtime.policy_qa.models import ExplanationContext


class SqlQueryAdapter(SqlQueryTool):
    """把 SQLDataFetcher 适配到 SqlQueryTool 接口"""

    def __init__(self, fetcher: SQLDataFetcher | None = None):
        self._fetcher = fetcher

    async def query(self, settlement_id: str) -> PatientSettlementData:
        if self._fetcher is None:
            self._fetcher = SQLDataFetcher()

        result = await self._fetcher.fetch_all_tables(settlement_id)

        # 从 SQL 结果映射到标准化字段（使用 normalizer 将编码转为中文标签）
        yb_zyfdxx = getattr(result, 'yb_zyfdxx', None) or {}
        yb_dyxxzy = getattr(result, 'yb_dyxxzy', None) or {}
        yb_dyxxnd = getattr(result, 'yb_dyxxnd', None) or {}
        yb_brdjxx = getattr(result, 'yb_brdjxx', None) or {}

        # ★ 使用 dictionary_normalizer 将编码转为中文标签
        normalizer = self._fetcher.normalizer if hasattr(self._fetcher, 'normalizer') else None
        if normalizer and isinstance(yb_brdjxx, dict):
            fund_type_raw = yb_brdjxx.get("fund_type", "")
            person_type_raw = yb_brdjxx.get("PER_TYPE", "")
            medical_type_raw = yb_brdjxx.get("yllb", "")
            fund_type = normalizer.normalize("fund_type", str(fund_type_raw)) or str(fund_type_raw)
            person_type = normalizer.normalize("person_type", str(person_type_raw)) or str(person_type_raw)
            medical_type = normalizer.normalize("medical_type", str(medical_type_raw)) or str(medical_type_raw)
        else:
            fund_type = str(yb_brdjxx.get("fund_type", ""))
            person_type = str(yb_brdjxx.get("PER_TYPE", ""))
            medical_type = str(yb_brdjxx.get("yllb", ""))

        total_fee = float(yb_zyfdxx.get("bdfyzje", 0))
        in_scope = float(yb_zyfdxx.get("bdybnzje", 0))

        return PatientSettlementData(
            settlement_id=settlement_id,
            treatment={
                "total_fee": total_fee,
                "in_scope": in_scope,
                "deductible": float(yb_dyxxzy.get("bcqfje", 0)),
                "pooling_self_pay": float(yb_zyfdxx.get("bdtczf", 0)),
                "pooling_payment": float(yb_zyfdxx.get("bdtczfje", 0)),
                "major_self_pay": float(yb_zyfdxx.get("bddegwyzf", 0)),
                "major_payment": float(yb_zyfdxx.get("bddegwyzfje", 0)),
                "personal_liability": float(yb_zyfdxx.get("bdgryf", 0)),
                "out_of_scope": max(0.0, total_fee - in_scope),
            },
            fee_details=result.yb_zyfymx if hasattr(result, 'yb_zyfymx') else [],
            annual={
                "year": yb_dyxxnd.get("fynd", ""),
                "accumulated": yb_dyxxnd.get("bnzqslj", 0),
            },
            admission=yb_dyxxzy,
            patient_info={
                "fund_type": fund_type,
                "person_type": person_type,
                "medical_type": medical_type,
            },
        )


class PolicySearchAdapter(PolicySearchTool):
    """把 PolicyRulesSearchEngine 适配到 PolicySearchTool 接口。

    优先使用 search_with_context（基于险种/人员/医疗类别 + 关键词过滤），
    比纯向量搜索更准确，不依赖 embedding 质量。
    """

    def __init__(self, engine: PolicyRulesSearchEngine | None = None):
        self._engine = engine

    async def search(
        self, query: str, filters: list[str], top_k: int,
        patient_info: dict | None = None,
    ) -> list[SkillPolicyRule]:
        if self._engine is None:
            from src.config.production import MILVUS_HOST, MILVUS_PORT
            self._engine = PolicyRulesSearchEngine(
                host=MILVUS_HOST, port=MILVUS_PORT, embedding_kind="hash"
            )

        import asyncio
        loop = asyncio.get_event_loop()

        # ★ 优先使用上下文搜索（按险种/人员/医疗类别过滤）
        if patient_info:
            insu_type = str(patient_info.get("fund_type", "") or "")
            psn_type = str(patient_info.get("person_type", "") or "")
            med_type = str(patient_info.get("medical_type", "") or "")

            # 只有当有实际上下文时才用 search_with_context
            if insu_type or psn_type or med_type:
                results = await loop.run_in_executor(
                    None,
                    lambda: self._engine.search_with_context(
                        question=query,
                        insu_type=insu_type if insu_type else None,
                        psn_type=psn_type if psn_type else None,
                        med_type=med_type if med_type else None,
                        top_k=top_k,
                    ),
                )
                # ★ 降级 1：精确匹配 0 结果 → 去掉险种过滤，只用医疗类别 + 人员类型
                if not results and insu_type:
                    results = await loop.run_in_executor(
                        None,
                        lambda: self._engine.search_with_context(
                            question=query,
                            insu_type=None,
                            psn_type=psn_type if psn_type else None,
                            med_type=med_type if med_type else None,
                            top_k=top_k,
                        ),
                    )
                # ★ 降级 2：仍然 0 → 完全去掉上下文，纯关键词搜索
                if not results:
                    results = await loop.run_in_executor(
                        None, lambda: self._engine.search(query, top_k=top_k)
                    )
            else:
                results = await loop.run_in_executor(
                    None, lambda: self._engine.search(query, top_k=top_k)
                )
        else:
            results = await loop.run_in_executor(
                None, lambda: self._engine.search(query, top_k=top_k)
            )

        # PolicyRulesSearchEngine.search() is synchronous, wrap in executor
        import asyncio

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, lambda: self._engine.search(query, top_k=top_k)
        )

        filtered = []
        for r in results:
            rule_type = r.get("rule_type", "") or ""
            if not filters or rule_type in filters:
                filtered.append(
                    SkillPolicyRule(
                        title=r.get("source_text", "") or "",
                        clause=r.get("clause_id", "") or "",
                        evidence_text=r.get("source_text", "") or "",
                        matched_reason=(
                            f"insu_type={r.get('insu_type', '')}, "
                            f"psn_type={r.get('psn_type', '')}"
                        )
                        if r.get("insu_type") or r.get("psn_type")
                        else "",
                        rule_type=rule_type,
                        score=float(r.get("score", 0.0)),
                    )
                )
        return filtered


class LlmExplainAdapter(LlmExplainTool):
    """把 ExplanationGenerator 适配到 LlmExplainTool 接口"""

    def __init__(self, generator: ExplanationGenerator | None = None):
        self._generator = generator

    async def generate_stream(self, context: dict) -> AsyncIterator[str]:
        if self._generator is None:
            from src.model_service.gateway import ModelGateway
            try:
                model = ModelGateway()
                self._generator = ExplanationGenerator(model_gateway=model)
            except Exception:
                # LLM 不可用，生成文本兜底解释
                yield self._build_fallback_text(context)
                return

        # 将 dict 适配为完整的 ExplanationContext
        from src.runtime.policy_qa.models import PolicyQAIntentResult, PolicyQAIntent
        intent_result = PolicyQAIntentResult(
            intent=getattr(PolicyQAIntent, str(context.get("intent", "fee_decomposition")), PolicyQAIntent.FEE_DECOMPOSITION),
            settlement_id=context.get("settlement_id", ""),
            confidence=0.9,
            query_type=context.get("query_type", ""),
            target_fee_item=context.get("target_fee_item", ""),
        )
        ctx = ExplanationContext(
            question=context.get("question", ""),
            user_role=context.get("user_role", "患者"),
            rag_miss=context.get("rag_miss", False),
        )
        ctx.intent = intent_result  # ★ 必须设置，_generate_placeholder 依赖它
        # ★ 补传费用分解结果和政策规则
        calc_result = context.get("calculation_result")
        if calc_result:
            from src.runtime.policy_qa.models import FeeDecompositionResult
            if isinstance(calc_result, FeeDecompositionResult):
                ctx.decomposition = calc_result
        policy_rules = context.get("policy_rules", [])
        if policy_rules:
            ctx.policy_rules = policy_rules

        # 尝试调 LLM，失败则兜底
        try:
            async for chunk in self._generator.generate(ctx):
                yield chunk
        except Exception:
            yield self._build_fallback_text(context)

    def _build_fallback_text(self, context: dict) -> str:
        """LLM 不可用时，从计算数据生成兜底文本解释"""
        calc = context.get("calculation_result", {}) or {}
        treatment = calc.get("treatment", {})
        segments = calc.get("segments", {})
        seg_list = segments.get("segments", [])
        reconciliation = segments.get("reconciliation", {})

        lines = ["## 费用分解结果\n"]

        total_fee = treatment.get("total_fee", 0)
        personal_liability = treatment.get("personal_liability", 0)
        pooling_self_pay = treatment.get("pooling_self_pay", 0)
        deductible = treatment.get("deductible", 0)

        lines.append(f"本次住院总费用: **{total_fee:,.2f}** 元")
        lines.append(f"个人应负: **{personal_liability:,.2f}** 元")
        lines.append("")

        if seg_list:
            lines.append("### 分段计算明细")
            for i, seg in enumerate(seg_list, 1):
                lines.append(
                    f"{i}. {seg.get('lower', 0):,.0f} - {seg.get('upper', '∞' if seg.get('upper') == float('inf') else seg.get('upper', 0)):,.0f} 元"
                    if seg.get('upper') != float('inf')
                    else f"{i}. {seg.get('lower', 0):,.0f} 元以上"
                )
                lines.append(f"   段内金额: {seg.get('amount', 0):,.2f} 元")
                lines.append(f"   自付金额: {seg.get('pay', 0):,.2f} 元")
                calc_text = seg.get("calculation", "")
                if calc_text:
                    lines.append(f"   计算: {calc_text}")
                policy = seg.get("policy_source", "")
                if policy:
                    lines.append(f"   政策: {policy}")
                lines.append("")

        if reconciliation:
            lines.append("### 对账结果")
            authoritative = reconciliation.get("authoritative_amount", 0)
            calculated = reconciliation.get("calculated_amount", 0)
            lines.append(f"系统金额: {authoritative:,.2f} 元")
            lines.append(f"计算金额: {calculated:,.2f} 元")
            lines.append(f"差异: {reconciliation.get('difference', 0):,.2f} 元")
            matched = reconciliation.get("matched", False)
            if matched:
                lines.append("✓ 计算与系统金额一致")
            else:
                lines.append("⚠️ 计算与系统金额存在差异，需人工复核")

        # 政策依据
        policy_rules = context.get("policy_rules", []) or []
        if policy_rules:
            lines.append("")
            lines.append("### 政策依据")
            for r in policy_rules[:5]:
                rule_type = getattr(r, 'rule_type', '') or r.get('rule_type', '')
                title = getattr(r, 'title', '') or r.get('title', '')
                evidence = getattr(r, 'evidence_text', '') or r.get('evidence_text', '')
                if title:
                    lines.append(f"- [{rule_type}] {title}")
                if evidence:
                    lines.append(f"  {evidence[:200]}")
        elif context.get("rag_miss"):
            lines.append("")
            lines.append("⚠️ 未检索到相关政策规则")

        return "\n".join(lines)
