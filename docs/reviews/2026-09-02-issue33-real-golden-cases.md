# Issue #33 真实语料黄金用例集（门诊+通用规则）

> 生成时间：2026-09-02T19:36:54
> 用例总数：82 条
> 覆盖维度：地区、政策时间、人群、医疗类别、医院等级、异地/转诊、金额分段、政策替代、宽泛问题

## 标注口径

1. **期望规则（expected_rule_ids）**：由人工根据结算上下文与政策文本判定必须召回的规则 rule_id。
2. **负例**：`is_negative=True` 表示该场景下不应召回任何规则；命中即视为错误适用。
3. **结算上下文**：包含 `insu_type`/`med_type`/`hosp_lv`/`psn_type`/`region`/`settlement_date`/`is_remote`。
4. **默认地区**：当 `region` 为空时，系统默认使用北京。
5. **默认时间**：当 `settlement_date` 为空时，不过滤有效期。
6. **宽泛问题**：无结算上下文，仅依赖自然语言问题；用于测试文本召回+适用性字段精排。
7. **跳过**（仅真实语料模式）：`skip=True` 表示该用例考查的机制在真实语料中不存在，不计入指标。
8. **真实正向用例**（仅真实语料模式）：`REAL_*` 前缀用例为基于真实规则全文通读标注的正向用例，notes 含标注依据（重复对/碎片/冲突规则的计入与排除理由），标注不依据检索结果反推。

## 用例列表

| 编号 | 场景 | 维度 | 地区 | 结算日期 | 期望规则数 | 负例 | 备注 |
|------|------|------|------|----------|------------|------|------|
| BJ_EMP_TERT_IP_BAND_1 | 北京在职职工三级医院住院，起付标准至3万元 | 地区,人群,医院等级,医疗类别,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_EMP_TERT_IP_BAND_2 | 北京在职职工三级医院住院，超过3万元至4万元 | 地区,人群,医院等级,医疗类别,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_EMP_TERT_IP_BAND_3 | 北京在职职工三级医院住院，超过4万元 | 地区,人群,医院等级,医疗类别,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_EMP_SEC_IP_BAND_1 | 北京在职职工二级医院住院，起付标准至3万元 | 医院等级 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_EMP_SEC_IP_BAND_2 | 北京在职职工二级医院住院，超过3万元至4万元 | 医院等级 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_EMP_SEC_IP_BAND_3 | 北京在职职工二级医院住院，超过4万元 | 医院等级 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_RET_TERT_IP_FORMULA | 北京退休人员三级医院住院，需命中折算公式 | 人群,政策替代 | 北京 | 2024-06-15 | 0 | 是 | 语料无住院退休折算规则（退休规则均为门诊比例/个人账户划入），期望诚实拒答 |
| BJ_RET_TERT_IP_BAND_1 | 北京退休人员三级医院住院第1档 | 人群,金额分段,政策替代 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_RET_TERT_IP_BAND_2 | 北京退休人员三级医院住院第2档 | 人群,金额分段,政策替代 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_RET_TERT_IP_BAND_3 | 北京退休人员三级医院住院第3档 | 人群,金额分段,政策替代 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_EMP_TERT_OP | 北京在职职工三级医院门诊 | 医疗类别 | 北京 | 2024-06-15 | 2 | 否 | 真实语料门诊比例按金额段拆分（2万以下70% / 2万以上60%），完整答案需两条同时召回；语料另有门诊大额互助规则（rule_2003952d3afc 70%），属另一政策维度不计入期望 |
| BJ_EMP_REMOTE | 北京参保人异地三级医院住院 | 异地/转诊 | 北京 | 2024-06-15 | 0 | 是 | 语料无异地就医支付比例规则（仅居民异地备案/手工报销流程规则），且 is_remote 字段全缺失，期望诚实拒答 |
| BJ_EMP_TERT_IP_2025 | 2025年北京在职职工三级医院住院 | 政策时间,政策版本 | 北京 | 2025-03-01 | 0 | 是 | 语料无 2025 版规则且无有效期字段，期望诚实拒答 |
| BJ_EMP_TERT_IP_2025_BAND2 | 2025年北京在职职工三级医院住院，超过3万元至4万元 | 政策时间,政策版本,金额分段 | 北京 | 2025-03-01 | 0 | 是 | 语料无 2025 版规则且无有效期字段，期望诚实拒答 |
| SH_EMP_TERT_IP | 上海在职职工三级医院住院 | 地区,金额分段 | 上海 | 2024-06-15 | 0 | 是 | 语料全部为本市（北京）政策，无上海规则，期望诚实拒答 |
| BJ_RESIDENT_TERT_IP | 北京城乡居民三级医院住院 | 人群,险种 | 北京 | 2024-06-15 | 0 | 是 | 居民住院规则按范围纪律排除，语料仅含居民门诊/通用规则，期望诚实拒答 |
| BJ_DEDUCT_TERT | 北京职工三级医院住院起付线 | 医疗类别,规则类型 | 北京 | 2024-06-15 | 0 | 是 | 语料无住院起付线规则（仅门诊起付线），期望诚实拒答；若召回门诊起付线则暴露医疗类别混淆 |
| BJ_CAP | 北京职工住院封顶线 | 规则类型 | 北京 | 2024-06-15 | 1 | 否 | rule_e44e75c149f9（10万元）med_type 为空属通用规则，适用住院场景；rule_eb4c465e6f2e 仅引用第三十三条无数值，不计入期望 |
| NEG_EXPIRED_2023 | 2024年结算不应命中已废止的2023规则 | 政策时间,发布状态,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料无有效期字段亦无 2023 已废止规则，期望诚实拒答 |
| NEG_FUTURE_2025 | 2024年结算不应命中2025年才生效规则 | 政策时间,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料无有效期字段亦无 2025 未来规则，期望诚实拒答 |
| NEG_REGION_SH | 北京结算不应命中上海规则 | 地区,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料无上海规则且 region 字段全缺失，期望诚实拒答 |
| NEG_PILOT | 非试点地区不应命中试点规则 | 发布状态,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料 publish_status 字段全缺失、无试点规则，期望诚实拒答 |
| NEG_REMOTE_FALSE | 本地结算不应命中异地规则 | 异地/转诊,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料 is_remote 字段全缺失，期望诚实拒答 |
| NEG_POP_STUDENT | 学生儿童不应命中在职职工规则 | 人群,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料无住院规则，学生儿童住院问题期望诚实拒答 |
| NEG_HOSP_PRIMARY | 一级医院不应命中三级医院规则 | 医院等级,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料无住院规则，期望诚实拒答 |
| NEG_OUTPATIENT_VS_IP | 住院场景不应命中门诊规则 | 医疗类别,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料含大量门诊规则，验证住院场景不误召回门诊规则，期望诚实拒答 |
| NEG_INSU_RESIDENT | 职工不应命中城乡居民规则 | 险种,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料同时含职工与居民规则，验证险种隔离：职工上下文不应召回居民规则 |
| NEG_REVOKED | 不应命中已撤销规则 | 发布状态,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料无 publish_status 字段、无已撤销规则，期望诚实拒答 |
| BJ_RET_SEC_IP | 北京退休人员二级医院住院 | 人群,医院等级 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_EMP_TERT_IP_BAND_ALL | 北京在职职工三级医院住院全段 | 金额分段,完整回答 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BJ_EMP_TERT_IP_NEAR_EXPIRY | 2024-12-30结算应仍命中2024规则 | 政策时间,边界 | 北京 | 2024-12-30 | 1 | 跳过 | 跳过：语料 effective_date/expiry_date 字段全缺失，时间边界过滤无法评估 |
| BJ_EMP_TERT_IP_EXPIRY_DAY | 2024-12-31结算仍命中2024规则 | 政策时间,边界 | 北京 | 2024-12-31 | 1 | 跳过 | 跳过：语料 effective_date/expiry_date 字段全缺失，时间边界过滤无法评估 |
| BJ_EMP_TERT_IP_NEW_YEAR | 2025-01-01结算命中2025规则 | 政策时间,政策版本,边界 | 北京 | 2025-01-01 | 1 | 跳过 | 跳过：语料无有效期字段且无多版本规则，版本切换边界无法评估 |
| BJ_EMP_TERT_IP_DEFAULT_REGION | 结算上下文未提供地区，默认北京 | 地区,默认值 |  | 2024-06-15 | 1 | 跳过 | 跳过：语料 region 字段全缺失（全部为本市政策），默认地区逻辑无法评估 |
| BJ_EMP_TERT_IP_NO_DATE | 结算上下文未提供结算日期，应不过滤时间 | 政策时间,默认值 | 北京 |  | 1 | 跳过 | 跳过：语料无有效期字段，无结算日期场景退化为普通过滤，评测价值低 |
| SH_EMP_TERT_IP_NO_REGION | 未提供地区时不应误命中上海规则 | 地区,反例 |  | 2024-06-15 | 0 | 是 | 语料无上海规则，期望诚实拒答 |
| BJ_EMP_TERT_IP_DRAFT | 草稿规则不应进入 Runtime | 发布状态,反例 | 北京 | 2024-06-15 | 0 | 是 | 语料无 publish_status 字段、无草稿规则，期望诚实拒答 |
| BJ_EMP_TERT_IP_VERSION_MISMATCH | 明确指定政策版本2024时不应命中2025规则 | 政策版本,反例 | 北京 | 2025-06-15 | 1 | 跳过 | 跳过：语料 policy_version 字段全缺失，版本过滤机制无法评估 |
| BULK_051 | 北京在职职工三级医院住院第1档 | 地区,人群,医院等级,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_052 | 北京在职职工三级医院住院第2档 | 金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_053 | 北京在职职工三级医院住院第3档 | 金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_054 | 北京在职职工二级医院住院第1档 | 医院等级,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_055 | 北京在职职工二级医院住院第2档 | 医院等级,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_056 | 北京在职职工二级医院住院第3档 | 医院等级,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_057 | 北京退休人员三级医院住院第4档 | 人群,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_058 | 北京退休人员三级医院住院第5档 | 人群,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_059 | 北京退休人员三级医院住院第6档 | 人群,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_060 | 北京退休人员三级医院住院第7档 | 人群,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_061 | 北京退休人员三级医院住院第8档 | 人群,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BULK_062 | 北京退休人员三级医院住院第9档 | 人群,金额分段 | 北京 | 2024-06-15 | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BROAD_DEDUCTIBLE | 宽泛问：北京住院起付线多少 | 宽泛问题 |  |  | 0 | 是 | 语料无住院起付线规则（仅门诊起付线），期望诚实拒答；若召回门诊起付线则暴露医疗类别混淆 |
| BROAD_CAP | 宽泛问：北京医保封顶线 | 宽泛问题 |  |  | 2 | 否 | 问题未限定险种：职工统筹封顶10万与居民大病封顶15万均为有效答案；rule_eb4c465e6f2e 无数值不计入 |
| BROAD_RETIREE_RATIO | 宽泛问：退休人员住院个人支付比例 | 宽泛问题,人群 |  |  | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BROAD_REMOTE | 宽泛问：异地就医报销比例 | 宽泛问题,异地/转诊 |  |  | 0 | 是 | 语料无异地就医支付比例规则（仅备案/垫付流程规则），期望诚实拒答 |
| BROAD_OUTPATIENT | 宽泛问：门诊报销比例 | 宽泛问题,医疗类别 |  |  | 1 | 否 | 问题未限定人群/险种，语料另有退休及居民门诊比例规则（rule_0c31054fbb71 / rule_cda56c7057bb1edd 等），其召回计为 FAR 信号 |
| BROAD_SHANGHAI | 宽泛问：上海住院报销 | 宽泛问题,地区 |  |  | 0 | 是 | 真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答 |
| BROAD_AMOUNT_BAND | 宽泛问：超过3万元至4万元报销比例 | 宽泛问题,金额分段 |  |  | 0 | 是 | 语料无 3万-4万 住院分段规则（大病保险分段为 5 万档），期望诚实拒答 |
| BROAD_VERSION | 宽泛问：2025年北京住院新规 | 宽泛问题,政策版本 |  |  | 0 | 是 | 语料无 2025 年规则，期望诚实拒答 |
| REAL_OP_EMP_DEDUCT | 在职职工门诊起付标准 | 真实正向,门诊起付线 |  |  | 1 | 否 | 唯一在职门诊起付线规则（1800元），语料无其他在职门诊起付线 |
| REAL_OP_RET_DEDUCT | 退休人员门诊起付标准 | 真实正向,门诊起付线 |  |  | 2 | 否 | 两条均为1300元：rule_bc4c8deba3574b52 为退休人员通用表述，rule_aac09533029c03a5 为70岁以上专项表述（rule_type=deductible），问题未限定年龄两者均应召回 |
| REAL_OP_EMP_SEC_BAND1 | 在职职工二级医院门诊2万元以下支付比例 | 真实正向,门诊分段 |  |  | 1 | 否 | 二级在职2万以下档唯一无冲突（统筹70%）；一级同档存在 rule_0412833fee42d9d1/rule_ccc47eef94d825d8/rule_f7226be3f086fdcf 三条冲突值（0.9/0.1/0.3），属数据质量问题，故选二级档标注 |
| REAL_OP_EMP_BAND2 | 在职职工门诊超过2万元支付比例 | 真实正向,门诊分段 |  |  | 2 | 否 | 两条均表述在职2万以上统筹60%；rule_1b5d162145d9c088 为同事实碎片（source_text 仅 "60%。"），维度完全一致计入期望 |
| REAL_OP_RET_BAND1 | 退休人员门诊2万元以下支付比例 | 真实正向,门诊分段 |  |  | 2 | 否 | 退休2万以下按年龄分档：70岁以下85%（rule_ca52d442e0eb77f8）+ 70岁以上90%（rule_63a423fab0492787），完整答案需两条同时召回；医院等级变体（一级90%等）与通用档数值冲突，属数据质量问题不计入 |
| REAL_OP_RET_BAND2 | 退休人员门诊超过2万元支付比例 | 真实正向,门诊分段 |  |  | 2 | 否 | 两条均表述退休2万以上80%；rule_31a8f163639447e4 为同事实碎片（"80%。"）计入期望 |
| REAL_LMAA_EMP_COMMUNITY | 在职职工社区门诊大额互助报销比例 | 真实正向,大额互助 |  |  | 2 | 否 | 在职社区门诊大额互助90%；rule_63e89e926492ebd8 为同事实碎片（"90%。"，rule_type=large_medical_mutual_aid_payment_ratio）计入期望 |
| REAL_LMAA_RET_COMMUNITY | 退休人员社区门诊报销比例 | 真实正向,大额互助 |  |  | 2 | 否 | 退休社区门诊90%（含大额互助80%+统一补充）；rule_4df372b59673556e 完整复述同一事实计入期望；80% 组件规则（rule_25721ca05b5d/rule_3222a148156d8c7d）仅回答大额互助子项，不计入 |
| REAL_LMAA_NON_COMMUNITY | 在职职工非社区门诊大额互助报销比例 | 真实正向,大额互助 |  |  | 1 | 否 | 非社区门诊大额互助70%（hosp_lv=无等级）；碎片 rule_69fc18433e6a7364 同为0.7但 hosp_lv 误标一级（与政策矛盾，一级社区应为90%），属数据冲突不计入 |
| REAL_DBI_DEDUCT | 城乡居民大病保险起付标准 | 真实正向,大病保险 |  |  | 1 | 否 | 2019年起付标准30404元（按上年度城镇居民20%低收入户人均可支配收入），语料唯一起付标准数值规则 |
| REAL_DBI_DEDUCT_POOR | 困难人员大病保险起付标准 | 真实正向,大病保险 |  |  | 1 | 否 | 困难人员起付标准降低一半（15202元），规则自身含数值可直接作答；基准规则 rule_5c825a5842dc 提供上下文但不直接回答困难标准，不计入 |
| REAL_DBI_RATIO_BAND1 | 困难人员大病5万元以内支付比例 | 真实正向,大病保险 |  |  | 1 | 否 | 5万以内档由60%提高至65%（amount_band=0-50000，困难人群），唯一对应规则 |
| REAL_DBI_RATIO_BAND2 | 困难人员大病超过5万元支付比例 | 真实正向,大病保险 |  |  | 1 | 否 | 超过5万档由70%提高至75%（amount_band=50000-，困难人群），唯一对应规则 |
| REAL_DBI_TILT_DIBAO | 低保对象大病保险倾斜政策 | 真实正向,大病保险 |  |  | 3 | 否 | 低保倾斜三件套：起付标准降低50% + 支付比例提高5个百分点 + 取消最高支付限额；完整答案恰为3条=TOP_K，测试多规则完整召回 |
| REAL_RES_OP_DEDUCT | 城乡居民门诊起付标准 | 真实正向,居民门诊 |  |  | 2 | 否 | 一级及以下100元 + 二级及以上550元，同一原文句按医院等级拆成两条，完整答案需同时召回 |
| REAL_RES_OP_RATIO | 城乡居民门诊支付比例 | 真实正向,居民门诊 |  |  | 2 | 否 | 一级55% + 二级及以上50%（年度累计封顶3000元），同一原文句拆分两条，需同时召回 |
| REAL_RES_OP_POOL50 | 居民门诊统筹支付比例下限 | 真实正向,居民门诊 |  |  | 1 | 否 | 门诊统筹支付比例不低于50%（doc_7ec146a78b34），唯一对应规则；与 REAL_RES_OP_RATIO 的分段比例属不同政策口径 |
| REAL_ER_OBS | 急诊留观费用报销规则 | 真实正向,急诊留观 |  |  | 1 | 否 | 急诊留观费用按住院医疗费用报销规定执行，语料唯一急诊留观支付规则 |
| REAL_FIRST_DIAG_REFERRAL | 居民门诊基层首诊与转诊规定 | 真实正向,居民门诊 |  |  | 3 | 否 | 首诊制度 + 凭首诊转诊证明转诊 + 转诊有效180天，三条构成完整流程；rule_956cc41cfe44（未经首诊不予支付，排除规则）属后果条款不计入 |
| REAL_MENTE_SCOPE | 城乡居民特殊病种范围 | 真实正向,门特 |  |  | 1 | 否 | 门特病种清单规则（恶性肿瘤门诊治疗/血友病/肾透析等），唯一对应规则 |
| REAL_MENTE_PAY | 门特费用支付标准 | 真实正向,门特 |  |  | 1 | 否 | 门特费用按住院标准支付，唯一对应规则 |
| REAL_MENTE_SETTLE | 门特结算期规则 | 真实正向,门特 |  |  | 2 | 否 | 当年备案者自备案首次就医至年度截止 + 一般情形按每保险年度一个结算期，两条互补构成完整答案 |
| REAL_ACCOUNT_45P | 45周岁以上在职职工个人账户划入比例 | 真实正向,个人账户 |  |  | 2 | 否 | 45+ 按缴费工资基数2%划入；语料存在 source_text 完全相同的重复对，两者均应视为有效答案（用于检验召回侧去重/并列行为） |
| REAL_PREMIUM | 职工基本医疗保险缴费比例 | 真实正向,缴费 |  |  | 2 | 否 | 个人按上年月平均工资2% + 单位按缴费工资基数之和9%，两条互补构成完整答案 |

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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无住院退休折算规则（退休规则均为门诊比例/个人账户划入），期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
      "rule_bd19807063be1fd8",
      "rule_e04620a0f3dffeb2"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "真实语料门诊比例按金额段拆分（2万以下70% / 2万以上60%），完整答案需两条同时召回；语料另有门诊大额互助规则（rule_2003952d3afc 70%），属另一政策维度不计入期望"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无异地就医支付比例规则（仅居民异地备案/手工报销流程规则），且 is_remote 字段全缺失，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无 2025 版规则且无有效期字段，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无 2025 版规则且无有效期字段，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料全部为本市（北京）政策，无上海规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "居民住院规则按范围纪律排除，语料仅含居民门诊/通用规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无住院起付线规则（仅门诊起付线），期望诚实拒答；若召回门诊起付线则暴露医疗类别混淆"
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
      "rule_e44e75c149f9"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "rule_e44e75c149f9（10万元）med_type 为空属通用规则，适用住院场景；rule_eb4c465e6f2e 仅引用第三十三条无数值，不计入期望"
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
    "skip": false,
    "notes": "语料无有效期字段亦无 2023 已废止规则，期望诚实拒答"
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
    "skip": false,
    "notes": "语料无有效期字段亦无 2025 未来规则，期望诚实拒答"
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
    "skip": false,
    "notes": "语料无上海规则且 region 字段全缺失，期望诚实拒答"
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
    "skip": false,
    "notes": "语料 publish_status 字段全缺失、无试点规则，期望诚实拒答"
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
    "skip": false,
    "notes": "语料 is_remote 字段全缺失，期望诚实拒答"
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
    "skip": false,
    "notes": "语料无住院规则，学生儿童住院问题期望诚实拒答"
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
    "skip": false,
    "notes": "语料无住院规则，期望诚实拒答"
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
    "skip": false,
    "notes": "语料含大量门诊规则，验证住院场景不误召回门诊规则，期望诚实拒答"
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
    "skip": false,
    "notes": "语料同时含职工与居民规则，验证险种隔离：职工上下文不应召回居民规则"
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
    "skip": false,
    "notes": "语料无 publish_status 字段、无已撤销规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "skip": true,
    "notes": "跳过：语料 effective_date/expiry_date 字段全缺失，时间边界过滤无法评估"
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
    "skip": true,
    "notes": "跳过：语料 effective_date/expiry_date 字段全缺失，时间边界过滤无法评估"
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
    "skip": true,
    "notes": "跳过：语料无有效期字段且无多版本规则，版本切换边界无法评估"
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
    "skip": true,
    "notes": "跳过：语料 region 字段全缺失（全部为本市政策），默认地区逻辑无法评估"
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
    "skip": true,
    "notes": "跳过：语料无有效期字段，无结算日期场景退化为普通过滤，评测价值低"
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
    "skip": false,
    "notes": "语料无上海规则，期望诚实拒答"
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
    "skip": false,
    "notes": "语料无 publish_status 字段、无草稿规则，期望诚实拒答"
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
    "skip": true,
    "notes": "跳过：语料 policy_version 字段全缺失，版本过滤机制无法评估"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
  },
  {
    "case_id": "BROAD_DEDUCTIBLE",
    "scenario": "宽泛问：北京住院起付线多少",
    "dimensions": [
      "宽泛问题"
    ],
    "settlement_context": {},
    "question": "北京住院起付线多少？",
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无住院起付线规则（仅门诊起付线），期望诚实拒答；若召回门诊起付线则暴露医疗类别混淆"
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
      "rule_e44e75c149f9",
      "rule_9da07fdaeaf8"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "问题未限定险种：职工统筹封顶10万与居民大病封顶15万均为有效答案；rule_eb4c465e6f2e 无数值不计入"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无异地就医支付比例规则（仅备案/垫付流程规则），期望诚实拒答"
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
      "rule_74af12a735aef785"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "问题未限定人群/险种，语料另有退休及居民门诊比例规则（rule_0c31054fbb71 / rule_cda56c7057bb1edd 等），其召回计为 FAR 信号"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无 3万-4万 住院分段规则（大病保险分段为 5 万档），期望诚实拒答"
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
    "expected_rule_ids": [],
    "is_negative": true,
    "skip": false,
    "notes": "语料无 2025 年规则，期望诚实拒答"
  },
  {
    "case_id": "REAL_OP_EMP_DEDUCT",
    "scenario": "在职职工门诊起付标准",
    "dimensions": [
      "真实正向",
      "门诊起付线"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "起付线",
      "target_amount": 0.0
    },
    "question": "在职职工门诊起付标准是多少元？",
    "expected_rule_ids": [
      "rule_8238788ad33d5cb4"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "唯一在职门诊起付线规则（1800元），语料无其他在职门诊起付线"
  },
  {
    "case_id": "REAL_OP_RET_DEDUCT",
    "scenario": "退休人员门诊起付标准",
    "dimensions": [
      "真实正向",
      "门诊起付线"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "退休人员",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "起付线",
      "target_amount": 0.0
    },
    "question": "退休人员门诊起付标准是多少元？",
    "expected_rule_ids": [
      "rule_bc4c8deba3574b52",
      "rule_aac09533029c03a5"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "两条均为1300元：rule_bc4c8deba3574b52 为退休人员通用表述，rule_aac09533029c03a5 为70岁以上专项表述（rule_type=deductible），问题未限定年龄两者均应召回"
  },
  {
    "case_id": "REAL_OP_EMP_SEC_BAND1",
    "scenario": "在职职工二级医院门诊2万元以下支付比例",
    "dimensions": [
      "真实正向",
      "门诊分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "二级",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 15000.0
    },
    "question": "在职职工二级医院门诊，2万元以下部分统筹基金支付比例是多少？",
    "expected_rule_ids": [
      "rule_7f3f6f0c6fd2a758"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "二级在职2万以下档唯一无冲突（统筹70%）；一级同档存在 rule_0412833fee42d9d1/rule_ccc47eef94d825d8/rule_f7226be3f086fdcf 三条冲突值（0.9/0.1/0.3），属数据质量问题，故选二级档标注"
  },
  {
    "case_id": "REAL_OP_EMP_BAND2",
    "scenario": "在职职工门诊超过2万元支付比例",
    "dimensions": [
      "真实正向",
      "门诊分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "在职职工门诊费用超过2万元的部分，统筹基金支付比例是多少？",
    "expected_rule_ids": [
      "rule_a9ba270201c559e1",
      "rule_1b5d162145d9c088"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "两条均表述在职2万以上统筹60%；rule_1b5d162145d9c088 为同事实碎片（source_text 仅 \"60%。\"），维度完全一致计入期望"
  },
  {
    "case_id": "REAL_OP_RET_BAND1",
    "scenario": "退休人员门诊2万元以下支付比例",
    "dimensions": [
      "真实正向",
      "门诊分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "退休人员",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 15000.0
    },
    "question": "退休人员门诊2万元以下部分报销比例是多少？",
    "expected_rule_ids": [
      "rule_ca52d442e0eb77f8",
      "rule_63a423fab0492787"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "退休2万以下按年龄分档：70岁以下85%（rule_ca52d442e0eb77f8）+ 70岁以上90%（rule_63a423fab0492787），完整答案需两条同时召回；医院等级变体（一级90%等）与通用档数值冲突，属数据质量问题不计入"
  },
  {
    "case_id": "REAL_OP_RET_BAND2",
    "scenario": "退休人员门诊超过2万元支付比例",
    "dimensions": [
      "真实正向",
      "门诊分段"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "退休人员",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 25000.0
    },
    "question": "退休人员门诊费用超过2万元的部分报销比例是多少？",
    "expected_rule_ids": [
      "rule_9f08b4ad7e8cf1e2",
      "rule_31a8f163639447e4"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "两条均表述退休2万以上80%；rule_31a8f163639447e4 为同事实碎片（\"80%。\"）计入期望"
  },
  {
    "case_id": "REAL_LMAA_EMP_COMMUNITY",
    "scenario": "在职职工社区门诊大额互助报销比例",
    "dimensions": [
      "真实正向",
      "大额互助"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "一级",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 0.0
    },
    "question": "在职职工在社区卫生服务机构门诊，大额医疗互助资金报销比例是多少？",
    "expected_rule_ids": [
      "rule_fe86fd3ef332",
      "rule_63e89e926492ebd8"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "在职社区门诊大额互助90%；rule_63e89e926492ebd8 为同事实碎片（\"90%。\"，rule_type=large_medical_mutual_aid_payment_ratio）计入期望"
  },
  {
    "case_id": "REAL_LMAA_RET_COMMUNITY",
    "scenario": "退休人员社区门诊报销比例",
    "dimensions": [
      "真实正向",
      "大额互助"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "一级",
      "psn_type": "退休人员",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 0.0
    },
    "question": "退休人员在社区卫生服务机构门诊，报销比例是多少？",
    "expected_rule_ids": [
      "rule_bb14031d909f",
      "rule_4df372b59673556e"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "退休社区门诊90%（含大额互助80%+统一补充）；rule_4df372b59673556e 完整复述同一事实计入期望；80% 组件规则（rule_25721ca05b5d/rule_3222a148156d8c7d）仅回答大额互助子项，不计入"
  },
  {
    "case_id": "REAL_LMAA_NON_COMMUNITY",
    "scenario": "在职职工非社区门诊大额互助报销比例",
    "dimensions": [
      "真实正向",
      "大额互助"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 0.0
    },
    "question": "在职职工在社区以外的定点医疗机构门诊，大额医疗互助报销比例是多少？",
    "expected_rule_ids": [
      "rule_2003952d3afc"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "非社区门诊大额互助70%（hosp_lv=无等级）；碎片 rule_69fc18433e6a7364 同为0.7但 hosp_lv 误标一级（与政策矛盾，一级社区应为90%），属数据冲突不计入"
  },
  {
    "case_id": "REAL_DBI_DEDUCT",
    "scenario": "城乡居民大病保险起付标准",
    "dimensions": [
      "真实正向",
      "大病保险"
    ],
    "settlement_context": {
      "insu_type": "大病保险",
      "med_type": "",
      "hosp_lv": "",
      "psn_type": "城乡居民",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "起付线",
      "target_amount": 0.0
    },
    "question": "城乡居民大病保险的起付标准是多少？",
    "expected_rule_ids": [
      "rule_5c825a5842dc"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "2019年起付标准30404元（按上年度城镇居民20%低收入户人均可支配收入），语料唯一起付标准数值规则"
  },
  {
    "case_id": "REAL_DBI_DEDUCT_POOR",
    "scenario": "困难人员大病保险起付标准",
    "dimensions": [
      "真实正向",
      "大病保险"
    ],
    "settlement_context": {
      "insu_type": "大病保险",
      "med_type": "",
      "hosp_lv": "",
      "psn_type": "困难人群",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "起付线",
      "target_amount": 0.0
    },
    "question": "低保等困难人员的城乡居民大病保险起付标准是多少？",
    "expected_rule_ids": [
      "rule_dfc997e0e80f"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "困难人员起付标准降低一半（15202元），规则自身含数值可直接作答；基准规则 rule_5c825a5842dc 提供上下文但不直接回答困难标准，不计入"
  },
  {
    "case_id": "REAL_DBI_RATIO_BAND1",
    "scenario": "困难人员大病5万元以内支付比例",
    "dimensions": [
      "真实正向",
      "大病保险"
    ],
    "settlement_context": {
      "insu_type": "大病保险",
      "med_type": "",
      "hosp_lv": "",
      "psn_type": "困难人群",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "大病自付",
      "target_amount": 30000.0
    },
    "question": "困难人员大病保险，起付标准以上5万元以内的个人自付费用支付比例是多少？",
    "expected_rule_ids": [
      "rule_eabcb26ebdb0"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "5万以内档由60%提高至65%（amount_band=0-50000，困难人群），唯一对应规则"
  },
  {
    "case_id": "REAL_DBI_RATIO_BAND2",
    "scenario": "困难人员大病超过5万元支付比例",
    "dimensions": [
      "真实正向",
      "大病保险"
    ],
    "settlement_context": {
      "insu_type": "大病保险",
      "med_type": "",
      "hosp_lv": "",
      "psn_type": "困难人群",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "大病自付",
      "target_amount": 60000.0
    },
    "question": "困难人员大病保险，超过5万元的个人自付费用支付比例是多少？",
    "expected_rule_ids": [
      "rule_3fdd1238293f"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "超过5万档由70%提高至75%（amount_band=50000-，困难人群），唯一对应规则"
  },
  {
    "case_id": "REAL_DBI_TILT_DIBAO",
    "scenario": "低保对象大病保险倾斜政策",
    "dimensions": [
      "真实正向",
      "大病保险"
    ],
    "settlement_context": {
      "insu_type": "城乡居民大病保险",
      "med_type": "",
      "hosp_lv": "",
      "psn_type": "低保对象",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "大病自付",
      "target_amount": 0.0
    },
    "question": "低保对象的大病保险有哪些倾斜政策？",
    "expected_rule_ids": [
      "rule_2e052d5d5ec61d3a",
      "rule_7ae1f61c041b73ff",
      "rule_af35738965046238"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "低保倾斜三件套：起付标准降低50% + 支付比例提高5个百分点 + 取消最高支付限额；完整答案恰为3条=TOP_K，测试多规则完整召回"
  },
  {
    "case_id": "REAL_RES_OP_DEDUCT",
    "scenario": "城乡居民门诊起付标准",
    "dimensions": [
      "真实正向",
      "居民门诊"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "城乡居民",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "起付线",
      "target_amount": 0.0
    },
    "question": "城乡居民医保门诊（急诊）的起付标准是多少？",
    "expected_rule_ids": [
      "rule_844017664834",
      "rule_b266a6011f26"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "一级及以下100元 + 二级及以上550元，同一原文句按医院等级拆成两条，完整答案需同时召回"
  },
  {
    "case_id": "REAL_RES_OP_RATIO",
    "scenario": "城乡居民门诊支付比例",
    "dimensions": [
      "真实正向",
      "居民门诊"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "城乡居民",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 0.0
    },
    "question": "城乡居民门诊费用超过起付标准后，医保基金支付比例是多少？",
    "expected_rule_ids": [
      "rule_0c31054fbb71",
      "rule_c0c06ba8a75b"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "一级55% + 二级及以上50%（年度累计封顶3000元），同一原文句拆分两条，需同时召回"
  },
  {
    "case_id": "REAL_RES_OP_POOL50",
    "scenario": "居民门诊统筹支付比例下限",
    "dimensions": [
      "真实正向",
      "居民门诊"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "",
      "psn_type": "",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 0.0
    },
    "question": "居民医保门诊统筹支付比例不低于多少？",
    "expected_rule_ids": [
      "rule_cda56c7057bb1edd"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "门诊统筹支付比例不低于50%（doc_7ec146a78b34），唯一对应规则；与 REAL_RES_OP_RATIO 的分段比例属不同政策口径"
  },
  {
    "case_id": "REAL_ER_OBS",
    "scenario": "急诊留观费用报销规则",
    "dimensions": [
      "真实正向",
      "急诊留观"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "门诊-急诊留观",
      "hosp_lv": "",
      "psn_type": "城乡居民",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 0.0
    },
    "question": "参保人员急诊留观发生的医疗费用如何报销？",
    "expected_rule_ids": [
      "rule_730543a736bd"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "急诊留观费用按住院医疗费用报销规定执行，语料唯一急诊留观支付规则"
  },
  {
    "case_id": "REAL_FIRST_DIAG_REFERRAL",
    "scenario": "居民门诊基层首诊与转诊规定",
    "dimensions": [
      "真实正向",
      "居民门诊"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "门诊-普通门急诊",
      "hosp_lv": "一级",
      "psn_type": "城乡居民",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "就医流程",
      "target_amount": 0.0
    },
    "question": "城乡老年人和劳动年龄内居民门诊就医的基层首诊和转诊规定是什么？",
    "expected_rule_ids": [
      "rule_29efc57f99c3",
      "rule_6497e489c1c4",
      "rule_eb166c734035"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "首诊制度 + 凭首诊转诊证明转诊 + 转诊有效180天，三条构成完整流程；rule_956cc41cfe44（未经首诊不予支付，排除规则）属后果条款不计入"
  },
  {
    "case_id": "REAL_MENTE_SCOPE",
    "scenario": "城乡居民特殊病种范围",
    "dimensions": [
      "真实正向",
      "门特"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "门诊-一般门特",
      "hosp_lv": "",
      "psn_type": "",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "支付范围",
      "target_amount": 0.0
    },
    "question": "城乡居民基本医疗保险的特殊病种包括哪些？",
    "expected_rule_ids": [
      "rule_d8302ad37c87"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "门特病种清单规则（恶性肿瘤门诊治疗/血友病/肾透析等），唯一对应规则"
  },
  {
    "case_id": "REAL_MENTE_PAY",
    "scenario": "门特费用支付标准",
    "dimensions": [
      "真实正向",
      "门特"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "门诊-一般门特",
      "hosp_lv": "",
      "psn_type": "城乡居民",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "统筹自付",
      "target_amount": 0.0
    },
    "question": "特殊病种门诊医疗费用按什么标准支付？",
    "expected_rule_ids": [
      "rule_b1005f370c2d"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "门特费用按住院标准支付，唯一对应规则"
  },
  {
    "case_id": "REAL_MENTE_SETTLE",
    "scenario": "门特结算期规则",
    "dimensions": [
      "真实正向",
      "门特"
    ],
    "settlement_context": {
      "insu_type": "城乡居民基本医疗保险",
      "med_type": "门诊-一般门特",
      "hosp_lv": "",
      "psn_type": "",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "就医流程",
      "target_amount": 0.0
    },
    "question": "特殊病种门诊治疗的结算期如何计算？",
    "expected_rule_ids": [
      "rule_e797192073c0",
      "rule_fbc97f217d2f"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "当年备案者自备案首次就医至年度截止 + 一般情形按每保险年度一个结算期，两条互补构成完整答案"
  },
  {
    "case_id": "REAL_ACCOUNT_45P",
    "scenario": "45周岁以上在职职工个人账户划入比例",
    "dimensions": [
      "真实正向",
      "个人账户"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "",
      "hosp_lv": "",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "个人账户",
      "target_amount": 0.0
    },
    "question": "45周岁以上的在职职工，个人账户按什么比例划入？",
    "expected_rule_ids": [
      "rule_aa5635596476",
      "rule_fc5d869d66d5"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "45+ 按缴费工资基数2%划入；语料存在 source_text 完全相同的重复对，两者均应视为有效答案（用于检验召回侧去重/并列行为）"
  },
  {
    "case_id": "REAL_PREMIUM",
    "scenario": "职工基本医疗保险缴费比例",
    "dimensions": [
      "真实正向",
      "缴费"
    ],
    "settlement_context": {
      "insu_type": "城镇职工基本医疗保险",
      "med_type": "",
      "hosp_lv": "",
      "psn_type": "在职职工",
      "region": "",
      "settlement_date": "",
      "is_remote": false,
      "target_field": "缴费",
      "target_amount": 0.0
    },
    "question": "职工基本医疗保险的缴费比例是多少（个人和单位分别缴多少）？",
    "expected_rule_ids": [
      "rule_0b5fda014f4f",
      "rule_e74984933d37"
    ],
    "is_negative": false,
    "skip": false,
    "notes": "个人按上年月平均工资2% + 单位按缴费工资基数之和9%，两条互补构成完整答案"
  }
]
```
