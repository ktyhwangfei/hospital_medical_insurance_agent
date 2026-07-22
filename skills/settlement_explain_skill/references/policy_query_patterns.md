# 政策查询模式定义

本文档定义各费用项在 Milvus 中的政策查询模式。
查询模式 = 一组 StructuredPolicyQuery，每个 query 包含
query_name、filters、text_must_include 等。

## 1. 统筹自付（pooling_self_pay）

需要两类政策规则：三级医院分段支付比例 + 退休人员折算公式。

```yaml
queries:
  - query_name: employee_inpatient_tertiary_segment_ratio
    required: true
    search_type: structured
    filters:
      insu_type: 城镇职工基本医疗保险
      med_type: 住院-普通住院
      hosp_lv: 三级医院
      rule_type: 支付比例
    psn_type_allow_all: true
    text_must_include_any:
      - 起付标准至3万元
      - 超过3万元至4万元
      - 超过4万元
    description: 三级医院职工住院分段支付比例

  - query_name: retiree_personal_ratio_formula
    required: true
    search_type: structured
    filters:
      insu_type: 城镇职工基本医疗保险
      med_type: 住院-普通住院
      psn_type: 退休人员
      rule_type: 计算公式
    text_must_include_all:
      - 退休人员
      - 个人支付比例
      - 60%
    description: 退休人员折算公式
```

## 2. 起付线（deductible）

```yaml
queries:
  - query_name: deductible_standard
    required: true
    search_type: structured
    filters:
      insu_type: 城镇职工基本医疗保险
      med_type: 住院-普通住院
      hosp_lv: 三级医院
      rule_type: 起付线标准
    description: 三级医院住院起付线标准
```

## 3. 大额自付（large_amount_self_pay）

```yaml
queries:
  - query_name: large_amount_segment_ratio
    required: true
    search_type: structured
    filters:
      insu_type: 城镇职工基本医疗保险
      med_type: 住院-普通住院
      rule_type: 大额支付比例
    description: 大额保障段支付比例
```

## 4. 报销比例（通用）

当用户问题不指定具体费用项时，使用通用模板：

```yaml
queries:
  - query_name: general_payment_ratios
    required: true
    filters:
      insu_type: 城镇职工基本医疗保险
      rule_type: 支付比例
    psn_type_allow_all: true
    description: 通用支付比例规则
```
