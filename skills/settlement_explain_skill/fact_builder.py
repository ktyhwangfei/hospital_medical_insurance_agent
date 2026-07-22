"""
fact_builder.py — FeeExplanationFact Pydantic model + FactBuilder.

标准化 Fact JSON 构建器，将 settlement_context + policy_evidence + segment_ratios
映射为结构化的 FeeExplanationFact，供 LLM prompt 组装使用。

不包含解释逻辑或文案生成。专注数据提取与标准化。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class FeeExplanationFact(BaseModel):
    """标准化费用解释事实，用于 LLM prompt 组装。

    所有金额字段默认为 0.0（从不 None），确保 JSON 序列化一致性。
    通过 .model_dump() 和 .model_dump_json() 序列化。
    """

    # ── 身份与上下文 ────────────────────────────────────────
    settlement_id: str = ""
    person_type: str = ""
    insurance_type: str = ""
    service_type: str = ""
    hospital_level: str = ""

    # ── 费用项标识 ──────────────────────────────────────────
    target_fee_item: str = ""
    target_fee_label: str = ""
    target_fee_definition: str = ""
    target_amount: float = 0.0

    # ── 结算金额字段 ────────────────────────────────────────
    deductible: float = 0.0
    medical_insurance_inner_amount: float = 0.0
    basic_pooling_payment: float = 0.0
    basic_pooling_self_pay: float = 0.0
    large_amount_payment: float = 0.0
    large_amount_self_pay: float = 0.0
    personal_total_pay: float = 0.0

    # ── 分段比例（医保政策段） ──────────────────────────────
    segment_ratios: list[dict] = Field(default_factory=list)
    has_retiree: bool = False
    retiree_ratio: Optional[int] = None
    retiree_adjusted_segments: Optional[list[float]] = None

    # ── 政策证据 ────────────────────────────────────────────
    policy_evidence: list[dict] = Field(default_factory=list)
    evidence_count: int = 0
    evidence_completeness: str = "none"

    # ── 警告与说明 ──────────────────────────────────────────
    warnings: list[str] = Field(default_factory=list)


class FactBuilder:
    """标准化 Fact 构建器。

    将结算上下文、政策证据和分段比例映射为 FeeExplanationFact。
    专注数据提取与标准化，不包含解释逻辑或文案生成。

    用法::
        builder = FactBuilder()
        fact = builder.build(settlement_ctx, evidence, segment_ratios, "pooling_self_pay")
        json_str = fact.model_dump_json(indent=2)
    """

    # 费用项 → (中文标签, 定义说明) 映射
    _FEE_DEFINITIONS: dict[str, tuple[str, str]] = {
        "pooling_self_pay": ("统筹自付", "基本医保统筹段内按政策比例由个人承担的金额"),
        "deductible": ("起付线", "医保开始报销前需先由个人承担的固定金额"),
        "large_amount_self_pay": ("大额自付", "进入大额医疗费用补助保障段后由个人承担的金额"),
        "pooling_payment": ("统筹支付", "基本医保统筹基金已支付的金额"),
        "personal_total_pay": ("个人总支付", "本次结算个人负担的各类费用合计"),
    }

    # 费用项 → 结算字段名 映射
    _FIELD_MAP: dict[str, str] = {
        "pooling_self_pay": "basic_pooling_self_pay",
        "deductible": "deductible",
        "large_amount_self_pay": "large_amount_self_pay",
        "pooling_payment": "basic_pooling_payment",
        "personal_total_pay": "personal_total_pay",
    }

    _DEFAULT_DEFINITION = "医保费用项"

    def build(
        self,
        settlement_context: Any,
        policy_evidence: list[dict],
        segment_ratios: dict,
        target_fee_item: str,
        fee_excludes: list[str] | None = None,
    ) -> FeeExplanationFact:
        """将结算上下文+证据+分段比例构建为标准化事实。

        通过 getattr() 访问 settlement_context 的属性，
        兼容 SimpleNamespace、SimpleNameSpace、dataclass、普通对象。

        Args:
            settlement_context: 结算上下文（属性式访问，如 SimpleNamespace）
            policy_evidence: 政策检索证据列表
            segment_ratios: _extract_segment_ratios() 返回的分段比例字典
            target_fee_item: 目标费用项键名（如 "pooling_self_pay"）
            fee_excludes: 可选的不包含费用项列表

        Returns:
            FeeExplanationFact 结构化事实
        """
        # ── 目标金额与标识 ──────────────────────────────────
        target_field = self._get_target_field(target_fee_item)
        target_amount = float(getattr(settlement_context, target_field, 0) or 0)

        label, definition = self._FEE_DEFINITIONS.get(
            target_fee_item, (target_fee_item, self._DEFAULT_DEFINITION)
        )

        # ── 提取结算金额字段 ────────────────────────────────
        deductible = float(getattr(settlement_context, "deductible", 0) or 0)
        inner = float(
            getattr(settlement_context, "medical_insurance_inner_amount", 0) or 0
        )
        pool_pay = float(
            getattr(settlement_context, "basic_pooling_payment", 0) or 0
        )
        pool_self = float(
            getattr(settlement_context, "basic_pooling_self_pay", 0) or 0
        )
        large_pay = float(
            getattr(settlement_context, "large_amount_payment", 0) or 0
        )
        large_self = float(
            getattr(settlement_context, "large_amount_self_pay", 0) or 0
        )
        personal = float(
            getattr(settlement_context, "personal_total_pay", 0) or 0
        )

        # ── 提取维度标识字段 ────────────────────────────────
        person_type = str(getattr(settlement_context, "person_type", "") or "")
        insurance_type = str(
            getattr(settlement_context, "insurance_type", "") or ""
        )
        service_type = str(
            getattr(settlement_context, "service_type", "") or ""
        )
        hospital_level = str(
            getattr(settlement_context, "hospital_level", "") or ""
        )
        settlement_id = str(
            getattr(settlement_context, "settlement_id", "") or ""
        )

        # ── 处理分段比例 ────────────────────────────────────
        employee = segment_ratios.get("employee", [])
        retiree = segment_ratios.get("retiree")
        has_retiree = retiree is not None

        # ── 处理证据摘要 ────────────────────────────────────
        evidence_summary: list[dict] = []
        for idx, ev in enumerate(policy_evidence):
            excerpt = self._clean_excerpt(str(ev.get("source_text", "")))
            reason = str(
                ev.get("applied_reason", "本次结算适用本规则。")
            )
            evidence_summary.append({
                "index": idx + 1,
                "excerpt": excerpt,
                "applied_reason": reason,
            })

        evidence_count = len(policy_evidence)

        # ── 证据完整性判定 ──────────────────────────────────
        has_complete = segment_ratios.get("has_complete", False)
        if has_complete:
            evidence_completeness = "complete"
        elif evidence_count > 0:
            evidence_completeness = "partial"
        else:
            evidence_completeness = "none"

        # ── 构建 warnings ───────────────────────────────────
        warnings: list[str] = []
        if fee_excludes:
            for excl in fee_excludes:
                warnings.append(f"本解释不包含{excl}。")
        if not has_complete:
            warnings.append("分段比例不完整，解释可能不够精确。")

        return FeeExplanationFact(
            settlement_id=settlement_id,
            person_type=person_type,
            insurance_type=insurance_type,
            service_type=service_type,
            hospital_level=hospital_level,
            target_fee_item=target_fee_item,
            target_fee_label=label,
            target_fee_definition=definition,
            target_amount=target_amount,
            deductible=deductible,
            medical_insurance_inner_amount=inner,
            basic_pooling_payment=pool_pay,
            basic_pooling_self_pay=pool_self,
            large_amount_payment=large_pay,
            large_amount_self_pay=large_self,
            personal_total_pay=personal,
            segment_ratios=employee,
            has_retiree=has_retiree,
            retiree_ratio=retiree.get("ratio") if retiree else None,
            retiree_adjusted_segments=retiree.get("segments")
            if retiree
            else None,
            policy_evidence=evidence_summary,
            evidence_count=evidence_count,
            evidence_completeness=evidence_completeness,
            warnings=warnings,
        )

    @staticmethod
    def _get_target_field(fee_item: str) -> str:
        """获取费用项对应的结算字段名。"""
        return FactBuilder._FIELD_MAP.get(fee_item, fee_item)

    @staticmethod
    def _clean_excerpt(text: str) -> str:
        """清理政策摘要文本。

        移除大括号后的元数据后缀，合并多余空行。
        与 BaseFeeStrategy._clean_policy_excerpt 逻辑一致。
        """
        import re

        cleaned = re.sub(r"\n?\{[^}]*\}[\s\S]*$", "", text).strip()
        cleaned = re.sub(r"\n{2,}", "\n", cleaned)
        cleaned = "\n".join(
            line.strip() for line in cleaned.split("\n") if line.strip()
        )
        return cleaned
