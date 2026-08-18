# S5 冲突分区维度发现 — TDD 实施计划

> 对应设计：`docs/superpowers/specs/2026-08-12-semantic-layer-metric-value-proactive-discovery-design.md` §4.8 / §5.3 / §6.1
> 对应 Issue：GitHub #13「政策知识的结构化如何发现新指标」——S5 是该 issue 的核心答案（主动、确定性地发现缺失的分类维度）。

## 目标

从规则塌缩冲突中**确定性**发现缺失的分类维度（轴），产出新轴提议（Enum 指标 + 值域），经审核落地为正式维度。不依赖 LLM 自报（区别于 S1），分类天然正确（维度而非数值）。

## 关键决策

1. **独立后处理，不侵入 compiler**。compiler `_compose` 的 CONFLICT 是 fail-closed 拦截信号（规则不进 runtime）；S5 是**学习信号**（读 extraction rules 自己分组，产出提议）。S5 = 纯函数 `discover_conflict_partitions(rules) -> list[ConflictPartitionSignal]`，在构建重抽后调用。

2. **身份签名** = `(rule_type, insu_type, med_type, psn_type, hosp_lv, setl_type)` 元组（设计 §4.8）。同签名下 ≥2 个不同数值 = 多值组。

3. **候选短语来源 = entities 的 AMOUNT/SERVICE 差异**（LLM 抽取时已标注，确定性读取）+ `relations.predicate` 补充。**不调 LLM 重新提取**，保证确定性。
   - 实测样本：entities 含 `基本医疗保险统筹基金最高支付限额|AMOUNT` 与 `大额医疗互助资金最高支付限额|AMOUNT`，差异词「统筹基金」「大额医疗互助资金」即为分区短语。

4. **完美分区才提议**：多值组的 N 个不同值，能被候选短语一一对应（含短语 X 的规则恒为值 A）。完美分区 → 提议；否则记 uncertainty，不提议（v1 不做部分分区降置信度）。

## 测试数据

`doc_7a1fbf7480d4`：`rule_type=支付比例` 下，基金归属（统筹基金 / 大额医疗互助资金）对应不同报销比例（90% / 80%）。
期望产出：`fund_type` 轴提议，`semantic_type=Enum`，值域 `{统筹基金, 大额医疗互助资金}`，status=proposed 待审核。

## Task 分解（TDD 红→绿）

### Task 1：枚举与证据模型扩展
- [ ] Step 1 红：`test_trigger_source_has_conflict_partition` 断言枚举值存在；`test_conflict_partition_signal_requires_axis_evidence` 断言缺身份签名/冲突值集时校验失败
- [ ] Step 2 绿：`TriggerSource` 加 `CONFLICT_PARTITION`；`DiscoveryEvidence` 增 `identity_signature` / `conflict_values` / `partition_phrases` 字段；`_validate_trigger_evidence` 加 CONFLICT_PARTITION 分支

### Task 2：身份分组与多值组识别
- [ ] Step 1 红：`test_group_by_identity_finds_multi_value_group` —— 给 doc_7a1fbf7480d4 两条支付比例 rule（同身份、不同值），期望分出一个多值组
- [ ] Step 2 绿：实现 `group_by_identity(rules) -> dict[signature, list[rule]]`，筛 `len(distinct_values) >= 2`
- 备注：身份字段缺失（如 `hosp_lv=''`）按空串入 key，TDD 驱动确认是否需要「空字段当通配」

### Task 3：候选归属短语提取（确定性）
- [ ] Step 1 红：`test_extract_partition_phrases_from_entities` —— 给多值组，期望提取 `{统筹基金, 大额医疗互助资金}`（来自 AMOUNT entity 差异，剔除公共后缀「最高支付限额」）
- [ ] Step 2 绿：实现 `extract_partition_phrases(group) -> set[str]` —— 取各组 AMOUNT/SERVICE entity.name，用最长公共子串剔除公共部分，留差异词
- 备注：entity 缺失时回退到 `rule_value`/`relations` 关键词，保持确定性

### Task 4：共现分区判定
- [ ] Step 1 红：`test_perfect_partition_passes` —— 短语能一一对应多值组的值；`test_non_partition_does_not_propose` —— 短语无法对应时不提议
- [ ] Step 2 绿：实现 `is_perfect_partition(group, phrases) -> bool` —— 每个 distinct value 恒与唯一短语共现

### Task 5：信号 → 新轴提议生成
- [ ] Step 1 红：`test_conflict_partition_produces_axis_proposal` —— CONFLICT_PARTITION 信号产出 Enum 指标提议（`fund_type` + 值域）
- [ ] Step 2 绿：实现提议构建：复用 `CreateMetricDraft`，`semantic_type=Enum`，`value_domain` = 发现的短语集，`indexed=True`，`trigger_source=CONFLICT_PARTITION`

### Task 6：接入构建流程
- [ ] Step 1 红：`test_rebuild_triggers_conflict_partition_discovery` —— 构建重抽后调用 `discover_conflict_partitions`，信号进 intake
- [ ] Step 2 绿：在 `knowledge_build_service` 重抽路径接入（复用 REBUILD 强制重抽修复点，同位置挂载）

### Task 7：真实数据集成测试
- [ ] `doc_7a1fbf7480d4` 重抽 → `semantic_proposals` 表产出 `fund_type` 提议，status=proposed，证据含身份签名 + 冲突值集 {90%, 80%} + 分区短语 + rule_id 列表

## 不做（YAGNI）

- **部分分区降置信度提议**：v1 只要完美分区；部分分区记 uncertainty 不提议。
- **跨文档聚合轴值**：v1 单文档内发现；跨文档合并走 D1 值域 diff。
- **LLM 辅助短语提取**：违背「确定性」承诺，与 S1 退化为同类。
- **自动命名轴 code**：`fund_type` 等 code 由审核人定，提议只给建议代号 + 候选值。

## 风险与边界

- **身份字段缺失**（样本 `hosp_lv=''`、`setl_type=''` 普遍为空）→ 分组 key 含空串；若分组过粗（空字段把不相关规则并组），Task 2 TDD 暴露后调整 key 构造。
- **entity 差异提取边界**（公共后缀/前缀）→ Task 3 用最长公共子串；复杂情况回退为「整 entity.name 作为短语」，让审核人裁剪。
- **完美分区过严** → 若真实数据极少完美分区，v1 可放宽为「主分区（≥80% 规则可解释）+ 降置信度」，但须先有完美分区基线测试，避免一开始就放宽。

## 验收

- Task 1-5 单元测试全绿（确定性，无 LLM 依赖）。
- Task 6-7 真实 PostgreSQL 集成：doc_7a1fbf7480d4 重抽产出 fund_type 提议。
- 产出提议经审核发布后，`semantic_metrics` 新增 `fund_type`（Enum），`semantic_value_domains` 新增对应值域，下游抽取契约立即可读。
