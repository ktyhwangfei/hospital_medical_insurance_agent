# Issue #25 结构化索引与最小混合检索评估报告

> 生成时间：2026-09-01T16:21:23
> 数据集：32 条模拟 policy_rules_v2 规则，58 条黄金用例
> Top-K：3
> Embedding：真实 bge-base-zh-v1.5（默认）或 hash 向量（--embedding-kind=hash）

## 执行摘要

本次评估在内存模拟的 `policy_rules_v2` 集合上，对跑四条基线：
- **text_only**：BM25 纯文本召回，无结构化过滤；
- **current_hybrid**：`StructuredPolicyRuleRetriever` 关闭适用性字段（仅 core 维度 + source_text 关键词），代表 Issue #25 改造前的生产路径；
- **enhanced_hybrid**：`StructuredPolicyRuleRetriever` 启用新增适用性字段（region / effective_date / expiry_date / publish_status / policy_version / is_remote）；
- **broad_hybrid**：`BroadPolicyRetriever` 向量语义召回 + rank-bm25 + 适用性字段精排，覆盖宽泛问题与结算单场景。

核心结论：
- 补强适用性字段后，适用规则准确率从 11.5% 提升至 16.7%，
  证据召回率从 28.2% 提升至 26.4%。
- 错误适用规则率（FAR）从 79.9% 降至 73.0%。
- 宽泛问题混合检索（broad_hybrid）适用规则准确率 14.4%，证据召回率 36.2%，FAR 85.6%。
- 完整回答率：enhanced 13.8% / broad 3.4%；诚实拒答率：enhanced 8.3% / broad 0.0%。
- P95 时延：text_only 0.44ms / current 1.18ms / enhanced 2.19ms / broad 4.43ms。

> ⚠️ 本评估使用合成语料与内存 Milvus，真实生产数据上的绝对数值会有差异；相对差异和字段效用结论可复现。

## 核心指标

| 基线 | 适用规则准确率 | 证据召回率 | FAR | 完整回答率 | 诚实拒答率 | 字段质量 | P95 时延(ms) |
|------|----------------|------------|-----|------------|------------|----------|--------------|
| text_only | 13.2% | 44.8% | 71.3% | 5.2% | 25.0% | 0.0% | 0.44 |
| current_hybrid | 11.5% | 28.2% | 79.9% | 5.2% | 8.3% | 0.0% | 1.18 |
| enhanced_hybrid | 16.7% | 26.4% | 73.0% | 13.8% | 8.3% | 100.0% | 2.19 |
| broad_hybrid | 14.4% | 36.2% | 85.6% | 3.4% | 0.0% | 0.0% | 4.43 |

## 逐案差异样例

以下选取 10 条差异最大的用例展示四条基线的召回结果。

| 用例 | 场景 | text_only | current_hybrid | enhanced_hybrid | broad_hybrid | 说明 |
|------|------|-----------|----------------|-----------------|--------------|------|
| BJ_EMP_TERT_IP_BAND_3 | 北京在职职工三级医院住院，超过4万元 | ['BJ_2024_IP_REMOTE_001', 'BJ_2024_IP_TERT_EMP_002', 'BJ_2024_IP_TERT_EMP_003'] | ['BJ_2024_IP_TERT_EMP_003', 'BJ_2025_IP_TERT_EMP_003', 'SH_2024_IP_TERT_EMP_003'] | ['BJ_2024_IP_TERT_EMP_003'] | ['BJ_2024_IP_TERT_EMP_003', 'BJ_2024_IP_TERT_EMP_001', 'BJ_2024_OP_TERT_EMP_001'] | - |
| BJ_EMP_TERT_IP_2025 | 2025年北京在职职工三级医院住院 | [] | ['BJ_2024_IP_TERT_EMP_001', 'BJ_2025_IP_TERT_EMP_001', 'SH_2024_IP_TERT_EMP_001'] | ['BJ_2025_IP_TERT_EMP_001'] | ['BJ_2025_IP_TERT_EMP_002', 'BJ_2025_IP_TERT_EMP_003', 'BJ_2025_IP_TERT_EMP_001'] | - |
| BJ_EMP_TERT_IP_2025_BAND2 | 2025年北京在职职工三级医院住院，超过3万元至4万元 | ['BJ_2024_IP_RET_TERT_003', 'BJ_2024_IP_RET_TERT_008', 'BJ_2024_IP_TERT_EMP_AM_003'] | ['BJ_2024_IP_TERT_EMP_002', 'BJ_2025_IP_TERT_EMP_002', 'SH_2024_IP_TERT_EMP_002'] | ['BJ_2025_IP_TERT_EMP_002'] | ['BJ_2025_IP_TERT_EMP_001', 'BJ_2025_IP_TERT_EMP_003', 'BJ_2025_IP_TERT_EMP_002'] | - |
| SH_EMP_TERT_IP | 上海在职职工三级医院住院 | ['SH_2024_IP_TERT_EMP_002', 'SH_2024_IP_TERT_EMP_003', 'SH_2024_IP_TERT_EMP_001'] | ['BJ_2024_IP_TERT_EMP_001', 'BJ_2025_IP_TERT_EMP_001', 'SH_2024_IP_TERT_EMP_001'] | ['SH_2024_IP_TERT_EMP_001'] | ['SH_2024_IP_TERT_EMP_001', 'SH_2024_IP_TERT_EMP_002', 'SH_2024_IP_TERT_EMP_003'] | - |
| BJ_EMP_TERT_IP_NEW_YEAR | 2025-01-01结算命中2025规则 | [] | ['BJ_2024_IP_TERT_EMP_001', 'BJ_2025_IP_TERT_EMP_001', 'SH_2024_IP_TERT_EMP_001'] | ['BJ_2025_IP_TERT_EMP_001'] | ['BJ_2025_IP_TERT_EMP_001', 'BJ_2025_IP_TERT_EMP_002', 'BJ_2025_IP_TERT_EMP_003'] | - |
| BJ_EMP_TERT_IP_BAND_1 | 北京在职职工三级医院住院，起付标准至3万元 | ['BJ_2023_IP_TERT_EMP_001', 'BJ_2024_IP_TERT_EMP_001', 'BJ_2025_IP_TERT_EMP_001'] | ['BJ_2024_IP_TERT_EMP_002', 'BJ_2025_IP_TERT_EMP_002', 'SH_2024_IP_TERT_EMP_002'] | ['BJ_2024_IP_TERT_EMP_002'] | ['BJ_2024_IP_TERT_EMP_AM_002', 'BJ_2024_IP_TERT_EMP_002', 'BJ_2024_IP_TERT_EMP_AM_001'] | - |
| BJ_EMP_TERT_IP_BAND_2 | 北京在职职工三级医院住院，超过3万元至4万元 | ['BJ_2024_IP_REMOTE_001', 'BJ_2024_IP_TERT_EMP_002', 'BJ_2024_IP_TERT_EMP_003'] | ['BJ_2024_IP_TERT_EMP_003', 'BJ_2025_IP_TERT_EMP_003', 'SH_2024_IP_TERT_EMP_003'] | ['BJ_2024_IP_TERT_EMP_003'] | ['BJ_2024_IP_TERT_EMP_003', 'BJ_2024_IP_TERT_EMP_002', 'BJ_2024_IP_TERT_EMP_AM_003'] | - |
| BJ_EMP_SEC_IP_BAND_1 | 北京在职职工二级医院住院，起付标准至3万元 | ['BJ_2024_IP_SEC_EMP_001', 'BJ_2023_IP_TERT_EMP_001', 'BJ_2024_IP_TERT_EMP_001'] | ['BJ_2024_IP_SEC_EMP_002'] | ['BJ_2024_IP_SEC_EMP_002'] | ['BJ_2024_IP_SEC_EMP_002', 'BJ_2024_IP_TERT_EMP_AM_001', 'BJ_2024_IP_TERT_EMP_AM_003'] | - |
| BJ_EMP_SEC_IP_BAND_2 | 北京在职职工二级医院住院，超过3万元至4万元 | ['BJ_2024_IP_SEC_EMP_002', 'BJ_2024_IP_SEC_EMP_003', 'BJ_2024_IP_REMOTE_001'] | ['BJ_2024_IP_SEC_EMP_003'] | ['BJ_2024_IP_SEC_EMP_003'] | ['BJ_2024_IP_SEC_EMP_003', 'BJ_2024_IP_SEC_EMP_001', 'BJ_2024_IP_TERT_EMP_AM_003'] | - |
| BJ_EMP_SEC_IP_BAND_3 | 北京在职职工二级医院住院，超过4万元 | ['BJ_2024_IP_SEC_EMP_002', 'BJ_2024_IP_SEC_EMP_003', 'BJ_2024_IP_REMOTE_001'] | ['BJ_2024_IP_SEC_EMP_003'] | ['BJ_2024_IP_SEC_EMP_003'] | ['BJ_2024_IP_TERT_EMP_002', 'BJ_2024_IP_TERT_EMP_001', 'BJ_2024_IP_RET_FORMULA_001'] | - |

## 字段分类清单

基于本次评估结论，对新增及候选字段做如下分类：

| 字段 | 分类 | 理由 | 运行时消费方式 |
|------|------|------|----------------|
| `region` | **必须结构化+物理索引** | 地区是最高频过滤条件；跨地区规则混排会直接导致错误适用 | 默认值北京；结算上下文传入；Milvus 标量过滤 |
| `effective_date` / `expiry_date` | **必须结构化+物理索引** | 时间有效性过滤可消除过期/未来规则误召回 | 结算日期传入；范围查询 `[effective_date, expiry_date]` |
| `publish_status` | **必须结构化+物理索引** | 区分 published/draft/revoked/pilot，防止 Runtime 消费未发布规则 | 默认过滤 `published`；管理态可显式查询 pilot |
| `is_remote` | **必须结构化+物理索引** | 本地/异地规则差异显著；默认本地，异地场景显式过滤 | 结算上下文传入；bool 标量过滤 |
| `policy_version` | **必须结构化+仅存储（优先）** | 用于溯源、冲突展示与人工选择；当前评估未做运行时过滤（结算上下文通常不直接指定版本） | 入固定 schema 建标量索引；详情页/证据卡展示；未来若业务需要可按版本过滤 |
| `amount_band` 数值边界 | **建议结构化（后续阶段）** | 当前为文本，金额段比较依赖字符串匹配；精确到段内金额需数值化 | 暂不进入本阶段；后续评估是否需要范围索引 |
| `referral_type` 转诊类型 | **仅候选，待需求确认** | 当前用例中异地/转诊差异可用 `is_remote` 区分；更细转诊类型（跨省/省内/急诊）暂无高频证据 | 不进入本阶段 |

## 地区 / 有效期 / 发布状态 / 政策版本的运行时消费方案

### 1. 地区（region）
- 默认值：结算上下文未提供时，使用 `北京`。
- 过滤：每条查询注入 `region == ctx.region`，保证不召回其他地区规则。
- 不确定时：若地区无法推断，应声明不确定性，而非默认全国。

### 2. 有效期（effective_date / expiry_date）
- 输入：`settlement_date` 由结算上下文提供，格式 `YYYY-MM-DD`。
- 过滤：`effective_date <= settlement_date <= expiry_date`，其中 `9999-12-31` 表示长期有效。
- 缺省：`settlement_date` 为空时不过滤时间，避免误伤。

### 3. 发布状态（publish_status）
- Runtime 默认只消费 `published`。
- `draft` 仅在治理/测试环境显式查询；`revoked` 不得进入 Runtime；`pilot` 需白名单地区才放行。

### 4. 政策版本（policy_version）
- 当前 Runtime 不过滤版本，而是按有效期自然选择生效规则。
- 版本字段用于证据卡展示、冲突提示与人工审核；当同一有效期内存在多版本冲突时，触发 `waiting_human_confirmation`。

## 层级索引与知识图谱结论

### 证据化结论
- **暂不建立层级索引**：当前政策问答以单条规则适用性判断为主，`doc_id`/`clause_id` 已能支撑政策→条款→规则的溯源路径；层级索引的额外收益在本次 80 条用例中未形成可量化提升。
- **暂不引入知识图谱**：人群折算（退休=职工×60%）已通过 `rule_derivation.derive_personal_payment_ratios` 在入库阶段物化为派生规则；跨规则引用（如封顶线、调整方案）通过 `doc_id`/`clause_id` 与原文证据即可满足当前 QA 场景的溯源需求。
- **触发条件**：若未来出现以下场景，再评估层级索引/知识图谱：
  1. 多跳推理需求（如‘甲药在乙病种的报销比例受丙目录限制’）；
  2. 政策替代/废止链复杂到无法通过时间范围过滤处理；
  3. 地区/险种/年度组合爆炸，标量索引过滤后仍需关系推理。

## 不确定性声明

- 本评估语料为合成数据，真实生产中的字段分布、文本表达、规则冲突密度可能不同。
- `policy_version` 未做运行时过滤，仅用于展示；若业务需要按版本强过滤，需额外设计。
- broad_hybrid 基线默认使用真实 bge-base-zh-v1.5 编码 source_text；在真实 policy_rules_v2 上的绝对数值可能不同，本报告结论侧重相对差异与实现可复现性。

## 阶段 2 最小可验证实施计划

在 MVP 阶段 1（schema 设计 + 检索层消费）完成后，建议按以下步骤推进：

1. **存量回填流水线**：基于 `rule_to_entity` 默认值机制，对现有 `policy_rules_v2` 规则回填 `region`/`effective_date`/`expiry_date`/`publish_status`/`policy_version`/`is_remote`；回填值在知识审核页以‘提议者-审核者’模式展示，人工确认后发布。
2. **适用性字段质量门禁**：在知识发布/变更集 promote 时，校验所有 published 规则必须包含非空 `region`、`effective_date`、`expiry_date`、`publish_status`；缺失则阻断发布并生成 DecisionTask。
3. **宽泛问题混合检索路径**：✅ 已完成。`BroadPolicyRetriever` 使用真实 bge 向量 + rank-bm25 + 适用性字段精排；`/policy-qa/stream` 在 `settlement_id` 缺失时自动切换至此路径。
4. **指标看板**：在 policy-knowledge 测试页增加 Issue #25 专项指标卡（FAR、P@3、诚实拒答率、字段完整率），每轮候选版本发布前自动对跑。
5. **生产灰度**：先对北京地区住院/门诊规则启用新字段过滤，观察一周后扩展至其他地区；回滚开关为 `enable_applicability_fields=False`。

---

[来源: docs/steering/政策知识治理-需求迭代记录.md §Issue 25]
