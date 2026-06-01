# 统筹自付解释样板链路设计

## 背景

当前政策问答链路已经具备“意图识别 → SQL 查询 → 问题重写 → 政策检索 → 费用拆分 Skill → 解释生成”的骨架，但对“为什么我这次统筹自付这么多？”这类问题没有形成稳定的可解释闭环。

主要问题不是缺少某一个步骤，而是步骤之间缺少结构化契约：

- 意图识别只得到粗粒度的待遇分解意图，后续无法明确目标金额是“统筹自付”。
- SQL 查询结果包含业务字段，但人员类别、险种、医疗类别、金额字段没有以稳定结构传递到后续步骤。
- 问题重写把业务上下文和检索查询混在一段长文本里，影响政策检索命中率。
- 政策检索没有稳定聚焦“城镇职工 + 住院 + 退休 + 统筹分段比例 + 退休人员系数”。
- 费用 Skill 有分段计算雏形，但没有把“业务库已结算金额为权威值”和“政策计算值为解释校验值”区分清楚。
- 解释生成容易只复述金额，而不是把金额、政策条文、比例、人员系数和计算过程串成因果链。

本设计只聚焦一个样板链路：用户询问“为什么这次统筹自付这么多？”时，系统必须通过 SQL 补充上下文，检索相关政策规则，找到费用解释 Skill，按分段规则计算并解释该数字。

## 目标

1. 将“统筹自付”识别为明确目标金额，而不是泛化为普通待遇分解。
2. 基于 SQL 查询补齐解释所需上下文：险种、医疗类别、人员类别、起付线、医保内金额、统筹自付、统筹支付、大额金额等。
3. 用结构化上下文重写检索查询，稳定命中“城镇职工退休人员住院统筹分段自付比例”相关政策。
4. 费用 Skill 按“分段金额 × 基础自付比例 × 退休人员系数”计算统筹自付解释值。
5. 以业务库 `yb_zyfdxx.bdtczf` 为权威金额，政策计算值只用于解释和校验。
6. 当计算值与业务库金额差异超过 `0.01` 元时，明确提示“政策解释计算与结算结果存在差异，需要人工复核”。
7. 输出必须包含数据来源字段、政策依据或不确定性声明。

## 非目标

1. 不在本次设计中完整重建通用费用解释树引擎。
2. 不覆盖所有医保外归因、目录自付、门诊、居民医保、异地就医等场景。
3. 不让大模型自行推断比例、分段、人员系数或金额。
4. 不替代医保正式结算结果；解释仅用于辅助理解与复核。

## 推荐方案

采用“现有运行时链路内补结构化统筹自付解释契约”的最小可行方案。

相比只改 Prompt，本方案能把业务上下文、检索目标、政策规则、计算过程和金额对账稳定串起来；相比直接做通用解释树，本方案范围更小，能先把用户最关注的样板问题打通，并为后续扩展其他金额解释保留结构。

## 数据流

```text
用户问题
  → 意图识别：target_fee_item = pooling_self_pay
  → SQL 查询：补齐城镇职工 / 普通住院 / 退休 / 金额字段
  → 结构化解释上下文：PoolingSelfPayContext
  → 问题重写：短检索查询 + 独立解释上下文
  → 政策检索：统筹分段比例规则 + 退休人员系数规则
  → FeeDecompositionSkill：分段计算与业务库金额对账
  → ExplanationGenerator：模板化/受约束解释
  → SSE/API 输出：金额、分段、政策依据、差异提示
```

## 组件设计

### 1. 意图识别

落点：[`src/runtime/policy_qa/intent_detector.py`](../../../src/runtime/policy_qa/intent_detector.py:95)、[`src/runtime/policy_qa/models.py`](../../../src/runtime/policy_qa/models.py:32)

保留现有 `PolicyQAIntent` 粗粒度枚举，同时给 `PolicyQAIntentResult` 增加结构化目标字段：

- `target_fee_item`: 当前目标费用项，样板链路使用 `pooling_self_pay`。
- `target_fee_label`: 面向用户的费用项名称，样板链路为“统筹自付”。

关键词降级规则：

- 包含“统筹自付”“统筹自费”“统筹个人自付”时，设置 `target_fee_item="pooling_self_pay"`。
- 包含“为什么”“这么多”“怎么算”“怎么来的”等解释词时，优先设置 `query_type="统筹自付解释"`。
- 粗粒度 `intent` 可继续使用 `TREATMENT_DECOMPOSITION` 或 `PAYMENT_RATIO`，但后续步骤必须以 `target_fee_item` 为准。

### 2. SQL 上下文补齐

落点：[`src/runtime/policy_qa/sql_data_fetcher.py`](../../../src/runtime/policy_qa/sql_data_fetcher.py:52)、[`src/knowledge_extension/rule_explanation/policy_retrieval/config/business_sql.yaml`](../../../src/knowledge_extension/rule_explanation/policy_retrieval/config/business_sql.yaml:45)

SQL 查询结果需要稳定输出以下字段：

- 身份上下文：`fund_type`、`fund_type_raw`、`PER_TYPE`、`PER_TYPE_raw`、`yllb`、`yllb_raw`。
- 金额上下文：`bcybnje`、`bcqfje`、`bdtczf`、`bdtczfje`、`bddegwyzf`、`bddegwyzfje`、`bdgryf`、`bdfyzje`。
- 解释辅助字段：`fynd`、`zqxh`、`missing_fields`。

关键要求：

- 人员类别必须能识别退休。若字典标准化结果不是“退休”但原始值包含退休语义，也要保留原始值供人员系数判断。
- 险种必须能识别城镇职工。
- 医疗类别必须能识别住院。
- 当前 SQL 没有统筹分段医保内金额时，允许使用现有估算逻辑：`医保内金额 - 大额支付 - 大额自付`，但必须在解释中标注“按现有字段估算统筹分段基数”。

### 3. 问题重写

落点：[`src/runtime/policy_qa/question_rewriter.py`](../../../src/runtime/policy_qa/question_rewriter.py:61)、[`src/runtime/policy_qa/models.py`](../../../src/runtime/policy_qa/models.py:52)

问题重写输出拆为两类信息：

1. `search_query`：只用于政策检索的短查询。
2. `explanation_context`：用于解释生成的业务上下文。

样板链路的检索查询示例：

```text
城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例 退休人员个人负担比例
```

不再把大段“业务上下文 + 用户问题”整体塞入向量检索文本。这样可以减少噪声，让检索更稳定命中统筹分段比例规则和退休优惠规则。

### 4. 政策检索

落点：[`src/runtime/policy_qa/orchestrator.py`](../../../src/runtime/policy_qa/orchestrator.py:240)、[`src/runtime/policy_qa/policy_rules_search.py`](../../../src/runtime/policy_qa/policy_rules_search.py:52)

样板链路需要检索两类政策规则：

1. 统筹分段比例规则：例如起付线以上至 3 万、3 万至 4 万、4 万以上的基础自付比例。
2. 退休人员系数规则：退休人员按基础自付比例的 60% 承担，或等价表述。

检索过滤策略：

- 优先过滤 `insu_type=城镇职工`。
- 优先过滤住院医疗类别。
- 人员类别优先匹配退休；如果政策规则使用“在职/退休”或“全部”，也允许作为候选。
- `rule_type` 优先匹配“统筹分段”“支付比例”“退休优惠”“人员系数”等。
- 如果强过滤无结果，逐步放宽过滤并记录 `warnings`，不能静默降级。

### 5. 费用解释 Skill

落点：[`src/runtime/policy_qa/fee_decomposition_skill.py`](../../../src/runtime/policy_qa/fee_decomposition_skill.py:36)、[`src/runtime/policy_qa/models.py`](../../../src/runtime/policy_qa/models.py:85)

Skill 负责生成可解释计算事实，而不是只给自然语言描述。

核心公式：

```text
统筹自付解释值 = Σ(分段内金额 × 基础自付比例 × 人员系数)
```

样板链路规则：

- 分段基数优先使用统筹分段医保内金额；缺失时使用 `医保内金额 - 大额支付 - 大额自付` 估算。
- 起算位置从本次起付线 `bcqfje` 之后开始。
- 退休人员系数为 `0.6`；在职人员系数为 `1.0`。
- 每个分段必须输出：分段范围、段内金额、基础比例、人员系数、实际比例、段内自付金额、政策来源。
- 合计后与业务库 `bdtczf` 对账。

新增对账结构建议：

```text
reconciliation:
  authoritative_amount: 业务库 bdtczf
  calculated_amount: Skill 分段计算合计
  difference: calculated_amount - authoritative_amount
  tolerance: 0.01
  matched: abs(difference) <= 0.01
  message: 对账结论
```

金额显示规则：

- 面向用户展示的“本次统筹自付金额”始终使用业务库 `bdtczf`。
- 分段过程展示 Skill 计算值。
- 差异超过 `0.01` 元时，必须输出复核提示。

### 6. 解释生成

落点：[`src/runtime/policy_qa/explanation_generator.py`](../../../src/runtime/policy_qa/explanation_generator.py:131)

解释生成器必须以结构化结果为事实来源：

- 可以由模板直接生成稳定解释。
- 如果调用 LLM，只允许润色模板事实，不允许新增比例、金额、分段或政策条文。
- 输出需要包含：患者上下文、业务库金额、分段计算过程、政策依据、对账结果、不确定性或复核提示。

样板输出结构：

```text
根据本次结算信息，您属于城镇职工医保、普通住院、退休人员。

本次业务库已结算的统筹自付金额为 X 元，来源为 yb_zyfdxx.bdtczf。

政策解释计算过程如下：
1. 起付线以上至 3 万元：段内金额 A 元 × 基础自付比例 15% × 退休人员系数 60% = B 元。
2. 3 万元至 4 万元：段内金额 C 元 × 基础自付比例 10% × 退休人员系数 60% = D 元。
3. 4 万元以上：段内金额 E 元 × 基础自付比例 5% × 退休人员系数 60% = F 元。

政策解释计算合计为 Y 元。业务库金额为 X 元。
若差异超过 0.01 元：政策解释计算与结算结果存在差异，需要人工复核。

依据：列出检索命中的政策条文；如未命中完整政策条文，则列出不确定性声明。
```

## 错误处理与边界条件

1. SQL 无结算记录：返回无法查询本次结算信息，不进入政策解释计算。
2. 缺少 `bdtczf`：不能回答具体统筹自付金额，只能提示业务库缺少权威金额。
3. 缺少人员类别：不能套用退休系数；输出不确定性。
4. 缺少政策分段规则：不编造比例，输出“政策分段规则不足，无法稳定解释计算过程”。
5. 检索只有部分分段：只展示已命中分段，并提示规则不完整，不能给出完整合计解释。
6. Skill 计算与业务库差异超过 `0.01` 元：以业务库为准，并提示人工复核。
7. LLM 不可用：使用模板解释作为降级输出。
8. Milvus 不可用：仍展示业务库金额和 SQL 上下文，但必须声明政策依据检索失败。

## 验收标准

对请求“为什么我这次统筹自付这么多？”：

1. 意图结果中必须包含 `target_fee_item="pooling_self_pay"`。
2. 重写查询必须包含城镇职工、退休、住院、统筹分段或自付比例关键词。
3. SQL 上下文必须保留业务库金额 `bdtczf`。
4. 检索结果必须优先包含统筹分段比例规则；缺失时输出明确 warning。
5. Skill 输出必须包含分段计算列表和对账结构。
6. 用户解释必须明确：业务库金额是权威金额；政策计算值是解释校验值。
7. 差异超过 `0.01` 元时必须输出人工复核提示。
8. 输出必须包含政策依据或不确定性声明。

## 测试策略

遵循项目硬性验证顺序：单元测试 → API 测试 → Flow 测试。

### 单元测试

落点建议：[`src/tests/unit/runtime/policy_qa/test_policy_qa.py`](../../../src/tests/unit/runtime/policy_qa/test_policy_qa.py:1)

新增或加固用例：

1. “统筹自付/统筹自费”识别为 `target_fee_item="pooling_self_pay"`。
2. SQL 上下文中“退休”可被稳定识别为退休人员系数 `0.6`。
3. 重写查询为短查询，包含城镇职工、退休、住院、统筹分段、自付比例。
4. 分段计算按基础比例与退休系数得到正确段内自付金额。
5. 对账容差为 `0.01` 元；差异超过容差时 `matched=false` 并返回复核提示。
6. 缺少政策分段规则时不编造比例。

### API 测试

落点建议：[`src/tests/integration/api/test_policy_qa_routes.py`](../../../src/tests/integration/api/test_policy_qa_routes.py:1)

验证流式接口返回步骤中包含：

- 意图步骤：目标费用项。
- 重写步骤：短检索查询。
- 分解步骤：统筹自付分段和对账结构。
- 解释步骤：业务库金额、政策计算过程、政策依据或不确定性。

### Flow 测试

落点建议：[`src/tests/integration/flow`](../../../src/tests/integration/flow)

端到端验证：

- 输入“为什么我这次统筹自付这么多？”。
- 输出包含“城镇职工”“住院”“退休”“统筹自付”。
- 输出包含分段比例、退休人员系数、业务库金额和政策依据。
- 当构造计算差异超过 `0.01` 元时，输出人工复核提示。

## 实施约束

1. 不直接修改正式结算结果。
2. 不让 LLM 生成未经检索或计算验证的比例和金额。
3. 所有模型调用仍通过统一模型网关。
4. 所有解释必须可追溯到 SQL 字段、政策规则或明确的不确定性声明。
5. 代码改造完成后，必须按项目规定顺序运行单元测试、API 测试、Flow 测试。

