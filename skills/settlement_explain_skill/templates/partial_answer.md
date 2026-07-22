# "部分回答" 模板

当 `can_answer = true` 但 `partial_answer = true` 时使用本模板。

## 使用条件

- 有真实结算数据 ✅
- 政策依据不完整 ⚠️

## 输出结构

### 【重要提示】

⚠️ 当前已匹配部分政策依据，以下解释可能不完整。

{target_field} 金额为 {target_amount} 元（来源于真实结算数据）。

已匹配的政策规则：
{% for evidence in policy_evidence %}
- {evidence.source_text | clean_json}
{% endfor %}

缺失的政策依据：
{% for missing in missing_evidence %}
- {missing}
{% endfor %}

### 【金额关系（基于真实数据）】

- 起付线 {deductible} 元
- 统筹支付 {basic_pooling_payment} 元
- 统筹自付 {basic_pooling_self_pay} 元

当前解释的是结算字段口径和已匹配的部分政策规则。
若要获得完整的政策依据解释，需要补充上述缺失的政策规则。
