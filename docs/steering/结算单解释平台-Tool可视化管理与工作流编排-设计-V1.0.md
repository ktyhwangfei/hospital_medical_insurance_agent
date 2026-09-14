# 结算单解释平台 —— Tool 可视化管理与工作流编排 设计 V1.0

> **版本**：V1.0 ｜ **日期**：2026-09-11 ｜ **状态**：设计评审稿（不涉及代码改动）
> **定位**：本文档是《结算单解释平台-功能补全详细设计-V1.0.md》之外的**独立技术路线**，由需求方明确指定架构方向，不采纳该文档"先验证再抽象"的建议，也不采纳 Issue #68 自身的裁决结论（"不建通用编排平台"）——仅取用 Issue #68 中记录的**四个真实用户问题**作为本次设计的目标验收场景。
> **关联**：Issue #68（问题原文来源，架构结论不采纳）、Issue #37（可信问题库，作为意图/追问机制的既有基础设施，非本设计的编排主体）、`docs/steering/结算单解释平台架构设计方案-V1.0.md`（Issue #69，Tool/Skill 边界定义仍适用）、`docs/steering/结算单解释平台-功能补全详细设计-V1.0.md`（G1-G9 缺口分析，本文档与其并行，非替代）

---

## 1. 需求方确认的技术路线

> "先做 Tool 的可视化管理，将数据、知识提炼成可复用的能力；然后通过 Tool 组成工作流；Agent 基于意图识别直接调用这个工作流。"

三层结构：

```
用户问题
   │
   ▼
Agent（意图识别 → 选择 Workflow → 驱动执行 → 组装证据与回答）
   │
   ▼
Workflow（Tool 的声明式编排：顺序 / 条件分支 / 少量动态判断点）
   │
   ▼
Tool（数据、知识、计算能力的可视化注册与治理单元）
   │
   ▼
既有能力实现（settlement_data_provider / structured_policy_retriever / adapters/ports / …）
```

**必须明确的一点**：Tool 层**不重新实现**能力，只是给现有能力（以及少量新增能力）加一层可注册、可版本化、可视化管理、可被 Workflow 引用的元数据外壳。真正的查询/计算逻辑仍然是现有 `runtime/policy_qa/`、`adapters/ports/` 里的确定性代码。这是与"新建平台层"划清界限的关键——**不重写，只包装+治理**。

---

## 2. 四个目标场景（来自 Issue #68，仅取问题原文）

| # | 问题 | 本质 | 需要的能力 |
|---|------|------|-----------|
| 1 | 同一患者、同药品，三次结算报销比例不同（7581.2/1774.68、7581.2/1091.56、7500/1087.5） | 跨结算单同类费用对比核验 | 多结算单查询、费用明细比对、政策时段匹配、乙类先行自付判断、年度累计起付查询 |
| 2 | 退一支胃镜麻药（达克罗宁）未退款反多扣 5 元 | 退费流水核验 | 原结算单查询、退费记录查询、退费重算规则、缺失证据识别与追问 |
| 3 | 急诊两天，特病(血友病)+低保二次报销，个人支付显著偏高 | 多重待遇叠加归因 | 结算查询、特病待遇状态查询、低保/救助报销记录查询、逐层分摊重算 |
| 4 | 无痛肠胃镜退费三问：起付线是否退、是否另有缴费、两张单据用哪张 | 退费结算架构核验 | 结算查询、退费记录查询、起付线记账规则、多票据效力判定 |

四个场景共享的 Tool 需求（去重后）：

```
T1 获取结算事实（已有：settlement_data_provider.get_settlement_context）
T2 获取费用明细（需新增：当前 SettlementContext 是否已含费用明细级数据需核实，若无需新增查询能力）
T3 获取退费记录（需新增：目前无 Tool，需先确认数据源——见 §7 待确认事项）
T4 获取待遇状态（特病/低保/救助）（需新增：目前无对应 adapter，需先确认数据源）
T5 政策检索（已有：structured_policy_retriever.retrieve）
T6 年度累计起付计算（需新增或确认是否已存在于 settlement_explain_skill 内部）
T7 退费重算规则（需新增，需先有权威退费规则来源）
T8 待遇叠加分摊重算（需新增，需先有权威叠加顺序规则来源）
T9 证据构建/引用组装（已有：policy_qa 现有 citations/uncertainties 机制，可直接复用不做 Tool 化）
```

> **关键风险**：T3/T4/T7/T8 目前在代码库中**没有对应的确定性实现**，也没有已接入的外部数据源（低保/救助系统、退费流水系统均未见于 `adapters/`）。Tool 可视化管理能治理"已有能力"，但不能替代"缺数据源"这一根本缺口。§7 会给出如何在缺数据源时仍推进 Tool/Workflow 骨架而不编造结论的做法。

---

## 3. Tool 层设计

### 3.1 Tool 的定义

一个 Tool 是"一个已被注册、有元数据、有版本、可被 Workflow 引用的原子能力"。对齐 `src/domain/AGENTS.md` 的 DDD 分类和 Skill 领域已有的 draft/version/release 三态模式：

```python
class ToolContractKind(StrEnum):
    PYTHON_CALLABLE = "python_callable"   # 直接包装现有函数/方法
    ADAPTER_PORT = "adapter_port"          # 包装 adapters/ports/ 的 Protocol 方法
    MCP_CAPABILITY = "mcp_capability"      # 包装已注册的 MCP 能力（如需要）

class ToolRiskLevel(StrEnum):
    READ_ONLY = "read_only"        # 纯查询，无副作用
    COMPUTE = "compute"             # 纯计算，无外部调用
    HIGH_RISK = "high_risk"         # 涉及退费/冲正等，必须走 waiting_human_confirmation

class ToolDefinition(BaseModel):
    tool_id: str                    # 如 tool_get_settlement_fact
    name: str                       # 中文名，如"获取结算事实"
    business_object: BusinessObject # 复用现有 domain/common/actions.py 枚举
    business_action: BusinessAction
    contract_kind: ToolContractKind
    target_ref: str                 # 指向被包装的函数/Protocol路径，如
                                     # "src.runtime.policy_qa.settlement_data_provider:SemanticSettlementDataProvider.get_settlement_context"
    input_schema: dict               # JSON Schema，供 Workflow 校验调用参数
    output_schema: dict
    risk_level: ToolRiskLevel
    owner: str
    status: Literal["draft", "validated", "materialized", "disabled", "archived"]

class ToolVersion(BaseModel):        # 不可变，同 SkillVersion 模式
    version_id: str
    tool_id: str
    semantic_version: str
    artifact_hash: str               # 对 target_ref 指向源文件做哈希，检测底层实现漂移
    created_by: str
    created_at: str
```

**不新建的东西**：不做通用"任意函数注册为 Tool"的开放式注册表，不做 Tool 市场、不接第三方 Tool。`target_ref` 只能指向项目内白名单目录（`runtime/policy_qa/`、`adapters/ports/`、`skill_infra/` 内已审查过的函数），机制与 `docs/governance/SKILL-ISOLATION-DESIGN.md` 的 import 白名单原则一致。

### 3.2 Tool 治理生命周期

复用 Skill 已验证的模式（`domain/skill/draft_models.py` / `version_models.py` / `governance_models.py`）：

```
ToolDraft（编辑中，可改 input/output schema、target_ref、risk_level）
   ↓ 校验（target_ref 是否存在、schema 是否合法、risk_level 是否与 target_ref 实际副作用一致）
ToolVersion（物化，artifact_hash 锁定）
   ↓ 人工审批（尤其 risk_level=HIGH_RISK 的 Tool，如涉及 BillingPort.preview_partial_refund）
ToolRelease（active，可被 Workflow 引用）
```

### 3.3 Tool 可视化管理（Portal）

新增 `/tools` 页面，复用 `src/runtime/skill_management/workbench_service.py` 的聚合读模型模式：

```python
class ToolWorkbenchItem(BaseModel):
    tool_id: str
    name: str
    business_object: str
    contract_kind: str
    risk_level: str
    status: str
    current_version: str | None
    used_by_workflows: list[str]     # 反查引用关系
    last_validated_at: str | None
```

页面能力：Tool 列表（按 business_object 分组）、Tool 详情（schema、target_ref、被哪些 Workflow 引用）、草稿编辑与校验、发布审批。**不做**可视化拖拽式"从数据库表直接生成 Tool"的自动化生成器——第一阶段 Tool 由人工登记（工程师把已有函数包一层元数据），不做代码生成。

---

## 4. Workflow 层设计

### 4.1 Workflow 的定义

Workflow = 一组 Tool 调用的声明式编排 + 少量显式标注的动态判断点。表达形式借用 Issue #68 记录里 `query_plan` / `dynamic_decisions` 的结构（仅借用这个数据结构本身，不采纳其"不建平台"的结论）：

```yaml
workflow_id: wf_settlement_reimbursement_diff
name: 跨结算同药报销比例差异核验
business_object: settlement
steps:
  - step_id: fetch_settlements
    tool: tool_get_settlement_fact
    input: { settlement_ids: "${input.settlement_ids}" }
  - step_id: fetch_fee_details
    tool: tool_get_fee_detail
    input: { settlement_ids: "${input.settlement_ids}" }
    depends_on: [fetch_settlements]
  - step_id: align_same_drug
    tool: tool_align_fee_items_by_drug_code
    depends_on: [fetch_fee_details]
  - step_id: check_annual_deductible
    tool: tool_get_annual_deductible_accumulation
    depends_on: [align_same_drug]
  - step_id: retrieve_policy_by_period
    tool: tool_retrieve_policy_evidence
    input: { effective_periods: "${align_same_drug.output.periods}" }
    depends_on: [check_annual_deductible]
dynamic_decisions:
  - decision_id: attribution_order
    description: 差异归因排查顺序（药编码→数量→年度累计→政策时段→乙类先行自付）
    resolution: llm_classify_once     # 仅做一次分类，不做自由规划
    fallback_order: [drug_code, quantity, annual_deductible, policy_period, class_b_copay]
missing_evidence_rules:
  - condition: "settlement_ids.length < 2"
    action: clarify
    message: 需要至少两笔结算单号才能对比差异
```

### 4.2 三条目标 Workflow

| Workflow | 覆盖问题 | 编排复杂度 |
|---|---|---|
| `wf_settlement_reimbursement_diff` | 问题1 | 顺序编排 + 1 处动态分类（归因顺序） |
| `wf_refund_verification` | 问题2、问题4 | 顺序编排 + 静态缺失证据清单（无需 LLM 判断） |
| `wf_benefit_stacking_attribution` | 问题3 | 顺序编排（法定顺序：基本医保→特病→低保/救助）+ 0 动态点 |

**不做**：不做通用 Graph 可视化编辑器（拖拽建流程图）、不做条件分支的图灵完备表达式语言、不支持 Workflow 间嵌套调用其他 Workflow（第一阶段每条 Workflow 独立、扁平）。

### 4.3 Workflow 执行引擎

不引入 LangGraph 之外的新执行框架，也不新建独立 `src/workflow_runtime/` 大型模块。执行器是一个薄解释器：

```python
class WorkflowExecutor:
    def execute(self, workflow: WorkflowDefinition, input: dict) -> WorkflowExecutionResult:
        # 1. 校验 missing_evidence_rules，命中则返回 clarify，不继续执行
        # 2. 按 steps 的 depends_on 拓扑顺序逐步调用 ToolRegistry.invoke(tool_id, input)
        # 3. dynamic_decisions 命中时，调用 ModelGateway 做一次分类（scene=workflow_decision），
        #    失败则降级用 fallback_order（同 skill_router 的 LLM 失败降级模式）
        # 4. 汇总每步 Tool 输出为 evidence chain，附 citations/uncertainties
```

Workflow 同样走 draft/version/release 三态治理，与 Tool 一致。

---

## 5. Agent 层设计

### 5.1 与现有 SkillRouter 的关系

现有 `skill_infra/unified_router.py` 做的是"文本 → skill_id"的单一选择。新增 `WorkflowRouter` 做"文本 + 结算上下文 → workflow_id + 缺失参数"，两者不是替代关系，是**新增的并行分支**：

```
POST /policy-qa/stream
   │
   ▼
意图判定：是否命中"对比/退费核验/待遇叠加"三类 Workflow 意图？
   ├─ 是 → WorkflowRouter → WorkflowExecutor → 生成 PolicyQAPublicResult
   └─ 否 → 现状不变：SkillRouter → settlement_explain_skill → PolicyQAPublicResult
```

**不改变唯一入口原则**：`/policy-qa/stream` 仍是唯一业务入口，`PolicyQARequest`/`PolicyQAPublicResult` 契约不变，Workflow 只是这一入口内部新增的一条执行路径，不新开 API。

### 5.2 意图识别范围

Agent 只做"一次分类 + 缺失参数提取"，不做自由规划：

```python
class WorkflowIntent(BaseModel):
    matched_workflow_id: str | None   # None = 走现有 Skill 链路
    extracted_params: dict             # 如 settlement_ids、fee_item_name
    missing_params: list[str]          # 若有缺失，交给 workflow 的 missing_evidence_rules 或 #37 澄清机制
```

若 `missing_params` 非空，复用 Issue #37 已完成的"澄清降级"机制（`可信问题库` 的确定性匹配+澄清降级+审核流），不重新发明追问逻辑。

---

## 6. 证据与审计

Workflow 每步 Tool 调用记录进入现有 `PolicyQAPublicResult.verification_summary` 同源的证据链结构，不新建独立审计体系：

```python
class ToolInvocationTrace(BaseModel):
    tool_id: str
    tool_version: str
    step_id: str
    input_digest: str        # 脱敏后的输入摘要，不落原始 PII
    output_summary: str
    duration_ms: int
```

高风险 Tool（`risk_level=HIGH_RISK`，如涉及 `BillingPort.preview_partial_refund`）调用前必须过 `security/risk_control/`，命中即转 `waiting_human_confirmation`，与现有硬约束一致，不因为"包装成 Tool"而绕过。

---

## 7. 待确认事项（阻塞 T3/T4/T7/T8 的关键缺口）

| 缺口 | 影响场景 | 需要什么 |
|---|---|---|
| 退费流水数据源 | 问题2、4 | `adapters/ports/billing.py` 目前只有 `preview_partial_refund`（预退费，未结算），没有"已发生退费记录查询"。需明确：退费记录是否已存在于结算库（SQL Server）某张表，还是需要新的外部接口 |
| 低保/救助报销记录数据源 | 问题3 | 未见任何 adapter。需明确：低保/大病/救助是否走医保系统内某张表，还是外部民政系统，是否有既有接口文档 |
| 退费重算规则权威来源 | 问题2、4 | 是否有政策/业务规则文档定义"退费如何影响统筹/自付分摊"，还是需要向医保业务专家取证 |
| 待遇叠加顺序权威来源 | 问题3 | Issue #68 记录称"逐层分摊重算顺序法定"，需确认具体法规/内部规则文档出处，不能由 LLM 自行推断叠加公式 |

**建议处理方式**：Tool/Workflow 骨架可以先按"缺失数据源"的形态搭建——即 T3/T4/T7/T8 先注册为 `status=draft` 的 Tool，`target_ref` 指向尚未实现的占位 Protocol（类似 `adapters/ports/data_supply.py` 未注册数据源时 `connect()` raise `RuntimeError` 的模式），Workflow 执行到这些步骤时返回 `answer_status=unavailable` + 明确 `uncertainties`，而不是编造结果。这与项目"来源可追溯、证据不足必须声明不确定性"的硬约束一致。

---

## 8. 落地路径（分阶段，先骨架后接入，不要求一次性交付）

| 阶段 | 内容 | 产出 | 依赖 |
|---|---|---|---|
| S0 | `ToolDefinition`/`ToolVersion` 领域模型 + 内存/PG 双存储（复用 Skill 存储双实现工厂模式） | `src/domain/tool/`（补齐当前空目录）+ `src/data_platform/storage/tool/`（补齐） | — |
| S1 | 把已有能力包装为初版 Tool：`tool_get_settlement_fact`（包装 `get_settlement_context`）、`tool_retrieve_policy_evidence`（包装 `structured_policy_retriever.retrieve`）、`tool_preview_partial_refund`（包装 `BillingPort.preview_partial_refund`） | 3-5 个 `status=materialized` 的 Tool | S0 |
| S2 | Tool 可视化管理页面 `Portal /tools`（列表+详情+草稿编辑），复用 workbench 聚合读模型模式 | Portal 新页面 | S0/S1 |
| S3 | `WorkflowDefinition` 领域模型 + `WorkflowExecutor` 薄解释器 | `src/runtime/workflow/` | S1 |
| S4 | 落地 `wf_refund_verification`（问题2/4，无需外部新数据源，可先用现有 `preview_partial_refund` + 静态缺失证据清单跑通骨架，即使暂缺"已发生退费记录"能力也能先验证追问机制） | 首条可跑通的 Workflow | S2/S3 |
| S5 | `WorkflowRouter` + `/policy-qa/stream` 内新增分支接入 | 意图识别到 Workflow 的路由 | S4 |
| S6 | 待 §7 数据源缺口解决后，落地 `wf_settlement_reimbursement_diff`（问题1）与 `wf_benefit_stacking_attribution`（问题3） | 剩余两条 Workflow | §7 解锁 |

建议先做 S0-S5（用问题2/4 打通端到端骨架，因为它复用现有 `BillingPort` 且缺口最小），再视 §7 缺口解决进度决定问题1/3 何时跟进。

---

## 9. 明确不做的事项（避免平台层泛化膨胀）

- 不做通用 Graph 可视化编辑器/拖拽式流程设计器
- 不做 Tool 市场、第三方 Tool 接入、自动代码生成注册 Tool
- 不做脱离 `/policy-qa/stream` 的新业务 API 入口
- 不允许 Workflow 内出现自由式 LLM 规划（每个 dynamic_decision 必须是"一次分类 + 明确 fallback"，不是开放式推理循环）
- 不在数据源缺失情况下编造 T3/T4/T7/T8 的计算结果——缺口未解决前，对应 Workflow 步骤必须返回 `unavailable` + `uncertainties`

---

## 10. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-11 | 初始版本：按需求方指定的 Tool 可视化管理 + 工作流编排 + Agent 意图驱动路线，设计四个目标场景（源自 Issue #68 问题原文）的落地方案 |
