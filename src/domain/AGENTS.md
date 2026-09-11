# domain/ — 纯领域模型

## 概述

业务实体定义，无基础设施耦合。两类模型：业务实体（frozen dataclass）+ Agent 定义（Pydantic BaseModel）。

## 结构

```
domain/
├── patient/        # Patient（patient_id, name）
├── insurance/      # InsuranceTransaction（settlement_status, error_code）
├── task/           # ClosureTask（task_type, status）
├── appeal/         # DenialRecord, AppealCase, Evidence
├── audit_risk/     # AuditResult, RiskFlag, ComplianceScore
├── drg_dip/        # DrgGroupResult, DipGroupResult, PaymentRate
├── medical_record/ # MedicalRecordHomepage, Diagnosis, Surgery
├── order_fee/      # Order, FeeItem, Drug, Consumable
├── common/         # Citation, Role 枚举
├── skill/          # Skill, SkillStep, SkillMetadata（Pydantic）
└── tool/           # Tool, ToolOwner, ToolType（Pydantic）
```

## 关键约定

- 业务实体使用 `@dataclass(frozen=True)`，不可变
- Agent 定义使用 Pydantic `BaseModel`，带验证
- `patient_id` + `encounter_id` 是跨域通用复合键
- `Role` 枚举在 `common/roles.py`：CASHIER, MEDICAL_OFFICE, INFORMATION_DEPARTMENT, MEDICAL_RECORD_STAFF, CLINICIAN
- `ToolOwner` 在 `tool/models.py`，与 `Role` 部分重复（缺少 CLINICIAN）

## 注意事项

- `Citation` 在 `domain/common/models.py` 和 `knowledge_extension/common/models.py` 各有一份，可能重复
- `McpRiskLevel` 从 `knowledge_extension.mcp_registry.models` 导入，是唯一的外部依赖
- `domain/tool/` 目录完全为空（无 `__init__.py`、无任何文件）— 不要 import `src.domain.tool`，会报 `ModuleNotFoundError`
- `domain/tool/` 是完全空目录（无 `__init__.py`、无代码）— 不要尝试 import，会报错

---

## 全局领域知识库 — 医院医保智能体系统

> **文档版本**: 1.1
> **更新日期**: 2026-08-14
> **维护说明**: 本文件为项目的 **通用语言（Ubiquitous Language）** 权威定义。所有代码中的类名、变量名、方法名必须严格遵循此字典。新增领域概念时，必须同步更新此文件。

---

### 目录

1. [限界上下文总览](#1-限界上下文总览)
1.5. [Business Action 业务动作层](#15-business-action-业务动作层)
2. [患者上下文（Patient）](#2-患者上下文-patient)
3. [医保上下文（Insurance）](#3-医保上下文-insurance)
4. [医嘱费用上下文（Order & Fee）](#4-医嘱费用上下文-order--fee)
5. [审核风险上下文（Audit & Risk）](#5-审核风险上下文-audit--risk)
6. [DRG/DIP 上下文](#6-drgdip-上下文)
7. [病案上下文（Medical Record）](#7-病案上下文-medical-record)
8. [申诉上下文（Appeal）](#8-申诉上下文-appeal)
9. [任务闭环上下文（Task & Closure）](#9-任务闭环上下文-task--closure)
10. [技能工具上下文（Skill & Tool）](#10-技能工具上下文-skill--tool)
11. [知识上下文（Knowledge）](#11-知识上下文-knowledge)
12. [安全上下文（Security）](#12-安全上下文-security)
13. [模型服务上下文（Model Service）](#13-模型服务上下文-model-service)
13.5. [Runtime 上下文（Runtime）](#135-runtime-上下文runtime)
13.6. [问答会话生命周期与轨迹（Policy QA）](#136-问答会话生命周期与轨迹policy-qa)
14. [共享通用层（Shared / Common）](#14-共享通用层-shared--common)
14.5. [门诊数据治理控制面（Outpatient Data Governance）](#145-门诊数据治理控制面outpatient-data-governance)
14.6. [治理数据流上下文（Governed Data Flow）](#146-治理数据流上下文governed-data-flow)
14.7. [健康运营上下文（Ops Health）](#147-健康运营上下文ops-health)
14.8. [数据目录上下文（Data Catalog）](#148-数据目录上下文data-catalog)
14.9. [语义指标政策承载（Metric Policy Carrier）](#149-语义指标政策承载metric-policy-carrier)
14.10. [数据供给分档（Data Supply）](#1410-数据供给分档data-supply)
14.11. [可信问题库（Trusted Question Library）](#1411-可信问题库trusted-question-library)
14.12. [门诊运营分析（Ops Analytics）](#1412-门诊运营分析ops-analytics)
15. [AI 编程工作流契约](#15-ai-编程工作流契约)

---

### 1. 限界上下文总览

本系统基于 **四层架构**（SaaS → PaaS → DaaS → 系统接入），从业务视角识别为 **12 个核心限界上下文**。每个上下文有独立的通用语言、业务规则和演化边界。

```
┌──────────────────────────────────────────────────────────────┐
│                    SaaS 应用产品层                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                    │
│  │  Portal   │  │  Admin   │  │  Embed   │                    │
│  │ (业务门户)│  │ (管理后台)│  │ (嵌入式) │                    │
│  └──────────┘  └──────────┘  └──────────┘                    │
├──────────────────────────────────────────────────────────────┤
│                    PaaS 平台支撑层                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │  Security│  │  Runtime │  │  Model   │  │  Knowledge│    │
│  │ (安全)   │  │ (运行时) │  │ (模型)   │  │ (知识)   │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│  ┌──────────┐  ┌──────────┐                                   │
│  │ Adapters │  │ Skill &  │                                   │
│  │ (适配器) │  │ Tool     │                                   │
│  └──────────┘  └──────────┘                                   │
├──────────────────────────────────────────────────────────────┤
│              DaaS 数据与知识服务层                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                    │
│  │ Data     │  │ Storage  │  │ Cache    │                    │
│  │ Platform │  │ (存储)   │  │ (缓存)   │                    │
│  └──────────┘  └──────────┘  └──────────┘                    │
├──────────────────────────────────────────────────────────────┤
│              领域模型层（跨层共享，纯业务）                    │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐   │
│  │Patient│Insur│Order│Audit│DRG/│Med  │Appeal│Task │         │
│  │      │ance │Fee  │Risk │DIP │Rec  │      │     │         │
│  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘   │
└──────────────────────────────────────────────────────────────┘
```

#### 上下文映射（Context Map）

| 限界上下文 | 核心职责 | 主要依赖 | 防腐层（ACL） |
|-----------|---------|---------|--------------|
| Patient | 患者基本信息、就诊信息 | 无 | HisPort |
| Insurance | 医保交易、结算、费用上传 | Patient | InsuranceInterfacePort |
| OrderFee | 医嘱、费用明细、药品耗材 | Patient | HisPort, BillingPort |
| AuditRisk | 事前审核、规则命中、合规评分 | Patient, OrderFee | PreAuditPort |
| DrgDip | DRG/DIP 分组、支付费率、盈亏 | Patient, MedicalRecord | DrgDipPort |
| MedicalRecord | 病案首页、诊断、手术、编码 | Patient | MedicalRecordPort, EmrPort |
| Appeal | 拒付记录、申诉案件、证据材料 | Insurance, MedicalRecord | — (内部) |
| TaskClosure | 任务闭环、待办、处理记录 | 所有上下文 | — (内部) |
| SkillTool | 技能注册、工具调度、MCP | 无 | — (内部) |
| Knowledge | 错误码知识、RAG、规则解释 | 无 | — (内部) |
| Security | 认证鉴权、脱敏、风控、审计 | 所有上下文 | — (横切) |
| ModelService | LLM/OCR/语音模型调用 | 无 | — (内部) |

#### 核心跨域复合键

- `(patient_id, encounter_id)` — 跨所有业务上下文的通用复合标识键

---

---

### 1.5. Business Action 业务动作层

#### 概述

Business Action 是平台最高层业务分类，位于限界上下文之上。所有 Agent、Skill、Workflow、Prompt、Tool 都必须挂载到统一的 Business Action。新增业务优先新增 Skill，而不是新增 Business Action。

参见：`Business Action Specification V1.0`（项目根目录下的设计规范文档）。

#### 代码位置

`src/domain/common/actions.py`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 业务动作 | `BusinessAction` | **Value Object** | `StrEnum` | 平台最高层业务分类，七类动作之一 |
| 解释 | `EXPLAIN` | Value Object | `StrEnum` | 解释已发生的事实，回答"为什么" |
| 查询 | `QUERY` | Value Object | `StrEnum` | 查询已有数据，回答"是什么" |
| 导办 | `GUIDE` | Value Object | `StrEnum` | 指导办理流程，回答"怎么办" |
| 核验 | `VERIFY` | Value Object | `StrEnum` | 验证已有结果是否正确，回答"对不对" |
| 对比 | `COMPARE` | Value Object | `StrEnum` | 比较两个对象，回答"有什么不同" |
| 评估 | `EVALUATE` | Value Object | `StrEnum` | 评估假设影响，回答"如果这样会怎样" |
| 分析 | `ANALYZE` | Value Object | `StrEnum` | 面向管理的统计分析，回答"有什么规律" |
| 业务对象 | `BusinessObject` | **Value Object** | `StrEnum` | Business Action 操作的对象 |
| 结算对象 | `SETTLEMENT` | Value Object | `StrEnum` | 医保结算数据 |
| 待遇对象 | `BENEFIT` | Value Object | `StrEnum` | 医保待遇数据 |
| 政策对象 | `POLICY` | Value Object | `StrEnum` | 医保政策规则 |
| 目录对象 | `DIRECTORY` | Value Object | `StrEnum` | 医保三大目录 |
| 慢特病对象 | `CHRONIC_DISEASE` | Value Object | `StrEnum` | 慢特病资格与报销 |
| 转诊对象 | `REFERRAL` | Value Object | `StrEnum` | 转诊转院流程 |
| 申诉对象 | `APPEAL` | Value Object | `StrEnum` | 医保拒付申诉 |
| 病案对象 | `MEDICAL_RECORD` | Value Object | `StrEnum` | 病案首页数据 |
| DRG/DIP对象 | `DRG_DIP` | Value Object | `StrEnum` | DRG/DIP 分组数据 |
| 投诉对象 | `COMPLAINT` | Value Object | `StrEnum` | 投诉与咨询数据 |
| 能力矩阵 | `VALID_ACTION_OBJECT_PAIRS` | **Value Object** | `frozenset` | 合法 Action-Object 组合白名单 |

#### 设计原则

1. **Business Action 是平台最高层业务分类，不允许随意扩展。**
2. **Skill 是平台唯一开发单元，所有研发工作围绕 Skill 展开。**
3. **Business Action 决定"做什么"，Business Object 决定"处理谁"，两者共同唯一确定一个 Skill。**
4. **新增业务优先新增 Skill，而不是新增 Business Action。**
5. **Evaluate（评估）与 Explain（解释）严格区分：解释过去发生的事实，评估未来假设的影响。**
6. **LLM 不决定业务分类，只负责辅助识别；Business Action 的定义始终由医保业务驱动，而不是模型能力驱动。**

#### Action × Object 能力矩阵

| Object | Explain | Query | Guide | Verify | Compare | Evaluate | Analyze |
|--------|---------|-------|-------|--------|---------|----------|---------|
| Settlement | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| Benefit | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| Policy | ✅ | ✅ | — | — | ✅ | — | — |
| Directory | ✅ | ✅ | — | ✅ | — | — | — |
| Chronic Disease | — | ✅ | ✅ | ✅ | — | — | — |
| Referral | — | — | ✅ | ✅ | — | — | — |
| Appeal | — | — | ✅ | — | — | — | — |
| Medical Record | — | — | — | ✅ | — | — | — |
| DRG/DIP | — | — | — | — | — | — | ✅ |
| Complaint | — | — | — | — | — | — | ✅ |

#### Skill 分类规范

每个 Skill 必须在 `skill_manifest.yaml` 中声明：

```yaml
business_action: explain       # BusinessAction 枚举值
business_object: settlement    # BusinessObject 枚举值
```

命名约定：`{BusinessObject}{BusinessAction}Skill`，例如 `SettlementExplainSkill`、`BenefitQuerySkill`。

#### 动作路由

```text
用户问题
  → Business Action Recognition（做什么）
  → Business Object Recognition（处理谁）
  → Skill Router（哪个 Skill）
  → Skill Execution
```

#### 与限界上下文的关系

- Business Action 是**行为维度**的分类，限界上下文是**领域维度**的分类
- 同一个 Business Object（如 Settlement）可能跨多个限界上下文（Insurance + OrderFee）
- 同一个 Business Action（如 Explain）可能在不同 Object 上由不同的 Skill 实现
- Business Action 层不替代限界上下文，而是作为顶层的路由维度补充

---

### 2. 患者上下文（Patient）

#### 概述

管理患者基本信息及就诊（住院/门诊）记录。是本系统所有业务场景的起始身份锚点。

#### 文件位置

`src/domain/patient/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 患者 | `Patient` | **Entity** | `@dataclass(frozen=True)` | 患者核心身份，通过 `patient_id` 唯一标识 |
| 患者ID | `patient_id` | Value Object | `str` | 全院唯一患者标识号 |
| 患者姓名 | `name` | Value Object | `str` | 患者姓名 |
| 就诊ID | `encounter_id` | Value Object | `str` | 每次住院/门诊的唯一标识，与 `patient_id` 配合使用 |
| HIS 适配器端口 | `HisPort` | **Domain Service** (接口) | Protocol | 从 HIS 系统查询患者就诊信息的防腐层端口 |

#### 业务规则

- `Patient` 是不可变对象（frozen dataclass），创建后不允许修改
- `patient_id` 是跨所有上下文的身份锚点，所有业务场景均通过它关联患者
- 外部数据通过 `HisPort` 防腐层获取，不直接依赖 HIS 系统实现

#### 生命周期

```
HIS 系统 → HisPort → Patient (查询/读取)
    ↑ 患者入院/挂号时在 HIS 中登记，本系统只读引用
```

---

### 3. 医保上下文（Insurance）

#### 概述

管理外部医保交易的只读信息，包括结算状态、费用上传状态和错误码。当前唯一 Policy QA 业务流只使用结算单上下文，不以错误码启动独立业务场景。

#### 文件位置

`src/domain/insurance/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 医保交易 | `InsuranceTransaction` | **Entity** | `@dataclass(frozen=True)` | 一条医保结算交易的完整记录 |
| 结算状态 | `settlement_status` | Value Object | `str` | 交易结算状态（成功/失败/处理中） |
| 上传状态 | `upload_status` | Value Object | `str` | 费用明细上传到医保的状态 |
| 错误码 | `error_code` | Value Object | `str \| None` | 医保接口返回的错误码，结算异常时的核心诊断入口 |
| 医保接口适配器端口 | `InsuranceInterfacePort` | **Domain Service** (接口) | Protocol | 与医保局端核心结算系统交互的防腐层端口 |
| 收费系统适配器端口 | `BillingPort` | **Domain Service** (接口) | Protocol | 与医院收费系统交互的防腐层端口 |
| 门诊部分项目预退费分析 | `OutpatientPartialPreRefundAnalysis` | **Domain Service** | Skill | 基于院端官方预结算结果，对拟退明细进行只读分析 |
| 拟退项目 | `PartialRefundItemRequest` | **Value Object** | `@dataclass(frozen=True)` | 指定费用明细 ID 与拟退数量的只读预结算输入 |
| 预结算结果 | `PartialRefundPreview` | **Value Object** | `@dataclass(frozen=True)` | 医院收费系统对门诊部分项目预退费的权威只读结果 |

#### 业务规则

- `settlement_status` 与 `error_code` 仅描述外部医保交易结果
- `error_code` 非空不会启动独立业务流程
- 医保交易数据通过 `InsuranceInterfacePort` 获取，不直接调用医保接口

#### 生命周期

```
外部医保系统 → InsuranceInterfacePort → InsuranceTransaction（只读记录）
```

---

### 4. 医嘱费用上下文（Order & Fee）

#### 概述

管理医生的诊疗医嘱及其对应的费用明细，包括药品、耗材和诊疗项目。

#### 文件位置

`src/domain/order_fee/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 医嘱 | `Order` | **Entity** (Aggregate Root) | `@dataclass(frozen=True)` | 医生开具的诊疗指令，聚合费用明细项 |
| 费用明细 | `FeeItem` | **Entity** | `@dataclass(frozen=True)` | 医嘱对应的单项费用，按类别区分 |
| 药品 | `Drug` | **Value Object** | `@dataclass(frozen=True)` | 医保药品目录中的药品记录 |
| 耗材 | `Consumable` | **Value Object** | `@dataclass(frozen=True)` | 医用耗材目录中的耗材记录 |
| 诊疗项目 | `Treatment` | **Value Object** | `@dataclass(frozen=True)` | 医疗服务项目的价格与医保属性 |
| 医嘱类型 | `order_type` | Value Object | `str` | 区分不同种类的医嘱 |
| 医嘱状态 | `status` | Value Object | `str` | 医嘱的执行状态 |
| 费用类别 | `category` | Value Object | `str` | "drug", "consumable", "treatment" 之一 |
| 医保目录标识 | `is_medical_insurance` | Value Object | `bool` | 是否在医保报销目录内 |
| 报销类别 | `reimbursement_category` | Value Object | `str` | 甲类/乙类/丙类 |

#### 业务规则

- `Order` 是聚合根（Aggregate Root），`FeeItem` 在 `Order` 边界内，通过 `items` 字段持有
- 费用类别 `category` 约束了 `FeeItem.code` 所指向的目录类型（药品/耗材/诊疗）
- `reimbursement_category`（甲/乙/丙）决定医保报销比例

#### 生命周期

```
医生开医嘱 → HIS 系统 → HisPort → Order (聚合 FeeItems) → 出院前质控 / 结算异常分析
```

---

### 5. 审核风险上下文（Audit & Risk）

#### 概述

管理医保事前审核结果、规则命中详情和合规性评分。是与东软事前审核系统交互的核心上下文。

#### 文件位置

`src/domain/audit_risk/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 审核结果 | `AuditResult` | **Entity** (Aggregate Root) | `@dataclass(frozen=True)` | 一次完整的事前审核结果，聚合风险标记 |
| 风险标记 | `RiskFlag` | **Entity** | `@dataclass(frozen=True)` | 单条规则触发的具体风险信号 |
| 规则命中 | `RuleHit` | **Value Object** | `@dataclass(frozen=True)` | 被触发的审核规则信息 |
| 合规评分 | `ComplianceScore` | **Value Object** | `@dataclass(frozen=True)` | 多维度合规性量化评分 |
| 风险等级 | `risk_level` | Value Object | `str` | "high" / "medium" / "low" |
| 严重程度 | `severity` | Value Object | `str` | 风险标记的严重程度 |
| 合规总评分 | `overall` (ComplianceScore) | Value Object | `float` | 综合合规性评分（0-100） |
| 编码准确率 | `coding_accuracy` | Value Object | `float` | 诊断/手术编码的准确度评分 |
| 文档完整度 | `documentation_completeness` | Value Object | `float` | 病历文档的完整性评分 |
| 计费准确率 | `billing_accuracy` | Value Object | `float` | 费用计费的准确性评分 |
| 事前审核适配器端口 | `PreAuditPort` | **Domain Service** (接口) | Protocol | 与东软事前审核系统交互的防腐层端口 |

#### 业务规则

- `AuditResult` 是聚合根，通过 `findings` 聚合 `RiskFlag`
- `compliance_score` 由三个子维度（编码/文档/计费）加权计算
- 高风险（`risk_level=high`）时输出需强制携带 `citations` 和 `uncertainties`
- 高风险动作必须在 `security/risk_control/` 中拦截，转为 `waiting_human_confirmation`

#### 生命周期

```
医保结算触发 → PreAuditPort → AuditResult (含 RiskFlags) → 出院前质控 / 风险提示
```

---

### 6. DRG/DIP 上下文

#### 概述

管理疾病诊断相关分组（DRG）和按病种分值付费（DIP）的分组结果、支付费率和盈亏分析。

#### 文件位置

`src/domain/drg_dip/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| DRG 分组结果 | `DrgGroupResult` | **Value Object** | `@dataclass(frozen=True)` | DRG 分组的核心产出，含权重和费用 |
| DIP 分组结果 | `DipGroupResult` | **Value Object** | `@dataclass(frozen=True)` | DIP 分组的核心产出 |
| 支付费率 | `PaymentRate` | **Value Object** | `@dataclass(frozen=True)` | 医保支付相关的费率标准 |
| 盈亏分析 | `ProfitLoss` | **Value Object** | `@dataclass(frozen=True)` | 按病种的成本盈亏计算结果 |
| DRG 编码 | `drg_code` | Value Object | `str` | DRG 分组代码 |
| DRG 权重 | `weight` | Value Object | `float` | DRG 相对权重（RW） |
| 支付费率值 | `payment_rate` / `rate_value` | Value Object | `float` | 医保支付费率 |
| 盈亏金额 | `amount` (ProfitLoss) | Value Object | `float` | 盈利/亏损金额 |
| 盈亏类别 | `category` (ProfitLoss) | Value Object | `str` | "profit" / "loss" / "break_even" |
| DIP 支付标准 | `payment_standard` | Value Object | `float` | 按病种分值付费的标准金额 |
| DRG/DIP 适配器端口 | `DrgDipPort` | **Domain Service** (接口) | Protocol | 与大瑞集思 DRG/DIP 系统交互的防腐层端口 |

#### 业务规则

- 所有模型均为 `frozen=True` 的 Value Object，无唯一标识（由 `patient_id + encounter_id` 隐式关联）
- DRG 和 DIP 是两类不同的分组体系，同一患者可能同时有 DRG 和 DIP 结果
- `ProfitLoss.category` 决定了是盈利、亏损还是持平，在运营驾驶舱中影响预警策略

#### 生命周期

```
出院结算 → DrgDipPort → DrgGroupResult / DipGroupResult → DRG/DIP 运营分析 / 出院前质控
```

---

### 7. 病案上下文（Medical Record）

#### 概述

管理病案首页信息，包括主要诊断、次要诊断、手术记录和编码信息。是出院前质控和病案首页风险导办的核心上下文。

#### 文件位置

`src/domain/medical_record/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 病案首页 | `MedicalRecordHomepage` | **Entity** (Aggregate Root) | `@dataclass(frozen=True)` | 本次住院的完整病案首页，聚合诊断/手术/编码 |
| 诊断记录 | `Diagnosis` | **Entity** | `@dataclass(frozen=True)` | 疾病诊断的编码与名称，区分主诊断和次诊断 |
| 手术记录 | `Surgery` | **Entity** | `@dataclass(frozen=True)` | 手术操作的相关信息 |
| 编码信息 | `Coding` | **Value Object** | `@dataclass(frozen=True)` | 诊断或手术的编码系统记录 |
| 出院状态 | `discharge_status` | Value Object | `str` | 出院方式（治愈/好转/未愈/死亡/转院） |
| 诊断类型 | `type` (Diagnosis) | Value Object | `str` | "primary"（主要诊断）/ "secondary"（次要诊断） |
| 编码系统 | `code_system` | Value Object | `str` | 编码标准（如 ICD-10、ICD-9-CM-3） |
| 病案适配器端口 | `MedicalRecordPort` | **Domain Service** (接口) | Protocol | 与病案管理系统交互的防腐层端口 |
| EMR 适配器端口 | `EmrPort` | **Domain Service** (接口) | Protocol | 与电子病历系统交互的防腐层端口 |

#### 业务规则

- `MedicalRecordHomepage` 是聚合根，`Diagnosis` 和 `Surgery` 在该边界内
- `primary_diagnosis` 只有一个，`secondary_diagnoses` 可以有零到多个
- `Diagnosis.type = "primary"` 是主要诊断，所有次要诊断的 `type = "secondary"`
- 诊断编码通常使用 ICD-10，手术编码使用 ICD-9-CM-3

#### 生命周期

```
医生书写病历 → EMR / 病案系统 → MedicalRecordPort / EmrPort → MedicalRecordHomepage → 质控
```

---

### 8. 申诉上下文（Appeal）

#### 概述

管理医保拒付记录和申诉案件的全流程，包括证据组织、材料生成和申诉进度跟踪。

#### 文件位置

`src/domain/appeal/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 拒付记录 | `DenialRecord` | **Entity** | `@dataclass(frozen=True)` | 医保拒付的原始记录，含拒付原因和金额 |
| 申诉案件 | `AppealCase` | **Entity** (Aggregate Root) | `@dataclass(frozen=True)` | 基于拒付发起的申诉全流程信息，聚合证据和材料 |
| 证据材料 | `Evidence` | **Entity** | `@dataclass(frozen=True)` | 支撑申诉的各类证据项 |
| 申诉附件 | `AppealMaterial` | **Entity** | `@dataclass(frozen=True)` | 申诉时提交的具体材料文件 |
| 拒付金额 | `denial_amount` | Value Object | `float` | 医保拒付的金额 |
| 申诉截止日 | `appeal_deadline` | Value Object | `str` | 提出申诉的最后期限 |
| 申诉状态 | `status` (AppealCase) | Value Object | `str` | "draft" / "submitted" / "under_review" / "approved" / "rejected" |
| 证据类型 | `type` (Evidence) | Value Object | `str` | "clinical"（临床）/ "coding"（编码）/ "policy"（政策） |
| 拒付ID | `denial_id` | Value Object | `str` | 唯一标识一次拒付记录 |
| 申诉ID | `appeal_id` | Value Object | `str` | 唯一标识一个申诉案件 |

#### 业务规则

- `AppealCase` 是聚合根，通过 `evidence` 和 `materials` 聚合证据和附件
- 申诉状态流转：`draft → submitted → under_review → (approved | rejected)`
- 必须在 `appeal_deadline` 前提交申诉，否则丧失申诉机会
- 证据类型 `clinical/policy/coding` 对应不同的证据来源和验证逻辑

#### 生命周期

```
医保拒付 → DenialRecord → AppealCase (draft)
    → 组织证据 (Evidence) → 生成材料 (AppealMaterial)
    → submitted → under_review → approved/rejected
```

---

### 9. 任务闭环上下文（Task & Closure）

#### 概述

管理 AI 导办产出的待办任务、处理记录和闭环追踪。是"分析结果→生成建议→分派任务→跟踪闭环"的关键环节。

#### 文件位置

`src/domain/task/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 闭环任务 | `ClosureTask` | **Entity** | `@dataclass` | 需要人工确认或执行的待办任务（**非 frozen**，状态可变） |
| 任务ID | `task_id` | Value Object | `str` | 唯一标识一个任务 |
| 任务类型 | `task_type` | Value Object | `str` | 区分不同的任务类别（如 rectification） |
| 任务状态 | `status` | Value Object | `str` | "pending" / "completed" / "cancelled" |
| 责任角色 | `responsible_role` | Value Object | `str` | 负责处理此任务的角色 |
| 任务描述 | `description` | Value Object | `str` | 任务的内容和操作指引 |
| 运行时任务 | `RuntimeTask` | **DTO** | Pydantic BaseModel | API 层传输的任务数据结构（含 workflow_id） |
| 任务确认请求 | `TaskConfirmRequest` | **DTO** | Pydantic BaseModel | 人工确认任务的请求结构 |
| 工作流ID | `workflow_id` | Value Object | `str` | 标识一次 AI 编排执行流程 |
| 任务闭环服务 | `TaskClosureService` | **Domain Service** | — | 管理待办生成、人工确认、处理记录、结果追踪 |

#### 业务规则

- `ClosureTask` 是可变的（`@dataclass` 而非 `frozen=True`），因为状态会流转
- `responsible_role` 与 `common/roles.py` 中的 `Role` 枚举对齐
- 高风险动作生成的任务必须等待人工确认（`waiting_human_confirmation`）
- 任务闭环包含：待办生成 → 消息提醒 → 人工确认 → 处理记录 → 结果追踪

#### 生命周期

```
场景分析完成 → ClosureTask (pending) → 消息提醒责任角色
    → 人工确认/处理 → ClosureTask (completed/cancelled)
    → 处理记录归档 → 结果追踪
```

---

### 10. 技能工具上下文（Skill & Tool）

#### 概述

管理 AI 技能（Skill）、工具（Tool）和 MCP 服务器的注册、调度和执行。是平台可扩展性的核心支撑。

#### 文件位置

`src/domain/skill/` + `src/knowledge_extension/mcp_registry/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 技能 | `Skill` | **Entity** (Aggregate Root) | Pydantic `BaseModel` | 可编排的 AI 能力单元，含多步骤和工具调用 |
| 技能步骤 | `SkillStep` | **Entity** | Pydantic `BaseModel` | 技能中的一个执行步骤，绑定特定工具 |
| 技能元数据 | `SkillMetadata` | **Value Object** | Pydantic `BaseModel` | 技能的版本、标签、作者等描述信息 |
| 技能版本 | `SkillVersion` | **Entity** | Pydantic `BaseModel`（frozen） | 由 Git 提交与制品哈希唯一追溯的不可变技能版本 |
| 技能制品快照 | `SkillArtifactSnapshot` | **Value Object** | Pydantic `BaseModel`（frozen） | Skill 目录规范化后的 Manifest、依赖、文件清单与 SHA-256 |
| 技能校验状态 | `SkillValidationStatus` | **Value Object** | `StrEnum` | pending / passed / failed |
| 技能测评集 | `SkillEvalSuite` | **Entity** | Pydantic `BaseModel`（frozen） | 按平台或单个 Skill 组织评测用例的治理资产；不等同于一次评测运行 |
| 技能评测任务 | `SkillEvalTask` | **Entity** | Pydantic `BaseModel`（frozen） | 一次可被多条类型化断言验证的端到端 Skill 任务；通过 revision 在工作区演进 |
| 评测数据定位 | `SkillEvalDataLocator` | **Value Object** | Pydantic `BaseModel`（frozen） | 用业务资源类型和 ID 安全定位评测数据，不包含物理表名或查询语句 |
| 评测环境要求 | `SkillEvalEnvironmentRequirement` | **Value Object** | Pydantic `BaseModel`（frozen） | 任务声明的数据源、政策、语义、工具、模型或安全依赖 |
| 技能评测数据集版本 | `SkillEvalDatasetVersion` | **Aggregate Root** | Pydantic `BaseModel`（frozen） | 冻结任务快照、环境契约和验证方案哈希的不可变版本 |
| 技能评测基准 | `SkillEvalBenchmark` | **Aggregate Root** | Pydantic `BaseModel`（frozen） | 绑定数据集版本、类型化环境快照、验证方案和硬门禁的不可变定义 |
| 评测轨迹接力点 | `TrajectoryPrefix` | **Value Object** | Pydantic `BaseModel`（frozen） | 仅保存可恢复结构化状态 schema 的执行边界，不包含隐藏思维过程 |
| 评测失败归因 | `FailureAttribution` | **Value Object** | Pydantic `BaseModel`（frozen） | 记录责任类型、失败阶段、稳定机器码和证据引用 |
| 技能评测用例 | `SkillEvalCase` | **Entity** | Pydantic `BaseModel`（frozen） | 归属于一个 SkillEvalSuite，固定、脱敏且可追溯的路由回归问题模板 |
| 技能评测运行 | `SkillEvalRun` | **Aggregate Root** | Pydantic `BaseModel`（frozen） | 绑定候选版本、基线、测试集和配置哈希的批量评测证据 |
| 技能评测结果 | `SkillEvalResult` | **Entity** | Pydantic `BaseModel`（frozen） | 单条用例的候选/基线路由结果与差异分类 |
| 技能评测指标 | `SkillEvalMetrics` | **Value Object** | Pydantic `BaseModel`（frozen） | 发布门禁使用的必测通过率、准确率和回归数量 |
| 技能发布 | `SkillRelease` | **Aggregate Root** | Pydantic `BaseModel`（frozen） | dev/test 环境中带 revision 的候选、审批和活动版本指针 |
| 技能发布审批 | `SkillReleaseApproval` | **Entity** | Pydantic `BaseModel`（frozen） | 冻结制品、评测、配置和基线的人工审批证据 |
| 技能发布状态 | `SkillReleaseStatus` | **Value Object** | `StrEnum` | candidate / approval_pending / approved / active / retired |
| Skill 错误维度 | `SkillErrorDimension` | **Value Object** | `StrEnum` | routing / calculation / policy_content / citation / answer_quality / safety / other |
| 反馈原因码 | `SkillFeedbackReasonCode` | **Value Object** | `StrEnum` | 「回答有误」反馈原因码，映射到初始错误维度 |
| 评测案例池条目 | `SkillEvalCasePoolItem` | **Entity** | Pydantic `BaseModel`（frozen） | 统一沉淀所有 Skill 错误，带租户去重、revision、状态机和脱敏来源 |
| 评测案例池状态 | `SkillEvalCasePoolStatus` | **Value Object** | `StrEnum` | pending_triage / transformed / confirmed / rejected |
| 评测资产引用 | `EvalCaseRef` | **Value Object** | Pydantic `BaseModel`（frozen） | 池条目确认后指向的路由用例或回归用例 |
| 分型回归用例 | `SkillRegressionCase` | **Entity** | Pydantic `BaseModel`（frozen） | 人工确认后的五类可执行维度回归用例，expected_assertions 为判别联合 |
| 回归断言（判别联合） | `RegressionAssertions` | **Value Object** | 判别联合 | Calculation/PolicyContent/Citation/AnswerQuality/SafetyAssertions，禁止自然语言裸 expected |
| 评测器状态 | `SkillRegressionEvaluatorStatus` | **Value Object** | `StrEnum` | available / blocked_by_evaluator / passed / failed / not_applicable |
| 类型化 proposal | `CaseProposal` | **DTO** | 判别联合 | AI 转换生成的六类候选（含 routing），人工确认前不形成资产 |
| 技能草稿 | `SkillDraft` | **Entity** | Pydantic `BaseModel`（frozen） | 创建/导入/复制/编辑中的过渡态草稿，带乐观锁 revision，校验通过并确认后才物化为正式定义 |
| AI 草稿 | `SkillDraft(source_type=AI_GENERATED)` | **Entity** | Pydantic `BaseModel`（frozen） | 人工接受 AI proposal 后创建的过渡态草稿；不直接进入运行时或正式 Skill 目录 |
| 技能草稿状态 | `SkillDraftStatus` | **Value Object** | `StrEnum` | editing / validated / materialized |
| 技能草稿来源 | `SkillDraftSourceType` | **Value Object** | `StrEnum` | template / import / copy / ai_generated |
| 技能执行契约 | `SkillExecutionContract` | **Value Object** | Pydantic `BaseModel`（frozen） | Skill 输入定义的唯一真相，声明公共输入与不同执行场景的数据依赖 |
| 公共输入 | `CommonInputSpec` | **Value Object** | Pydantic `BaseModel`（frozen） | 绝大多数执行场景共享的上下文与业务指标依赖 |
| 执行场景 | `ExecutionProfileSpec` | **Value Object** | Pydantic `BaseModel`（frozen） | 同一 Skill 核心能力不变、数据依赖不同的一种执行配置 |
| 业务指标输入 | `MetricInputSpec` | **Value Object** | Pydantic `BaseModel`（frozen） | 执行契约中对语义层业务指标的依赖声明 |
| AI 生成提案 | `SkillAIGenerationResponse` | **DTO** | Pydantic `BaseModel`（frozen） | 模型输出经服务端校验、哈希和溯源封装后的候选 proposal；未被接受前不产生草稿 |
| Skill 候选制品 | `SkillCandidateArtifact` | **Value Object** | Pydantic `BaseModel`（frozen） | 由已接受草稿生成、仅供隔离评测的不可变制品；存放于运行时 `skills/` 之外 |
| 技能定义 | `SkillDefinition` | **Entity** | Pydantic `BaseModel`（frozen） | 正式目录中可加载定义的治理生命周期状态（enabled/disabled/archived），与不可变 `SkillVersion` 区分 |
| 技能生命周期状态 | `SkillLifecycleStatus` | **Value Object** | `StrEnum` | enabled / disabled / archived |
| 技能治理阶段 | `SkillGovernanceStage` | **Value Object** | `StrEnum` | 工作台只读投影的 evaluate / diagnose / modify / review / release / healthy 阶段 |
| 技能治理优先级 | `SkillGovernancePriority` | **Value Object** | `StrEnum` | 工作台只读投影的 blocked / high / normal 优先级 |
| 技能下一步动作 | `SkillNextAction` | **Value Object** | `StrEnum` | 由版本、评测、草稿和发布事实派生的唯一下一步，不单独持久化 |
| 技能拥有者 | `ToolOwner` | **Value Object** | `StrEnum` | 技能/工具的归属角色（与 `Role` 一致但缺少 CLINICIAN） |
| MCP 服务器 | `McpServer` | **Entity** | Pydantic `BaseModel` | 通过 MCP 协议注册的外部能力服务器 |
| MCP 能力 | `McpCapability` | **Entity** | Pydantic `BaseModel` | MCP 服务器暴露的具体能力点（工具/资源/提示） |
| MCP 风险等级 | `McpRiskLevel` | **Value Object** | `StrEnum` | "low" / "medium" / "high" |
| MCP 传输类型 | `McpTransportType` | **Value Object** | `StrEnum` | "stdio" / "sse" / "streamable_http" |
| 能力类型 | `McpCapabilityType` | **Value Object** | `StrEnum` | "tool" / "resource" / "prompt" / "service" |
| 意图关键词 | `intent_keywords` | Value Object | `list[str]` | 技能匹配用户意图的关键词列表 |
| 技能执行引擎 | `SkillExecutionEngine` | **Domain Service** | — | 负责技能步骤的解析和执行调度 |
| MCP 客户端网关 | `McpClientGateway` | **Domain Service** | — | 负责 MCP 服务器的连接管理和能力调用 |

#### 业务规则

- `Skill.skill_id` 必须使用 kebab-case 或 snake_case
- `McpCapability.requires_human_confirmation` 为 `True` 时（高风险或有外部副作用），必须等待人工确认
- `ToolOwner` 与 `Role` 枚举部分重复但缺少 `CLINICIAN`，使用时需注意
- Skill 评测用例禁止保存患者原始上下文或含敏感信息的样本
- SkillEvalDatasetVersion、SkillEvalBenchmark、SkillEvalRun 及其任务结果、轨迹和归因均不可修改；工作区任务通过 revision 产生新快照
- 评测轨迹只保存动作、脱敏观察和结构化状态，禁止保存模型隐藏思维过程
- Skill 错误统一先进 `SkillEvalCasePoolItem`；routing 投影到现有 `SkillEvalCase`，其余五类写入 `SkillRegressionCase`；`other` 仅表示尚未完成分型，不生成可执行资产
- 回归用例的 `expected_assertions` 必须是判别联合结构化断言，禁止保存自然语言裸 expected；历史回答不直接成为 expected
- 评测器缺失时回归用例状态为 `blocked_by_evaluator`，不会显示通过或放行发布；非路由结果不污染 top1 accuracy
- test 发布必须绑定通过的评测与人工审批；同一 Skill 和环境只能有一个 active release
- 阶段 2 的 `SkillRelease` 仅支持 dev/test 且为 shadow，不改变真实运行时版本选择
- AI proposal 只是候选；必须经人工接受才能创建 `AI_GENERATED` 草稿，禁止直接写入正式 Skill 目录
- Skill 候选制品必须在运行时 `skills/` 之外隔离构建与评测，未通过门禁和人工确认不得物化
- `domain/tool/` 目录完全为空（无 `__init__.py`）— **不要 import**

#### 生命周期

```
技能注册（Skill Create）→ 意图关键词匹配 → SkillExecutionEngine
    → 按依赖顺序执行 SkillStep → 调用 McpCapability / Tool
    → 返回执行结果和引用来源
```

---

### 11. 知识上下文（Knowledge）

#### 概述

管理医保政策知识库、错误码解释、规则解释、RAG 检索、提示模板和申诉模板。是 AI 输出的可信知识底座。

#### 文件位置

`src/knowledge_extension/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 错误码知识条目 | `ErrorCodeEntry` | **Entity** | dict (in_memory) | 错误码的完整解释和处理建议 |
| 规则解释 | `RuleExplanation` | **Entity** | 数据库实体 | 医保规则的中文解释和适用条件 |
| 知识资产 | `KnowledgeAsset` | **Entity** | 数据库实体 | 知识资产的元数据和内容 |
| 知识切片 | `KnowledgeChunk` | **Entity** | 数据库实体 | 知识资产的切片单元，用于向量检索 |
| 申诉模板 | `AppealTemplate` | **Entity** | 数据库实体 | 各类拒付原因的申诉材料模板 |
| 提示模板 | `PromptTemplate` | **Entity** | Pydantic `BaseModel` | 场景/角色化的 LLM 提示模板 |
| RAG 管线 | `RAGPipeline` | **Domain Service** | — | 检索→重排→上下文组装的完整管线 |
| 知识扩展服务 | `KnowledgeEnhancementService` | **Domain Service** | — | 统一的场景知识增强入口 |
| 可见性范围 | `VisibilityScope` | **Value Object** | Pydantic `BaseModel` | 知识资产的角色/租户/院区可见性控制 |
| 知识扩展状态 | `KnowledgeExtensionStatus` | **Value Object** | `StrEnum` | "success" / "no_hit" / "partial_degraded" 等 |
| 引用来源 | `Citation` | **Value Object** | Pydantic `BaseModel` | 知识输出的来源追溯（**存在两份：domain 和 knowledge 各有一份**） |
| 审核通过单元 | `ApprovedUnit` | **Value Object** | Pydantic `BaseModel` | 单元页审核通过、可进入知识结构化阶段的政策 Unit |
| 单元医疗类别分类器 | `med_type_classifier` | **Domain Service** | 纯函数模块 | 就近原则（单元原文→条款路径→文档标题）确定性识别医疗类别；无命中回退「通用」（Issue #19） |
| 单元医疗类别人工修正 | `UnitMedTypeOverride` | **Entity** | Pydantic `BaseModel` | 人工修正某单元的医疗类别，读取时覆盖自动分类；可删除以恢复自动 |
| 政策知识项 | `KnowledgeItem` | **Entity** | Pydantic `BaseModel` | 从一个 Unit 提炼的独立结构化知识，以稳定 `knowledge_id` 标识 |
| 指标来源绑定 | `MetricSourceBinding` | **Entity** | Pydantic `BaseModel` | 将结构化字段或政策 Knowledge 字段绑定到统一标准指标，保留来源版本和证据 |
| 来源值映射 | `SourceValueMapping` | **Entity** | Pydantic `BaseModel` | 将某个来源字段的原始值映射到标准指标的统一标准值 |
| 标准值提案 | `StandardValueProposal` | **Entity** | Pydantic `BaseModel` | 现有标准值域无法承接来源值时提交的人工审核草稿 |
| 语义提议 | `SemanticProposal` | **Aggregate Root** | Pydantic `BaseModel` | 系统从抽取等运行信号主动发现指标或值域缺口后形成的统一审核对象，必须经人工审核后才能发布 |
| 发现信号 | `DiscoverySignal` | **Value Object** | Pydantic `BaseModel` | 携带触发来源、结构化证据与建议落地字段的主动发现输入 |
| 发现证据 | `DiscoveryEvidence` | **Value Object** | Pydantic `BaseModel` | 可追溯到政策文档、单元、提取记录或 bjyb 数据字段的结构化证据；数据库证据需标明采纳/排除等级与理由，同一来源重复观测需幂等合并 |
| 冲突诊断 | `ConflictDiagnosis` | **Value Object** | `StrEnum` | 规则值冲突的确定性分类；只有缺失维度且满足严格分区时可形成候选 |
| 冲突分区证据 | `ConflictPartitionEvidence` | **Value Object** | Pydantic `BaseModel`（frozen） | 记录身份签名、冲突值、分区映射、覆盖率、排他性及 extraction snapshot 的强证据 |
| 维度候选提议 | `DimensionCandidateProposal` | **Value Object** | Pydantic `BaseModel`（frozen） | S5 从冲突严格分区发现的候选维度和值域，仅能装入 `SemanticProposal` 等待人工建模审核 |
| 维度建模结论 | `DimensionReviewConclusion` | **Value Object** | `StrEnum` | 人工判定新增维度、拆分指标、时间版本、值归一化、抽取不完整、证据不足或驳回 |
| 政策事实 | `PolicyFact` | **Value Object** | Pydantic `BaseModel`（frozen） | LLM 提取后、业务推导前的最小政策事实 |
| 规则主体 | `subject` | **Value Object** | `str` | 一条规则实际计算或约束的完整业务度量身份；与适用条件、结果、证据共同构成原子规则语义 |
| 综合报销比例 | `overall_reimbursement_ratio` | **Value Object** | `subject` 标准值 | 多支付来源共同形成的总体报销比例，不归属于单一基金 |
| 大额医疗互助资金支付比例 | `large_medical_mutual_aid_payment_ratio` | **Value Object** | `subject` 标准值 | 明确由大额医疗互助资金承担的分项支付比例 |
| 政策表达式 | `PolicyExpression` | **Value Object** | Pydantic `BaseModel`（frozen） | 确定性规则关系及运算符、引用和参数 |
| 规范规则 | `CanonicalRule` | **Entity** | Pydantic `BaseModel`（frozen） | 编译后可审核、发布且具有稳定规则标识的规则 |
| 编译运行 | `CompileRun` | **Aggregate Root** | Pydantic `BaseModel`（frozen） | 一次不可变政策规则编译运行及其输入输出快照 |
| 编译步骤 | `CompileStep` | **Entity** | Pydantic `BaseModel`（frozen） | 编译运行中按序追加的阶段输入、输出和状态 |
| 校验问题 | `ValidationIssue` | **Value Object** | Pydantic `BaseModel`（frozen） | 带稳定错误码、阶段、严重度和处理建议的编译问题 |
| 知识答案验证 | `KnowledgeAnswerVerification` | **Domain Service** | — | 以 `qa_turn_id` 为句柄验证 Policy QA 回答的引用真实性与结论与结构化知识一致性；确定性优先、fail-closed |
| 知识答案断言 | `KnowledgeAnswerAssertions` | **Value Object** | 判别联合 | 答案验证五个维度的结构化断言，独立于 Skill 的 `RegressionAssertions`，禁止自然语言裸期望 |
| 答案验证维度 | `KnowledgeAnswerVerificationDimension` | **Value Object** | `StrEnum` | citation_authenticity / citation_support / conclusion_consistency / calculation_consistency / coverage_completeness |
| 答案验证状态 | `KnowledgeAnswerVerificationStatus` | **Value Object** | `StrEnum` | passed / failed / not_evaluable / blocked_by_evaluator / review_required |
| 引用关联方法 | `CitationLinkMethod` | **Value Object** | `StrEnum` | internal_id_match / normalized_exact_match / metadata_constrained_match / vector_candidate_fallback / unverified；前三级可强通过，向量仅候选发现不做真实性证明 |
| 答案验证夹具 | `AnswerVerificationFixture` | **Value Object** | Pydantic `BaseModel`（frozen） | 挂载在经典 Policy QA 用例上的确定性公开答案、引用、内部证据与门禁维度声明 |
| 答案验证运行 | `AnswerVerificationRun` | **Aggregate Root** | Pydantic `BaseModel` | 一次候选政策 release 的答案验证门禁运行，汇总逐用例阻断原因并决定是否可发布 |
| 策略答案验证门禁服务 | `PolicyAnswerVerificationGateService` | **Domain Service** | — | 使用候选 release 知识源和用例夹具执行答案验证，作为质量门禁之外的第二道发布阻断 |

#### 业务规则

- AI 输出必须携带 `citations` 来源引用，或声明 `uncertainties` — 禁止无来源的确定性结论
- 错误码知识库支持 PostgreSQL 和内存两种存储，通过配置切换
- 知识资产使用 `VisibilityScope` 控制可见性（角色 + 租户 + 院区）
- `Citation` 在 `src/domain/common/models.py` 和 `src/knowledge_extension/common/models.py` 各有一份，需要注意区分
- 结构化字段与政策 Knowledge 字段是两类权威来源，通过 `MetricSourceBinding` 多对一汇聚到同一标准指标；不得分别建立平行指标体系
- 新指标、来源值映射和标准值提案默认均为 `draft`，只有语义层独立审核动作可以发布
- 一条规范规则必须由 `subject + conditions + result + evidence` 独立表达完整业务语义；规则主体细化不得自动扩张语义层指标，比例结果仍复用基础 `payment_ratio`
- 答案验证的引用真实性必须用规则 ID/原文片段/hash 证明，向量检索只能召回候选，不得单独作为真实性证明；公开 excerpt 找不到原文即 fail-closed
- 覆盖完整性在没有 coverage planner 的问题类型上必须返回 `not_evaluable` 而非 `passed`，防止"看起来全覆盖"的假安全感

#### 生命周期

```
用户提问/系统触发 → KnowledgeEnhancementService
    → RAGPipeline（检索 + 重排）
    → 错误码知识 / 规则解释 / 提示模板
    → 结果 + Citation 引用 → AgentResponse
```

#### 语义查询模型通用语言

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 语义数据集 | `SemanticDataset` | **Entity** | Pydantic `BaseModel` | 已登记且可查询的物理表或视图，以 `dataset_code` 唯一标识 |
| 数据集键 | `DatasetKey` | **Value Object** | Pydantic `BaseModel` | primary / unique / foreign 复合键声明；primary key 决定数据集行粒度 |
| 语义字段 | `SemanticField` | **Entity** | Pydantic `BaseModel` | 物理列的 identifier / dimension / fact 语义声明，以 `field_code` 唯一标识 |
| 数据集关系 | `DatasetRelation` | **Entity** | Pydantic `BaseModel` | 由两端已登记键定义的等值关系，不包含用户 SQL 或 JOIN 表达式 |
| 数据质量规则 | `DataQualityRule` | **Entity** | Pydantic `BaseModel` | coverage / uniqueness / not_null 运行时核验规则 |
| 语义查询 | `SemanticQuery` | **Value Object** | Pydantic `BaseModel` | 只包含业务对象、范围锚点、指标、维度和受限过滤的查询契约 |
| 逻辑查询计划 | `LogicalQueryPlan` | **Value Object** | Pydantic `BaseModel` | 预聚合分支、公共粒度、关联和质量检查的稳定执行契约 |
| 语义查询结果 | `SemanticQueryResult` | **DTO** | Pydantic `BaseModel` | 查询行、模型版本、范围、质量状态、证据和警告 |

- `scope.anchor` 用于定位业务主体及完整范围；普通 `filters` 只限制参与计算的数据行，两者禁止混用。
- 多事实数据集必须分别预聚合到公共实体粒度后再关联，禁止先连接原始事实行。
- 运行时只消费已发布查询模型；关系歧义、重复主键或可能放大金额时 fail-closed。

---

### 12. 安全上下文（Security）

#### 概述

横切所有上下文的认证鉴权、数据脱敏、风险控制和审计留痕能力。

#### 文件位置

`src/security/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 授权服务 | `AuthorizationService` | **Domain Service** | — | 角色和权限校验 |
| 脱敏服务 | `DesensitizationService` | **Domain Service** | — | 敏感数据脱敏处理 |
| 风控服务 | `RiskControlService` | **Domain Service** | — | 高风险动作拦截和异常输出拦截 |
| 审计服务 | `AuditService` | **Domain Service** | — | 操作审计留痕和事件追踪 |
| 高风险动作 | `HIGH_RISK_ACTIONS` | Value Object | `set` | 需人工确认的高风险操作集合 |
| 角色 | `Role` | **Value Object** | `StrEnum` | CASHIER / MEDICAL_OFFICE / INFORMATION_DEPARTMENT / MEDICAL_RECORD_STAFF / CLINICIAN |
| 审计事件 | `AuditEvent` | **Value Object** | Pydantic `BaseModel` | 审计日志的事件结构 |

#### 业务规则

- 高风险动作（退费/冲正/正式结算/病案修改等）必须在 `risk_control/` 中拦截
- 敏感数据（患者姓名、身份证号等）通过 `desensitization/` 脱敏后输出
- 所有 AI 交互和工具调用必须经过审计留痕

---

### 13. 模型服务上下文（Model Service）

#### 概述

管理所有 LLM 调用、模型路由、降级策略和推理服务。所有模型调用必须通过此上下文。

#### 文件位置

`src/model_service/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 模型网关 | `ModelGateway` | **Domain Service** (接口) | — | 统一模型调用入口，路由到具体 Provider |
| 模型请求 | `ModelRequest` | **DTO** | `@dataclass` | 模型调用的完整请求参数 |
| 模型响应 | `ModelResponse` | **DTO** | `@dataclass` | 模型调用的完整响应结果 |
| 流式块 | `StreamChunk` | **DTO** | `@dataclass` | SSE 流式响应的数据块 |
| Token 用量 | `TokenUsage` | **Value Object** | `@dataclass` | Prompt/Completion Token 计数 |
| 消息 | `Message` | **Value Object** | `@dataclass` | Chat 消息的 role/content 对 |
| 模型类型 | `model_type` | Value Object | `str` | 区分不同模型（如 gpt-4, qwen 等） |
| 场景 | `scene` | Value Object | `str` | 调用场景，用于模型路由策略 |

#### 业务规则

- **所有 LLM 调用必须通过 `ModelGateway`**，禁止直接调用 HTTP 接口
- 异常必须通过 `model_service/exceptions.py` 分类处理
- 模型路由由 `model_type` + `scene` 共同决定

---

### 13.5. Runtime 上下文（Runtime）

#### 概述

管理 Policy QA 运行时的会话级业务记忆、上下文规划与推理状态，是“问题分类 → 技能匹配 → 上下文规划”的支撑。设计决策沿用 ADR-007（RuntimeContext 演进而非新建 BusinessSession）与 ADR-008（Context Planner 作为规划阶段）；ADR-009 的 `scenario_executor` 集成已随 Issue #21 退役。

#### 文件位置

`src/runtime/memory/` + `src/runtime/context_composer/` + `src/runtime/intent/planner.py` + `src/runtime/reasoning/` + `src/runtime/runtime_state/models.py` + `src/data_platform/storage/memory/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 业务记忆 | `BusinessMemory` | **Entity**（可变） | Pydantic `BaseModel` | 会话级业务记忆，通过 `memory_id` 唯一标识；仅存领域对象引用（`ref_id`）+ 关键字段快照（`object_snapshot`），领域真相以语义层/外部系统为准 |
| 记忆类型 | `MemoryType` | **Value Object** | `StrEnum` | 记忆对应的业务对象类型：patient / visit / settlement / policy / rule / drug / disease / indicator / conversation |
| 过期策略 | `ExpirePolicy` | **Value Object** | `StrEnum` | 记忆失效策略：SESSION（会话结束）/ TOPIC（话题切换）/ STICKY（跨话题保留）/ TIME（时间过期，默认 30 分钟无活动失效） |
| 记忆快照版本 | `version` (BusinessMemory) | Value Object | `int` | 快照版本号，刷新时 +1，用于检测领域对象更新 |
| 上下文需求 | `ContextNeed` | **Value Object** | Pydantic `BaseModel` | Context Planner 的输出：需要加载哪些业务对象、命中哪些记忆、是否下探语义层（`must_query_semantic`）、是否话题/主体切换 |
| 推理状态 | `ReasoningState` | **Entity**（可变） | Pydantic `BaseModel` | 会话级推理临时态，通过 `session_id` 标识，聚合推理链与假设；与 LangGraph checkpoint 通过 `workflow_id` 关联而非合并 |
| 推理步骤 | `ReasoningStep` | **Entity** | Pydantic `BaseModel` | 推理链中的一个中间结论，含 `claim` / `kind` / `depends_on` / `confidence` / `citations` / `source_memory_ids`（来源可追溯） |
| 推理步骤类型 | `ReasoningStep.kind`（规划抽为 `ReasoningKind` 枚举） | Value Object | `str` 字面量 | 取值："fact"（事实）/ "inference"（推论）/ "hypothesis"（假设）/ "verified"（已验证）；当前为 `str` 字段，后续演进为独立枚举 |
| 推理假设 | `Hypothesis` | **Entity**（可变） | Pydantic `BaseModel` | 待验证假设，状态流转：open → confirmed / rejected；确认后自动转为 verified 推理步骤 |
| 记忆存储端口 | `MemoryStore` | **Domain Service**（接口） | Protocol | 业务记忆存储接口（save / get / list_by_session / delete 等），PostgreSQL / 内存双实现，`USE_MEMORY_STORAGE=1` 回退内存 |
| 记忆管理器 | `MemoryManager` | **Domain Service**（实现） | — | 记忆生命周期管理：合并（Merge）、覆盖（Replace）、过期（Expire）、刷新（Refresh）、压缩（Compression）、会话恢复（Replay） |
| 上下文规划器 | `ContextPlanner` | **Domain Service**（实现） | — | 意图识别管道第三阶段（解析 → 匹配 → 规划）：从意图提取所需业务对象类型，检查 Memory 命中，检测话题/主体切换 |
| 上下文编排器 | `ContextComposer` | **Domain Service**（实现） | — | 从 Memory 挑选最有价值信息并排序，按 Token 预算组织为 LLM Context；超预算时摘要（summarize）而非截断（truncate） |
| LLM 上下文 | `LLMContext` | **DTO** | Pydantic `BaseModel` | Context Composer 的输出契约：会话摘要 + 选中记忆（`MemoryBrief`）+ 推理链 + 预算用量 |
| 推理状态管理器 | `ReasoningStateManager` | **Domain Service**（实现） | — | 推理链维护、假设管理（创建/确认/拒绝）、连续追问的推理复用 |

#### 业务规则

- `BusinessMemory` 不复制领域对象全部数据，仅保存引用 + 关键字段快照；领域真相权威来源是语义层与外部系统（经 `adapters/` 防腐层）
- 记忆的 `importance`（0~1）供 Composer 排序：> 0.7 全量放入，0.3~0.7 摘要放入，≤ 0.3 丢弃
- TIME 策略记忆超过阈值（默认 30 分钟）无活动自动失效（`MemoryManager.expire_by_time`）
- `ReasoningStep` 必须携带 `citations` 或 `source_memory_ids` 以满足"来源可追溯"安全约束
- 推理状态是会话级临时态，不复用为知识；与 LangGraph 图执行状态（checkpoint）分离存储
- `MemoryStore` 遵循 ports/adapter 模式，默认 PostgreSQL，`USE_MEMORY_STORAGE=1` 回退内存实现

#### 生命周期

```
用户消息 → 意图解析（parser）→ 技能匹配（skill_matcher）→ 上下文规划（ContextPlanner）
    → 输出 ContextNeed（命中记忆 / 下探语义层 / 话题主体切换）
    → MemoryManager 读取/写入 BusinessMemory（MemoryStore）
    → ContextComposer 编排 LLMContext（Token 预算 + 摘要策略）
    → ReasoningStateManager 维护推理链（ReasoningStep）与假设（Hypothesis）
    → 注入 RuntimeContext → 场景执行
```

---

### 13.6. 问答会话生命周期与轨迹（Policy QA）

> Issue #30 新增。设计详见 `docs/steering/政策问答-轨迹持久化与挂起升级恢复-设计-V1.0.md`；实现：`src/runtime/policy_qa/session_lifecycle.py`、`src/data_platform/storage/policy_qa/trajectory_storage.py`。

| 通用语言 | 代码标识 | 战术分类 | 代码模式 | 含义 |
|------|------|------|------|------|
| 轨迹轮次 | `trajectory turn`（表 `policy_qa_trajectories` 行） | **Entity**（不可变日志） | 行记录 | 一轮 QA 的可重放公开快照：context_need + memory_updates + 完整 result；失败轮也落一行（answer_status=unavailable） |
| 会话状态 | `Session.status`（active/suspended/escalated/closed） | **Value Object** | `str` 字面量 | 问答会话生命周期；状态机：active⇄suspended、active→escalated→(resolve)→active、非终态→closed（closed 终态） |
| 挂起 | `suspend` | 动作 | — | 用户主动暂停会话（等补材料等）；挂起后拒绝新问答（409 SESSION_NOT_ACTIVE） |
| 升级工单 | `policy_qa_escalation` task | **Entity** | task_closure 记录 | 问题升级医保办人工处理；waiting_human_confirmation → resolve 回填 escalation_reply 后会话恢复 active |
| 轨迹重放 | `restore/replay` | 动作 | — | 按 session_id 读全部轮次快照重建对话/记忆/锚点；读取按所有权校验，非本人 404 |

> 状态机合法转移与所有权校验的唯一权威实现在 `session_lifecycle.py`；前端恢复重建的纯函数在 `policy-qa-session.ts::restoreSessionState`。

---

### 14. 共享通用层（Shared / Common）

#### 概述

跨所有上下文共享的基础模型、异常定义、DTO 和合约。

#### 文件位置

`src/shared/` + `src/domain/common/` + `src/adapters/base/`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 引用来源 | `Citation` | **Value Object** | `@dataclass(frozen=True)` (domain) / Pydantic (knowledge) | **存在两份**，domain 版三个字段，knowledge 版更丰富 |
| 审核事件 | `AuditEvent` | **Value Object** | Pydantic `BaseModel` | 审计留痕的事件结构 |
| 错误详情 | `ErrorDetail` | **DTO** | Pydantic `BaseModel` | `{ error_code, message, audit_event }` 标准异常结构 |
| 运行时任务 | `RuntimeTask` | **DTO** | Pydantic `BaseModel` | API 层的任务传输对象 |
| 角色 | `Role` | **Value Object** | `StrEnum` | 系统五大角色定义 |
| 适配器调用结果 | `AdapterCallResult` | **DTO** | Pydantic `BaseModel` | 统一的外部系统调用结果包装 |
| 适配器调用状态 | `AdapterCallStatus` | **Value Object** | `StrEnum` | "success" / "failed" |
| 数据质量状态 | `DataQualityStatus` | **Value Object** | `StrEnum` | "complete" / "degraded" / "missing"（支持优雅降级） |
| 适配器错误 | `AdapterError` | **Exception** | — | 外部系统调用失败的异常类型 |

#### 跨上下文约定

- `patient_id + encounter_id` 是跨所有业务上下文的通用复合键
- 错误响应统一使用 `ErrorDetail` 结构，通过 `error_detail()` 工厂函数创建
- 适配器统一返回 `AdapterCallResult`，不抛出异常（支持优雅降级）
- `DataQualityStatus` 的 `DEGRADED` / `MISSING` 状态用于外部系统不可用时的降级策略

---

### 14.5. 门诊数据治理控制面（Outpatient Data Governance）

#### 文件位置

`src/data_platform/outpatient_governance.py` + `src/adapters/insurance_interface/outpatient_source.py`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 门诊数据源 | `OutpatientDataSource` | **DTO** | Pydantic `BaseModel` | 一家医院的门诊 SQL Server 只读数据源配置，不含密码或密文 |
| 同步任务 | `OutpatientSyncJob` | **DTO** | Pydantic `BaseModel` | 数据源唯一的 CDC 或定时 SQL 同步运行配置；禁止另建 `pipeline`、`source job`、`import task` 同义模型 |
| 同步尝试 | `OutpatientSyncAttempt` | **DTO** | Pydantic `BaseModel` | 同步任务一次可审计的实际执行记录 |
| 来源检查点 | `OutpatientCheckpoint` | **Value Object** | `@dataclass(frozen=True)` | CDC LSN 或定时 SQL 时间窗的来源中立进度位置 |

---

### 14.6. 治理数据流上下文（Governed Data Flow）

> 依据：issue #65 Phase 0 契约冻结 + `docs/research/治理中心全流程可视化配置-开源调研与落地方案-V1.0.md`。
> Golden Flow 基准：issue #62 门诊四加工字段（口径句 v4）。

#### 文件位置

`src/domain/governed_flow/models.py`（DSL 契约）+ `src/domain/governed_flow/validation.py`（图与契约校验） + `src/domain/governed_flow/compiler.py`（View 编译器）
+ `src/runtime/flow/flow_service.py`（生命周期服务）+ `src/runtime/flow/flow_query_service.py`（受控问数服务）+ `src/data_platform/storage/flow/`（存储与部署/读取适配器）+ `src/runtime/api/flow_routes.py`（API）

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 治理数据流 | `FlowDefinition` | **Aggregate Root** | Pydantic `BaseModel` | 数据加工→语义指标→受控消费的声明式版本化资产；画布只编辑它，不编辑 SQL |
| 流节点 | `FlowNode`（discriminated union） | **Entity** | Pydantic `BaseModel` | 八类白名单节点：source/filter/join/aggregate/derived_metric/dimension/quality_gate/consumer |
| 流边 | `FlowEdge` | **Value Object** | Pydantic `BaseModel` | 节点连接；图必须无环（DAG） |
| 流状态 | `FlowStatus` | **Value Object** | `StrEnum` | draft → validating → pending_review → published → deprecated |
| 来源节点 | `SourceNode` | **Entity** | Pydantic `BaseModel` | 只引用已登记数据集（dataset_code），禁止连接串；不允许有入边 |
| 过滤节点 | `FilterNode` | **Entity** | Pydantic `BaseModel` | AND 组合条件；`in_or_null` 算子表达口径句的 `IN(...) OR IS NULL` 分支 |
| 过滤条件 | `FlowFilterCondition` | **Value Object** | Pydantic `BaseModel` | 字段+算子+值+可选值域声明；字段必须在 source contract 内 |
| 聚合节点 | `AggregateNode` | **Entity** | Pydantic `BaseModel` | group_by + measures；空 group_by=全局单行快照（#62 形态） |
| 聚合度量 | `AggregateMeasure` | **Value Object** | Pydantic `BaseModel` | 算子白名单 count/count_distinct/sum/avg；count_distinct 必须显式 distinct_key；空值/冲正策略显式声明 |
| 派生指标节点 | `DerivedMetricNode` | **Entity** | Pydantic `BaseModel` | AST 白名单算术公式（仅 + - * / 与依赖变量），禁止 eval/任意 SQL |
| 维度节点 | `DimensionNode` | **Entity** | Pydantic `BaseModel` | 值域 + 权限级别（summary/detail），保留下钻边界 |
| 质量门禁节点 | `QualityGateNode` | **Entity** | Pydantic `BaseModel` | 口径签核/勾稽恒等/行数/空值率/新鲜度/权限检查 |
| 消费节点 | `ConsumerNode` | **Entity** | Pydantic `BaseModel` | query_planner/skill/dashboard_card/weekly_report/assistant；只读引用已发布指标；不允许有出边 |
| 来源契约 | `SourceContract` | **Value Object** | Pydantic `BaseModel` | 本 flow 实际引用的字段白名单 |
| 指标输出绑定 | `MetricOutputBinding` | **Value Object** | Pydantic `BaseModel` | flow 产出指标与语义层绑定；口径句（policy_definition）必填，发布前必须已签核 |
| 政策载体 | `PolicyCarrier` | **Value Object** | Pydantic `BaseModel` | 复用 #60 结构：doc_number/region_scope/effective_start/effective_end/policy_rule_ref |
| 发布修订 | `FlowPublishedRevision` | **Entity**（不可变） | Pydantic `BaseModel` | 原子锁定 flow revision + semantic revision + 产物 hash；回滚只切换 active revision，不删除历史 |
| 内容哈希 | `compute_flow_content_hash()` | — | 纯函数 | 规范化 JSON 的 sha256；排除 revision/status/发布元数据/画布坐标，节点顺序无关 |
| 状态流转 | `transition_flow_status()` | — | 纯函数 | 非法流转抛 `FlowStateInvalidError`；deprecated 为终态 |
| 治理流服务 | `FlowGovernanceService` | **Domain Service** | 无状态服务类 | 编排存储/校验/编译；发布原子锁三要素，回滚只切活跃版本 |
| 流存储端口 | `GovernedFlowStorage` | **Port** | `typing.Protocol` | 主表 CRUD + 发布证据 + 活跃指针；内存/PG 双实现，`USE_MEMORY_STORAGE=1` 回退 |
| 编译产物 | `CompiledFlowArtifact` | **Value Object** | Pydantic `BaseModel` | view_name + view_sql（CREATE OR ALTER VIEW）+ 查询计划 + artifact_hash |
| 查询计划步 | `CompileStep` | **Value Object** | Pydantic `BaseModel` | 每节点一步；Phase 2 画布预览与 Phase 3 消费契约对接载体 |
| 编译失败 | `FlowCompileError` | — | `ValueError` 子类 | args[0] 为 FLOW_* 错误码；标识符注入/分叉拓扑/非 view 物化一律拒绝 |
| 校验阻断 | `FlowPublishBlockedError` | — | `ValueError` 子类 | 携带完整 `FlowValidationReport`；API 映射 422 fail closed |
| 语义版本锁 | `compute_semantic_revision()` | — | 纯函数 | 数据集/关系/指标口径/派生依赖锚点的 sha256，发布时与 artifact_hash 一并锁定 |
| 视图部署端口 | `FlowViewDeployer` | **Port** | `typing.Protocol` | publish/rollback 先经它把 CREATE OR REPLACE VIEW 落 PG 落地库再动证据；部署失败抛异常（fail closed） |
| 视图读取端口 | `FlowViewReader` | **Port** | `typing.Protocol` | 受控问数只读已部署视图的列投影通道；内存模式 fail-closed 拒读 |
| 受控问数服务 | `FlowQueryService` | **Domain Service** | 无状态服务类 | 只消费 published 活跃版本；消费前重编译验 artifact_hash（T8）；指标 ⊆ consumer.consumes、维度 ⊆ 维度绑定白名单（T11）；勾稽门禁逐行评估 |
| 受控问数结果 | `FlowQueryResult` | **Value Object** | Pydantic `BaseModel` | 数值 + 发布证据（revision_id/artifact_hash/view_name）+ 门禁评估三件套；恒等失败时 unavailable 且数值扣发 |
| 门禁评估结果 | `FlowGateResult` | **Value Object** | Pydantic `BaseModel` | check_type + passed + detail；失败 detail 必须携带差异事实 |
| 证据不一致 | `FlowArtifactMismatchError` | — | `FlowStateInvalidError` 子类 | 发布证据 artifact_hash 与定义重编译产物不一致（T8 篡改拦截）；API 409 `FLOW_ARTIFACT_MISMATCH` |
| 消费白名单拒止 | `FlowConsumeMetricUnknownError` / `FlowConsumeDimensionForbiddenError` | — | `ValueError` 子类 | 请求指标不在 consumer.consumes / 请求维度不在维度绑定白名单（T11）；API 422 |
| 消费歧义拒猜 | `FlowConsumeAmbiguousError` | — | `FlowStateInvalidError` 子类 | 指标码驱动解析（query_by_metrics）命中多个已发布消费契约，拒绝猜测；API 409 `FLOW_CONSUME_AMBIGUOUS` |

#### 业务规则（Phase 0 冻结）

1. 节点/算子/消费方均为白名单枚举，扩充必须过评审并同步本字典。
2. 过滤与聚合引用的字段必须在 `SourceContract.fields` 内；数据集/join 关系必须已登记。
3. `T_CureType` 过滤必须显式声明 `value_domain=MZ_CURE_TYPE`；med_type 是政策知识管线医疗类别维度，两域不混用（#62 签核结论）。
4. 发布门禁 fail closed：口径句未签核、依赖未发布、图有环、越权字段任一存在即 blocking。
5. 冻结错误码见 `models.py::FLOW_ERROR_CODES`，API 层按 `FLOW_*` 前缀映射 HTTP 状态。

---

### 14.7. 健康运营上下文（Ops Health）

> 依据：issue #45 P0 + issue #50 生命周期 + issue #53 L1 自动修复 + issue #51 P1-5 LLM 智能诊断 + issue #52 P1-6 定时巡检调度 + `docs/research/资产健康运营平台-开源调研与落地方案-V1.0.md` §6。
> 定位：横跨四类资产（skill/knowledge/data/runtime）的问题汇聚层；「发现」（#45：只读检查器 + fingerprint 去重落库）、「手动处置」（#50：ignore/reopen 流转 + 事件留痕）、「解决」（#53：L1 白名单自动修复 + 修复后强制验证闭环）、「诊断」（#51：LLM 智能诊断，citations 强制）与「调度」（#52：定时巡检，claim 抢占不重复执行）已落地。

#### 文件位置

`src/domain/ops/models.py`（领域模型）+ `src/runtime/ops/checkers.py`（检查器注册）+ `src/runtime/ops/remediation.py`（L1 修复白名单与执行器）+ `src/runtime/ops/service.py`（巡检编排与生命周期状态机）+ `src/runtime/ops/scheduler.py`（巡检调度器）+ `src/runtime/ops/diagnosis.py`（LLM 智能诊断）+ `src/data_platform/storage/ops/`（存储 ports/adapter 四件套）+ `src/runtime/api/ops_routes.py`（API）+ `scripts/run_ops_inspection_worker.py`（定时巡检 worker）+ portal `/ops` 页（`src/apps/portal/app/ops/page.tsx` + `finding-detail-drawer.tsx` + `src/lib/ops-api.ts`）

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 资产健康问题 | `OpsFinding` | **Aggregate Root** | Pydantic `BaseModel`（frozen） | 问题库单行；fingerprint 唯一，复现累计 occurrence_count，revision 乐观锁 |
| 问题草稿 | `FindingDraft` | **Value Object** | Pydantic `BaseModel`（frozen） | 检查器单次产出、未落库；payload 只含脱敏安全字段 |
| 问题指纹 | `finding_fingerprint()` | 值函数 | — | 去重键 `asset_type:asset_id:check_id`；同资产同检查项复现只累计 |
| 受检资产类型 | `OpsAssetType` | **Value Object** | `StrEnum` | skill / knowledge / data / runtime 四域 |
| 问题严重度 | `OpsSeverity` | **Value Object** | `StrEnum` | critical（立即处理）/ warning（排期）/ info（记录） |
| 问题状态 | `OpsFindingStatus` | **Value Object** | `StrEnum` | open（#45 巡检产出）/ ignored（#50 忽略）/ resolved（#53 修复验证通过） |
| 生命周期事件 | `OpsFindingEvent` | **Entity** | Pydantic `BaseModel`（frozen） | 一次 ignore/reopen/resolved/reopened 流转留痕（actor + 可选 reason + created_at），追加只增不改 |
| 事件类型 | `OpsFindingEventType` | **Value Object** | `StrEnum` | ignored / reopened / resolved（#53 修复验证通过）/ reopened 复用（巡检发现已解决问题复发） |
| 问题详情 | `OpsFindingDetail` | **DTO** | Pydantic `BaseModel` | finding 当前态 + events 时间线（升序）+ remediations 修复记录（升序），详情页/流转接口返回体 |
| 检查器注册项 | `CheckSpec` | **Value Object** | frozen dataclass | 代码内注册（id/资产类型/描述/runner），不引入 YAML 配置系统 |
| 检查器读取面 | `GovernanceStatusReader` | **Port** | `typing.Protocol` | 检查器对治理控制面的最小只读依赖（list_sources/get_job） |
| 健康运营巡检服务 | `OpsHealthService` | **Domain Service** | — | 逐检查器只读取数→问题库去重落库；单检查器失败不中断整次巡检；承载 ignore/reopen/remediate 状态机 |
| 巡检结果 | `OpsInspectionResult` | **DTO** | Pydantic `BaseModel` | checked_at / check_count / finding_count / findings / checker_errors + 调度回填 inspection_id·trigger_source + computed new_finding_count（首见问题数） |
| 修复运行 | `OpsRemediationRun` | **Entity** | Pydantic `BaseModel`（frozen） | 一次修复尝试留痕：status 记动作执行、verification_result 记修复后验证（None=未验证）；追加只增不改 |
| 修复风险级 | `RemediationRiskLevel` | **Value Object** | `StrEnum` | L1（白名单自动执行）/ L2（人工确认） |
| 修复运行状态 | `RemediationRunStatus` | **Value Object** | `StrEnum` | succeeded（动作已执行）/ failed（动作未发起，after_evidence 携带原因） |
| 验证结果 | `VerificationResult` | **Value Object** | `StrEnum` | passed（检查复跑通过→resolved）/ failed（复跑仍报问题→保持 open） |
| 修复动作执行结果 | `RemediationActionOutcome` | **DTO** | Pydantic `BaseModel`（frozen） | 执行器返回体：executed + before/after 证据快照（脱敏字段） |
| 修复白名单项 | `RemediationSpec` | **Value Object** | frozen dataclass | action_id ↔ check_id ↔ risk_level ↔ executor 的白名单注册；`default_remediation_whitelist()` 代码内注册 |
| 修复执行器 | `RemediationExecutor` | **Port** | `typing.Protocol`（Callable） | `(OpsFinding, action_id) -> RemediationActionOutcome`；业务修复逻辑的唯一扩展点 |
| 重试门诊同步 | `retry_data_sync` | 修复动作 | — | 本期唯一 L1 动作：复用 data_governance 同步入口重试失败/滞后的门诊同步任务 |
| 诊断报告 | `OpsDiagnosisReport` | **DTO** | Pydantic `BaseModel` | 单条 finding 的 LLM 诊断（存 `OpsFinding.diagnosis`，最新覆盖）：status/root_cause/citations/uncertainties/actions/model_route |
| 诊断结论状态 | `DiagnosisStatus` | **Value Object** | `StrEnum` | complete（有引用）/ insufficient_evidence（无引用，不落根因不留建议） |
| 诊断建议分级 | `DiagnosisActionLevel` | **Value Object** | `StrEnum` | L1 自动白名单 / L2 人工确认 / L3 禁止自动执行（仅提示）；建议仅作指引，执行仍受 #53 白名单约束 |
| 诊断证据引用 | `DiagnosisCitation` | **Value Object** | Pydantic `BaseModel`（frozen） | citation_id（E1..En）+ source + quote；**只能从证据目录选取，quote 取自目录原文，模型不可编造** |
| 诊断建议动作 | `DiagnosisAction` | **Value Object** | Pydantic `BaseModel`（frozen） | level + description + citation_ids；未挂任何有效引用的建议在构建时丢弃 |
| 诊断结果 | `OpsDiagnosisResult` | **DTO** | Pydantic `BaseModel` | diagnose 端点返回体：刷新后的 finding（含新报告）+ 报告本体 |
| 诊断不可用 | `DiagnosisUnavailableError` | 异常 | — | 模型未配置/调用失败/输出不可解析；API 503 `DIAGNOSIS_UNAVAILABLE`，不落库不覆盖旧报告 |
| 智能诊断服务 | `OpsDiagnosisService` | **Domain Service** | — | 证据目录（payload+定向补充，过脱敏）→ ModelGateway scene=asset_diagnosis → 校验落库；citations 硬约束 |
| 证据目录构建 | `build_evidence_catalog()` | 值函数 | — | payload 逐字段 + 定向补充证据（`supplement.*`），统一 `redact_sensitive_text` 后编号 E1..En |
| 定向证据采集器 | `EvidenceCollector` | **Port** | `typing.Protocol`（Callable） | `(OpsFinding) -> [(source, quote)]`；默认实现为门诊同步问题附最近尝试记录 |
| 巡检运行 | `OpsInspectionRun` | **Entity** | Pydantic `BaseModel`（frozen） | 一次巡检留痕：trigger_source / status / triggered_by / 起止时间 / finding_count / new_finding_count / checker_errors；追加只增不改 |
| 巡检触发方式 | `OpsInspectionTrigger` | **Value Object** | `StrEnum` | manual（手动，绕过到期检查）/ scheduled（定时，仅 next_run_at 到期可认领） |
| 巡检状态 | `OpsInspectionStatus` | **Value Object** | `StrEnum` | running / succeeded / failed |
| 检查器错误 | `OpsCheckerError` | **Value Object** | Pydantic `BaseModel`（frozen） | 单检查器执行失败记录（check_id + message），不中断整次巡检 |
| 巡检调度状态 | `OpsInspectionScheduleState` | **DTO** | Pydantic `BaseModel` | 单行调度表投影：next_run_at + active_inspection_id 互斥位 |
| 巡检摘要 | `OpsInspectionSummary` | **DTO** | Pydantic `BaseModel` | 周期 + 下次巡检时间 + in_progress + 最近一次运行；portal 摘要条数据 |
| 巡检调度器 | `OpsInspectionScheduler` | **Domain Service** | — | run_manual / run_scheduled_once / get_summary；claim 抢占 + 完成推进 next_run_at |
| 巡检认领 | `claim_inspection()` | Port 方法 | — | 事务内 `FOR UPDATE SKIP LOCKED` 抢占单行调度表（active 互斥 + 定时到期检查），败者得 None |
| 巡检进行中 | `InspectionInProgressError` | 异常 | — | 手动触发被并发巡检抢占（API 409 `INSPECTION_IN_PROGRESS`） |

#### 业务规则

1. 检查器**只读**复用既有域状态数据（如 data_governance 连接探测、同步任务状态），不改其任何表。
2. 滞后判定：应到未到超过 `max(2×调度间隔, 15 分钟)` 宽限才告警（`LAG_GRACE_FLOOR_MINUTES`）。
3. payload 只允许 safe_* / 状态码 / 时间戳等脱敏字段，检查器取数侧负责不带出凭据与连接串。
4. upsert 语义：首见插入 open/1 次；复现 occurrence_count+1、last_seen_at/severity/payload 刷新，status 与 diagnosis 不动（复现不复活已忽略问题；诊断归 P1）。
5. 生命周期状态机（#50）：ignore 仅允许 open→ignored（reason 必填）；reopen 仅允许 ignored|resolved→open；非法流转抛 `InvalidFindingTransitionError`（API 409 `FINDING_TRANSITION_INVALID`）。
6. 乐观锁：流转必须携带 `expected_revision`，与库内不一致抛 `FindingRevisionConflictError`（API 409 `FINDING_REVISION_CONFLICT`）；revision 随每次 upsert/流转递增。
7. 事件留痕与状态更新同事务（storage `transition_finding` 单调用），事件追加只增不改，构成详情页时间线。
8. API 鉴权：签名 JWT `ops:read`（GET）/ `ops:write`（POST /ops/inspections、ignore、reopen、remediate），与 data-governance 同模式。
9. L1 白名单（#53）：只收录幂等、可重放、可验证的修复动作，本期仅 `data_sync_failed → retry_data_sync`；非白名单 check_id 的修复请求抛 `RemediationNotAllowedError`（API 409 `REMEDIATION_NOT_WHITELISTED`），portal 不展示修复按钮。
10. 修复仅允许对 open 问题发起（同 ignore）；执行器先做动作、后强制重跑该问题的触发检查器（按 fingerprint 匹配草稿）：复跑通过→resolved（事件 reason 记 `L1 修复动作 xxx 验证通过`）；复跑仍报→upsert 复现（occurrence_count+1）保持 open；检查器异常→不判定验证结果，状态不动，`after_evidence.verification_error` 记原因。
11. 修复运行留痕先于状态流转：动作未发起（如任务 paused/draft、同步任务不存在）记 `failed` 运行行且不触发验证，问题状态不动；`expected_revision` 乐观锁只约束 resolved 流转，冲突时运行行仍保留（动作幂等可重放）。
12. 已解决问题复现：巡检 upsert 后自动 open（系统 actor `system:ops-inspector` 记 reopened 事件）；ignored 问题复现不复活（#50 规则）。
13. 诊断（#51）只读：`POST /ops/findings/{id}/diagnose`（ops:write）不改 status/revision；报告覆盖写入 `diagnosis` 列。citations 硬约束：引用只能从证据目录选取（模型只可挑选不可编造 quote）；引用为空 → status=insufficient_evidence、root_cause 置空、actions 清空，不驱动任何修复动作（负例测试守护）。
14. 诊断输入过 `security/desensitization`：证据目录构建时统一 `redact_sensitive_text`，PHI 原值不进模型也不落库；报告记录 `model_route`（scene/model_type/实际 model_name）供审计。
15. 诊断模型调用走 `ModelGateway` scene=`asset_diagnosis`、model_type=`llm`（路由表显式条目，治理路由发布优先）；模型失败/输出不可解析抛 `DiagnosisUnavailableError`（API 503），不落库不覆盖旧报告。
16. 调度（#52）复用门诊同步 `claim_due_job` 单进程 PostgreSQL 模式（不引入 Airflow/Temporal/celery）：单行调度表 `ops_inspection_schedule`（schedule_id=1 CHECK）持 next_run_at 与 active_inspection_id 互斥位；claim 在事务内 `FOR UPDATE SKIP LOCKED` 抢占，并发恰一胜出、败者得 None（活库双连接验收）；手动触发被并发占用抛 `InspectionInProgressError`（API 409）。
17. 触发语义：manual 绕过到期检查即可认领；scheduled 仅 next_run_at 到期可认领（worker 轮询，未到期返 None）；两类完成后统一推 next_run_at = 完成时间 + 周期（env `OPS_INSPECTION_INTERVAL_MINUTES` 默认 1440=每日，非法/<1 回退默认；周期不落库）。
18. 失败语义：单检查器失败不中断整次巡检（记 checker_errors，status 仍 succeeded）；灾难性巡检失败落 failed 运行行——checker_errors 只存安全文案「巡检执行异常，详见服务端日志」（异常原文可能含连接信息不落库），next_run_at 顺延一整周期，worker 记日志不重试。
19. 运行留痕：每次巡检写 `ops_inspections` 行（起止时间/触发人/两类计数/checker_errors）；`OpsInspectionResult.inspection_id`/`trigger_source` 由调度器回填——直接调用 `OpsHealthService.run_inspection`（未经调度器，如修复后验证）不留运行行。new_finding_count = occurrence_count==1 的首见问题数（复现累计不算新发现）。

---

### 14.8. 数据目录上下文（Data Catalog）

> 依据：issue #38。
> 定位：三级资产（源表字段 dataset/field → 语义对象/指标 object/metric → 消费方 consumer=skill）的**只读聚合目录**——统一搜索、资产详情、血缘链与同步 SLA 看板；不新增任何存储表，全部数据来自既有注册中心/治理控制面/发现层/skill manifest 的运行时聚合。

#### 文件位置

`src/runtime/catalog/service.py`（`CatalogService` 编排 + `PgCatalogSyncReader` 活库适配 + DTO 全集）+ `src/runtime/api/catalog_routes.py`（API）+ portal `/catalog` 页（`src/apps/portal/app/catalog/page.tsx` + `asset-detail-drawer.tsx` + `src/lib/catalog-api.ts`）

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 数据目录服务 | `CatalogService` | **Domain Service** | — | 双端口只读编排：SemanticRegistry（语义资产）+ CatalogSyncReader（治理控制面）+ skill manifest 消费方；搜索/详情/血缘/SLA 四入口 |
| 目录资产 | `CatalogAsset` | **DTO** | Pydantic `BaseModel` | 五类资产的统一投影（asset_type ∈ dataset/field/object/metric/consumer + asset_id + title/subtitle + matched_on 命中字段） |
| 资产类型 | `CatalogAssetType` | **Value Object** | `Literal` | dataset / field / object / metric / consumer 五类（`ASSET_TYPES`） |
| 资产详情 | `CatalogAssetDetail` | **DTO** | Pydantic `BaseModel` | asset + summary 摘要 KVs + 按类型可选分节（fields/metrics/datasets/consumers/batches/versions/value_mappings） |
| 目录血缘 | `CatalogLineage` | **DTO** | Pydantic `BaseModel` | 血缘链投影：sources（数据源）→ batches（同步批次）→ datasets+fields（投影表/字段）→ metrics（指标）→ consumers + versions（消费方与语义版本） |
| SLA 看板 | `CatalogSlaBoard` / `CatalogSourceSla` | **DTO** | Pydantic `BaseModel` | 每数据源：连接/任务状态、P95 与最近非空延迟、质量门、语义版本、近 10 次尝试统计、最近批次（真实行） |
| 目录同步读取面 | `CatalogSyncReader` | **Port** | `typing.Protocol` | 目录对治理控制面的最小只读依赖（list_sources/get_job/get_sync_status/list_recent_batches/list_attempts）；`PgCatalogSyncReader` 为活库实现 |
| 消费方 | `CatalogConsumerInfo` | **DTO** | Pydantic `BaseModel` | 从 `skills/*/skill_manifest.yaml` needed_objects 解析的 skill 级消费方（consumer_id=skill 目录名，consumed_objects/consumed_metrics） |

#### 业务规则

1. **只读聚合零新表**：目录不建任何存储表、无任何写端点；语义资产来自 SemanticRegistry、批次/SLA 来自治理控制面、字段描述/主键来自发现层（`table:column` 键）、消费方来自 skill manifest，均运行时聚合。
2. 批次只挂接落地库数据集：仅 `datasource_id == "outpatient_postgres"`（`PROJECTION_DATASOURCE_ID`）的数据集展示同步批次与 SLA 延迟，外部源数据集不伪造批次。
3. 指标↔数据集双向挂接：指标按 `object_code` 归属对象、按 `source_field` 三段式（datasource.table.column）精确触达字段级投影表；血缘字段取指标 source_field 引用的列。
4. API 只读无鉴权（沿语义层 GET 先例）；五类资产类型用 `Literal` 参数自动 422，未知资产 404 `CATALOG_ASSET_NOT_FOUND`。

---

### 14.9. 语义指标政策承载（Metric Policy Carrier）

> 依据：issue #35 follow-up / issue #60（切片①-③ 经 PR#61 落地：subkind/policy_carrier 字段 + A/B 两态发布门禁 + 快照携带；切片④ 本期补齐：policy_rule_ref 溯源 + 幽灵档拒绝 + 查询层生效期裁剪）。
> 定位：政策口径类指标（结算法则/报销规则/目录待遇）在发布的指标定义上硬携带 文号/地域/生效期，保证可溯源、不二次漂移；承载单源在 zcgz 规则行（`policy_extractions`），指标只冗余。

#### 文件位置

`src/semantic_layer/models.py`（Metric.subkind/policy_carrier + ObjectVersionMetric 快照冻结）+ `src/semantic_layer/registry.py`（发布门禁 + `PolicyRuleReader` Port + `PgPolicyRuleReader`）+ `src/semantic_layer/query_planner.py`（`_assert_metric_in_force` 生效期裁剪）

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 政策承载 | `policy_carrier` | **Value Object** | Metric 上的 `dict` 字段 | `{doc_number, region_scope, effective_start, effective_end?, policy_rule_ref?}`；A 类发布硬卡组 |
| 政策判别位 | `subkind` | **Value Object** | Metric 上的 `str` 字段 | `policy_rate`（A 报销/统筹/补差金额类）/ `policy_elig`（A 待遇资格/准入）/ None·空（B 运营事实类） |
| 政策规则引用 | `policy_rule_ref` | **Value Object** | policy_carrier 键 | zcgz 规则行实体主键（`policy_extractions.extraction_id`），非 section/文号；单源在 zcgz，指标只冗余 |
| 幽灵档 | — | 业务规则 | — | 引用的规则行已废止（archived）而承载缺 `effective_end` 的发布态：废止事实必须落到废止日，否则拒绝发布 |
| 政策规则读取面 | `PolicyRuleReader` | **Port** | `typing.Protocol` | 发布门禁对 zcgz 规则行的只读溯源句柄 `get_rule(rule_ref)`（至少含 status）；None=不校验（存量兼容） |
| PG 政策规则读取器 | `PgPolicyRuleReader` | **Adapter** | 普通 class | 同库窄列 SELECT（extraction_id/status）；不反向 import knowledge_extension，保持依赖方向 |
| 生效期裁剪 | `_assert_metric_in_force` | 值函数 | — | 查询层按执行日对照生效区间：effective_start>今日 → 未生效拒查；effective_end<今日 → 已废止拒查；格式非法跳过 |

#### 业务规则

1. A/B 两态门禁（PR#61，验收#1）：subkind∈{policy_rate, policy_elig} 缺 doc_number/region_scope/effective_start 任一 → 发布拒绝并逐项指明；B 类（空/运营）不因未填 policy_carrier 被拒（验收#3 存量回归）。
2. 溯源校验（#60 切片④，验收#4）：policy_rule_ref 非空（不分 A/B）→ 必须命中同库 zcgz 规则行；引用不存在 → 拒绝发布并指明引用值；仅在注入 `PolicyRuleReader` 时生效（生产 `get_semantic_registry()` 注入，内存注册表/存量构造路径不受影响）。
3. 幽灵档拒绝（#60 切片④，验收#2）：引用行 status=archived（已废止）而承载缺 effective_end → 拒绝并指向废止事实；补齐废止日或引用现行行（end=null=现行）合法。
4. 查询层生效期裁剪（规格「查询层不得用已废止时段值」）：`_resolve_metrics` 对带承载指标按查询执行日裁剪，已废止/未生效指标不可进入任何查询；日期格式非法时跳过（发布门禁负责硬卡，查询层不因脏数据阻断）。
5. 快照一致性（验收#5，PR#61）：policy_carrier + subkind 随 BusinessObjectVersion 发布冻结（`ObjectVersionMetric.from_metric` 深拷贝），回滚=版本指针恢复旧快照。

---

### 14.10. 数据供给分档（Data Supply）

> 依据：issue #27。定位：语义层（需求侧）定跨院不变的视图/字段/值域标准，供给侧按院区分档实现；平台只通过 `DataSupplyConnectionPort` 取只读连接，不感知分档细节。规范文档：`docs/steering/数据接入规范.md`。

#### 文件位置

`src/adapters/ports/data_supply.py`（端口）+ `src/adapters/data_supply/sqlserver_direct.py`（一档适配器）+ 组合根 `src/runtime/policy_qa/settlement_data_provider.py`（注入 `connect_fn`，连接能力来自 `SemanticDataSource.open_connection`）

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 数据供给连接端口 | `DataSupplyConnectionPort` | **Port** | `runtime_checkable Protocol` | `connect(datasource_id) -> Any` 只读 PEP 249 连接契约；供给侧不可用抛 `RuntimeError` |
| SQL Server 直连供给适配器 | `SqlServerDirectSupplyAdapter` | **Adapter** | 普通 class | 一档实现：CDR 只读视图直连，构造注入 `connect_fn`，禁止反向 import runtime |

#### 业务规则

1. 三档供给：一档 CDR 只读视图直连（SQL Server）；二档厂商 API/中间件同步（门诊 PG 同步即此形态）；三档医保局代理暂缓——档位差异被端口吸收，语义层与查询服务不感知。
2. 适配器只接受注入的 `connect_fn`，组合根在 `SemanticSettlementDataProvider`；adapters 包不得反向 import `src.runtime`（防腐层依赖方向）。
3. 供给侧四承诺：只读、可审计、单条低频查询、码值稳定；需求侧标准（视图/字段/值域）以 `docs/steering/数据接入规范.md` 为单源，跨院不变。
4. `SemanticDataSource.open_connection` 是 provider 历史回退链的公开化（注册数据源→发现层最近扫描→env 配置），区别于严格模式的 `connect_datasource`。

---

### 14.11. 可信问题库（Trusted Question Library）

> 依据：issue #37、设计文档 §14.1。定位：高频问法沉淀为「标准问题 + 同义表达 + 绑定查询计划」的可信条目，人工审核后发布；生产问数优先确定性匹配可信问题执行，不确定降级候选澄清，**绝不猜测执行**。「文本一致 + 计划人工审核」是结果 100% 正确的机制保证。

#### 文件位置

`src/domain/question_library/models.py`（领域模型）+ `src/runtime/question_library/matcher.py`（匹配引擎）+ `src/runtime/question_library/service.py`（领域服务）+ 存储 `src/data_platform/storage/question_library/`（ports / in_memory / postgres / factory）+ API `src/runtime/api/question_library_routes.py` + portal `src/apps/portal/app/question-library/page.tsx`

#### 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 可信问题 | `TrustedQuestion` | **Aggregate Root** | Pydantic BaseModel | 聚合根：标准问题/同义/适用角色/指标/维度/时间口径/筛选/查询计划/允许下钻/预期结果/审核人/版本；`tq_` 前缀 ID |
| 可信问题草稿 | `TrustedQuestionDraft` | **Entity** | Pydantic BaseModel | 创建载荷；model_validator 校验 metadata 镜像 query_plan（object_code/metrics/group_by 三一致） |
| 可信问题状态 | `TrustedQuestionStatus` | **Value Object** | StrEnum | draft → published（审核通过 version+1 记审核人）/ archived（驳回或归档）；不可逆出 draft |
| 问题匹配引擎 | `QuestionMatcher` | **Domain Service** | 普通 class | 命中=归一化文本与标准问题或任一同义**完全相等**；否则 bigram Jaccard 澄清候选（≥0.35，最多 5 个） |
| 问题匹配结果 | `QuestionMatchOutcome` | **Value Object** | Pydantic BaseModel | hit（question + matched_text）/ clarify（candidates + resolved）；`QuestionMatchCandidate` 带 score |
| 问题匹配事件 | `QuestionMatchEvent` | **Entity** | Pydantic BaseModel | append-only 留痕：每次 match（hit/clarify）与 resolve（selected）；`qme_` 前缀 ID |
| 问题文本归一化 | `normalize_question_text` | — | 函数 | NFKC + 小写 + 剥 `[\W_]+`（标点/空白）；唯一性与命中判定统一口径 |
| 同义冲突异常 | `QuestionSynonymConflictError` | — | Exception | 新文本归一化后已被其他非归档问题占用，报持有 `question_id` |
| 可信问题存储端口 | `TrustedQuestionStorage` | **Port** | Protocol | insert/get/list/list_published/update(乐观锁)/list_texts/事件读写/计数 |
| 冷启动候选 | `ColdStartCandidate` | **Value Object** | Pydantic BaseModel | tasks 表 policy_qa 历史问法频次聚合，排除已被覆盖的归一化文本 |

#### 业务规则

1. **只有归一化完全相等才命中自动执行**（标准问题或任一同义）；模糊相似度再高也只产生澄清候选，由用户选择后执行——不确定不执行是硬约束。
2. 草稿创建时绑定查询计划必须经 `SemanticQueryPlanner` dry-run 校验可编译，metadata（object_code/metrics/dimensions）必须与 query_plan 一致，防止展示与执行两张皮。
3. 状态机：draft →（review approve）published（version+1、reviewer 记录）/ draft →（review reject 或 archive）archived；只有 published 可被匹配命中与执行。
4. 全库归一化文本唯一（跨非归档问题的标准问题与同义）：`list_texts` 建归一化→持有者索引，冲突即拒，保证匹配命中唯一不歧义。
5. 执行走存储的 query_plan **逐字**交给 `SemanticQueryService`（与结算问数同通道同数据源），并先按 `applies_to_roles` 角色门禁（空角色=全员）。
6. 每次匹配都落 `question_match_events`（含澄清时用户最终选择的 selected 事件），澄清事件在 portal 一键采纳为已发布问题的同义——「越问越准」闭环的数据底座。
7. 更新走乐观锁：`expected_revision` 比较-交换，存储将 revision 置 expected+1，过期即 `QuestionRevisionConflictError`（HTTP 409）。

---

### 14.12. 门诊运营分析（Ops Analytics）

> 依据：issue #40、docs/superpowers/plans/2026-08-27-outpatient-p0-data-contract.md Task 5、docs/reviews/2026-08-27-outpatient-data-contract-review.md（P3 冻结语义）。定位：六指标 × 五维度的受控问数仪表盘 + 行级下钻 + 周报运营指导；有界确定性聚合，结论可溯源到指标批次。

#### 文件位置

`src/domain/ops_analytics/models.py`（领域模型）+ `src/runtime/ops_analytics/service.py`（领域服务）+ API `src/runtime/api/ops_analytics_routes.py` + portal `src/apps/portal/app/ops-analytics/page.tsx`

#### 通用语言字典

| 英文命名 | 中文术语 | DDD 分类 | 说明 |
|---------|---------|---------|------|
| `OpsResultStatus` | 运营结果状态 | Value Object | `complete` / `partial` / `unavailable`，冻结契约三态 |
| `OpsMetricCard` | 指标卡 | Value Object | 单指标值 + result_status + halt_reason/halt_detail，值与不可用原因二选一 |
| `OpsOverview` | 指标总览 | Value Object | 六指标卡集合 + 数据范围 + 指标批次（data_batch_ids） |
| `OpsAnalyticsDimension` | 分析维度 | Value Object | `fund_type` / `cure_type` / `settle_state` / `department`（五维度中受支持的拆分键） |
| `OpsDimensionItem` | 维度拆分项 | Value Object | 码 + 中文标签 + 四指标值 + 笔数占比 |
| `OpsTrendPoint` | 月度趋势点 | Value Object | YYYY-MM 桶 + 四指标值 |
| `OpsDrillRow` | 就诊下钻行 | Value Object | T_TradeNo 粒度就诊明细，行携带 data_batch_id 指标批次溯源 |
| `OpsWeekDelta` | 周环比 | Value Object | 单指标本周/上周值 + delta/pct/direction；除零时 pct=None 不猜 |
| `OpsConclusion` | 周报结论 | Value Object | 文本 + citations（metric_definition 口径 / metric_batch 指标批次） |
| `OpsWeeklyReport` | 运营周报 | Value Object | 四指标环比 + 结论 + AI 摘要（可降级）+ uncertainties |
| `OpsAnalyticsService` | 门诊运营分析服务 | Domain Service | 有界确定性聚合；读取面 Protocol 注入（PostgreSQLClient 同形） |

#### 业务规则

1. **口径唯一真源**：聚合 WHERE 谓词逐字取自 `docs/processing/outpatient_processed_view.sql`（口径句 v4，已签核），服务不重新发明口径；活库冒烟与 `v_op_outpatient_processed` 四指标对账。
2. **诚实不可用**：就诊人次 / 次均费用 / 科室维度保持 `unavailable`（halt_reason=`data_unavailable`，HIS 就诊关联是 P1 必需输入、禁止跨源临时 JOIN），绝不估算；每个结果恰好一个 halt_reason。
3. **有界确定性**：只执行常量 SQL 模板 + 参数化过滤（维度列、日期、分页白名单），禁止任意 SQL 拼接；读取面经 Protocol 注入。
4. **结论可溯源**：所有结果携带 `data_batch_ids`（mz_trade.data_batch_id 指标批次）；周报每条结论的 citations 同时引用指标口径（metric_definition）与指标批次（metric_batch）。
5. **AI 摘要有界**：模型调用走 `ModelGateway` 统一入口（scene=`ops_weekly_summary`），prompt 仅含已计算数值结论并禁止引入未给出的数字；模型未配置或失败时诚实降级（summary=None + uncertainties），不返回假数据。

---


### 15. AI 编程工作流契约

#### 契约 1：先查后写

**规则**：生成任何后端代码（特别是 Domain 层代码）前，必须先读取本文件（`src/domain/AGENTS.md`）中的通用语言字典。

**具体约束**：
1. **命名校验**：新类/变量/方法名必须在本文档的"通用语言字典"中查证——如果已有定义，严格使用；如果无定义，说明是新概念，执行"同步更新"流程
2. **DDD 分类校验**：确认新模型应归为 Entity、Value Object、Aggregate Root 还是 Domain Service，并在代码中遵循对应的模式约定：
   - Aggregate Root：使用 `@dataclass(frozen=True)` + 持有子 Entity 的集合字段
   - Entity：使用 `@dataclass(frozen=True)`，有唯一标识字段
   - Value Object：使用 `@dataclass(frozen=True)`，无唯一标识，不可变
   - Domain Service：定义为无状态的 Protocol / Service 类
   - DTO：使用 Pydantic `BaseModel`（API 传输对象）
3. **边界校验**：确认新代码是否应归属于现有的限界上下文，还是需要创建新的上下文

#### 契约 2：同步更新

**规则**：当在开发中推导出新的业务概念时，必须主动更新本文档。

**触发条件**（满足任意一条即触发）：
1. 创建了新的 `src/domain/**/models.py` 文件或其中的模型类
2. 现有的领域模型增加了新字段，且涉及新的业务概念
3. 发现了现有代码中有未在本文档中记录的领域概念
4. 对现有业务概念的中英文命名做了调整
5. 识别出新的限界上下文或上下文间的新依赖关系

**更新步骤**：
1. 在本文档对应的限界上下文章节中新增或修改条目
2. 如果是全新上下文，在"限界上下文总览"中新增一节
3. 明确标注 DDD 战术分类（Entity / Value Object / Aggregate Root / Domain Service）
4. 简述业务规则和生命周期
5. 在 Git commit message 中注明 `docs(domain-glossary): 新增概念 xxx`

#### 契约 3：命名一致性

**规则**：领域概念的中文术语、英文命名和代码标识符必须三位一体。

```
中文术语（本文档）←→ 英文命名（本文档）←→ 代码标识符（.py / .ts）
```

- 代码中的 Python 类名 = 英文命名的 `PascalCase`（如 `InsuranceTransaction`）
- 代码中的 Python 变量名 = 英文命名的 `snake_case`（如 `settlement_status`）
- 代码中的 TypeScript 类型名 = 英文命名的 `PascalCase`
- 代码中的 API JSON 字段 = 英文命名的 `snake_case`
- 代码中的数据库列名 = 英文命名的 `snake_case`

**禁止以下行为**：
- ❌ 中文术语和英文命名不一致（如术语叫"患者"，英文命名用 `Customer`）
- ❌ 同一概念在代码中有多个不同命名（如有时叫 `patient`，有时叫 `person`）
- ❌ 英文命名与代码标识符大小写风格不一致

#### 契约 4：防腐层纪律

**规则**：所有外部系统交互必须通过 `adapters/ports/` 中定义的 Protocol 接口。

```
业务逻辑层 → Protocol 端口（Port）→ 适配器实现（Adapter）→ 外部系统
```

- 业务逻辑严禁直接依赖外部系统接口或数据格式
- 替换真实系统时只需实现对应 Protocol，无需修改业务逻辑
- 适配器统一返回 `AdapterCallResult`，通过 `DataQualityStatus` 支持降级

#### 契约 5：来源可追溯

**规则**：AI 输出必须携带来源引用或声明不确定性。

- 确定性结论：必须附带 `Citation`，指明 `source_type`、`source_id`、`summary`
- 不确定性结论：必须在 `uncertainties` 字段中明确声明
- 禁止无来源的确定性结论（如"根据系统分析，该问题..."）

---

### 附录 A：术语索引（按字母排序）

| 英文命名 | 中文术语 | 所属上下文 | DDD 分类 |
|---------|---------|-----------|---------|
| `AdapterCallResult` | 适配器调用结果 | Shared | DTO |
| `AppealCase` | 申诉案件 | Appeal | Aggregate Root |
| `AppealMaterial` | 申诉附件 | Appeal | Entity |
| `AppealTemplate` | 申诉模板 | Knowledge | Entity |
| `AuditEvent` | 审计事件 | Security / Shared | Value Object |
| `AuditResult` | 审核结果 | AuditRisk | Aggregate Root |
| `AuditService` | 审计服务 | Security | Domain Service |
| `BillingPort` | 收费系统适配器端口 | Insurance | Domain Service |
| `BusinessAction` | 业务动作 | Common | Value Object |
| `BusinessMemory` | 业务记忆 | Runtime | Entity |
| `BusinessObject` | 业务对象 | Common | Value Object |
| `ChatRequest` | Chat 请求 | Shared | DTO |
| `Citation` | 引用来源 | Shared / Knowledge | Value Object |
| `ClosureTask` | 闭环任务 | TaskClosure | Entity |
| `Coding` | 编码信息 | MedicalRecord | Value Object |
| `ColdStartCandidate` | 冷启动候选 | QuestionLibrary | Value Object |
| `CheckSpec` | 检查器注册项 | OpsHealth | Value Object |
| `CommonInputSpec` | 公共输入 | SkillTool | Value Object |
| `ComplianceScore` | 合规评分 | AuditRisk | Value Object |
| `ConflictDiagnosis` | 冲突诊断 | Knowledge | Value Object |
| `ConflictPartitionEvidence` | 冲突分区证据 | Knowledge | Value Object |
| `CompileRun` | 编译运行 | Knowledge | Aggregate Root |
| `CompileStep` | 编译步骤 | Knowledge | Entity |
| `Consumable` | 耗材 | OrderFee | Value Object |
| `CanonicalRule` | 规范规则 | Knowledge | Entity |
| `CatalogAsset` | 目录资产 | DataCatalog | DTO |
| `CatalogAssetDetail` | 资产详情 | DataCatalog | DTO |
| `CatalogAssetType` | 资产类型 | DataCatalog | Value Object |
| `CatalogConsumerInfo` | 消费方 | DataCatalog | DTO |
| `CatalogLineage` | 目录血缘 | DataCatalog | DTO |
| `CatalogService` | 数据目录服务 | DataCatalog | Domain Service |
| `CatalogSlaBoard` / `CatalogSourceSla` | SLA 看板 | DataCatalog | DTO |
| `CatalogSyncReader` | 目录同步读取面 | DataCatalog | Port |
| `ContextComposer` | 上下文编排器 | Runtime | Domain Service |
| `ContextNeed` | 上下文需求 | Runtime | Value Object |
| `ContextPlanner` | 上下文规划器 | Runtime | Domain Service |
| `DataQualityStatus` | 数据质量状态 | Shared | Value Object |
| `DataSupplyConnectionPort` | 数据供给连接端口 | Adapters | Port |
| `DenialRecord` | 拒付记录 | Appeal | Entity |
| `DesensitizationService` | 脱敏服务 | Security | Domain Service |
| `Diagnosis` | 诊断记录 | MedicalRecord | Entity |
| `DimensionCandidateProposal` | 维度候选提议 | Knowledge | Value Object |
| `DimensionReviewConclusion` | 维度建模结论 | Knowledge | Value Object |
| `DipGroupResult` | DIP 分组结果 | DrgDip | Value Object |
| `DrgDipPort` | DRG/DIP 适配器端口 | DrgDip | Domain Service |
| `DrgGroupResult` | DRG 分组结果 | DrgDip | Value Object |
| `Drug` | 药品 | OrderFee | Value Object |
| `EmrPort` | EMR 适配器端口 | MedicalRecord | Domain Service |
| `ExpirePolicy` | 过期策略 | Runtime | Value Object |
| `ErrorCodeEntry` | 错误码知识条目 | Knowledge | Entity |
| `ErrorDetail` | 错误详情 | Shared | DTO |
| `Evidence` | 证据材料 | Appeal | Entity |
| `ExecutionProfileSpec` | 执行场景 | SkillTool | Value Object |
| `FeeItem` | 费用明细 | OrderFee | Entity |
| `FailureAttribution` | 评测失败归因 | SkillTool | Value Object |
| `FindingDraft` | 问题草稿 | OpsHealth | Value Object |
| `FlowDefinition` | 治理数据流 | GovernedFlow | Aggregate Root |
| `FlowEdge` | 流边 | GovernedFlow | Value Object |
| `FlowFilterCondition` | 过滤条件 | GovernedFlow | Value Object |
| `FlowNode` | 流节点 | GovernedFlow | Entity |
| `FlowPublishedRevision` | 流发布修订 | GovernedFlow | Entity |
| `FlowStatus` | 流状态 | GovernedFlow | Value Object |
| `GovernanceStatusReader` | 检查器读取面 | OpsHealth | Port |
| `HisPort` | HIS 适配器端口 | Patient | Domain Service |
| `Hypothesis` | 推理假设 | Runtime | Entity |
| `InsuranceInterfacePort` | 医保接口适配器端口 | Insurance | Domain Service |
| `InsuranceTransaction` | 医保交易 | Insurance | Entity |
| `IntentResult` | 意图识别结果 | Runtime | DTO |
| `KnowledgeAsset` | 知识资产 | Knowledge | Entity |
| `KnowledgeChunk` | 知识切片 | Knowledge | Entity |
| `KnowledgeEnhancementService` | 知识扩展服务 | Knowledge | Domain Service |
| `KnowledgeExtensionStatus` | 知识扩展状态 | Knowledge | Value Object |
| `LLMContext` | LLM 上下文 | Runtime | DTO |
| `MetricInputSpec` | 业务指标输入 | SkillTool | Value Object |
| `MetricOutputBinding` | 指标输出绑定 | GovernedFlow | Value Object |
| `McpCapability` | MCP 能力 | SkillTool | Entity |
| `McpRiskLevel` | MCP 风险等级 | SkillTool | Value Object |
| `McpServer` | MCP 服务器 | SkillTool | Entity |
| `McpTransportType` | MCP 传输类型 | SkillTool | Value Object |
| `MedicalRecordHomepage` | 病案首页 | MedicalRecord | Aggregate Root |
| `UnitMedTypeOverride` | 单元医疗类别人工修正 | Knowledge | Entity |
| `med_type_classifier` | 单元医疗类别分类器 | Knowledge | Domain Service |
| `MedicalRecordPort` | 病案适配器端口 | MedicalRecord | Domain Service |
| `MemoryManager` | 记忆管理器 | Runtime | Domain Service |
| `MemoryStore` | 记忆存储端口 | Runtime | Domain Service |
| `MemoryType` | 记忆类型 | Runtime | Value Object |
| `ModelGateway` | 模型网关 | ModelService | Domain Service |
| `ModelRequest` | 模型请求 | ModelService | DTO |
| `ModelResponse` | 模型响应 | ModelService | DTO |
| `OpsAssetType` | 受检资产类型 | OpsHealth | Value Object |
| `OpsFinding` | 资产健康问题 | OpsHealth | Aggregate Root |
| `OpsFindingDetail` | 问题详情 | OpsHealth | DTO |
| `OpsFindingEvent` | 生命周期事件 | OpsHealth | Entity |
| `OpsFindingEventType` | 事件类型 | OpsHealth | Value Object |
| `OpsFindingPage` | 问题分页结果 | OpsHealth | DTO |
| `OpsFindingStatus` | 问题状态 | OpsHealth | Value Object |
| `OpsDiagnosisReport` | 诊断报告 | OpsHealth | DTO |
| `OpsDiagnosisResult` | 诊断结果 | OpsHealth | DTO |
| `OpsDiagnosisService` | 智能诊断服务 | OpsHealth | Domain Service |
| `DiagnosisStatus` | 诊断结论状态 | OpsHealth | Value Object |
| `DiagnosisActionLevel` | 诊断建议分级 | OpsHealth | Value Object |
| `DiagnosisCitation` | 诊断证据引用 | OpsHealth | Value Object |
| `DiagnosisAction` | 诊断建议动作 | OpsHealth | Value Object |
| `DiagnosisUnavailableError` | 诊断不可用异常 | OpsHealth | 异常 |
| `OpsHealthService` | 健康运营巡检服务 | OpsHealth | Domain Service |
| `OpsInspectionRun` | 巡检运行 | OpsHealth | Entity |
| `OpsInspectionScheduleState` | 巡检调度状态 | OpsHealth | DTO |
| `OpsInspectionStatus` | 巡检状态 | OpsHealth | Value Object |
| `OpsInspectionSummary` | 巡检摘要 | OpsHealth | DTO |
| `OpsInspectionScheduler` | 巡检调度器 | OpsHealth | Domain Service |
| `OpsInspectionTrigger` | 巡检触发方式 | OpsHealth | Value Object |
| `OpsCheckerError` | 检查器错误 | OpsHealth | Value Object |
| `InspectionInProgressError` | 巡检进行中异常 | OpsHealth | 异常 |
| `OpsInspectionResult` | 巡检结果 | OpsHealth | DTO |
| `OpsRemediationRun` | 修复运行 | OpsHealth | Entity |
| `OpsSeverity` | 问题严重度 | OpsHealth | Value Object |
| `OpsAnalyticsDimension` | 分析维度 | OpsAnalytics | Value Object |
| `OpsAnalyticsService` | 门诊运营分析服务 | OpsAnalytics | Domain Service |
| `OpsConclusion` | 周报结论 | OpsAnalytics | Value Object |
| `OpsDimensionItem` | 维度拆分项 | OpsAnalytics | Value Object |
| `OpsDrillRow` | 就诊下钻行 | OpsAnalytics | Value Object |
| `OpsMetricCard` | 指标卡 | OpsAnalytics | Value Object |
| `OpsOverview` | 指标总览 | OpsAnalytics | Value Object |
| `OpsResultStatus` | 运营结果状态 | OpsAnalytics | Value Object |
| `OpsTrendPoint` | 月度趋势点 | OpsAnalytics | Value Object |
| `OpsWeekDelta` | 周环比 | OpsAnalytics | Value Object |
| `OpsWeeklyReport` | 运营周报 | OpsAnalytics | Value Object |
| `Order` | 医嘱 | OrderFee | Aggregate Root |
| `OutpatientPartialPreRefundAnalysis` | 门诊部分项目预退费分析 | Insurance | Domain Service |
| `Patient` | 患者 | Patient | Entity |
| `PaymentRate` | 支付费率 | DrgDip | Value Object |
| `PartialRefundItemRequest` | 拟退项目 | Insurance | Value Object |
| `PartialRefundPreview` | 预结算结果 | Insurance | Value Object |
| `PolicyExpression` | 政策表达式 | Knowledge | Value Object |
| `PolicyCarrier` | 政策载体 | GovernedFlow | Value Object |
| `PolicyRuleReader` | 政策规则读取面 | SemanticLayer | Port |
| `PgPolicyRuleReader` | PG 政策规则读取器 | SemanticLayer | Adapter |
| `PolicyFact` | 政策事实 | Knowledge | Value Object |
| `PreAuditPort` | 事前审核适配器端口 | AuditRisk | Domain Service |
| `ProfitLoss` | 盈亏分析 | DrgDip | Value Object |
| `PromptTemplate` | 提示模板 | Knowledge | Entity |
| `QuestionMatchCandidate` | 问题匹配候选 | QuestionLibrary | Value Object |
| `QuestionMatchEvent` | 问题匹配事件 | QuestionLibrary | Entity |
| `QuestionMatcher` | 问题匹配引擎 | QuestionLibrary | Domain Service |
| `QuestionMatchOutcome` | 问题匹配结果 | QuestionLibrary | Value Object |
| `QuestionSynonymConflictError` | 同义冲突异常 | QuestionLibrary | Exception |
| `RAGPipeline` | RAG 管线 | Knowledge | Domain Service |
| `ReasoningState` | 推理状态 | Runtime | Entity |
| `ReasoningStateManager` | 推理状态管理器 | Runtime | Domain Service |
| `ReasoningStep` | 推理步骤 | Runtime | Entity |
| `ReasoningStep.kind` | 推理步骤类型 | Runtime | Value Object |
| `RemediationActionOutcome` | 修复动作执行结果 | OpsHealth | DTO |
| `RemediationExecutor` | 修复执行器 | OpsHealth | Port |
| `RemediationRiskLevel` | 修复风险级 | OpsHealth | Value Object |
| `RemediationRunStatus` | 修复运行状态 | OpsHealth | Value Object |
| `RemediationSpec` | 修复白名单项 | OpsHealth | Value Object |
| `RiskControlService` | 风控服务 | Security | Domain Service |
| `RiskFlag` | 风险标记 | AuditRisk | Entity |
| `Role` | 角色 | Shared | Value Object |
| `RuleExplanation` | 规则解释 | Knowledge | Entity |
| `RuleHit` | 规则命中 | AuditRisk | Value Object |
| `RuntimeTask` | 运行时任务 | Shared | DTO |
| `SqlServerDirectSupplyAdapter` | SQL Server 直连供给适配器 | Adapters | Adapter |
| `SourceContract` | 来源契约 | GovernedFlow | Value Object |
| `Skill` | 技能 | SkillTool | Aggregate Root |
| `SkillAIGenerationResponse` | AI 生成提案 | SkillTool | DTO |
| `SkillCandidateArtifact` | Skill 候选制品 | SkillTool | Value Object |
| `SkillDraft(source_type=AI_GENERATED)` | AI 草稿 | SkillTool | Entity |
| `SkillExecutionEngine` | 技能执行引擎 | SkillTool | Domain Service |
| `SkillExecutionContract` | 技能执行契约 | SkillTool | Value Object |
| `SkillEvalSuite` | 技能测评集 | SkillTool | Entity |
| `SkillEvalTask` | 技能评测任务 | SkillTool | Entity |
| `SkillEvalDataLocator` | 评测数据定位 | SkillTool | Value Object |
| `SkillEvalEnvironmentRequirement` | 评测环境要求 | SkillTool | Value Object |
| `SkillEvalDatasetVersion` | 技能评测数据集版本 | SkillTool | Aggregate Root |
| `SkillEvalBenchmark` | 技能评测基准 | SkillTool | Aggregate Root |
| `SkillGovernancePriority` | 技能治理优先级 | SkillTool | Value Object |
| `SkillGovernanceStage` | 技能治理阶段 | SkillTool | Value Object |
| `SkillMetadata` | 技能元数据 | SkillTool | Value Object |
| `SkillNextAction` | 技能下一步动作 | SkillTool | Value Object |
| `SkillStep` | 技能步骤 | SkillTool | Entity |
| `StreamChunk` | 流式块 | ModelService | DTO |
| `Surgery` | 手术记录 | MedicalRecord | Entity |
| `TaskConfirmRequest` | 任务确认请求 | TaskClosure | DTO |
| `TokenUsage` | Token 用量 | ModelService | Value Object |
| `ToolOwner` | 技能拥有者 | SkillTool | Value Object |
| `TrajectoryPrefix` | 评测轨迹接力点 | SkillTool | Value Object |
| `Treatment` | 诊疗项目 | OrderFee | Value Object |
| `TrustedQuestion` | 可信问题 | QuestionLibrary | Aggregate Root |
| `TrustedQuestionDraft` | 可信问题草稿 | QuestionLibrary | Entity |
| `TrustedQuestionStatus` | 可信问题状态 | QuestionLibrary | Value Object |
| `TrustedQuestionStorage` | 可信问题存储端口 | QuestionLibrary | Port |
| `VerificationResult` | 验证结果 | OpsHealth | Value Object |
| `VisibilityScope` | 可见性范围 | Knowledge | Value Object |
| `ValidationIssue` | 校验问题 | Knowledge | Value Object |

---

### 附录 B：DDD 模式速查

| DDD 模式 | 代码规范 | 可变性 | 唯一标识 | 典型用途 |
|---------|---------|--------|---------|---------|
| **Aggregate Root** | `@dataclass(frozen=True)` 或 `BaseModel` | 不可变 | 有 (aggregate_id) | Order, MedicalRecordHomepage, AppealCase, Skill, AuditResult |
| **Entity** | `@dataclass(frozen=True)` | 不可变 | 有 (entity_id) | Patient, InsuranceTransaction, RiskFlag, Diagnosis |
| **Value Object** | `@dataclass(frozen=True)` | 不可变 | **无** | Drug, ComplianceScore, Citation, Role |
| **Domain Service (接口)** | `Protocol` | 无状态 | 不适用 | PreAuditPort, HisPort, ModelGateway |
| **Domain Service (实现)** | 普通 class | 无状态 | 不适用 | SkillExecutionEngine, RAGPipeline |
| **DTO / 请求响应** | Pydantic `BaseModel` | 可变 | 视情况 | ChatRequest, AgentResponse, AdapterCallResult |
| **可变的 Entity** | `@dataclass` (无 frozen) | **可变** | 有 | ClosureTask（状态会流转） |

---

*本文档将随项目演进持续更新。发现遗漏或命名不一致，请及时补充。*
