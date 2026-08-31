# 评估：是否需要引入 Coding Agent（智能问数 + 费用分解）

> **日期**：2026-08-27
> **状态**：评估结论，待决策
> **背景**：核心需求需要"智能问数"和"费用分解"。假设出发点是 LLM 不擅长计算，考虑通过 coding agent（LLM 生成并执行代码）补齐计算能力。

---

## 结论（一句话）

**费用分解：不需要 coding agent，现有确定性 calculator 已闭环。智能问数：缺口真实存在，但正确解法是扩展已有的语义层（LLM 只做"问数意图 → 受治理指标"的映射，数字永远走固定 SQL + 确定性求值），而不是引入在线代码执行。Coding agent 若要引入，只应定位为离线指标/skill 开发辅助，产出物必须过已有的 AST 校验 + 评测 + 信息科审批管线。**

---

## 一、纠正出发点里的一个前提

"费用分解 + LLM 不擅长计算 → 需要 coding agent 补齐"这个推理对**费用分解不成立**。`skills/settlement_explain_skill/calculator.py` 已经把这条链路闭环：

| 计算项 | 谁算的 | 状态 |
|---|---|---|
| 起付线/统筹自付/大额自付等金额 | SQL Server 预计算字段直取 | 不经 LLM |
| 统筹自付分段分解（金额 × 基准比例 × 人员系数） | `FeeDecompositionCalculator` 纯 Python 确定性计算 | 不经 LLM |
| 退休 60% 系数 | 硬编码 `0.6` | 不经 LLM |
| **计算值 vs 库内权威值对账**（容差 0.01） | reconciliation 块，`abs(diff) < 0.01` | 自带审计 |
| 丙类/自费分类 | `OutOfScopeCalculator` | 不经 LLM |

费用分解的数字链路是 **DB 预计算 → Python 确定性分解 → 对账验证**，LLM 只做文字合成。这正是行业最佳实践（Provenant 医疗账单审计 Agent 的核心原则："LLM may not do arithmetic"）。**在费用分解上引入 coding agent 是退化，不是补齐。**

---

## 二、真正的缺口在"智能问数"

全代码库**没有 NL2SQL 能力**：

- `SqlServerBusinessDataClient` 只执行 `business_sql.yaml` 里的固定 SQL（按 settlement_id 参数化），不支持任意查询
- `DataAccessPort` 只有 `get_patient()` / `get_insurance_transaction()` 两个固定方法
- `src/semantic_layer/` 是**指标目录（Metric Catalog）**：metric code → 固定 SQL 映射，不是自然语言查询引擎；`/semantic-layer` 页面是治理工作台，不是问数界面

"上个月 DRG 超支科室排名""某患者全年丙类费用合计"这类**自由聚合问数**目前答不了。这是真缺口。

---

## 三、三条路线对比（附行业实测数据）

| 路线 | 生产准确率 | 可审计性 | 安全风险 | 与现有架构契合度 |
|---|---|---|---|---|
| **开放式 Coding Agent**（LLM 写代码 + 沙箱执行） | 结果受模型、提示词和执行环境影响，不能直接承诺生产准确率 | 弱（代码是 LLM 临时产物） | 高——smolagents 官方说明本地执行无法做到完全安全，稳健隔离需 Docker/E2B 等远程沙箱 | 差：模型网关无 tool-call 协议，需大改 |
| **自由 Text-to-SQL** | Spider 2.0 中 GPT-4o 仅 **10.1%**；Omni 汇总的 LiveSQLBench-Large 约 **30-36%**，Spider 2.0-Lite 最优 **69.65%** | 无 | 高（SQL 注入面 + 错误表/错误指标静默出错） | 差 |
| **语义层 + 确定性工具**（已有地基） | dbt Labs 2026 自建基准 **98.2-100%**；超范围问题**报错而不是给错数** | 强（同一指标 → 同一 SQL） | 低（攻击面收敛到受治理指标集） | **高：semantic_layer registry + formula_evaluator + skill 治理已就位** |

关键差异：**Text-to-SQL 会"自信地给出错误数字"，语义层会"告诉你答不了"**。医保场景下后者是硬性要求（与 AGENTS.md "来源可追溯 / 禁止无来源确定性结论"原则一致）。

---

## 四、可复用的现有地基

1. **`src/semantic_layer/`** — registry（指标/维度/值域 CRUD + 版本快照）+ `formula_evaluator.py`（**AST 白名单求值器，明文禁止 eval/exec**）+ `MetricDataQueryService`。缺的只是"NL → 指标+维度"的映射层和指标覆盖率
2. **Skill 插件机制** — `skill_manifest.yaml` + `assembler.py` + `SkillLoader` 自动发现；`BusinessAction.query` × `BusinessObject.settlement` 挂载位已在枚举中。新增"问数 skill"不改产品代码
3. **治理管线** — draft → AST 安全校验（`draft_validator` 禁 eval/exec/subprocess）→ 路由评测 100% 通过 → 信息科审批 → 物化。任何新增计算能力都必须过这条管线，天然防"AI 乱写代码上线"
4. **Docker 沙箱** — `candidate_execution_docker.py` 已有完整实现（`--network none --read-only --cap-drop ALL --memory 128m`），但它是**离线评测用**，不是在线执行路径
5. **模型网关现状** — `OpenAICompatibleProvider._build_payload()` 只有 `{model, messages, temperature, max_tokens, stream}`，**无 tools/functions 字段**。在线 coding agent 需非平凡扩展

---

## 五、推荐架构（混合方案）

```
用户问题
   │
   ▼
意图分类（LLM，temperature=0，仅分类）
   ├─ 费用分解/结算解释 → 现有 settlement_explain_skill（已闭环，不动）
   ├─ 指标类问数（排名/汇总/趋势）
   │     → 新 data_query_skill：LLM 只做 NL → {指标code, 维度, 筛选} 的结构化映射
   │     → 语义层查指标目录 → 固定 SQL 执行 → formula_evaluator 计算
   │     → 指标目录覆盖不了 → 明确回答"暂不支持"，不猜数
   └─ 真正开放的探索性问题 → 转人工/声明不支持
```

**Coding agent 的定位（若引入）：**

- 不是在线问答链路的一环（OWASP LLM06 Excessive Agency + Rule of Two：不可信输入 + 敏感数据 + 状态变更三者俱全时必须人工审批）
- 可以是**离线指标开发辅助**：帮信息科在语义层治理工作台起草新指标的 SQL/公式，产出物走 draft → AST 校验 → 评测 → 审批的既有管线。这是 skill_management 治理管线已支持的模式，增量成本最小

---

## 六、落地增量估算

| 工作项 | 说明 | 量级 |
|---|---|---|
| NL → 指标映射器 | LLM 结构化输出（指标 code + 维度 + 时间窗），Pydantic 校验，白名单拒绝目录外指标 | 中 |
| 指标目录补覆盖 | 按业务优先级补 DRG 超支、科室排名、丙类占比等高频指标的固定 SQL | 持续治理工作 |
| `data_query_skill` | manifest + assembler，复用 semantic_layer + formula_evaluator | 小 |
| `VALID_ACTION_OBJECT_PAIRS` 白名单核对 | query × settlement 等组合确认 | 极小 |
| 模型网关 tool-call 扩展 | **仅当坚持在线 coding agent 才需要——不推荐** | 大（可不做） |

---

## 七、参考来源

- 代码摸查：`skills/settlement_explain_skill/calculator.py`、`src/semantic_layer/`（registry/data_query/formula_evaluator）、`src/knowledge_extension/rule_explanation/policy_retrieval/sqlserver_business_data_client.py`、`src/skill_infra/`、`src/runtime/skill_management/`（draft_validator/materializer/governance_service/ai_authoring）、`src/model_service/gateway.py` + `providers/openai_compatible.py`
- [smolagents 安全执行文档](https://huggingface.co/docs/smolagents/en/tutorials/secure_code_execution)（本地执行无法做到完全安全；稳健隔离建议采用 E2B/Docker）
- [dbt Labs 2026：Semantic Layer vs Text-to-SQL 自建基准](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)（98.2-100% vs 84-90%）
- [Spider 2.0 官方基准](https://spider2-sql.github.io/)（GPT-4o 仅完成 10.1% 的企业级工作流任务）
- [Omni.co：Why text-to-SQL fails in production](https://omni.co/blog/why-text-to-sql-fails)（LiveSQLBench-Large 约 30-36%；Spider 2.0-Lite 最优 69.65%）
- [OWASP LLM Top 10 2026：LLM01 Prompt Injection / LLM06 Excessive Agency](https://github.com/GenAI-Security-Project/GenAI-LLM-Top10)
- [Provenant：医疗账单审计 Agent（LLM 不做算术，HMAC 签名计算回执）](https://github.com/BeamusWayne/provenant)
- [arXiv:2604.05150 — Compiled AI：医疗行政工作流要求确定性/可审计，编译期生成 + 运行期确定性执行](https://arxiv.org/html/2604.05150v1)

---

## 后续可选项

- 产出 `data_query_skill` 详细设计：NL → 指标映射契约、指标目录覆盖清单、与现有 skill 治理管线的对接点

---

## 附录 A：智能问数是否做成 Skill —— 判断标准与设计（2026-08-27 补充）

### A.1 "该不该做成 Skill"的 5 条检验标准

从 `skills/AGENTS.md` 设计原则与 `src/domain/common/actions.py` 约定提炼，**全满足才做成 Skill**：

| # | 检验问题 | 含义 |
|---|---|---|
| 1 | 它是面向用户的业务能力，能被自然语言路由命中吗？ | Skill 是 `/policy-qa` 对话入口下 SkillRouter 的分发单位。内部机制（数据访问、模型调用、公式求值）不是 Skill |
| 2 | 它含有产品层不该写死的业务逻辑吗？ | 比例、政策查询计划、指标白名单、展示配置——必须声明式配置化，这是 Skill 存在的核心理由 |
| 3 | 它能映射到 BusinessAction × BusinessObject 白名单组合吗？ | 每个 Skill 必须唯一归属于一个 Primary Action；组合必须在 `VALID_ACTION_OBJECT_PAIRS` 里 |
| 4 | 它需要独立的治理生命周期吗？ | 版本化、路由评测 100% 通过、信息科审批、可禁用/归档——业务能力需要，平台机制不需要 |
| 5 | 它自包含吗？ | input schema → execute() → output schema + trace_events；不写 UI、不直接调 HTTP、外部访问走 MCP |

**反面清单**（不是 Skill，应放 src/ 平台层）：被多个 Skill 共用的引擎、数据访问客户端、模型网关、公式求值器、MCP 注册中心。判据一句话：**Skill 之间互相独立不依赖；凡是会被"共用"的东西就下沉到平台层。**

### A.2 检验结论：智能问数应该做成 Skill

| 检验 | 结果 |
|---|---|
| 1. 自然语言路由的业务能力？ | 是（"上个月 DRG 超支科室排名"需被路由命中） |
| 2. 有不该写死的业务逻辑？ | 是（可用指标/维度白名单、问法同义词、展示分组、答案模板） |
| 3. Action × Object 组合？ | `analyze × settlement`、`analyze × drg_dip`、`query × settlement` **都已在白名单**，无需改枚举 |
| 4. 需要治理生命周期？ | 是（指标口径变更要评测 + 审批） |
| 5. 自包含？ | 是（问题+上下文 → 结构化数据+解读+引用） |

### A.3 关键设计决策：引擎下沉，Skill 只做壳

智能问数与费用解释的结构性差异：费用解释是**固定 13 步流程**，而"NL → 指标映射 → SQL 生成 → 执行 → 渲染"是**通用引擎**，未来 benefit、drg_dip 等对象的问数都会复用。若把引擎塞进 skill 目录，会违反"skill 互相独立"约束。正确拆法：

```
src/semantic_layer/                      ← 平台层（引擎）
├── nl_metric_mapper.py     (新) NL → {metric_code, dimensions, filters, time_window}
│                                 LLM 结构化输出 + Pydantic 校验 + 目录白名单拒绝
├── data_query.py           (已有) MetricDataQueryService，扩：按指标定 SQL 执行
├── formula_evaluator.py    (已有) AST 白名单求值，直接使用
└── registry.py             (已有) 指标目录，作为映射的唯一合法来源

skills/settlement_analyze_skill/         ← Skill 壳（声明式，薄）
├── skill_manifest.yaml     business_action: analyze / business_object: settlement
│                           supported_intents: 排名/超支/合计/趋势/占比/对比/多少...
│                           needed_objects: 声明可用指标范围（复用现有机制）
├── schemas/                input/output/trace_event 契约
├── templates/              数据解读文案模板（结论 + 引用，不写死数字）
├── scripts/                输出校验（禁无来源数字、禁模板泄漏，仿 validate_skill_result.py）
└── tests/                  验收用例（每个高频问法一个 case）
```

调用链：`/policy-qa/stream` → SkillRouter 命中 → `SettlementAnalyzeSkill.execute()` → 平台层 `nl_metric_mapper` + `MetricDataQueryService` → 模板合成答案。复刻现有分工：`settlement_data_provider`/`structured_policy_retriever` 在 `src/runtime/policy_qa/`（平台层），settlement_explain_skill 只带策略配置和模板。

### A.4 Skill 设计要点

1. **Action 选 `analyze` 不选 `query`**：`query` 是"是什么"（查单条已有数据），`analyze` 是"有什么规律"（统计分析，面向医保办/管理者）。单值查询类问题可作为 `query × settlement` 的独立 profile，在同一 skill 的 `execution_contract.profiles` 里拆开（仿 settlement_explain_skill 按费用项拆 6 个 profile）
2. **可回答性必须显式**：映射到的指标不在 `needed_objects` 声明范围内 → 走 `cannot_answer` 返回"暂不支持该指标"，**禁止猜数**。对齐 AGENTS.md"无来源不得出确定性结论"，也是语义层路线相对 text-to-SQL 的核心优势
3. **每个数字带引用**：输出 schema 里每个数值字段携带 `{metric_code, sql_ref, data_source, time_window}`，前端可溯源，复用现有 `citations` 约定
4. **路由关键词只放"用户会说出口的词"**：排名、超支、占比、趋势、合计、对比、平均……内部字段名交给 LLM 语义路由兜底，遵守 manifest ~25 词精简原则
5. **走完整治理管线**：draft → `SkillDraftValidator`（AST 安全 + business_mounting 校验）→ 路由评测 100% → 信息科审批 → 物化。开发期直接建目录可被 SkillLoader 自动发现跑通，但上线前应补 governance 评测用例
