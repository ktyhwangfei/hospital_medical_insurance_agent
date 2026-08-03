# 政策知识“单元 × 知识对比页”现状审查与重做建议

**日期**：2026-08-03  
**审查对象**：`ktyhwangfei/issue-2` / `9b3c503`  
**固定点**：`fd12c79`  
**结论状态**：待用户确认，禁止据此直接实施

## 1. 结论摘要

第一版不是“完全没做”，而是完成了页面骨架和若干局部算法，却做错了产品信息架构，并把最关键的治理闭环做成了展示层模拟。

- 需求 1 只有三栏外观，落在新增“对比”模块而不是现有知识页，因此按补充需求判定为未达标。
- 需求 2（一单元多知识、联动）部分达标，但左栏没有限定“单元页审核通过”的单元，并使用不稳定的 `extraction_id + rule_index` 作为知识身份，数量口径也错误。
- 需求 5（语义层字段和值域作为标化来源）方向正确，但右栏只是请求时临时投影，缺少契约版本、知识身份和失败显式化。
- 需求 3、4、6、7 只有表面实现，存在语义错误或治理越界。
- 需求 8 的核心——候选版本与当前版本同集对跑、真实质量比较、门禁后实际替换——没有实现。

因此不建议在 `9b3c503` 上继续堆补丁。建议保留其“读取 published zcgz 提取契约”的正确方向，把现有知识页重做为三栏知识工作台，并在其后新增独立测试页；同时重做页面状态模型、只读知识工作台服务、语义变更入口和版本化质量门禁。

## 2. 审查范围与证据

### 2.1 已阅读资料

- `AGENTS.md`、`PROGRESS.md`、`src/domain/AGENTS.md`
- `src/apps/portal/AGENTS.md`
- `src/knowledge_extension/AGENTS.md`
- `src/knowledge_extension/rule_explanation/AGENTS.md`
- `src/semantic_layer/AGENTS.md`
- `src/tests/AGENTS.md`
- `docs/governance/TEST-VERIFICATION-MATRIX.md`
- `docs/steering/政策知识治理平台设计-V2.1.md`
- `docs/steering/语义层设计文档.md`
- `docs/steering/接口设计文档.md`
- 提交 `9b3c503` 的前端、服务、存储、路由和测试文件
- 当前 `main` 的 policy pipeline、SemanticRegistry、语义层 API、单元页和知识页

### 2.2 验证结果

- 单元测试：`25 passed in 0.28s`。提交文档声称“24 passed”，计数已漂移。
- API 测试：运行 124 秒后超时。卡点是测试请求触发真实 Milvus 连接，再由业务代码吞掉异常并降级为空结果。
- 提交没有新增对应 Flow 测试或 Playwright 页面交互测试。
- 本轮未改前端，因此不执行“前端改动后的浏览器验证”；实施阶段必须按要求使用 `/policy-knowledge/knowledge` 和 `/policy-knowledge/test` 实页验证并截图。

## 3. 八条需求逐项评估

| # | 结论 | 现有实现 | 主要差距 |
|---|---|---|---|
| 1 | 未达标 | `compare/page.tsx:239-405` 确有三栏外观 | 三栏被放在新增 `/policy-knowledge/compare`，而非现有知识页；导航被错误扩成“对比”模块 |
| 2 | 部分达标 | 左栏切换单元；中栏可循环 `extractions[].rules[]`；知识点击联动左栏和右栏 | 左栏未限定单元页审核通过的单元；“几条”统计的是 extraction 数而非 knowledge 数（`:257-258,276`）；知识只用数组下标标识；无联动 E2E 测试 |
| 3 | 未达标 | `_build_sentence()` 将字段排序后拼为“字段名：原值；字段名：原值” | 不是连贯句意；不使用标准值；没有主语、条件、结论和单位规则；测试只断言字符串包含字段名和值 |
| 4 | 未达标 | `completeness` 与名为 `accuracy` 的加权分数 | 完整性把全部契约字段当分母，未区分知识类型与“不适用”；准确性没有对照原文/人工真值，只是 LLM confidence 与值域合规率；缺失 confidence 时默认 0.7 |
| 5 | 部分达标 | `build_contract()` 调用 `build_extraction_schema(registry, "zcgz")` 获取 published 字段和值域，方向正确 | 结果是临时计算投影，不绑定 contract/schema version；构建失败返回空契约和 HTTP 200；历史知识会被最新契约重新解释，无法复现 |
| 6 | 高风险部分实现 | 未映射字段可创建 `zcgz.{field}` Metric | 服务直接访问 `registry._store`，创建 draft 后立即 `publish_object("zcgz")`，可能把同对象其他草稿一起发布；绕过语义层职责与人工审核 |
| 7 | 高风险部分实现 | 可追加标准值或保存 source→standard 映射 | 同样直接写私有 store；没有变更提案、审计、并发/重复校验和版本绑定；对比页复制了语义层已有写 API |
| 8 | 实质未实现 | 有搜索面板、用例 CRUD、质量图表和名为 publish 的端点 | 没有候选版本；只查当前库；`target` 未参与测试；“发布”只把报告标为 baseline，未替换任何 Knowledge；相等也放行；原知识页仍保留搜索；无真实搜索、版本对跑、Flow/E2E |

用户补充后的正确业务流是：

```text
文档页形成原始政策
  → 单元页拆分并人工审核
  → 仅审核通过的 Unit 进入知识页左栏
  → 中栏生成/展示该 Unit 的结构化 Knowledge
  → 右栏展示 Knowledge ↔ Metric/ValueDomain 标化结果
  → 测试页对候选知识版本执行检索与经典用例
  → 门禁通过
  → Knowledge 发布并允许被外部 RAG/Agent 消费
```

## 4. 关键缺陷清单

### 4.1 阻断级：发布门禁没有发布对象

`policy_compare_routes.py:335-379` 的 `/compare/publish` 只调用 `mark_as_baseline()`。它既没有候选 release，也没有调用 Knowledge 发布流程，更没有切换当前读取版本。页面却显示“发布替换当前版本”。这是错误成功反馈，必须阻断上线。

同时，`evaluate_publish_gate()` 使用 `current >= baseline`，而需求原文是“质量比当前版本高”。首版无 baseline 时只要达到固定阈值即可建立基线，也没有证明这个 baseline 对应当前生产知识版本。

补充需求进一步明确：测试通过之前，候选 Knowledge 只能在治理门户内部查看，不得进入对外检索池；只有门禁通过后的 Published/active release 才能供 RAG/Agent 使用。现实现没有这条隔离边界。

### 4.2 阻断级：测试运行没有候选/基线隔离

`run_quality_tests()` 对当前 `RulesSearchService` 重复检索。它不能回答“候选版本是否比当前版本好”，只能生成同一当前库的一份分数。历史报告与当前知识数据也没有 release_id、schema_version、case_set_version 关联，之后无法复现。

此外：

- `TestCase.target` 被保存但没有传给 `search_fn`。
- 测试页允许选择 `database/both`，却不提供后端要求的 `metric_codes/context`，这些选项会返回 400。
- 用例表单不提供 target 和 filters 编辑，无法维护精准/跨世界经典用例。
- 第一版把“一致性”定义为 precise/semantic/hybrid 三种模式结果集合的 Jaccard；用户现已确认主门禁应采用同版本同配置重复运行的稳定性，跨模式 Jaccard 只作诊断。
- API 测试验证的是“Milvus 不可用时门禁能失败”，不是“真实候选质量能正确比较”。

### 4.3 阻断级：对比服务越界写语义层

`knowledge_compare_service.py:401-478` 直接操作私有 `registry._store`。这违反治理平台只读消费提取契约、映射治理归语义层的边界。[来源：政策知识治理平台设计 V2.1 §2.4、§4.5、§5.6]

尤其是“新增指标后自动 publish_object”会冻结并发布 `zcgz` 对象当时的全部指标，不能保证只发布本次新增项。正确语义应是：知识页发现差距 → 创建语义层草稿/变更提案 → 在语义层审核与发布 → 新契约生效 → 知识页重新计算右栏标化结果。

### 4.4 阻断级：信息架构和单元准入口径错误

提交新增了 `/policy-knowledge/compare` 导航，并在该页面内放“对比/测试”双 tab。用户已确认政策知识模块应固定为“概览、文档、单元、知识、测试”：三栏属于知识页，测试是知识页之后的独立页面。

现实现还把重新解析得到的全部结构叶子放入左栏，没有以“单元页审核通过”为准入条件。这样未审核、已驳回或仅解析出来的内容也可能进入知识工作区，不符合“先审单元，再形成知识”的治理顺序。

### 4.5 高：单元与知识之间没有稳定关系键

现实现每次从 `policy_documents.content_text` 重新解析叶子，再通过文本匹配把 extraction 关联到叶子（`knowledge_compare_service.py:239-315`）。它没有使用稳定 `unit_id ↔ knowledge_id` 关系：

- 匹配可能为空或一条 extraction 命中多个叶子；异常被吞后返回空列表。
- 每条 Knowledge 仅由 `extraction_id + rule_index` 临时标识；重新提取或规则重排后身份漂移。
- 测试只断言“至少有一个单元匹配成功”，没有覆盖错配、多配和稳定性。

这与“Policy Unit 是唯一内容锚点、Knowledge 从 Unit 派生”的设计不一致。[来源：政策知识治理平台设计 V2.1 §1.3、§2.2、§2.3]

### 4.6 高：可信度名称与计算含义不符

当前“准确性”并未测量事实正确性。建议把可直接观测的信号分开，禁止用一个漂亮总分掩盖含义：

- `extraction_confidence`：模型自报/提取器信号，不等于准确率。
- `schema_completeness`：只检查该 knowledge_type/rule_type 的适用必填字段。
- `value_domain_compliance`：枚举值是否在标准域或存在明确映射。
- `evidence_alignment`：字段值是否能在 evidence quote/Unit 原文找到支持。
- `gold_accuracy`：仅在经典用例或人工标注存在时计算。

没有人工真值时，应显示“准确性未评估”，而不是给默认 70% 置信后合成“准确性”。

### 4.7 高：字段连读不是业务句子

当前输出示例实质是：

> 险种类别：城镇职工；医疗类别：住院；支付比例：85%；规则类型：报销比例

目标应表达为一条可读政策知识，例如：

> 城镇职工参保人在二级医院住院时，统筹基金支付比例为 85%。

建议使用确定性模板，不引入不必要的 LLM 调用：按 knowledge_type/rule_type 选择句式，将适用条件、对象、动作/指标、标准值和例外按语义槽位组句；无法成句时回退为结构化字段列表并标注“不完整”，不要伪装成完整句。

### 4.8 中：API、类型与存储不符合仓库约定

- 12 个新端点没有同步 `docs/steering/接口设计文档.md`。
- 服务与存储大量返回裸 `dict[str, Any]`，路由没有 `response_model`，不符合 Pydantic/AgentResponse 约定。
- `quality_test_store.py` 把 DDL、PostgreSQL、内存实现和工厂放在单文件，缺少 ports/adapter 和正式迁移。
- `/compare/units` 聚合读取、解析、匹配、标化和评分，边界过宽。
- `compare/page.tsx` 885 行，同时承担两页 UI、API 调用、CRUD、质量报告和发布操作；未走 portal `api-client`。
- AI 输出/标准化结论没有结构化 citation 或 uncertainty；只显示截断 source_text。

### 4.9 中：错误被降级成“正常空数据”

- `build_contract()` 捕获所有异常后返回空字段和值域，前端无法区分“确实无契约”和“语义层故障”。
- `_search_policy()` 捕获异常后返回空结果，并用模块级 `_milvus_available=False` 锁死后续请求，服务恢复后进程内仍不重试。
- `_published_completeness()` 在 Milvus 不可用时硬编码返回 0.8，质量门禁因此包含伪造数据。
- 前端多处 `catch { /* ignore */ }`，文档、用例和质量加载失败时给用户空白而非可诊断错误。

## 5. 方案选项

### 方案 A：知识工作台读模型 + 独立版本化质量域（推荐）

保留现有 policy pipeline、SemanticRegistry 与 RulesSearchService，通过两个窄服务组装：

1. `KnowledgeWorkbenchQueryService` 只读返回已审核通过的 Unit、Knowledge、字段/值域标化和可信度证据，供现有知识页三栏展示。
2. `PolicyQualityService` 管理 case set、candidate release、baseline release、双版本测试和 promotion gate。

语义指标/值域变更走语义层公开服务，以草稿或变更提案形式创建；对比域不直接写 Registry store。

优点：边界清楚，复用现有能力，能形成真实发布闭环；改动可拆为最小可验证单元。缺点：需要引入明确的 release/version 选择器，并补一段候选检索能力。

### 方案 B：知识页纯前端编排现有 API

前端分别调用文档结构、extractions、extraction-schema、语义指标和值域 API，在浏览器完成关联与标化；测试页复用现有 rules/search。

优点：后端新增少。缺点：关联逻辑重复、请求多、无法可靠固定 contract/release 版本，也无法完成真正的候选发布门禁。不推荐。

### 方案 C：独立物化对比/质量平台

建立专用 compare snapshot 表和候选 Milvus collection，所有 Unit/Knowledge/Mapping/质量结果物化后展示。

优点：审计、复现和大数据量性能最佳。缺点：引入第二套知识读模型和同步机制，超出 issue #2 的最小范围。除非数据规模或合规要求明确，不建议首轮采用。

## 6. 推荐重做方案

### 6.1 信息架构、页面与交互

政策知识导航固定为：

```text
概览 → 文档 → 单元 → 知识 → 测试
```

- `/policy-knowledge/knowledge`：重做为三栏知识工作台，不再新增“对比”导航。
- `/policy-knowledge/test`：作为知识页之后的独立页面，承接原知识页的全部检索入口、经典用例、版本对比和发布门禁。
- 删除 `9b3c503` 的 `/policy-knowledge/compare` 产品入口；可复用其中合格的局部展示代码，但不能保留错误导航结构。

知识页状态模型：

1. 左栏只查询并展示在单元页**审核通过**的 Unit；显示真实 `knowledge_count`、审核信息和质量告警。已驳回、待审、无效单元不得进入。
2. 中栏一张卡对应一条稳定 `knowledge_id`；展示业务句、适用条件、证据、可信度分项。
3. 点击 Knowledge 后，左栏高亮所属 Unit，右栏只展示该知识的字段映射，而不是重复铺满该 Unit 的全部卡片。
4. 右栏逐行展示 `source field/raw value → metric code/standard value`，明确 `mapped / unmapped / not_applicable / invalid`。
5. 未映射字段和值域只创建“变更草稿/提案”，成功后给出跳转语义层审核入口；不在知识页自动发布。
6. 未通过测试的 Knowledge 明确显示“候选/仅内部可见”；通过测试并发布后才显示“已发布/可对外使用”。
7. 测试和发布以整批候选 Knowledge release 为单位；页面可以定位单条失败知识，但不提供绕过批次门禁的单条发布按钮。
8. 右栏未映射字段提供单条“生成指标”和批量选择模式；只有人工点击才创建，系统不得后台自动补指标。

未映射字段交互参考现有 `/semantic-layer/discovery`：

- 单条：展开字段 → 预填指标名称/编码 → 选择语义类型、单位、值域 → 人工点击生成。
- 批量：进入批量模式 → 勾选/全选 → 在批量面板逐行确认名称、编码、语义类型、单位和值域 → 提交 → 展示 created/skipped/error 明细。
- 知识页场景的归属对象固定为 `zcgz`，无需重复选择。
- 复用交互模式和语义层公开 API/组件，不复制一套 compare 专用写服务。
- 不照搬 `semantic-layer/discovery/page.tsx:1559-1562` 将所有批量项硬编码为 `Atomic + Amount` 的逻辑；每个政策字段必须按实际语义确认。

桌面三栏建议 3/4/5；窄屏改为“单元 → 知识 → 标化详情”的分步抽屉或纵向视图。正文不使用 9px 微字作为主要信息。

### 6.2 后端边界

建议组件：

- `knowledge_workbench/models.py`：`KnowledgeWorkbenchResult`、`ApprovedUnit`、`StructuredKnowledge`、`StandardizedKnowledge`、`FieldMapping`、`ConfidenceBreakdown`、`Citation`。
- `knowledge_workbench/service.py`：只读组装，依赖 ApprovedUnit repository、Knowledge repository、PublishedExtractionContract port。
- `knowledge_workbench/sentence_builder.py`：按 knowledge_type/rule_type 的确定性语义模板组句。
- `quality/models.py`：`TestCaseSet`、`KnowledgeRelease`、`QualityRun`、`QualityReport`、`PromotionDecision`。
- `quality/service.py`：对同一 case_set 分别运行 baseline/candidate，生成可复现报告并执行门禁。
- `quality/ports.py` + PostgreSQL/in-memory adapter + 正式 migration。

政策治理服务只依赖语义层的公开查询/命令接口，不访问 `_store`。新增指标和值域应由 `semantic_routes`/SemanticRegistry 的公开应用服务处理。

### 6.3 API 草案

| 方法 | 路径 | 职责 |
|---|---|---|
| GET | `/policy-pipeline/knowledge-workbench/documents/{doc_id}` | 返回审核通过 Unit 和带 contract_version 的三栏只读模型 |
| POST | 复用/增强 `/semantic/metrics` | 人工单条创建 `zcgz` draft 指标，不自动发布 |
| POST | 复用/增强 `/semantic/metrics/batch` | 人工勾选后批量创建 `zcgz` draft 指标，返回逐项结果 |
| POST | `/semantic/value-domain-proposals` | 创建标准值/映射草稿或可审计变更 |
| GET/POST/PUT/DELETE | `/policy-quality/test-cases` | 经典用例 CRUD，包含 target、filters、expected units/fields/values |
| POST | `/policy-quality/runs` | 指定 `candidate_release_id` 与 `baseline_release_id`，同集对跑 |
| GET | `/policy-quality/runs/{run_id}` | 返回分项、逐用例差异和门禁理由 |
| POST | `/policy-quality/releases/{release_id}/promote` | 二次校验报告未过期后，实际切换当前 Knowledge release |

所有路由应声明 Pydantic request/response model，并按项目统一响应与 `error_detail()` 输出错误；比较结果携带 Unit citation/evidence 或明确 uncertainty。

### 6.4 数据模型要点

`StructuredKnowledge` 至少需要：

- `knowledge_id`、`unit_id`、`extraction_id`
- `knowledge_type`、`rule_type`
- `raw_fields`、`sentence`
- `evidence`、`extractor`
- `contract_version`、`knowledge_version`、`status`
- `confidence_breakdown`

`FieldMapping` 至少需要：

- `source_field`、`raw_value`
- `metric_code`、`standard_value`
- `value_domain_code`
- `field_status`、`value_status`
- `reason`、`proposal_id`

`QualityRun` 必须冻结：

- `case_set_version`
- `candidate_release_id`、`baseline_release_id`
- `contract_version`
- 检索配置、top_k、随机性参数/模型版本
- 逐用例命中明细、时间、执行状态与失败原因

### 6.5 质量定义与发布门禁

建议把“准确率”拆成可验证指标：

- 检索：hit@k、precision@k、recall@k；可选 MRR。
- 知识：适用字段完整性、值域合规率、Evidence 对齐率、人工黄金字段/值准确率。
- 一致性：定义为同一候选版本在相同用例集、检索配置和模型参数下重复运行的结果稳定性；跨模式 Jaccard 只作为诊断项，不进入主门禁。

门禁建议：

1. candidate 与 baseline 必须使用同一 case_set_version 和同一检索配置。
2. 关键用例零回归。
3. candidate 综合质量分必须严格高于 baseline，而不是相等放行。
4. 一致性达到阈值且不低于 baseline。
5. 报告未过期，candidate release 自测试后未变化。
6. 门禁针对整批 candidate release 计算，不允许拆出单个 Unit/Knowledge 单独发布。
7. 通过后由 promotion 服务原子切换 active release，并将该批 Knowledge 纳入对外检索池；任一步失败都不修改 baseline、生产指针或外部可见性。

阈值应配置在质量策略中并版本化，不散落为函数常量。

### 6.6 测试设计

按 R3/R4 最高风险执行，并严格串行：

1. T1：句子模板、字段映射、值域映射、适用字段完整性、Evidence 对齐、双版本门禁、失败显式化。
2. T2a：typed API 契约、语义变更只生成 draft、真实 candidate/baseline run、promotion 成功后 active release 变化。
3. T2b：文档 → Unit → 多 Knowledge → 标化 → 建议语义变更 → 语义审核发布 → 重跑对比；候选质量测试 → 门禁 → 实际 promotion。
4. T4：三栏选择/高亮/滚动、一个 Unit 多 Knowledge、未映射处理、测试用例维护、基线差异图、门禁阻断与成功发布。
5. 浏览器人工验收：使用项目脚本启动服务，访问 `/policy-knowledge/knowledge` 与 `/policy-knowledge/test`，保留桌面和窄屏截图。

测试必须至少包含：一单元多知识、一个 extraction 多 rule、知识重排后 identity 不变、字段不适用不扣完整性、错误值但值域合法仍判不准确、Milvus/语义层不可用不伪造分数、候选等于基线不放行、发布后生产读取版本确实变化。

## 7. 建议实施切片（用户确认后再计划）

1. **MVU-1：知识页三栏正确性**：知识页左栏只显示审核通过 Unit；建立稳定 Unit/Knowledge identity、typed response、连贯句子和可解释可信度；完成三栏交互。
2. **MVU-2：语义差距闭环**：未映射字段/值域生成 draft 或提案，语义层审核发布后对比结果更新。
3. **MVU-3：知识页后的独立测试页**：迁移全部搜索入口、经典用例 CRUD、真实结果明细和可视化；候选 Knowledge 保持仅内部可见。
4. **MVU-4：版本质量门禁与对外发布**：candidate/baseline 同集对跑、严格提升门禁、实际 promotion、外部检索池切换与回滚信息。

每个切片分别完成 T1 → T2a → T2b；涉及前端的切片再完成 T4 和截图，不把四个切片一次性塞进一个巨型提交。

## 8. 已收口的设计决策

### 8.1 候选知识隔离与原子发布

采用“每个 Knowledge release 一对独立 Milvus collection + PostgreSQL 活动版本指针”：

- 候选版本构建 `policy_facts_{release_id}` 与 `policy_rules_{release_id}`，完整写入、建索引并加载后才可测试。
- `knowledge_releases` 保存候选版本、两端 collection 名、契约版本、用例集版本、测试配置、质量报告与状态；单行活动指针指向当前对外 release。
- 测试页分别用候选 collection 对和当前活动 collection 对执行同批用例，避免候选数据污染生产检索。
- 门禁通过后，在 PostgreSQL 事务中只原子切换活动 release 指针；检索服务从同一 release 记录同时解析 facts/rules collection，禁止分别切换造成混版。
- 回滚只需将活动指针切回仍在保留期内的上一 release；旧 collection 按保留策略异步清理，不属于发布事务。

选择依据：现有 `create_policy_facts_collection()`、`create_policy_rules_v2_collection()` 和 `RulesSearchService` 已支持 collection 名参数化，改造边界小；现有 Milvus schema 没有 `release_id`，若混存版本则所有精准、语义和混合查询都必须追加过滤，且事实/规则主键和索引会长期混杂。独立版本 collection 更符合整批测试与原子发布语义。

### 8.2 指标来源、统一对齐与治理发布

指标来源与发布存储不是同一概念，设计中必须分开：

- **权威来源 A——结构化数据源**：从数据库表、接口等结构化来源的原始字段及其实际值域提炼指标；字段元数据、值域样本和来源定位是该指标的权威来源证据。
- **权威来源 B——非结构化政策知识**：从审核通过的政策 Unit 所形成的结构化 Knowledge 字段及其值域提炼指标；原文片段、Unit、Knowledge、字段和值域是该指标的权威来源证据。
- **治理发布目录**：SemanticRegistry/PostgreSQL 保存经过提炼、人工审核并发布的指标定义及版本，供语义查询和知识提取契约消费；它是运行发布目录，不替代上述两类业务权威来源。YAML 仅承担初始化/导入等工程用途，不作为第三类指标业务来源。
- 每个 draft/published Metric 和 ValueDomain 都必须记录 `source_type`、稳定 `source_ref`、来源字段/值域证据及版本，支持从发布指标追溯到结构化字段或政策 Knowledge。
- **统一对齐是核心模型**：结构化字段与政策 Knowledge 字段不各建一套平行指标，而是多来源字段映射到同一个标准 Metric；各来源原始值再映射到该 Metric 的同一套标准 ValueDomain。一个标准指标允许绑定多个结构化/非结构化来源，来源差异通过字段映射和值域映射表达。
- 政策知识右栏应优先推荐并允许人工绑定已有标准指标及值域；只有确认不存在可复用标准指标时，“生成指标”才创建新的 `zcgz` draft。否则会不断制造重复指标，破坏跨结构化与非结构化数据的统一对齐目标。
- 来源值无法映射到现有标准值时，只能由人工发起“新增标准值”草稿；经语义层审核发布后才扩充统一标准值域。知识页不得自动或直接修改正式值域。
以下事项已由用户补充确认，不再列为歧义：三栏属于知识页；测试是其后的独立页面；原知识页搜索逻辑迁入测试页；测试通过前不得对外使用；测试与发布按整批候选 Knowledge release 执行并原子切换；一致性按同版本同配置重复运行稳定性衡量，跨模式重合度只作诊断；未映射字段必须由人工单条或批量点击生成指标，交互参考语义层发现页；点击“生成指标”只创建 `zcgz` draft，语义层审核发布后才进入带版本的提取契约；结构化字段与政策字段统一映射到同一套标准指标和值域；无法映射的来源值由人工创建标准值草稿，审核发布后生效。

## 9. 建议确认结论

推荐选择方案 A。产品信息架构、双来源统一指标/值域、人工治理边界、批量统一测试和原子发布方案均已收口。下一步仅在用户确认本报告后输出逐文件实施计划，再进入编码；在此之前不合并或重写 `9b3c503` 的业务代码。
