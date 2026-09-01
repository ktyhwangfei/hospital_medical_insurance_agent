# Issue #25 评估报告：医保政策知识结构化索引与最小混合检索

> **定位**：Issue #25 第一阶段的结构化评估报告，供人工确认后进入编码。  
> **状态**：评估草案，核心数据待真实 Milvus 与结算库验证。  
> **约束**：本报告不涉及提取契约、Milvus schema、索引或存量数据的实际修改。

---

## 1. 执行摘要

### 1.1 结论速览

| 问题 | 结论 | 证据 |
|------|------|------|
| 是否需要补强适用性字段？ | **是**。当前 `policy_rules_v2` 的固定 schema 缺少地区、有效期、发布状态、政策版本、异地/转诊标记，导致跨地区/跨年度/异地就医场景无法可靠过滤。 | [来源: `policy_rules_schema_v2.py` CORE_DIM_FIELDS 仅 6 个业务维度] |
| 是否需要立即建立层级索引？ | **否，证据不足**。当前用例规模（72 条）未证明必须引入树形/层级索引；标量过滤 + 适用性字段即可覆盖 80% 以上场景。 | [推断: 基于用例分层分析] |
| 是否需要知识图谱？ | **否**。当前规则以"一条规则 = 条件 + 结果 + 证据"即可表达，跨规则关系（如退休折算）可通过派生规则或运行时关联解决，无需图数据库。 | [来源: Issue 9 退休折算已用 `rule_derivation.derive_personal_payment_ratios` 解决] |
| 最小可验证实施单元？ | 在 `policy_rules_v2` 中新增 `region`、`effective_date`、`expiry_date`、`publish_status`、`policy_version`、`is_remote` 等字段；仅对其中高频过滤字段建物理索引；更新 `StructuredPolicyRuleRetriever` 在运行时消费这些字段；同时保留/引入向量/BM25 作为宽泛问题的宽召回层。 | [建议] |

### 1.2 关键指标预期（待真实数据验证）

| 指标 | 纯文本召回 | 当前混合检索 | 补强适用性字段后 | 向量+BM25+结构化字段 |
|------|:----------:|:------------:|:----------------:|:--------------------:|
| 错误适用规则率（FAR） | 高（>30%） | 中（15-25%） | 低（<8%） | 低（<8%） |
| 适用规则准确率（P@3） | 中（60-70%） | 中高（75-85%） | 高（>90%） | 高（>90%） |
| 证据召回率 | 高但不精确 | 中 | 高且精确 | 高且精确 |
| 完整回答率 | 中 | 中高 | 高 | 高 |
| 诚实拒答率 | 低 | 中 | 高 | 高 |
| 宽泛问题召回 | 高 | 低 | 低 | 高 |

> 注：以上为基于代码结构和用例设计的**方向性预期**，非实测结果。实测需在 Milvus 与结算库可用时执行。

---

## 2. 评估目标与范围

### 2.1 目标

1. 量化当前检索在适用性判断上的缺陷。
2. 明确哪些字段必须从"文本/详情字段"提升为"结构化标量字段"。
3. 给出地区、有效期、发布状态、政策版本的运行时消费方案。
4. 判断是否需要层级索引或知识图谱。
5. 形成最小可验证实施计划。

### 2.2 范围边界

- **生产读路径**：`src/runtime/policy_qa/structured_policy_retriever.py`（Policy QA 唯一入口 `/policy-qa/stream`）。
- **参考路径**：`src/knowledge_extension/rule_explanation/policy_retrieval/milvus_retriever.py`（旧 fact/node 混合检索，不直接服务生产 Policy QA）。
- **schema 基线**：`src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py`。
- **数据集**：`docs/reviews/2026-09-01-issue25-golden-cases.md` 72 条黄金用例。

### 2.3 非目标

- 不修改提取契约。
- 不修改 Milvus schema。
- 不重建索引。
- 不迁移/重写存量数据。

---

## 3. 三条基线设计方案

### 3.1 基线 A：纯文本召回

**实现方式**：
- 对 `policy_rules_v2` 的 `source_text` 和 `rule_value` 做向量检索（复用现有 `vector` 字段）。
- 不使用任何标量过滤（insu_type/med_type/hosp_lv/psn_type 等）。
- 检索结果直接作为证据，不做适用性校验。

**目的**：建立"无结构=高误召回"的下限。

**预期问题**：
- 地区错误：北京/上海/广州同名规则均可能召回。
- 时间错误：新旧政策同时召回。
- 人群错误：在职/退休规则混淆。
- 医疗类别错误：住院/门诊规则混淆。

### 3.2 基线 B：当前混合检索

**实现方式**：
- 使用当前 `StructuredPolicyRuleRetriever`：标量过滤 + source_text 关键词过滤。
- 使用 Skill 定义的 `build_policy_queries`（如 `pooling_self_pay` 的 YAML 查询计划）。
- 向量仅作为 schema 要求存在，实际不用于排序或召回。

**目的**：建立当前生产实现的基线。

**已知限制**：
- 只能过滤已固定 schema 的 6 个维度（rule_type/insu_type/med_type/hosp_lv/psn_type/setl_type）。
- `psn_type` 多值用逗号串存储，精确人群检索失败（Issue 9 遗留）。
- 缺少地区、时间、异地、版本字段，相关维度无法过滤。
- 对宽泛问题（无结算上下文）召回能力不足，因为必须依赖结构化查询条件。

### 3.3 基线 C：向量/BM25 宽召回 + 补强适用性字段的混合检索

**实现方式**：
- 对宽泛问题（无明确结算上下文或问题不指向具体费用项）：先通过向量检索（`vector` 字段）和/或 BM25（`source_text` 全文索引）做宽召回，再利用新增适用性字段做精排/过滤。
- 对结算单驱动的精确场景：继续使用 `StructuredPolicyRuleRetriever` 标量过滤，并增加 `region`、`effective_date`、`expiry_date`、`publish_status`、`policy_version`、`is_remote` 过滤。
- 在内存/mock 中模拟新增字段，对高频过滤字段建立 mock 索引，其余字段做查询后过滤。

**目的**：同时验证"补强字段提升准确率"和"向量/BM25 提升宽泛问题召回率"两个收益。

**约束**：
- 由于不改 schema，基线 C 通过 Python 内存过滤模拟，不写入 Milvus。
- 向量/BM25 能力复用现有 `vector` 字段；BM25 需要 Milvus 2.5+ 或引入 Elasticsearch，本阶段仅做方案设计，不实际部署。

---

## 4. 可重复评估脚本设计

### 4.1 输入

- 黄金用例 JSON（从 `docs/reviews/2026-09-01-issue25-golden-cases.md` 解析）。
- 当前 policy_rules_v2 快照（通过 `query_rules_by_doc` 或全量 `query` 导出）。

### 4.2 输出

- 每条用例在三条基线下的：召回规则列表、适用/不适用判定、`answer_status`、P95 时延。
- 汇总指标表。
- 逐案差异 Markdown。

### 4.3 脚本位置建议

```
scripts/eval/issue25_retrieval_baseline.py
```

**脚本伪代码**：

```python
# 1. 加载黄金用例
# 2. 加载 policy_rules_v2 规则快照
# 3. 对每条用例：
#    a. 基线 A：纯向量检索 source_text（使用现有 embedding_text/vector）
#    b. 基线 B：调用 StructuredPolicyRuleRetriever（当前实现）
#    c. 基线 C：向量/BM25 宽召回 → 内存适用性字段精排/过滤
#       - 有结算上下文：优先 StructuredPolicyRuleRetriever + 新增字段
#       - 宽泛问题：向量/BM25 召回 top_k → 按 region/effective_date 等字段过滤
# 4. 计算指标并输出 report.json / report.md
# 5. 单独输出宽泛问题子集的召回贡献分析
```

### 4.4 环境要求

- Milvus 可连接（当前 WSL2 Docker，需 `networkingMode=mirrored`）。
- 可选：真实结算库（用于验证 settlement_context 映射）；无库时允许手工注入上下文。

---

## 5. 代码现状分析

### 5.1 当前 schema 可用字段

[来源: `src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py`]

```python
CORE_DIM_FIELDS = (
    "rule_id", "fact_id", "doc_id",
    "rule_type",    # 规则业务类别
    "insu_type",    # 险种
    "med_type",     # 医疗类别
    "hosp_lv",      # 医院等级
    "psn_type",     # 人群标签
    "setl_type",    # 结算方式
    "schema_version",
    "vector",
)
```

`DETAIL_FIELDS` 走 dynamic field，含 `payment_ratio`、`personal_payment_ratio`、`deductible_amount`、`cap_amount`、`amount_band`、`time_period`、`admission_order`、`priority`、`rule_value`、`source_text`、`entities`、`relations`。

### 5.2 当前检索实现

[来源: `src/runtime/policy_qa/structured_policy_retriever.py`]

- 使用 `MilvusClient.query` 做标量过滤。
- `expr` 构建：字段相等/LIKE 过滤。
- `psn_type` 可宽松匹配（`psn_type_allow_all`）。
- `source_text` 关键词过滤在查询后 Python 层执行。
- 去重使用 `rule_instance_key`（基于 policy_id/clause_id/source_text/维度字段等）。

### 5.3 当前缺失字段

| 业务维度 | 当前状态 | 影响 |
|----------|----------|------|
| 地区（region） | 无 | 异地/跨地区用例无法过滤 |
| 生效日期（effective_date） | 无 | 跨年度/过渡期用例无法过滤 |
| 失效日期（expiry_date） | 无 | 已废止规则可能错误召回 |
| 发布状态（publish_status） | 无 | 试行/征求意见稿可能误用 |
| 政策版本（policy_version） | 无 | 政策替代/修订无法追踪 |
| 异地标记（is_remote） | 无 | 本地/异地规则混淆 |
| 转诊类型（referral_type） | 无 | 转诊规则无法精确命中 |
| 金额段下限（amount_band_low） | 无（仅文本） | 无法按金额数值过滤 |
| 金额段上限（amount_band_high） | 无（仅文本） | 无法按金额数值过滤 |
| 险种细分 | 部分（insu_type） | 新农合/公费医疗等可能缺失 |

---

## 6. 字段清单：必须结构化 / 仅存储 / 建立物理索引

### 6.1 必须结构化（进入固定 schema + 标量索引）

> 这些字段高频用于过滤，且值域有限/可标准化，必须进入 `CORE_DIM_FIELDS` 并建索引。

| 字段 | 类型 | 默认值/值域示例 | 建索引理由 |
|------|------|-------------------|------------|
| `region` | VARCHAR | "北京"（默认）、上海、广州、京津冀、全国 | 地区是最强适用性维度之一 |
| `effective_date` | VARCHAR | "1900-01-01" | 年度过滤、跨年结算；格式 `YYYY-MM-DD` |
| `expiry_date` | VARCHAR | "9999-12-31" 表示长期有效 | 过滤已废止规则；格式 `YYYY-MM-DD` |
| `publish_status` | VARCHAR | "published"、draft、revoked、pilot | 防止草稿/试行规则误用 |
| `policy_version` | VARCHAR | "1.0"、"2025_v1"、"2026_v2" | 政策替代与追溯 |
| `is_remote` | BOOL | false | 异地规则快速过滤 |

### 6.2 仅存储（进入 dynamic field 或详情字段，不建索引）

> 这些字段用于展示、溯源或低频过滤，不适合建标量索引。

| 字段 | 类型 | 说明 |
|------|------|------|
| `policy_title` | VARCHAR | 政策标题，用于 citation 展示 |
| `clause_path` | VARCHAR | 条款路径，用于溯源 |
| `clause_id` | VARCHAR | 条款 ID，关联 policy_documents |
| `replaces` | VARCHAR | 被替代的政策版本，用于治理 |
| `amends` | VARCHAR | 修订来源，用于治理 |
| `notes` | TEXT | 人工审核备注 |
| `entities` | JSON | 提取的实体，供 S5 冲突诊断 |
| `relations` | JSON | 实体关系，供治理台展示 |

### 6.3 建立物理索引（在固定 schema 中新增后）

> 索引策略：对高频等值/范围查询字段建立标量索引；向量索引保持现有 `vector` 不变。

| 字段 | 索引类型 | 理由 |
|------|----------|------|
| `region` | 标量索引 | 等值过滤，高频 |
| `effective_date` | 标量索引 | 范围过滤，高频 |
| `expiry_date` | 标量索引 | 范围过滤，高频 |
| `publish_status` | 标量索引 | 等值过滤，高频 |
| `policy_version` | 标量索引 | 等值过滤，中频 |
| `is_remote` | 标量索引 | 布尔过滤，高频 |
| `amount_band_low` / `amount_band_high` | 标量索引 | 数值范围过滤，中频 |

---

## 7. 运行时消费方案

### 7.1 地区（region）

**消费位置**：`StructuredPolicyRuleRetriever.plan_queries`

**规则**：
1. 从结算上下文获取 `region`：优先参保地，异地就医时同时考虑就医地。
2. 若 `region` 为空，默认使用本地（如"北京"）。
3. 查询 expr 增加 `region == "{region}" or region == "全国"`。

**示例**：
```python
expr_parts.append(f'(region == "{ctx.region}" or region == "全国")')
```

### 7.2 有效期（effective_date / expiry_date）

**消费位置**：`StructuredPolicyRuleRetriever.execute_query` 或查询规划层。

**规则**：
1. 从结算上下文获取 `settlement_date`，格式统一为 `YYYY-MM-DD`。
2. 过滤条件：`effective_date <= settlement_date <= expiry_date`。
3. 若规则 `expiry_date` 为 "9999-12-31"，视为长期有效。

**示例**：
```python
expr_parts.append(f'effective_date <= "{settlement_date}"')
expr_parts.append(f'(expiry_date == "9999-12-31" or expiry_date >= "{settlement_date}")')
```

### 7.3 发布状态（publish_status）

**消费位置**：查询规划层。

**规则**：
1. 默认只查询 `publish_status == "published"`。
2. 治理台调试模式可放开到 `draft`/`pilot`，但 Runtime 只消费 `published`。

### 7.4 政策版本（policy_version）

**消费位置**：查询后去重/排序。

**规则**：
1. 对同一政策主题的多版本规则，取 `policy_version` 最新且 `effective_date <= settlement_date` 的版本。
2. 若存在 `replaces` 关系，优先返回替代版本。
3. 在 `rule_instance_key` 中纳入 `policy_version`，避免不同版本被去重覆盖。

---

## 8. 层级索引 vs 知识图谱：证据化结论

### 8.1 层级索引

**定义**：按"政策文件 → 章 → 条 → 项 → 目"建立树形索引，支持层级导航和聚合。

**分析**：
- 当前 `policy_documents` 已通过 `structure_parser` 维护文档结构，`doc_id` + `clause_id` 已能表达层级关系。
- 检索粒度是"规则"而非"文档节点"，规则本身已携带 `clause_id` 溯源。
- 72 条黄金用例中，没有一例必须依赖层级索引才能正确判定适用性。

**结论**：**暂不建立独立层级索引**。现有 `doc_id/clause_id` + 适用性字段已足够。[已确认]

### 8.2 知识图谱

**定义**：将政策、规则、条件、结果、人群、医院、疾病等建模为图节点和关系。

**分析**：
- 当前规则表达形式为"条件 → 结果"，本质是属性图，可用标量字段覆盖。
- 跨规则关系（如退休折算 = 在职比例 × 0.6）已通过 `rule_derivation.derive_personal_payment_ratios` 在编译期派生为独立规则，无需图遍历。
- 政策替代/修订关系可通过 `replaces`/`amends` 字段线性表达。
- 引入知识图谱会增加存储、查询复杂度和治理成本。
- 医保政策问答当前阶段以"高召回、高准确、可溯源到政策"为核心，结构化标量字段 + 向量/BM25 混合检索更能直接满足该场景。

**结论**：**暂不引入知识图谱**。优先通过标量字段 + 派生规则 + 向量/BM25 混合检索解决问题，保留未来扩展可能。[已确认]

### 8.3 什么情况下需要重新评估？

- 出现必须跨文档、跨章节、跨政策文件进行多跳推理才能回答的用例。
- 政策规则数量达到万级，标量索引性能显著下降。
- 业务方明确要求可视化政策血缘/影响分析。

---

## 9. 预期逐案差异示例

### 示例 1：A02（上海就医，北京政策不适用）

| 基线 | 召回规则 | 判定 | 问题 |
|------|----------|------|------|
| A 纯文本 | 北京职工住院分段比例 | 错误适用 | 无地区过滤 |
| B 当前混合 | 北京职工住院分段比例 | 错误适用 | 无 `region` 字段 |
| C 补强字段 | 无 / MISSING | unavailable | `region == 上海` 无匹配 |

### 示例 2：B10（2023年旧比例今年不适用）

| 基线 | 召回规则 | 判定 | 问题 |
|------|----------|------|------|
| A 纯文本 | 2023年规则 + 2026年规则 | 混乱 | 无时间过滤 |
| B 当前混合 | 可能召回 2023/2026 规则 | 可能错误 | 无 `effective_date/expiry_date` |
| C 补强字段 | 2026年现行规则 | complete | 时间过滤生效 |

### 示例 3：C25（人群字段"在职职工,退休人员"）

| 基线 | 召回规则 | 判定 | 问题 |
|------|----------|------|------|
| A 纯文本 | 复合人群规则 | 可能正确 | 文本相似 |
| B 当前混合 | 复合人群规则 | 可能错误 | `psn_type == 退休人员` 无法命中逗号串 |
| C 补强字段 | 退休规则（需人群数组化） | complete | 人群数组化后精确匹配 |

> 说明：C25 也说明 Issue 9 遗留的 `psn_type` 数组化仍需解决，属于 Issue 25 可顺带验证的数据质量项。

---

## 10. 风险与建议

### 10.1 数据质量风险

- 新增字段后，存量规则需要回填，否则新字段为空会导致规则被过度过滤。
- `region`、`effective_date` 等字段依赖政策文档元数据，若上传时未提取则需补充文档级信息。
- 回填策略采用**提议者-审核者模型**：系统自动提议默认值（如 `region="北京"`、`expiry_date="9999-12-31"`），人工在知识审核页复核并修正后发布；避免全量自动回填引入不可见的适用性错误。

### 10.2 性能风险

- 标量索引字段增加会提高存储和写入成本，但 Milvus 标量索引开销相对可控。
- `effective_date/expiry_date` 的范围查询需确认 Milvus 标量索引是否支持高效范围过滤；若不支持，可在应用层做二次过滤。

### 10.3 治理风险

- `publish_status` 和 `policy_version` 需要与发布管理流程联动，避免治理态与运行态不一致。
- 建议新增字段后，旧规则默认 `publish_status="published"`、`expiry_date="9999-12-31"`，`region="北京"`，避免升级后规则不可见。

---

## 11. 不确定性声明

- [来源: `docs/reviews/2026-09-01-issue25-golden-cases.md`] 72 条用例为构造数据，未经过真实线上结算库验证。
- [来源: 当前工作区无 `.env` MODEL_API_KEY] 无法运行真实模型和完整 Policy QA 流程；基线 C 通过内存模拟实现。
- [推断: 基于 `policy_rules_schema_v2.py` 和 `structured_policy_retriever.py`] 字段缺失为代码事实；收益预期为方向性判断，非实测。
- [建议] 人工确认本报告后，优先执行一次真实数据对跑，再决定是否进入编码。

---

## 12. 最小可验证实施计划（MVP）

### 阶段 1：字段与 schema 设计（1 周）

1. 在 `policy_rules_schema_v2.py` 的 `CORE_DIM_FIELDS` 中新增：
   - `region`（VARCHAR，默认"北京"）
   - `effective_date`（VARCHAR，默认"1900-01-01"，格式 `YYYY-MM-DD`）
   - `expiry_date`（VARCHAR，默认"9999-12-31"，格式 `YYYY-MM-DD`）
   - `publish_status`（VARCHAR，默认"published"）
   - `policy_version`（VARCHAR，默认"1.0"）
   - `is_remote`（BOOL，默认 false）
2. 在 `_create_indexes` 中为新增高频字段建立标量索引。
3. 更新 `rule_to_entity`：从上传的文档元数据或规则提取结果中读取这些字段；日期统一转 `YYYY-MM-DD`。
4. 更新 `unpack_detail` 和 `OUTPUT_FIELDS`，确保下游无感。

### 阶段 2：检索层消费（1 周）

1. 在 `NormalizedPolicyContext` 中新增：`region`、`settlement_date`、`is_remote`。
2. 在 `StructuredPolicyRuleRetriever` 中：
   - `plan_queries` 默认注入 `region`、`publish_status` 过滤。
   - `execute_query` 注入 `effective_date/expiry_date` 范围过滤。
   - 对 `is_remote` 场景增加异地规则过滤逻辑。
3. 更新 `policy_qa_routes.py` 的 `_normalize_*` 函数，从 settlement_context 映射新字段。

### 阶段 3：数据回填与迁移（1-2 周）

采用**提议者-审核者模型**：

1. **系统提议**：对存量 policy_rules_v2 规则自动生成默认值：
   - `region` 默认"北京"。
   - `effective_date` 从文档元数据或发布记录推断；无法推断则默认"1900-01-01"。
   - `expiry_date` 默认"9999-12-31"。
   - `publish_status` 默认"published"。
   - `is_remote` 默认 false。
2. **人工审核**：在知识审核页展示系统提议，审核人员可逐条修正 `region`、`effective_date`、`expiry_date`、`is_remote` 等字段；修正后进入发布流程。
3. **发布生效**：审核通过后的规则重新写入 policy_rules_v2，未审核规则保持默认值可见但标记为 `proposed`。

### 阶段 4：混合检索增强（向量/BM25）（1 周）

1. 在 `StructuredPolicyRuleRetriever` 中增加宽召回分支：
   - 检测问题/上下文：有 `settlement_id` 且问题指向具体费用项 → 走结构化标量过滤。
   - 无结算上下文或问题宽泛 → 走向量/BM25 宽召回，再经适用性字段过滤。
2. 向量召回复用现有 `vector` 字段；BM25 评估 Milvus 2.5+ 全文索引或 Elasticsearch 集成成本。
3. 新增 `answer_mode` 标记，前端/日志可区分"结构化精确匹配"与"宽召回+精排"。

### 阶段 5：评估与验证（1 周）

1. 运行 `scripts/eval/issue25_retrieval_baseline.py`，对比三条基线。
2. 目标：FAR < 8%，P@3 > 90%，诚实拒答率 > 80%。
3. 增加宽泛问题子集，验证向量/BM25 对召回率的贡献。
4. 通过后更新 `PROGRESS.md` 和 `docs/steering/政策知识治理-需求迭代记录.md` Issue 25 小节状态为"已验证"。

### 阶段 6：后续可选扩展

- 若金额分段过滤需求强烈，将 `amount_band_low`/`amount_band_high` 提升为固定 schema 字段。
- 若转诊/异地场景复杂，增加 `referral_type`、`settlement_mode` 字段。
- 仅当出现多跳推理需求时，再评估层级索引或知识图谱。

---

## 13. 决策确认记录（2026-09-01）

| # | 问题 | 决策 |
|---|------|------|
| 1 | 新增字段清单（§6.1） | ✅ 确认 |
| 2 | `region` 默认值 | ✅ 使用"北京" |
| 3 | `effective_date`/`expiry_date` 格式 | ✅ `YYYY-MM-DD` VARCHAR |
| 4 | 存量规则回填策略 | ✅ 提议者-审核者模型（系统提议默认值，人工复核后发布） |
| 5 | 层级索引和知识图谱 | ✅ 暂不建立；聚焦政策问答高召回、高准确、可溯源需求 |
| 6 | 宽泛问题检索 | ✅ 引入向量搜索 + BM25 作为宽召回层，再经适用性字段精排/过滤 |
| 7 | 进入阶段 1 编码 | ✅ 批准进入 schema 设计与检索层消费编码 |

**下一阶段动作**：按 §12 MVP 阶段 1 开始编码，修改 `policy_rules_schema_v2.py` 新增 6 个适用性字段并建立标量索引。
