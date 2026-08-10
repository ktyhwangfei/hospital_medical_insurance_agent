"""政策规则折算展开（问题2修复）。

把相对/折算比例规则在入库时物化成多条绝对比例规则，避免运行时计算、让按人群检索直接命中。

典型场景：退休人员个人支付比例 = 职工个人支付比例 × 60%。
- 折算规则：psn_type=退休人员，rule_value 含「×60%」/「为职工支付比例的60%」，payment_ratio 空。
- 基数规则：rule_type=支付比例，psn_type=在职职工，rule_value 含「职工个人支付X%」
  （payment_ratio 存的是统筹基金支付比例，个人支付比例只在 rule_value 文本里）。
- 展开：基数个人支付 X × 系数 → 退休规则（psn_type=退休人员, personal_payment_ratio=绝对值,
  复用 hosp_lv/amount_band/med_type/insu_type，基金支付比例在职=退休不变一并复用）。

设计要点：
- 纯函数、不依赖外部服务；对 build_ingest_records 产出的 rule_entities 后处理，追加派生规则。
- 不改 schema：personal_payment_ratio 走 detail FieldTrace（U2 已加进 DETAIL_FIELDS）。
- 派生规则溯源：rule_value 注明折算公式与基数；source_text 继承折算规则原文。
"""
from __future__ import annotations

import re
import uuid
from typing import Any

# 折算系数：rule_value 中「×60%」「×0.6」「为…的60%」
_FACTOR_RE = re.compile(r"[×xX]\s*(\d+(?:\.\d+)?)\s*%|[×xX]\s*(0?\.\d+)|为.{0,12}的\s*(\d+(?:\.\d+)?)\s*%")
# 基数个人支付比例：rule_value 中「职工个人支付15%」「个人支付13%」
_PERSONAL_PCT_RE = re.compile(r"(?:职工)?个人支付\s*(\d+(?:\.\d+)?)\s*[%％]")


def _detail_value(entity: dict[str, Any], field: str) -> str:
    """取 rule_entity 的详情字段裸值（FieldTrace dict → .value；裸值直取）。"""
    v = entity.get(field)
    if isinstance(v, dict):
        v = v.get("value")
    return str(v or "").strip()


def _has_retiree(entity: dict[str, Any]) -> bool:
    psn = str(entity.get("psn_type") or "")
    return "退休" in psn


def _has_employee(entity: dict[str, Any]) -> bool:
    psn = str(entity.get("psn_type") or "")
    return "在职" in psn


def _extract_factor(rule_value: str) -> float | None:
    """从折算规则 rule_value 提取乘数系数（60%→0.6）。"""
    m = _FACTOR_RE.search(rule_value)
    if not m:
        return None
    for g in m.groups():
        if g is None:
            continue
        try:
            val = float(g)
        except ValueError:
            continue
        # 「×60%」「为…的60%」→ 百分比转小数；「×0.6」→ 直接是小数
        if val > 1:
            return round(val / 100, 4)
        return val
    return None


def _extract_personal_pct(rule_value: str) -> float | None:
    """从基数规则 rule_value 反解析职工个人支付比例（15%→15.0，百分数值）。"""
    m = _PERSONAL_PCT_RE.search(rule_value)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _ft(value: Any, extracted_at: str = "", confidence: float = 0.7) -> dict[str, Any]:
    """构造 FieldTrace（与 rule_to_entity 的详情字段格式一致）。"""
    return {
        "value": value,
        "extracted_at": extracted_at,
        "schema_version": 1,
        "confidence": confidence,
    }


def derive_personal_payment_ratios(rule_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """折算展开：从退休×系数规则 + 在职基数规则物化退休 personal_payment_ratio 绝对值规则。

    按文档分组展开（折算规则与基数规则须同 doc_id）。返回追加的派生规则，不修改输入。
    """
    if not rule_entities:
        return []

    derived: list[dict[str, Any]] = []
    # 按 doc_id 分组（跨文档不混）
    docs: dict[str, list[dict[str, Any]]] = {}
    for e in rule_entities:
        docs.setdefault(str(e.get("doc_id") or ""), []).append(e)

    for doc_rules in docs.values():
        derived.extend(_derive_one_doc(doc_rules))
    return derived


def _derive_one_doc(rule_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """单文档内展开。"""

    # 1. 找折算规则（退休 + rule_value 含系数）
    factor_rules: list[dict[str, Any]] = []
    for e in rule_entities:
        if not _has_retiree(e):
            continue
        coef = _extract_factor(_detail_value(e, "rule_value"))
        if coef is not None:
            factor_rules.append((e, coef))

    if not factor_rules:
        return []

    # 2. 找基数规则（在职 + 支付比例 + rule_value 含职工个人支付X%）
    base_rules: list[dict[str, Any]] = []
    for e in rule_entities:
        if str(e.get("rule_type") or "") != "支付比例":
            continue
        if not _has_employee(e):
            continue
        personal = _extract_personal_pct(_detail_value(e, "rule_value"))
        if personal is not None:
            base_rules.append((e, personal))

    if not base_rules:
        return []

    # 3. 展开：每条折算规则 × 每条匹配基数 → 退休 personal_payment_ratio 绝对值
    derived: list[dict[str, Any]] = []
    for factor_rule, coef in factor_rules:
        for base_rule, base_personal in base_rules:
            # 维度对齐：折算规则说「同级别医院、同费用段」→ 继承基数维度
            hosp_lv = base_rule.get("hosp_lv") or ""
            amount_band = _detail_value(base_rule, "amount_band")
            med_type = base_rule.get("med_type") or ""
            insu_type = base_rule.get("insu_type") or ""
            setl_type = base_rule.get("setl_type") or ""

            result_pct = round(base_personal * coef, 4)
            result_str = f"{result_pct:g}%"
            base_str = f"{base_personal:g}%"

            base_fund = _detail_value(base_rule, "payment_ratio")  # 基金支付比例在职=退休，复用
            rv = (
                f"退休人员个人支付比例 = 同级别医院、同费用段职工个人支付比例{base_str} × {coef*100:g}%"
                f" = {result_str}（折算派生）"
            )

            entity: dict[str, Any] = {
                "rule_id": f"rule_{uuid.uuid4().hex[:12]}",
                "fact_id": factor_rule.get("fact_id", ""),
                "doc_id": factor_rule.get("doc_id", ""),
                "rule_type": "支付比例",
                "insu_type": insu_type,
                "med_type": med_type,
                "hosp_lv": hosp_lv,
                "psn_type": "退休人员",
                "setl_type": setl_type,
                "schema_version": factor_rule.get("schema_version", 1),
                "vector": factor_rule.get("vector") or [0.0] * 8,
                # 详情字段（FieldTrace）
                "payment_ratio": _ft(base_fund),  # 基金支付比例在职=退休，复用
                "personal_payment_ratio": _ft(result_str),
                "amount_band": _ft(amount_band),
                "rule_value": _ft(rv),
                "source_text": _ft(_detail_value(factor_rule, "source_text") or _detail_value(factor_rule, "rule_value")),
                # 溯源：系数 + 基数引用
                "personal_payment_coefficient": _ft(coef),
                "referenced_clause": _ft("职工个人支付比例"),
            }
            derived.append(entity)
    return derived
