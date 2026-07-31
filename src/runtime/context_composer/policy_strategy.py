"""政策检索策略 — Composer 的内部策略

将 `policy_qa/structured_policy_retriever` 收编为 Composer 的检索策略之一。
保留原有能力，但通过策略接口封装，便于 Composer 统一调度。
"""

from typing import Any

from src.runtime.context_composer.models import MemoryBrief
from src.runtime.memory.models import BusinessMemory, MemoryType
from src.runtime.policy_qa.structured_policy_retriever import (
    NormalizedPolicyContext,
    StructuredPolicyRuleRetriever,
    retrieve_policy_evidence,
)


class PolicyRetrievalStrategy:
    """政策检索策略 — 基于 Milvus 标量查询的结构化政策规则检索。

    当 Composer 检测到当前上下文需要政策规则时，调用此策略
    检索相关政策，并将结果转换为 MemoryBrief。
    """

    def __init__(self, host: str = "127.0.0.1", port: str = "19530"):
        self._host = host
        self._port = port

    def retrieve(
        self,
        settlement_context: dict[str, Any],
        target_field: str = "统筹自付",
    ) -> list[MemoryBrief]:
        """检索政策证据并转换为 MemoryBrief 列表。

        Args:
            settlement_context: 标准化结算上下文字典
            target_field: 目标字段

        Returns:
            MemoryBrief 列表，供 Composer 排序和筛选
        """
        result = retrieve_policy_evidence(
            settlement_context=settlement_context,
            host=self._host,
            port=self._port,
        )

        briefs: list[MemoryBrief] = []
        for evidence in result.selected_evidence:
            # 将政策证据转换为 MemoryBrief
            summary = self._build_summary(evidence)
            briefs.append(MemoryBrief(
                memory_id=f"policy_{evidence.evidence_id}",
                type=MemoryType.POLICY.value,
                summary=summary,
                importance=evidence.score,  # 结构化匹配默认满分 1.0
            ))

        return briefs

    @staticmethod
    def _build_summary(evidence) -> str:
        """从政策证据构建自然语言摘要。"""
        parts = [f"[政策规则] {evidence.rule_type}"]
        if evidence.insu_type:
            parts.append(f"险种={evidence.insu_type}")
        if evidence.med_type:
            parts.append(f"医疗类别={evidence.med_type}")
        if evidence.hosp_lv:
            parts.append(f"医院等级={evidence.hosp_lv}")
        if evidence.psn_type:
            parts.append(f"人群={evidence.psn_type}")
        if evidence.source_text:
            text = evidence.source_text[:100]
            parts.append(f"内容={text}")
        if evidence.applied_reason:
            parts.append(f"适用原因={evidence.applied_reason}")
        return " | ".join(parts)


class PolicyRetrievalComposerBridge:
    """Composer 与 Policy 检索的桥接器。

    当 Composer 在组装 LLMContext 时，发现缺少 POLICY 类型的记忆，
    可通过此桥接器动态检索并补充。
    """

    def __init__(self, strategy: PolicyRetrievalStrategy | None = None):
        self._strategy = strategy or PolicyRetrievalStrategy()

    def enrich_memories(
        self,
        memories: list[BusinessMemory],
        settlement_context: dict[str, Any],
    ) -> list[BusinessMemory]:
        """为记忆列表补充政策检索结果。

        如果当前记忆列表中缺少 POLICY 类型，则触发检索。
        """
        has_policy = any(m.type == MemoryType.POLICY for m in memories)
        if has_policy:
            return memories

        briefs = self._strategy.retrieve(settlement_context)
        for brief in briefs:
            memories.append(BusinessMemory(
                memory_id=brief.memory_id,
                session_id="",  # 由调用方填充
                type=MemoryType.POLICY,
                ref_id=brief.memory_id,
                object_snapshot={"summary": brief.summary},
                importance=brief.importance,
                last_used_at="",
                created_at="",
            ))

        return memories
