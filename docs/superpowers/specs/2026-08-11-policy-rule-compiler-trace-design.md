# Issue 15：政策规则编译管线与逐规则溯源设计

日期：2026-08-11
状态：待用户书面审阅
范围：政策知识结构化、编译结果持久化、规则级溯源查询与 Portal 抽屉

## 1. 需求与成功标准

Issue #15 要求在 LLM Extraction 与正式 Policy Rule 之间增加确定性 Policy Rule Compiler。用户确认以《医保政策结构化编译管线设计规范 V1.0》为基线，并补充以下硬性要求：

- 编译结果必须持久化，不能只在内存返回；
- 原始输入、LLM 提取结果和每个管线步骤的输入、输出、状态、问题及异常都必须保留；
- 每条规则知识必须提供「查看溯源」操作；
- 溯源采用规则列表内的右侧抽屉展示；
- 任一不确定、冲突或溯源落库失败都必须 fail-closed，禁止进入正式 Runtime。

成功标准：

1. 不使用 `doc_id`、`unit_id`、条款号或退休 60% 生产硬编码，重新生成第三十六条 Golden Case 的正确规则。
2. 「退休人员比例 = 在职人员 × 60%」和「第二次住院起付线 = 第一次住院 × 50%」复用同一 RELATIVE + MULTIPLY 机制。
3. 派生规则包含 `derived_from`、`evidence`、`formula`、`compiler_version`。
4. AMBIGUOUS、NOT_FOUND、CONFLICT、REVIEW、FAIL 均不得进入激活 Release。
5. 用户能从任一规则反查编译运行、Extraction、政策文档/单元，以及全部步骤输入输出。

[来源: GitHub Issue #15；用户于 2026-08-11 确认的 V1 设计基线与补充要求]

## 2. 方案选择

### 方案 A：兼容现有发布链路的确定性 Compiler（采用）

在现有 Extraction 与 `policy_rules_v2` 之间插入 Compiler，复用语义层、变更集审核、版本化 Release、Milvus 检索和 Runtime 读取链路。新增 PostgreSQL 编译轨迹存储和规则级查询 API。

优点：满足核心验收，改动集中，可沿用现有发布与回滚能力。
代价：第一版仍沿用现有 `policy_rules_v2` Runtime schema。

### 方案 B：同步建设七张新表与全新管理门户（不采用）

完整落地远期数据模型和独立门户。边界完整，但首次交付过大，会重复已有 ChangeSet、Release 和工作台能力。

### 方案 C：仅泛化 `rule_derivation.py`（不采用）

改动最少，但无法提供 Raw Fact、分层校验、失败门禁、运行版本和逐步骤溯源，不能达到 Issue #15 的目标。

## 3. 总体架构

```text
Policy Document / Unit
        ↓
LLM Extraction（现有 ModelGateway）
        ↓
创建 CompileRun，保存不可变输入与 LLM 输出快照
        ↓
Canonicalize
        ↓
Compose by RuleKey
        ↓
Resolve Reference
        ↓
Derive
        ↓
Validate
        ↓
ChangeSet 人工审核 / 质量门禁
        ↓
写入版本化 Release collection
        ↓
保存 PublishStep + RuleLineage
        ↓
激活 Release
        ↓
Runtime 读取 policy_rules_v2 兼容实体
```

Compiler 是纯确定性组件，不调用模型、不修改原始 Extraction，也不直接激活 Release。LLM 仍通过 `model_service/gateway` 调用；Compiler 只消费其已保存输出。

## 4. 核心模型

模型放在 `src/knowledge_extension/rule_explanation/policy_compiler/`，并同步更新 `src/domain/AGENTS.md` 通用语言字典。

### 4.1 PolicyFact

保存从 LLM 输出适配得到、尚未业务推导的最小政策事实：事实 ID、来源文档/单元/Extraction、subject、population、conditions、value、relation、evidence、confidence。

### 4.2 PolicyRelation 与 PolicyExpression

V1 支持：

- ABSOLUTE；
- RELATIVE + MULTIPLY；
- COMPLEMENT；
- REFERENCE + DIRECT_COPY；
- SEGMENT。

表达式执行器只识别 operator、target、reference、factor/total，不识别具体条款或人群名称。

### 4.3 CanonicalRule

包含业务 subject、标准化条件、结果、来源类型 DIRECT/DERIVED、证据、依赖、公式、有效期、compiler_version、rule_version 和状态。

### 4.4 ValidationIssue

稳定字段：issue_id、severity、code、stage、fact_id/rule_id、message、recommended_action。自然语言 message 不能替代错误码。

### 4.5 CompilationResult

包含 rules、issues、unresolved_relations、steps、metrics 和最终状态。只有 PASS 或允许发布的 WARN 规则能成为 ChangeSet 候选。

## 5. 编译阶段

### 5.1 Canonicalize

复用现有 Semantic Registry、Metric Registry、Value Domain 和 Mapping Registry，完成字段、值域、人群、比例、金额、区间和条件标准化。Normalize 不做互补、折算或其他业务推理。

### 5.2 Compose

按 RuleKey 组合属于同一业务规则的字段。RuleKey 由 subject、population、service_type、hospital_level、treatment_type、segment、admission_order、effective_period 和 additional_conditions 构成；Unit 只属于证据，不属于规则身份。

### 5.3 Resolve

精确匹配关系依赖的基础规则，结果只能为 RESOLVED、AMBIGUOUS、NOT_FOUND、CONFLICT。只有 RESOLVED 能进入 Derive。

### 5.4 Derive

V1 执行 MULTIPLY、COMPLEMENT 和 DIRECT_COPY。输入、关系和公式必须全部确定；不得从描述性政策语言猜测数值。

### 5.5 Validate

依次执行 Schema、Semantic、Relation 和 Consistency 校验，覆盖必填字段、类型/范围、值域、引用完整性、重复/冲突、比例范围、区间重叠和条件缺失。

### 5.6 Publish

Publish 不直接写当前生产集合，而是复用现有版本化 Release 构建与激活流程。先保存完整编译轨迹和 RuleLineage，再允许激活 Release。

## 6. 持久化与溯源

采用现有 ports/adapter 约定，提供 `CompilationTraceStore`、`InMemoryCompilationTraceStore` 和 `PostgresCompilationTraceStore`。生产默认 PostgreSQL，测试和 `USE_MEMORY_STORAGE=1` 使用内存实现。

### 6.1 `policy_compile_runs`

每次编译一条不可变运行记录：

```text
run_id PK
document_id
unit_id
extraction_id
raw_input JSONB
llm_output JSONB
model_name
prompt_version
schema_version
compiler_version
status
metrics JSONB
error JSONB
started_at
finished_at
```

成功和失败运行均保留。重新编译创建新 run，不覆盖历史 run。

### 6.2 `policy_compile_steps`

每一步一条追加记录：

```text
step_id PK
run_id FK
sequence_no
stage
status
input_payload JSONB
output_payload JSONB
issues JSONB
error JSONB
duration_ms
started_at
finished_at
```

stage 固定为 INPUT_SNAPSHOT、LLM_EXTRACTION、CANONICALIZE、COMPOSE、RESOLVE、DERIVE、VALIDATE、PUBLISH 或 LEGACY_IMPORT。

### 6.3 扩展 `policy_rule_lineage`

在现有 rule_id、extraction_id、doc_id 基础上增加：

```text
compile_run_id
rule_version
canonical_rule JSONB
```

建立 `rule_id → rule_version → compile_run → extraction → document/unit` 链路。Milvus 只保存 Runtime 所需的当前发布实体，PostgreSQL 保存审计事实。

### 6.4 写入时序

1. 先创建 RUNNING run；
2. 每个阶段开始和结束时写对应 step；
3. 失败时写 FAILED step 和 run，停止后续阶段；
4. 校验通过后构建版本化 Release collection；
5. 保存 PUBLISH step、CanonicalRule 快照和 lineage；
6. 最后激活 Release。

轨迹数据库不可用、任一步落库失败或最终 lineage 缺失时禁止激活 Release。

## 7. API 与 Portal

在现有 `policy-workbench` 路由增加：

```text
GET /api/v1/medical-insurance-ai-agent/policy-workbench/rules/{rule_id}/trace
```

返回 Pydantic `RuleCompilationTraceResponse`：规则当前版本、原始输入、LLM 输出、步骤列表、ValidationIssue、发布信息和历史版本摘要。响应不得使用裸 `dict` 作为顶层契约。

规则知识列表的每行固定增加「查看溯源」按钮。点击后打开右侧抽屉：

1. 顶部显示 rule_id、版本、DIRECT/DERIVED、编译状态和发布时间；
2. 依次显示原始输入、LLM 提取、Canonicalize、Compose、Resolve、Derive、Validate、Publish；
3. 每一步默认显示摘要，展开后左右展示输入/输出 JSON；
4. FAILED/REVIEW/CONFLICT 步骤高亮错误码和建议动作；
5. 长 JSON 可打开完整视图；
6. 接口按需懒加载，不增加规则列表首屏查询量。

读取权限沿用政策知识管理员边界；输出经现有脱敏机制处理。政策原文和证据必须保留来源标识。

## 8. 存量迁移

1. 冻结现有 `fix_xxx.py`，不继续增加业务逻辑；
2. 将第三十六条当前人工确认数据转为 Golden Case #001；
3. 对 reviewed/published Extraction 运行新 Compiler，生成新 run、steps 和 CanonicalRule 候选；
4. 对比旧/新规则数量、值、人群、条件和证据；
5. 差异进入人工审核，不自动覆盖；
6. 通过后生成新 Release 并切换 Runtime；
7. 无法重建的历史规则仅建立 LEGACY_IMPORT 记录，明确缺失步骤，不伪造中间结果。

## 9. 错误处理与回滚

- LLM 输出不是合法结构：保存 LLM_EXTRACTION FAILED，禁止编译；
- 引用缺失或歧义：保存 NOT_FOUND/AMBIGUOUS Issue，进入 REVIEW；
- 规则冲突或区间重叠：保存 CONFLICT Issue，进入 REVIEW/FAIL；
- 比例、金额或时间非法：Schema Validation FAIL；
- PostgreSQL 轨迹写入失败：停止，不构建或激活 Release；
- Milvus Release 构建失败：保存 PUBLISH FAILED，活动 Release 不变；
- 激活失败：保留未激活 Release 和完整轨迹，活动 Release 不变。

回滚使用现有活动 Release 指针切回上一版本；编译 run 和 steps 为审计记录，不删除。

## 10. 测试策略

本改动横跨 `knowledge_extension`、存储、Runtime API 和 Portal，按 R4 执行人工设计与完整串行验证。

### T1 单元测试

- 模型校验；
- 比例、金额、人群、区间标准化；
- RuleKey 组合；
- RESOLVED/AMBIGUOUS/NOT_FOUND/CONFLICT；
- MULTIPLY、COMPLEMENT、DIRECT_COPY；
- Schema/Semantic/Relation/Consistency Validator；
- 内存和 PostgreSQL Store 契约；
- 第三十六条、第二次住院 Golden Test；
- 基础规则缺失、冲突、比例大于 100%、区间重叠 Mutation Test。

### T2a API 测试

- 正常规则轨迹查询；
- 派生规则依赖和公式；
- 历史 LEGACY_IMPORT；
- 不存在的 rule_id；
- 未授权访问；
- 强类型响应契约。

### T2b Flow 测试

完整验证 Extraction → run/steps → ChangeSet → Review → Release → Runtime → Trace。另验证任何步骤失败时活动 Release 不变且故障现场可查询。

### Portal 验证

- Vitest：按钮、抽屉、懒加载、步骤展开、输入/输出、错误态和历史态；
- TypeScript `tsc --noEmit`；
- Playwright：从规则知识列表打开溯源抽屉并检查完整步骤。

严格按 T1 → T2a → T2b → Portal 顺序执行，前一步失败即停止。

## 11. 明确不做

V1 不建设大而全 DSL、可视化规则编排器、通用规则平台、复杂跨文件模糊引用、复杂资格审批或嵌套例外推理。首版不新建独立管理门户，也不复制现有 ChangeSet/Release 能力。

## 12. 实施边界

最小可验证用户故事：

> 政策管理员查看一条已发布规则，点击「查看溯源」，能够看到该规则对应的政策输入、LLM 提取结果、每个确定性编译步骤的输入输出、校验问题和发布版本；任一不确定或轨迹缺失的规则不能进入活动 Runtime。

该故事完成前不扩展 V2 能力。
