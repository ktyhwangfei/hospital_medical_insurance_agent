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

        # 从 SQL 结果映射到标准化字段
        yb_zyfdxx = result.yb_zyfdxx if hasattr(result, 'yb_zyfdxx') else {}
        yb_dyxxzy = result.yb_dyxxzy if hasattr(result, 'yb_dyxxzy') else {}
        yb_dyxxnd = result.yb_dyxxnd if hasattr(result, 'yb_dyxxnd') else {}
        yb_brdjxx = result.yb_brdjxx if hasattr(result, 'yb_brdjxx') else {}

        total_fee = float(yb_zyfdxx.get("bdfyzje", 0))
        in_scope = float(yb_zyfdxx.get("bdybnzje", 0))

        treatment = {
            "total_fee": total_fee,
            "in_scope": in_scope,
            "deductible": float(yb_dyxxzy.get("bcqfje", 0)),
            "pooling_self_pay": float(yb_zyfdxx.get("bdtczf", 0)),
            "pooling_payment": float(yb_zyfdxx.get("bdtczfje", 0)),
            "major_self_pay": float(yb_zyfdxx.get("bddegwyzf", 0)),
            "major_payment": float(yb_zyfdxx.get("bddegwyzfje", 0)),
            "personal_liability": float(yb_zyfdxx.get("bdgryf", 0)),
            "out_of_scope": max(0.0, total_fee - in_scope),
        }

        return PatientSettlementData(
            settlement_id=settlement_id,
            treatment=treatment,
            fee_details=result.yb_zyfymx if hasattr(result, 'yb_zyfymx') else [],
            annual={
                "year": yb_dyxxnd.get("fynd", ""),
                "accumulated": yb_dyxxnd.get("bnzqslj", 0),
            },
            admission=yb_dyxxzy,
            patient_info={
                "fund_type": str(yb_brdjxx.get("fund_type", "")),
                "person_type": str(yb_brdjxx.get("PER_TYPE", "")),
                "medical_type": str(yb_brdjxx.get("yllb", "")),
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
            model = ModelGateway()
            self._generator = ExplanationGenerator(model_gateway=model)

        # 将 dict 适配为完整的 ExplanationContext
        ctx = ExplanationContext(
            question=context.get("question", ""),
            user_role=context.get("user_role", "患者"),
            rag_miss=context.get("rag_miss", False),
        )
        # ★ 补传费用分解结果和政策规则
        calc_result = context.get("calculation_result")
        if calc_result:
            from src.runtime.policy_qa.models import FeeDecompositionResult
            if isinstance(calc_result, FeeDecompositionResult):
                ctx.decomposition = calc_result
        policy_rules = context.get("policy_rules", [])
        if policy_rules:
            ctx.policy_rules = policy_rules

        async for chunk in self._generator.generate(ctx):
            yield chunk
