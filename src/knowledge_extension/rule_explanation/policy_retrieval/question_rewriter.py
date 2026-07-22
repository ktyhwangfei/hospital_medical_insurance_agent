from __future__ import annotations

from .case_context import CaseContext


POPULATION_LABELS = {
    "adult": "成人",
    "student_child": "学生儿童",
    "all": "",
    "unknown": "",
}

INSURANCE_LABELS = {
    "urban_rural_resident": "城乡居民医保",
    "employee": "职工医保",
    "unknown": "",
}

SERVICE_LABELS = {
    "inpatient": "住院",
    "outpatient": "门诊",
    "unknown": "",
}


# def rewrite_question(question: str, context: CaseContext) -> str:
#     parts: list[str] = []

#     if context.hospital_level and context.hospital_level != "unknown":
#         parts.append(f"{context.hospital_level}医院")

#     if context.population:
#         label = POPULATION_LABELS.get(context.population, context.population)
#         if label:
#             parts.append(label)

#     if context.insurance_type:
#         label = INSURANCE_LABELS.get(context.insurance_type, context.insurance_type)
#         if label:
#             parts.append(label)

#     if context.admission_order == "1":
#         parts.append("首次")
#     elif context.admission_order in ["2", ">=2"]:
#         parts.append("第二次及以后")

#     if context.service_type:
#         label = SERVICE_LABELS.get(context.service_type, context.service_type)
#         if label:
#             parts.append(label)

#     if context.target_object == "deductible":
#         parts.append("起付线")
#     elif context.target_object == "payment_ratio":
#         parts.append("支付比例")
#     elif context.target_object == "cap":
#         parts.append("最高支付限额")

#     prefix = "".join(parts) or question

#     if context.target_amount is not None:
#         return f"{prefix}为什么是{context.target_amount:g}元？"

#     if any(k in question for k in ["为什么", "怎么算", "如何计算"]):
#         return f"{prefix}为什么？"

#     return f"{prefix}是多少？"




def rewrite_question(question: str, context: CaseContext) -> str:
    context_lines = []

    def add(label: str, value):
        if value not in [None, "", "unknown"]:
            context_lines.append(f"{label}: {value}")

    add("医院等级", context.hospital_level)
    add("人员类别", context.population)
    add("险种类型", context.insurance_type)
    add("服务类型", context.service_type)
    add("住院顺序", context.admission_order)
    add("结算年度", context.settlement_year)
    add("目标金额", context.target_amount)
    add("目标对象", context.target_object)

    if not context_lines:
        return question

    return (
        "请结合以下业务上下文回答用户问题。\n"
        "【业务上下文】\n"
        + "\n".join(context_lines)
        + "\n\n【用户问题】\n"
        + question
    )
