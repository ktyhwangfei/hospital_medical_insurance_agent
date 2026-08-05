# 单一答案解释模板

本模板用于生成面向当前院端经办角色的自然语言解释。

## 模板变量

| 变量 | 来源 | 说明 |
|------|------|------|
| `{target_amount}` | case_context | 目标金额（如 4,962.67） |
| `{deductible}` | case_context | 起付线金额 |
| `{basic_pooling_payment}` | case_context | 统筹支付金额 |
| `{basic_pooling_self_pay}` | case_context | 统筹自付金额 |
| `{large_amount_self_pay}` | case_context | 大额自付金额 |
| `{personal_total_pay}` | case_context | 个人总支付金额 |
| `{target_field}` | — | 目标字段中文名（如 "统筹自付"） |
| `{person_type}` | case_context | 人员类别 |
| `{insurance_type}` | case_context | 险种 |
| `{hospital_level}` | case_context | 医院等级 |
| `{has_complete}` | evidence | 政策是否完整 |

## 输出结构

### 【本次结论】

本次结算中，您的"{target_field}"为 {target_amount} 元。

### 【这是什么钱】

这笔钱不是全部自费，也不是大额自付，而是已经进入基本医保统筹报销范围后，
按照政策比例仍需要个人承担的部分。

### 【本次适用的政策依据】

根据已匹配到的政策，本次 {insurance_type} {hospital_level} {service_type}
费用按以下规则报销：

{% for evidence in policy_evidence %}
政策依据 {{ loop.index }}：
政策原文摘录：
"{{ evidence.source_text | clean_json }}"

本次适用原因：
{{ evidence.applied_reason }}
{% endfor %}

### 【政策比例怎么影响您】

根据已匹配到的政策规则，三级医院住院费用不是由医保 100% 报销，
而是按费用区间分段支付：

{% for seg in employee_segments %}
{{ loop.index }}. {{ seg.band }}：
   统筹基金支付 {{ seg.fund_ratio }}%，职工个人支付 {{ seg.employee_self_ratio }}%
{% endfor %}

{% if retiree_factor %}
您本次属于退休人员，政策还规定：
退休人员个人支付比例为职工个人支付比例的 {{ retiree_factor }}%。

所以退休人员实际个人承担比例为：

{% for seg in retiree_segments %}
{{ loop.index }}. {{ seg.band }}：
   {{ seg.employee_self_ratio }}% × {{ retiree_factor }}% = {{ seg.retiree_self_ratio }}%
{% endfor %}

因此，{target_amount} 元不是系统随意给出的金额，
而是本次结算在真实结算数据基础上，按照三级医院住院分段支付比例
和退休人员折算规则形成的基本统筹段个人承担金额。
{% endif %}

### 【本次金额关系】

- 起付线 {deductible} 元：医保开始报销前，先由个人承担的部分
- 统筹支付 {basic_pooling_payment} 元：基本医保统筹基金已经支付的部分
- 统筹自付 {basic_pooling_self_pay} 元：基本医保统筹段内，按比例由个人承担的部分
- 大额自付 {large_amount_self_pay} 元：进入大额保障段后个人承担的部分，和统筹自付不是一回事
- 个人总支付 {personal_total_pay} 元：包含多类个人负担，不等于统筹自付

### 【一句话总结】

{target_amount} 是"基本医保统筹段内按政策比例需要您个人承担的钱"，
不包含起付线、大额自付、医保外费用和目录先行自付。

{% if not has_complete %}
当前解释的是政策口径和结算结果，若要逐段复算还需要分段金额明细。
{% endif %}
