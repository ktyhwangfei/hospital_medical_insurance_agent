"""
医保政策问答RAG系统 - 费用拆分计算Skill

核心逻辑: 分段计算，每段独立比例
- 统筹自付 = Σ(各分段金额 × 各分段自付比例)
- 各分段自付比例 = 基础比例 × 人员系数

示例(退休人员，统筹内97,372.18元):
- 650-3万:   29,350 × 15%×60% = 29,350 × 9% = 2,641.50
- 3-4万:    10,000 × 10%×60% = 10,000 × 6% = 600.00
- 4万以上:   57,372.18 × 5%×60% = 57,372.18 × 3% = 1,721.17
- 合计:     2,641.50 + 600.00 + 1,721.17 = 4,962.67
"""

from __future__ import annotations

import logging
from typing import Any

from src.runtime.policy_qa.models import (
    EvidenceItem,
    FeeCategory,
    FeeDecomposition,
    FeeDecompositionResult,
    PolicyRule,
    SegmentCalculationResult,
    SegmentInfo,
    SQLQueryResult,
    TreatmentDecomposition,
    TreatmentItem,
)

logger = logging.getLogger(__name__)


class FeeDecompositionSkill:
    """
    费用拆分计算Skill

    核心逻辑: 分段计算，每段独立比例
    """

    def decompose(
        self,
        sql_results: SQLQueryResult,
        policy_rules: list[PolicyRule],
    ) -> FeeDecompositionResult:
        """
        执行完整费用分解

        Args:
            sql_results: SQL查询结果
            policy_rules: 检索到的政策规则

        Returns:
            FeeDecompositionResult: 费用分解结果
        """
        try:
            # 1. 解析SQL结果
            treatment = sql_results.yb_zyfdxx
            fee_details = sql_results.yb_zyfymx
            annual = sql_results.yb_dyxxnd
            admission = sql_results.yb_dyxxzy
            patient = sql_results.yb_brdjxx

            # 2. 解析政策规则(分段+比例)
            segments = self._parse_segments(policy_rules)
            person_ratio = self._get_person_ratio(patient)

            # 3. 分段计算统筹自付
            pooling_amount, pooling_warnings = self._derive_pooling_amount(treatment)

            segment_calc = self._calculate_segmented(
                amount=pooling_amount,
                segments=segments,
                person_ratio=person_ratio,
                deductible=admission.get("bcqfje", 0),
            )
            segment_calc.warnings.extend(pooling_warnings)
            segment_calc = self._reconcile_pooling_self_pay(
                segment_calc,
                authoritative_amount=float(treatment.get("bdtczf", 0) or 0),
                tolerance=0.01,
            )

            # 4. 待遇分解
            treatment_decomp = self._decompose_treatment(
                treatment, fee_details, policy_rules, segment_calc, admission
            )

            # 5. 费用分解(按收费项目等级)
            fee_decomp = self._decompose_fees(fee_details)

            # 6. 溯源证据
            evidence = self._build_evidence(
                treatment_decomp, fee_decomp, segment_calc, fee_details, policy_rules
            )

            return FeeDecompositionResult(
                treatment=treatment_decomp,
                fees=fee_decomp,
                segments=segment_calc,
                evidence=evidence,
            )

        except Exception as e:
            logger.exception("Failed to decompose fees")
            return FeeDecompositionResult()

    def _parse_segments(self, policy_rules: list[PolicyRule]) -> list[tuple[float, float, float, str, str]]:
        """
        从政策规则解析分段信息，保留规则溯源

        Returns:
            [(下限, 上限, 基础比例, rule_id, source_text), ...]
        """
        segments = []
        for rule in policy_rules:
            if rule.rule_type == "统筹分段":
                band = rule.amount_band
                ratio_str = rule.payment_ratio
                try:
                    ratio = float(ratio_str.replace("%", "")) / 100 if "%" in ratio_str else float(ratio_str)
                except (ValueError, TypeError):
                    ratio = 0.0

                # 解析 "650-30000" 格式
                lower, upper = self._parse_band(band)
                # 保留规则ID和原文用于溯源
                segments.append((lower, upper, ratio, rule.rule_id, rule.source_text))

        # 按下限排序
        segments.sort(key=lambda x: x[0])
        return segments

    def _parse_band(self, band: str) -> tuple[float, float]:
        """
        解析金额分段

        Args:
            band: 分段字符串，如 "650-30000"

        Returns:
            (下限, 上限)
        """
        try:
            if "-" in band:
                parts = band.split("-")
                lower = float(parts[0])
                upper = float(parts[1]) if len(parts) > 1 and parts[1] not in ("inf", "") else float("inf")
                return lower, upper
            else:
                # 单个值，如 "1000"，表示下限
                val = float(band)
                return val, float("inf")
        except (ValueError, IndexError):
            return 0.0, float("inf")

    def _get_person_ratio(self, patient: dict[str, Any]) -> float:
        """
        获取人员系数。

        退休人员: 60% (即自付比例×0.6)
        在职人员: 100% (即自付比例×1.0)
        """
        per_type = str(patient.get("PER_TYPE", "") or "")
        per_type_raw = str(patient.get("PER_TYPE_raw", "") or "")
        text = f"{per_type} {per_type_raw}"
        if any(keyword in text for keyword in ["退休", "退职"]):
            return 0.6
        if per_type.strip() == "2" or per_type_raw.strip() == "2":
            return 0.6
        return 1.0

    def _derive_pooling_amount(self, treatment: dict[str, Any]) -> tuple[float, list[str]]:
        """推导统筹分段基数，并返回解释 warning。"""
        tcfdhybn = float(treatment.get("tcfdhybn", 0) or 0)
        if tcfdhybn > 0:
            return tcfdhybn, []

        bdybnzje = float(treatment.get("bdybnzje", 0) or 0)
        degwyzfje = float(treatment.get("bddegwyzfje", 0) or 0)
        degwyzf = float(treatment.get("bddegwyzf", 0) or 0)
        estimated = bdybnzje - degwyzfje - degwyzf
        return max(estimated, 0.0), ["按现有字段估算统筹分段基数：医保内金额 - 大额支付 - 大额自付"]

    def _reconcile_pooling_self_pay(
        self,
        segment_calc: SegmentCalculationResult,
        authoritative_amount: float,
        *,
        tolerance: float = 0.01,
    ) -> SegmentCalculationResult:
        """将政策解释计算值与业务库统筹自付金额对账。"""
        calculated = round(segment_calc.total_pay, 2)
        authoritative = round(float(authoritative_amount or 0), 2)
        difference = round(calculated - authoritative, 2)

        segment_calc.total_pay = calculated
        segment_calc.authoritative_amount = authoritative
        segment_calc.reconciliation_difference = difference
        segment_calc.reconciliation_tolerance = tolerance
        # 若统筹分段基数来自估算，即使金额在容差内也不能视为稳定对账命中。
        segment_calc.reconciliation_matched = abs(difference) <= tolerance and not segment_calc.warnings
        if segment_calc.reconciliation_matched:
            segment_calc.reconciliation_message = "政策解释计算与业务库金额一致"
        else:
            segment_calc.reconciliation_message = "政策解释计算与结算结果存在差异，需要人工复核"
        return segment_calc

    def _calculate_segmented(
        self,
        amount: float,
        segments: list[tuple[float, float, float, str, str]],
        person_ratio: float,
        deductible: float,
    ) -> SegmentCalculationResult:
        """
        分段计算统筹自付（含规则溯源）

        公式: 每段自付 = 段内金额 × 基础比例 × 人员系数

        Args:
            amount: 统筹内金额
            segments: 分段信息 [(下限, 上限, 基础比例, rule_id, source_text), ...]
            person_ratio: 人员系数
            deductible: 起付线

        Returns:
            SegmentCalculationResult: 分段计算结果
        """
        result = SegmentCalculationResult()
        remaining = amount - deductible  # 扣除起付线后的金额
        current_pos = deductible  # 从起付线开始

        for lower, upper, base_ratio, rule_id, policy_source in segments:
            if remaining <= 0:
                break

            # 调整分段下限(不能低于当前位置)
            effective_lower = max(lower, current_pos)

            # 计算段内金额
            if upper == float("inf"):
                segment_amount = remaining
            else:
                segment_amount = min(remaining, upper - effective_lower)

            if segment_amount <= 0:
                continue

            # 计算该段自付
            actual_ratio = base_ratio * person_ratio
            segment_pay = segment_amount * actual_ratio

            # 记录计算过程（含规则溯源）
            result.segments.append(
                SegmentInfo(
                    lower=effective_lower,
                    upper=upper if upper != float("inf") else amount,
                    amount=segment_amount,
                    base_ratio=base_ratio,
                    person_ratio=person_ratio,
                    actual_ratio=actual_ratio,
                    pay=segment_pay,
                    calculation=f"{segment_amount:,.2f} × {base_ratio:.0%} × {person_ratio:.0%} = {segment_amount:,.2f} × {actual_ratio:.0%} = {segment_pay:,.2f}",
                    rule_id=rule_id,
                    policy_source=policy_source,
                )
            )

            result.total_pay += segment_pay
            remaining -= segment_amount
            current_pos = upper if upper != float("inf") else amount

        return result

    def _decompose_treatment(
        self,
        treatment: dict[str, Any],
        fee_details: list[dict[str, Any]],
        policy_rules: list[PolicyRule],
        segment_calc: SegmentCalculationResult,
        admission: dict[str, Any] | None = None,
    ) -> TreatmentDecomposition:
        """待遇分解"""
        # 计算医保外金额
        # 优先从 fee_details 汇总，如果没有则用 总费用 - 医保内 计算
        out_of_scope_from_details = sum(item.get("ybwje", 0) for item in fee_details)
        total_fee = treatment.get("bdfyzje", 0)
        in_scope = treatment.get("bdybnzje", 0)
        
        if out_of_scope_from_details > 0:
            out_of_scope = out_of_scope_from_details
        else:
            # fallback: 总费用 - 医保内
            out_of_scope = total_fee - in_scope if total_fee > in_scope else 0

        # 起付线从admission表获取
        deductible_amount = admission.get("bcqfje", 0) if admission else 0

        # 统筹内金额（tcfdhybn或估算值）
        pooling_amount, _ = self._derive_pooling_amount(treatment)

        # 统筹自付：以业务库结算字段为权威值，分段计算仅用于解释和对账
        pooling_self_pay = treatment.get("bdtczf", 0)

        return TreatmentDecomposition(
            total_fee=TreatmentItem(
                value=total_fee,
                source="yb_zyfdxx.bdfyzje",
            ),
            in_scope=TreatmentItem(
                value=in_scope,
                source="yb_zyfdxx.bdybnzje",
            ),
            deductible=TreatmentItem(
                value=deductible_amount,
                source="yb_dyxxzy.bcqfje",
                policy=self._find_deductible_rule(policy_rules),
                calculation="政策规定首次住院起付线",
            ),
            pooling_amount=pooling_amount,
            pooling_self_pay=TreatmentItem(
                value=pooling_self_pay,
                source="yb_zyfdxx.bdtczf",
                policy=self._find_ratio_rule(policy_rules, "统筹"),
                calculation=self._format_segment_calculation(segment_calc) if segment_calc.segments else "政策分段规则不足，无法稳定解释计算过程",
            ),
            pooling_payment=TreatmentItem(
                value=treatment.get("bdtczfje", 0),
                source="yb_zyfdxx.bdtczfje",
                policy=self._find_ratio_rule(policy_rules, "统筹"),
                calculation=f"统筹内金额 - 统筹自付 = {pooling_amount:,.2f} - {pooling_self_pay:,.2f} = {treatment.get('bdtczfje', 0):,.2f}",
            ),
            major_payment=TreatmentItem(
                value=treatment.get("bddegwyzfje", 0),
                source="yb_zyfdxx.bddegwyzfje",
                policy=self._find_ratio_rule(policy_rules, "大额"),
            ),
            major_self_pay=TreatmentItem(
                value=treatment.get("bddegwyzf", 0),
                source="yb_zyfdxx.bddegwyzf",
                policy=self._find_ratio_rule(policy_rules, "大额"),
            ),
            personal_liability=TreatmentItem(
                value=treatment.get("bdgryf", 0),
                source="yb_zyfdxx.bdgryf",
            ),
            out_of_scope=TreatmentItem(
                value=out_of_scope,
                source="yb_zyfymx.ybwje汇总" if out_of_scope_from_details > 0 else "总费用-医保内",
                policy=self._find_out_of_scope_rules(policy_rules),
            ),
        )

    def _decompose_fees(self, fee_details: list[dict[str, Any]]) -> FeeDecomposition:
        """费用分解(按收费项目等级)"""
        categories = {
            "甲类": {"total": 0, "in_scope": 0, "out_of_scope": 0, "items": []},
            "乙类": {"total": 0, "in_scope": 0, "out_of_scope": 0, "items": []},
            "丙类": {"total": 0, "in_scope": 0, "out_of_scope": 0, "items": []},
        }

        for item in fee_details:
            sfxmdj = item.get("sfxmdj", "")
            zje = item.get("zje", 0)
            ybnje = item.get("ybnje", 0)
            ybwje = item.get("ybwje", 0)

            if sfxmdj == "1":  # 甲类
                category = "甲类"
            elif sfxmdj == "2":  # 乙类
                category = "乙类"
            elif sfxmdj == "3":  # 丙类
                category = "丙类"
            else:
                continue

            categories[category]["total"] += zje
            categories[category]["in_scope"] += ybnje
            categories[category]["out_of_scope"] += ybwje
            categories[category]["items"].append(item)

        fee_categories = [
            FeeCategory(
                category=cat_name,
                total_amount=cat_data["total"],
                in_scope_amount=cat_data["in_scope"],
                out_of_scope_amount=cat_data["out_of_scope"],
                items=cat_data["items"],
            )
            for cat_name, cat_data in categories.items()
        ]

        total_amount = sum(cat.total_amount for cat in fee_categories)
        in_scope_total = sum(cat.in_scope_amount for cat in fee_categories)
        out_of_scope_total = sum(cat.out_of_scope_amount for cat in fee_categories)

        return FeeDecomposition(
            categories=fee_categories,
            total_amount=total_amount,
            in_scope_total=in_scope_total,
            out_of_scope_total=out_of_scope_total,
        )

    def _build_evidence(
        self,
        treatment: TreatmentDecomposition,
        fees: FeeDecomposition,
        segments: SegmentCalculationResult,
        fee_details: list[dict[str, Any]],
        policy_rules: list[PolicyRule],
    ) -> list[EvidenceItem]:
        """构建溯源证据"""
        evidence = []

        # 1. 待遇分解证据
        evidence.append(
            EvidenceItem(
                item="总费用",
                value=treatment.total_fee.value,
                source_table="yb_zyfdxx",
                source_field="bdfyzje",
            )
        )

        evidence.append(
            EvidenceItem(
                item="医保内",
                value=treatment.in_scope.value,
                source_table="yb_zyfdxx",
                source_field="bdybnzje",
            )
        )

        evidence.append(
            EvidenceItem(
                item="起付线",
                value=treatment.deductible.value,
                source_table="yb_dyxxzy",
                source_field="bcqfje",
                policy_rule={"rule_type": "起付线", "source_text": treatment.deductible.policy or ""},
            )
        )

        # 2. 分段计算证据
        evidence.append(
            EvidenceItem(
                item="统筹自付",
                value=segments.total_pay,
                source_table="yb_zyfdxx",
                source_field="bdtczf",
                calculation={
                    "formula": "统筹自付 = Σ(各分段金额 × 各分段自付比例 × 人员系数)",
                    "segments": [
                        {
                            "range": f"{seg.lower:,.0f}-{seg.upper:,.0f}",
                            "amount": seg.amount,
                            "base_ratio": seg.base_ratio,
                            "person_ratio": seg.person_ratio,
                            "actual_ratio": seg.actual_ratio,
                            "pay": seg.pay,
                        }
                        for seg in segments.segments
                    ],
                    "total": segments.total_pay,
                },
            )
        )

        # 3. 费用分解证据
        for cat in fees.categories:
            evidence.append(
                EvidenceItem(
                    item=f"{cat.category}费用",
                    value=cat.total_amount,
                    source_table="yb_zyfymx",
                    source_field="sfxmdj",
                    calculation={
                        "in_scope": cat.in_scope_amount,
                        "out_of_scope": cat.out_of_scope_amount,
                        "items_count": len(cat.items),
                    },
                )
            )

        return evidence

    def _find_deductible_rule(self, policy_rules: list[PolicyRule]) -> str:
        """查找起付线规则"""
        for rule in policy_rules:
            if rule.rule_type == "起付线":
                return rule.source_text
        return ""

    def _find_ratio_rule(self, policy_rules: list[PolicyRule], keyword: str) -> str:
        """查找比例规则"""
        for rule in policy_rules:
            if keyword in rule.rule_type and "比例" in rule.rule_type:
                return rule.source_text
        return ""

    def _find_out_of_scope_rules(self, policy_rules: list[PolicyRule]) -> str:
        """查找医保外规则"""
        out_of_scope_rules = []
        for rule in policy_rules:
            if "丙类" in rule.source_text or "自费" in rule.source_text:
                out_of_scope_rules.append(rule.source_text)
        return "；".join(out_of_scope_rules) if out_of_scope_rules else ""

    def _format_segment_calculation(self, segment_calc: SegmentCalculationResult) -> str:
        """格式化分段计算过程（含政策溯源）"""
        lines = ["统筹自付分段计算:"]
        for seg in segment_calc.segments:
            lines.append(f"  {seg.lower:,.0f}-{seg.upper:,.0f}: {seg.calculation}")
            if seg.policy_source:
                lines.append(f"    政策依据: {seg.policy_source}")
        lines.append(f"  合计: {segment_calc.total_pay:,.2f}")
        return "\n".join(lines)
