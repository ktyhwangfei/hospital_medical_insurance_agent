# 医保办视角解释模板

本模板用于生成专业口径的解释，按审核说明格式输出。

## 输出结构

### 一、字段来源

本次解释对象为"{target_field}"，金额为 {target_amount} 元。
取自真实结算结果字段。

### 二、结算上下文

- 参保体系：{insurance_type}
- 人员类别：{person_type}
- 医疗类别：{service_type}
- 医院等级：{hospital_level}
- 起付线：{deductible} 元
- 医保内费用：{medical_insurance_inner_amount} 元
- 基本统筹支付：{basic_pooling_payment} 元
- 基本统筹自付：{basic_pooling_self_pay} 元
- 大额支付：{large_amount_payment} 元
- 大额自付：{large_amount_self_pay} 元
- 个人总支付：{personal_total_pay} 元

### 三、适用政策规则

{% if employee_segments %}
本次为 {insurance_type} {person_type} {hospital_level} {service_type}，
匹配到 {hospital_level} 住院分段支付比例：

{% for seg in employee_segments %}
- {{ seg.band }}：统筹基金支付 {{ seg.fund_ratio }}%，职工个人支付 {{ seg.employee_self_ratio }}%
{% endfor %}

{% if retiree_factor %}
同时，本次人员类别为 {person_type}，匹配到退休人员折算规则：
- 退休人员个人支付比例为职工个人支付比例的 {{ retiree_factor }}%

因此，退休人员在上述分段中的个人负担比例为：
{% for seg in retiree_segments %}
- {{ seg.band }}：{{ seg.employee_self_ratio }}% × {{ retiree_factor }}% = {{ seg.retiree_self_ratio }}%
{% endfor %}
{% else %}
（退休人员折算公式未匹配到。）
{% endif %}
{% else %}
（适用政策规则未匹配。）
{% endif %}

### 四、金额口径说明

{target_amount} 元不是通过"医保内费用 - 统筹支付"简单倒推得到，
也不包含起付线、大额自付、目录外费用。
它是结算系统在完成起付线扣减、统筹段归集、年度累计、封顶线控制和
分段比例计算后，写入基本统筹自付字段的结果。

### 五、当前解释完整性

{% for item in completed %}
- 已完成：{item}
{% endfor %}

如果需要做到逐分段复算 {target_amount} 元，
还需要进一步返回每个分段实际进入金额、年度统筹累计和封顶线占用明细。
