"""费用计算器 — 纯业务逻辑，只依赖 tool_interfaces.py。

每个计算器负责一种 target_fee_item 的计算逻辑。
新增费用项时在此文件添加计算器类，并在底部 CALCULATOR_REGISTRY 注册。
"""

import re

from .tool_interfaces import PatientSettlementData, PolicyRule


# ── 统筹自付分段计算 ────────────────────────────────────────────

class FeeDecompositionCalculator:
    """统筹自付 = Σ(各分段金额 × 各分段自付比例)"""

    def calculate(
        self,
        sql_data: PatientSettlementData,
        policy_rules: list[PolicyRule],
    ) -> dict:
        treatment = sql_data.treatment or {}
        patient_info = sql_data.patient_info or {}

        # 1. 提取关键参数
        total_fee = treatment.get("total_fee", 0)
        in_scope = treatment.get("in_scope", 0)
        deductible = treatment.get("deductible", 0)
        pooling_self_pay_authoritative = treatment.get("pooling_self_pay", 0)
        pooling_payment = treatment.get("pooling_payment", 0)
        major_self_pay = treatment.get("major_self_pay", 0)
        major_payment = treatment.get("major_payment", 0)
        out_of_scope = treatment.get("out_of_scope", 0)
        personal_liability = treatment.get("personal_liability", 0)

        # 2. 确定人员类型和对应的系数
        person_type = str(patient_info.get("person_type", "在职"))
        is_retired = "退休" in person_type
        fund_type = str(patient_info.get("fund_type", "城镇职工"))

        # 3. 构建分段规则（从政策规则中提取）
        segments = self._build_segments(in_scope, deductible, fund_type, is_retired, policy_rules)

        # 4. 分段计算
        total_calculated = 0.0
        for seg in segments:
            seg["person_ratio"] = self._get_person_ratio(fund_type, is_retired)
            seg["actual_ratio"] = seg["base_ratio"] * seg["person_ratio"]
            seg["pay"] = round(seg["amount"] * seg["actual_ratio"], 2)
            total_calculated += seg["pay"]

        # 5. 与权威金额对账
        reconciliation = {
            "authoritative_amount": pooling_self_pay_authoritative,
            "calculated_amount": round(total_calculated, 2),
            "difference": round(pooling_self_pay_authoritative - total_calculated, 2),
            "tolerance": 0.01,
            "matched": abs(pooling_self_pay_authoritative - total_calculated) < 0.01,
            "message": (
                "计算与结算结果一致"
                if abs(pooling_self_pay_authoritative - total_calculated) < 0.01
                else "政策解释计算与结算结果存在差异，需要人工复核"
            ),
        }

        return {
            "treatment": {
                "total_fee": total_fee,
                "in_scope": in_scope,
                "deductible": deductible,
                "pooling_self_pay": pooling_self_pay_authoritative,
                "pooling_payment": pooling_payment,
                "major_self_pay": major_self_pay,
                "major_payment": major_payment,
                "out_of_scope": out_of_scope,
                "personal_liability": personal_liability,
            },
            "segments": {
                "segments": segments,
                "total_pay": round(total_calculated, 2),
                "reconciliation": reconciliation,
            },
            "evidence_count": len(policy_rules),
        }

    def _build_segments(self, in_scope, deductible, fund_type, is_retired, rules):
        """从政策规则中构建分段信息"""
        segments = []
        # 起付线以下段
        if deductible > 0:
            ded_amount = min(deductible, in_scope)
            segments.append({
                "lower": 0,
                "upper": deductible,
                "amount": ded_amount,
                "base_ratio": 0.0,
                "person_ratio": 0.0,
                "actual_ratio": 0.0,
                "pay": 0.0,
                "rule_id": "deductible_rule",
                "policy_source": "起付线规则",
                "calculation": f"起付线以下: {ded_amount:,.2f} × 0% = 0",
            })

        remaining = max(0, in_scope - deductible)

        # 从规则中提取分段比例
        band_rules = [r for r in rules if r.rule_type == "payment_ratio"]
        for rule in band_rules:
            band = self._parse_band(rule.evidence_text)
            if band and band["lower"] < band.get("upper", float("inf")):
                upper = band["upper"]
                if remaining <= 0:
                    break
                seg_amount = min(upper - band["lower"], remaining)
                if seg_amount > 0:
                    segments.append({
                        "lower": band["lower"],
                        "upper": upper,
                        "amount": seg_amount,
                        "base_ratio": band["ratio"],
                        "person_ratio": 0.0,  # filled later
                        "actual_ratio": 0.0,  # filled later
                        "pay": 0.0,           # filled later
                        "rule_id": rule.clause or "",
                        "policy_source": rule.title or rule.clause or "",
                        "calculation": (
                            f"{seg_amount:,.2f} × {band['ratio']*100:.1f}% × "
                            f"人员系数（待定）"
                        ),
                    })
                remaining -= seg_amount

        return segments

    def _parse_band(self, text: str) -> dict | None:
        """从政策条文解析分段信息，如 '3万-4万: 10%' → {lower: 30000, upper: 40000, ratio: 0.10}"""
        if not text:
            return None
        band_match = re.search(
            r'(\d+\.?\d*)\s*[-~万到至]+\s*(\d+\.?\d*)\s*[万:：]*\s*(\d+\.?\d*)\s*%?',
            text
        )
        if band_match:
            lower_val = float(band_match.group(1))
            upper_val = float(band_match.group(2))
            ratio_val = float(band_match.group(3))
            # 如果数值较小（<100），可能是以"万"为单位
            if lower_val < 100:
                lower_val *= 10000
            if upper_val < 100:
                upper_val *= 10000
            if ratio_val > 1:
                ratio_val /= 100
            return {"lower": lower_val, "upper": upper_val, "ratio": ratio_val}
        return None

    def _get_person_ratio(self, fund_type: str, is_retired: bool) -> float:
        """获取人员系数 — 退休人员 60%，在职人员 100%"""
        return 0.6 if is_retired else 1.0


# ── 个人应付计算 ────────────────────────────────────────

class PersonalLiabilityCalculator:
    """个人应付 = 统筹自付 + 大额自付 + 医保外"""

    def calculate(
        self,
        sql_data: PatientSettlementData,
        policy_rules: list[PolicyRule],
    ) -> dict:
        treatment = sql_data.treatment or {}
        total_fee = treatment.get("total_fee", 0)
        pooling_self_pay = treatment.get("pooling_self_pay", 0)
        major_self_pay = treatment.get("major_self_pay", 0)
        out_of_scope = treatment.get("out_of_scope", 0)
        personal_liability = treatment.get("personal_liability", 0)
        in_scope = treatment.get("in_scope", 0)
        deductible = treatment.get("deductible", 0)
        pooling_payment = treatment.get("pooling_payment", 0)
        major_payment = treatment.get("major_payment", 0)

        return {
            "treatment": {
                "total_fee": total_fee,
                "in_scope": in_scope,
                "deductible": deductible,
                "pooling_self_pay": pooling_self_pay,
                "pooling_payment": pooling_payment,
                "major_self_pay": major_self_pay,
                "major_payment": major_payment,
                "out_of_scope": out_of_scope,
                "personal_liability": personal_liability,
            },
            "components": [
                {
                    "label": "统筹自付",
                    "amount": pooling_self_pay,
                    "percentage": round(pooling_self_pay / personal_liability * 100, 1) if personal_liability > 0 else 0,
                    "source": "统筹基金分段计算（起付线以上按比例个人自付）",
                },
                {
                    "label": "大额自付",
                    "amount": major_self_pay,
                    "percentage": round(major_self_pay / personal_liability * 100, 1) if personal_liability > 0 else 0,
                    "source": "大额医疗费用补助个人自付部分",
                },
                {
                    "label": "医保外",
                    "amount": out_of_scope,
                    "percentage": round(out_of_scope / personal_liability * 100, 1) if personal_liability > 0 else 0,
                    "source": "不在医保目录内的费用（丙类、自费等）",
                },
            ],
            "evidence_count": len(policy_rules),
        }


# ── 起付线解释 ──────────────────────────────────────────

class DeductibleExplainer:
    """解释当前结算的起付线规则"""

    def calculate(
        self,
        sql_data: PatientSettlementData,
        policy_rules: list[PolicyRule],
    ) -> dict:
        treatment = sql_data.treatment or {}
        patient_info = sql_data.patient_info or {}

        deductible = treatment.get("deductible", 0)
        in_scope = treatment.get("in_scope", 0)

        deductible_rules = [r for r in policy_rules if r.rule_type == "deductible"]

        return {
            "treatment": {
                "deductible": deductible,
                "in_scope": in_scope,
                "fund_type": patient_info.get("fund_type", ""),
                "person_type": patient_info.get("person_type", ""),
                "medical_type": patient_info.get("medical_type", ""),
            },
            "rules": [
                {
                    "clause": r.clause or "",
                    "evidence": r.evidence_text or "",
                    "matched_reason": r.matched_reason or "",
                }
                for r in deductible_rules
            ],
            "summary": (
                f"当前结算起付线为 {deductible:,.2f} 元，"
                f"医保内金额 {in_scope:,.2f} 元，"
                f"其中起付线以下 {min(deductible, in_scope):,.2f} 元由个人全额负担"
            ),
            "evidence_count": len(deductible_rules),
        }


# ── 医保外费用解释 ──────────────────────────────────────

class OutOfScopeCalculator:
    """解释医保外费用构成"""

    def calculate(
        self,
        sql_data: PatientSettlementData,
        policy_rules: list[PolicyRule],
    ) -> dict:
        treatment = sql_data.treatment or {}
        fee_details = sql_data.fee_details or []

        total_fee = treatment.get("total_fee", 0)
        out_of_scope = treatment.get("out_of_scope", 0)
        out_of_scope_percentage = round(out_of_scope / total_fee * 100, 1) if total_fee > 0 else 0

        # 分类医保外费用
        categories: dict[str, float] = {}
        for fee in fee_details:
            if isinstance(fee, dict) and fee.get("reimbursement_category") in ("丙类", "自费", "out_of_scope"):
                cat = str(fee.get("category", "其他"))
                amount = float(fee.get("amount", 0))
                categories[cat] = categories.get(cat, 0) + amount

        return {
            "treatment": {
                "total_fee": total_fee,
                "out_of_scope": out_of_scope,
                "out_of_scope_percentage": out_of_scope_percentage,
            },
            "categories": [
                {"name": name, "amount": amount}
                for name, amount in sorted(categories.items(), key=lambda x: -x[1])
            ],
            "summary": (
                f"医保外费用合计 {out_of_scope:,.2f} 元，"
                f"占总费用 {out_of_scope_percentage}%"
            ),
            "evidence_count": len(policy_rules),
        }


# ── 计算器注册表 ─────────────────────────────────────────

CALCULATOR_REGISTRY = {
    "FeeDecompositionCalculator":  FeeDecompositionCalculator,
    "PersonalLiabilityCalculator": PersonalLiabilityCalculator,
    "DeductibleExplainer":         DeductibleExplainer,
    "OutOfScopeCalculator":        OutOfScopeCalculator,
}
