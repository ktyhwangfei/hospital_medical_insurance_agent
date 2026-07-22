from __future__ import annotations

import re

from .models import SearchQuery

def _parse_money_to_number(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*元?", text)
    if m:
        return float(m.group(1)) * 10000

    m = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
    if m:
        return float(m.group(1))

    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if nums:
        return float(nums[-1])

    return None


def understand_query(question: str) -> SearchQuery:
    q = question.strip()
    sq = SearchQuery(question=q)

    if any(k in q for k in ["起付线", "起付标准", "起付金额"]):
        sq.target_object = "deductible"
        sq.fact_types = ["deductible"]
    elif any(k in q for k in ["支付比例", "报销比例", "基金支付比例"]):
        sq.target_object = "payment_ratio"
        sq.fact_types = ["payment_ratio"]
    elif any(k in q for k in ["封顶线", "最高支付", "最高限额", "累计最高"]):
        sq.target_object = "cap"
        sq.fact_types = ["cap"]

    if any(k in q for k in ["为什么", "怎么算", "如何计算", "怎么得出", "计算过程"]):
        sq.intent = "explain_calculation"
        sq.need_calculation_explanation = True
        sq.need_formula = True

    target_value = _parse_money_to_number(q)
    if target_value is not None:
        sq.target_value = target_value
        if sq.intent == "explain_calculation" or "为什么" in q:
            sq.need_calculation_explanation = True
            sq.need_formula = True

    if sq.need_calculation_explanation and sq.target_object == "deductible":
        sq.fact_types = ["deductible", "formula"]

    if any(k in q for k in ["学生儿童", "学生", "儿童"]):
        sq.population = "student_child"
    elif any(k in q for k in ["成人", "老年人", "劳动年龄"]):
        sq.population = "adult"

    if "住院" in q:
        sq.service_type = "inpatient"
    elif "门诊" in q:
        sq.service_type = "outpatient"

    if "三级" in q:
        sq.hospital_level = "三级"
    elif "二级" in q:
        sq.hospital_level = "二级"
    elif "一级及以下" in q:
        sq.hospital_level = "一级及以下"
    elif "一级" in q:
        sq.hospital_level = "一级及以下"

    if any(k in q for k in ["首次", "第一次"]):
        sq.admission_order = "1"
    elif any(k in q for k in ["第二次及以后", "第二次以后", "二次及以后"]):
        sq.admission_order = ">=2"
    elif any(k in q for k in ["第二次", "二次"]):
        sq.admission_order = "2"

    if any(k in q for k in ["跨周期", "累计", "1950"]):
        if sq.target_object == "deductible":
            sq.need_calculation_explanation = True
            sq.need_formula = True
            sq.fact_types = ["deductible", "formula"]

    return sq
