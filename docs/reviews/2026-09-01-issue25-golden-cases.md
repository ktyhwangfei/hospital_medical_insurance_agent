# Issue #25 黄金用例集

> 生成时间：2026-09-01T11:41:56
> 用例总数：58 条
> 覆盖维度：地区、政策时间、人群、医疗类别、医院等级、异地/转诊、金额分段、政策替代、宽泛问题

## 标注口径

1. **期望规则（expected_rule_ids）**：由人工根据结算上下文与政策文本判定必须召回的规则 rule_id。
2. **负例**：`is_negative=True` 表示该场景下不应召回任何规则；命中即视为错误适用。
3. **结算上下文**：包含 `insu_type`/`med_type`/`hosp_lv`/`psn_type`/`region`/`settlement_date`/`is_remote`。
4. **默认地区**：当 `region` 为空时，系统默认使用北京。
5. **默认时间**：当 `settlement_date` 为空时，不过滤有效期。
6. **宽泛问题**：无结算上下文，仅依赖自然语言问题；用于测试文本召回+适用性字段精排。

## 用例列表

| 编号 | 场景 | 维度 | 地区 | 结算日期 | 期望规则数 | 负例 | 备注 |
|------|------|------|------|----------|------------|------|------|
| BJ_EMP_TERT_IP_BAND_1 | 北京在职职工三级医院住院，起付标准至3万元 | 地区,人群,医院等级,医疗类别,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_EMP_TERT_IP_BAND_2 | 北京在职职工三级医院住院，超过3万元至4万元 | 地区,人群,医院等级,医疗类别,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_EMP_TERT_IP_BAND_3 | 北京在职职工三级医院住院，超过4万元 | 地区,人群,医院等级,医疗类别,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_EMP_SEC_IP_BAND_1 | 北京在职职工二级医院住院，起付标准至3万元 | 医院等级 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_EMP_SEC_IP_BAND_2 | 北京在职职工二级医院住院，超过3万元至4万元 | 医院等级 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_EMP_SEC_IP_BAND_3 | 北京在职职工二级医院住院，超过4万元 | 医院等级 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_RET_TERT_IP_FORMULA | 北京退休人员三级医院住院，需命中折算公式 | 人群,政策替代 | 北京 | 2024-06-15 | 1 | 否 | 应同时命中公式与物化规则，但期望至少命中公式 |
| BJ_RET_TERT_IP_BAND_1 | 北京退休人员三级医院住院第1档 | 人群,金额分段,政策替代 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_RET_TERT_IP_BAND_2 | 北京退休人员三级医院住院第2档 | 人群,金额分段,政策替代 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_RET_TERT_IP_BAND_3 | 北京退休人员三级医院住院第3档 | 人群,金额分段,政策替代 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_EMP_TERT_OP | 北京在职职工三级医院门诊 | 医疗类别 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_EMP_REMOTE | 北京参保人异地三级医院住院 | 异地/转诊 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_EMP_TERT_IP_2025 | 2025年北京在职职工三级医院住院 | 政策时间,政策版本 | 北京 | 2025-03-01 | 1 | 否 |  |
| BJ_EMP_TERT_IP_2025_BAND2 | 2025年北京在职职工三级医院住院，超过3万元至4万元 | 政策时间,政策版本,金额分段 | 北京 | 2025-03-01 | 1 | 否 |  |
| SH_EMP_TERT_IP | 上海在职职工三级医院住院 | 地区,金额分段 | 上海 | 2024-06-15 | 1 | 否 |  |
| BJ_RESIDENT_TERT_IP | 北京城乡居民三级医院住院 | 人群,险种 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_DEDUCT_TERT | 北京职工三级医院住院起付线 | 医疗类别,规则类型 | 北京 | 2024-06-15 | 1 | 否 |  |
| BJ_CAP | 北京职工住院封顶线 | 规则类型 | 北京 | 2024-06-15 | 1 | 否 |  |
| NEG_EXPIRED_2023 | 2024年结算不应命中已废止的2023规则 | 政策时间,发布状态,反例 | 北京 | 2024-06-15 | 0 | 是 | 2023规则 expiry_date=2023-12-31，不应命中 |
| NEG_FUTURE_2025 | 2024年结算不应命中2025年才生效规则 | 政策时间,反例 | 北京 | 2024-06-15 | 0 | 是 | 2025规则 effective_date=2025-01-01，不应命中 |
| NEG_REGION_SH | 北京结算不应命中上海规则 | 地区,反例 | 北京 | 2024-06-15 | 0 | 是 |  |
| NEG_PILOT | 非试点地区不应命中试点规则 | 发布状态,反例 | 北京 | 2024-06-15 | 0 | 是 | pilot 规则 publish_status=pilot，非默认 published |
| NEG_REMOTE_FALSE | 本地结算不应命中异地规则 | 异地/转诊,反例 | 北京 | 2024-06-15 | 0 | 是 |  |
| NEG_POP_STUDENT | 学生儿童不应命中在职职工规则 | 人群,反例 | 北京 | 2024-06-15 | 0 | 是 |  |
| NEG_HOSP_PRIMARY | 一级医院不应命中三级医院规则 | 医院等级,反例 | 北京 | 2024-06-15 | 0 | 是 |  |
| NEG_OUTPATIENT_VS_IP | 住院场景不应命中门诊规则 | 医疗类别,反例 | 北京 | 2024-06-15 | 0 | 是 |  |
| NEG_INSU_RESIDENT | 职工不应命中城乡居民规则 | 险种,反例 | 北京 | 2024-06-15 | 0 | 是 |  |
| NEG_REVOKED | 不应命中已撤销规则 | 发布状态,反例 | 北京 | 2024-06-15 | 0 | 是 | BJ_2023_IP_TERT_EMP_001 publish_status=revoked |
| BJ_RET_SEC_IP | 北京退休人员二级医院住院 | 人群,医院等级 | 北京 | 2024-06-15 | 1 | 否 | 语料未覆盖二级退休，测试诚实拒答或近似召回 |
| BJ_EMP_TERT_IP_BAND_ALL | 北京在职职工三级医院住院全段 | 金额分段,完整回答 | 北京 | 2024-06-15 | 3 | 否 |  |
| BJ_EMP_TERT_IP_NEAR_EXPIRY | 2024-12-30结算应仍命中2024规则 | 政策时间,边界 | 北京 | 2024-12-30 | 1 | 否 |  |
| BJ_EMP_TERT_IP_EXPIRY_DAY | 2024-12-31结算仍命中2024规则 | 政策时间,边界 | 北京 | 2024-12-31 | 1 | 否 |  |
| BJ_EMP_TERT_IP_NEW_YEAR | 2025-01-01结算命中2025规则 | 政策时间,政策版本,边界 | 北京 | 2025-01-01 | 1 | 否 |  |
| BJ_EMP_TERT_IP_DEFAULT_REGION | 结算上下文未提供地区，默认北京 | 地区,默认值 |  | 2024-06-15 | 1 | 否 | region 空 → 默认北京 |
| BJ_EMP_TERT_IP_NO_DATE | 结算上下文未提供结算日期，应不过滤时间 | 政策时间,默认值 | 北京 |  | 1 | 否 | 无日期不过期过滤，可能多召回，正例只要包含2024即可 |
| SH_EMP_TERT_IP_NO_REGION | 未提供地区时不应误命中上海规则 | 地区,反例 |  | 2024-06-15 | 0 | 是 | region 默认北京，上海规则不应命中 |
| BJ_EMP_TERT_IP_DRAFT | 草稿规则不应进入 Runtime | 发布状态,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料无 draft 规则，此用例验证过滤逻辑存在性 |
| BJ_EMP_TERT_IP_VERSION_MISMATCH | 明确指定政策版本2024时不应命中2025规则 | 政策版本,反例 | 北京 | 2025-06-15 | 1 | 否 | 当前 retrieve 未消费 policy_version 过滤，此用例记录待增强点 |
| BULK_051 | 北京在职职工三级医院住院第1档 | 地区,人群,医院等级,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_052 | 北京在职职工三级医院住院第2档 | 金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_053 | 北京在职职工三级医院住院第3档 | 金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_054 | 北京在职职工二级医院住院第1档 | 医院等级,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_055 | 北京在职职工二级医院住院第2档 | 医院等级,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_056 | 北京在职职工二级医院住院第3档 | 医院等级,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_057 | 北京退休人员三级医院住院第4档 | 人群,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_058 | 北京退休人员三级医院住院第5档 | 人群,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_059 | 北京退休人员三级医院住院第6档 | 人群,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_060 | 北京退休人员三级医院住院第7档 | 人群,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_061 | 北京退休人员三级医院住院第8档 | 人群,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BULK_062 | 北京退休人员三级医院住院第9档 | 人群,金额分段 | 北京 | 2024-06-15 | 1 | 否 |  |
| BROAD_DEDUCTIBLE | 宽泛问：北京住院起付线多少 | 宽泛问题 |  |  | 1 | 否 | 无结算上下文，依赖文本召回+适用性字段精排 |
| BROAD_CAP | 宽泛问：北京医保封顶线 | 宽泛问题 |  |  | 1 | 否 |  |
| BROAD_RETIREE_RATIO | 宽泛问：退休人员住院个人支付比例 | 宽泛问题,人群 |  |  | 1 | 否 |  |
| BROAD_REMOTE | 宽泛问：异地就医报销比例 | 宽泛问题,异地/转诊 |  |  | 1 | 否 |  |
| BROAD_OUTPATIENT | 宽泛问：门诊报销比例 | 宽泛问题,医疗类别 |  |  | 1 | 否 |  |
| BROAD_SHANGHAI | 宽泛问：上海住院报销 | 宽泛问题,地区 |  |  | 1 | 否 |  |
| BROAD_AMOUNT_BAND | 宽泛问：超过3万元至4万元报销比例 | 宽泛问题,金额分段 |  |  | 1 | 否 |  |
| BROAD_VERSION | 宽泛问：2025年北京住院新规 | 宽泛问题,政策版本 |  |  | 1 | 否 | 无结算日期，无法做时间过滤，可能多版本召回 |

## 用例原始数据

```json
[
  {
    "case_id": "BJ_EMP_TERT_IP_BAND_1",
    "scenario": "北京在职职工三级医院住院，起付标准至3万元",
    "dimensions": [
      "地区",
      "人群",
      "医院等级",
      "医疗类别",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 35000.0
    },
    "question": "北京在职职工三级医院住院，起付标准至3万元的支付比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_IP_BAND_2",
    "scenario": "北京在职职工三级医院住院，超过3万元至4万元",
    "dimensions": [
      "地区",
      "人群",
      "医院等级",
      "医疗类别",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 45000.0
    },
    "question": "北京在职职工三级医院住院，超过3万元至4万元的支付比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_002"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_IP_BAND_3",
    "scenario": "北京在职职工三级医院住院，超过4万元",
    "dimensions": [
      "地区",
      "人群",
      "医院等级",
      "医疗类别",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 55000.0
    },
    "question": "北京在职职工三级医院住院，超过4万元的支付比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_003"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_SEC_IP_BAND_1",
    "scenario": "北京在职职工二级医院住院，起付标准至3万元",
    "dimensions": [
      "医院等级"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "二级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 35000.0
    },
    "question": "北京在职职工二级医院住院，起付标准至3万元的支付比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_IP_SEC_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_SEC_IP_BAND_2",
    "scenario": "北京在职职工二级医院住院，超过3万元至4万元",
    "dimensions": [
      "医院等级"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "二级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 45000.0
    },
    "question": "北京在职职工二级医院住院，超过3万元至4万元的支付比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_IP_SEC_EMP_002"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_SEC_IP_BAND_3",
    "scenario": "北京在职职工二级医院住院，超过4万元",
    "dimensions": [
      "医院等级"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "二级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 55000.0
    },
    "question": "北京在职职工二级医院住院，超过4万元的支付比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_IP_SEC_EMP_003"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_RET_TERT_IP_FORMULA",
    "scenario": "北京退休人员三级医院住院，需命中折算公式",
    "dimensions": [
      "人群",
      "政策替代"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院，统筹自付怎么算？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_FORMULA_001"
    ],
    "is_negative": false,
    "notes": "应同时命中公式与物化规则，但期望至少命中公式"
  },
  {
    "case_id": "BJ_RET_TERT_IP_BAND_1",
    "scenario": "北京退休人员三级医院住院第1档",
    "dimensions": [
      "人群",
      "金额分段",
      "政策替代"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第1档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_RET_TERT_IP_BAND_2",
    "scenario": "北京退休人员三级医院住院第2档",
    "dimensions": [
      "人群",
      "金额分段",
      "政策替代"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第2档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_002"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_RET_TERT_IP_BAND_3",
    "scenario": "北京退休人员三级医院住院第3档",
    "dimensions": [
      "人群",
      "金额分段",
      "政策替代"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第3档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_003"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_OP",
    "scenario": "北京在职职工三级医院门诊",
    "dimensions": [
      "医疗类别"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 500.0
    },
    "question": "北京在职职工三级医院门诊报销比例？",
    "expected_rule_ids": [
      "BJ_2024_OP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_REMOTE",
    "scenario": "北京参保人异地三级医院住院",
    "dimensions": [
      "异地/转诊"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": true,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京参保人异地就医三级医院住院支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_REMOTE_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_IP_2025",
    "scenario": "2025年北京在职职工三级医院住院",
    "dimensions": [
      "政策时间",
      "政策版本"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2025-03-01",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "2025年北京在职职工三级医院住院支付比例？",
    "expected_rule_ids": [
      "BJ_2025_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_IP_2025_BAND2",
    "scenario": "2025年北京在职职工三级医院住院，超过3万元至4万元",
    "dimensions": [
      "政策时间",
      "政策版本",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2025-03-01",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 35000.0
    },
    "question": "2025年北京在职职工三级医院住院，3-4万元段支付比例？",
    "expected_rule_ids": [
      "BJ_2025_IP_TERT_EMP_002"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "SH_EMP_TERT_IP",
    "scenario": "上海在职职工三级医院住院",
    "dimensions": [
      "地区",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "上海",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "上海在职职工三级医院住院支付比例？",
    "expected_rule_ids": [
      "SH_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_RESIDENT_TERT_IP",
    "scenario": "北京城乡居民三级医院住院",
    "dimensions": [
      "人群",
      "险种"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "居民",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京城乡居民三级医院住院支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_RESIDENT_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_DEDUCT_TERT",
    "scenario": "北京职工三级医院住院起付线",
    "dimensions": [
      "医疗类别",
      "规则类型"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "起付线",
      "target_amount": 1300.0
    },
    "question": "北京职工三级医院住院起付线多少？",
    "expected_rule_ids": [
      "BJ_2024_DEDUCT_TERT_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_CAP",
    "scenario": "北京职工住院封顶线",
    "dimensions": [
      "规则类型"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "封顶线",
      "target_amount": 500000.0
    },
    "question": "北京职工住院年度最高支付限额是多少？",
    "expected_rule_ids": [
      "BJ_2024_CAP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "NEG_EXPIRED_2023",
    "scenario": "2024年结算不应命中已废止的2023规则",
    "dimensions": [
      "政策时间",
      "发布状态",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "2024年结算是否适用2023年已废止规则？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": "2023规则 expiry_date=2023-12-31，不应命中"
  },
  {
    "case_id": "NEG_FUTURE_2025",
    "scenario": "2024年结算不应命中2025年才生效规则",
    "dimensions": [
      "政策时间",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "2024年结算是否适用2025年规则？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": "2025规则 effective_date=2025-01-01，不应命中"
  },
  {
    "case_id": "NEG_REGION_SH",
    "scenario": "北京结算不应命中上海规则",
    "dimensions": [
      "地区",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京参保人在上海规则里报销？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": ""
  },
  {
    "case_id": "NEG_PILOT",
    "scenario": "非试点地区不应命中试点规则",
    "dimensions": [
      "发布状态",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "非试点地区是否适用试点报销比例？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": "pilot 规则 publish_status=pilot，非默认 published"
  },
  {
    "case_id": "NEG_REMOTE_FALSE",
    "scenario": "本地结算不应命中异地规则",
    "dimensions": [
      "异地/转诊",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "本地住院是否适用异地报销规则？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": ""
  },
  {
    "case_id": "NEG_POP_STUDENT",
    "scenario": "学生儿童不应命中在职职工规则",
    "dimensions": [
      "人群",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "学生儿童",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "学生儿童住院是否按在职职工比例报销？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": ""
  },
  {
    "case_id": "NEG_HOSP_PRIMARY",
    "scenario": "一级医院不应命中三级医院规则",
    "dimensions": [
      "医院等级",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "一级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "一级医院住院是否按三级医院比例？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": ""
  },
  {
    "case_id": "NEG_OUTPATIENT_VS_IP",
    "scenario": "住院场景不应命中门诊规则",
    "dimensions": [
      "医疗类别",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "住院统筹自付是否适用门诊比例？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": ""
  },
  {
    "case_id": "NEG_INSU_RESIDENT",
    "scenario": "职工不应命中城乡居民规则",
    "dimensions": [
      "险种",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "城镇职工是否适用城乡居民规则？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": ""
  },
  {
    "case_id": "NEG_REVOKED",
    "scenario": "不应命中已撤销规则",
    "dimensions": [
      "发布状态",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "已撤销规则是否仍适用？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": "BJ_2023_IP_TERT_EMP_001 publish_status=revoked"
  },
  {
    "case_id": "BJ_RET_SEC_IP",
    "scenario": "北京退休人员二级医院住院",
    "dimensions": [
      "人群",
      "医院等级"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "二级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员二级医院住院支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_001"
    ],
    "is_negative": false,
    "notes": "语料未覆盖二级退休，测试诚实拒答或近似召回"
  },
  {
    "case_id": "BJ_EMP_TERT_IP_BAND_ALL",
    "scenario": "北京在职职工三级医院住院全段",
    "dimensions": [
      "金额分段",
      "完整回答"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京在职职工三级医院住院各段支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_001",
      "BJ_2024_IP_TERT_EMP_002",
      "BJ_2024_IP_TERT_EMP_003"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_IP_NEAR_EXPIRY",
    "scenario": "2024-12-30结算应仍命中2024规则",
    "dimensions": [
      "政策时间",
      "边界"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-12-30",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "2024年底结算适用哪版规则？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_IP_EXPIRY_DAY",
    "scenario": "2024-12-31结算仍命中2024规则",
    "dimensions": [
      "政策时间",
      "边界"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-12-31",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "2024年最后一天结算适用规则？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_IP_NEW_YEAR",
    "scenario": "2025-01-01结算命中2025规则",
    "dimensions": [
      "政策时间",
      "政策版本",
      "边界"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2025-01-01",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "2025年第一天结算适用规则？",
    "expected_rule_ids": [
      "BJ_2025_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BJ_EMP_TERT_IP_DEFAULT_REGION",
    "scenario": "结算上下文未提供地区，默认北京",
    "dimensions": [
      "地区",
      "默认值"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "未提供地区时默认适用北京规则？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": "region 空 → 默认北京"
  },
  {
    "case_id": "BJ_EMP_TERT_IP_NO_DATE",
    "scenario": "结算上下文未提供结算日期，应不过滤时间",
    "dimensions": [
      "政策时间",
      "默认值"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "无结算日期时是否返回所有版本规则？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": "无日期不过期过滤，可能多召回，正例只要包含2024即可"
  },
  {
    "case_id": "SH_EMP_TERT_IP_NO_REGION",
    "scenario": "未提供地区时不应误命中上海规则",
    "dimensions": [
      "地区",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "未提供地区时是否会召回上海规则？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": "region 默认北京，上海规则不应命中"
  },
  {
    "case_id": "BJ_EMP_TERT_IP_DRAFT",
    "scenario": "草稿规则不应进入 Runtime",
    "dimensions": [
      "发布状态",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "草稿规则是否会被召回？",
    "expected_rule_ids": [],
    "is_negative": true,
    "notes": "语料无 draft 规则，此用例验证过滤逻辑存在性"
  },
  {
    "case_id": "BJ_EMP_TERT_IP_VERSION_MISMATCH",
    "scenario": "明确指定政策版本2024时不应命中2025规则",
    "dimensions": [
      "政策版本",
      "反例"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2025-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0,
      "policy_version": "2024"
    },
    "question": "指定2024版本时不应命中2025规则？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": "当前 retrieve 未消费 policy_version 过滤，此用例记录待增强点"
  },
  {
    "case_id": "BULK_051",
    "scenario": "北京在职职工三级医院住院第1档",
    "dimensions": [
      "地区",
      "人群",
      "医院等级",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京在职职工三级医院住院第1档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_052",
    "scenario": "北京在职职工三级医院住院第2档",
    "dimensions": [
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京在职职工三级医院住院第2档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_002"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_053",
    "scenario": "北京在职职工三级医院住院第3档",
    "dimensions": [
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京在职职工三级医院住院第3档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_003"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_054",
    "scenario": "北京在职职工二级医院住院第1档",
    "dimensions": [
      "医院等级",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "二级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京在职职工二级医院住院第1档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_SEC_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_055",
    "scenario": "北京在职职工二级医院住院第2档",
    "dimensions": [
      "医院等级",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "二级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京在职职工二级医院住院第2档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_SEC_EMP_002"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_056",
    "scenario": "北京在职职工二级医院住院第3档",
    "dimensions": [
      "医院等级",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "二级",
      "psn_type": "在职职工",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京在职职工二级医院住院第3档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_SEC_EMP_003"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_057",
    "scenario": "北京退休人员三级医院住院第4档",
    "dimensions": [
      "人群",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第4档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_004"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_058",
    "scenario": "北京退休人员三级医院住院第5档",
    "dimensions": [
      "人群",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第5档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_005"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_059",
    "scenario": "北京退休人员三级医院住院第6档",
    "dimensions": [
      "人群",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第6档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_006"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_060",
    "scenario": "北京退休人员三级医院住院第7档",
    "dimensions": [
      "人群",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第7档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_007"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_061",
    "scenario": "北京退休人员三级医院住院第8档",
    "dimensions": [
      "人群",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第8档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_008"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BULK_062",
    "scenario": "北京退休人员三级医院住院第9档",
    "dimensions": [
      "人群",
      "金额分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "住院-普通住院",
      "hosp_lv": "三级",
      "psn_type": "退休人员",
      "region": "北京",
      "settlement_date": "2024-06-15",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "北京退休人员三级医院住院第9档的支付比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_TERT_009"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BROAD_DEDUCTIBLE",
    "scenario": "宽泛问：北京住院起付线多少",
    "dimensions": [
      "宽泛问题"
    ],
    "settlement_context": {},
    "question": "北京住院起付线多少？",
    "expected_rule_ids": [
      "BJ_2024_DEDUCT_TERT_001"
    ],
    "is_negative": false,
    "notes": "无结算上下文，依赖文本召回+适用性字段精排"
  },
  {
    "case_id": "BROAD_CAP",
    "scenario": "宽泛问：北京医保封顶线",
    "dimensions": [
      "宽泛问题"
    ],
    "settlement_context": {},
    "question": "北京医保封顶线是多少？",
    "expected_rule_ids": [
      "BJ_2024_CAP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BROAD_RETIREE_RATIO",
    "scenario": "宽泛问：退休人员住院个人支付比例",
    "dimensions": [
      "宽泛问题",
      "人群"
    ],
    "settlement_context": {},
    "question": "退休人员住院个人支付比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_IP_RET_FORMULA_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BROAD_REMOTE",
    "scenario": "宽泛问：异地就医报销比例",
    "dimensions": [
      "宽泛问题",
      "异地/转诊"
    ],
    "settlement_context": {},
    "question": "异地就医报销比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_IP_REMOTE_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BROAD_OUTPATIENT",
    "scenario": "宽泛问：门诊报销比例",
    "dimensions": [
      "宽泛问题",
      "医疗类别"
    ],
    "settlement_context": {},
    "question": "门诊报销比例是多少？",
    "expected_rule_ids": [
      "BJ_2024_OP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BROAD_SHANGHAI",
    "scenario": "宽泛问：上海住院报销",
    "dimensions": [
      "宽泛问题",
      "地区"
    ],
    "settlement_context": {},
    "question": "上海住院报销比例是多少？",
    "expected_rule_ids": [
      "SH_2024_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BROAD_AMOUNT_BAND",
    "scenario": "宽泛问：超过3万元至4万元报销比例",
    "dimensions": [
      "宽泛问题",
      "金额分段"
    ],
    "settlement_context": {},
    "question": "住院费用超过3万元至4万元报销比例？",
    "expected_rule_ids": [
      "BJ_2024_IP_TERT_EMP_002"
    ],
    "is_negative": false,
    "notes": ""
  },
  {
    "case_id": "BROAD_VERSION",
    "scenario": "宽泛问：2025年北京住院新规",
    "dimensions": [
      "宽泛问题",
      "政策版本"
    ],
    "settlement_context": {},
    "question": "2025年北京住院有什么新报销政策？",
    "expected_rule_ids": [
      "BJ_2025_IP_TERT_EMP_001"
    ],
    "is_negative": false,
    "notes": "无结算日期，无法做时间过滤，可能多版本召回"
  }
]
```
