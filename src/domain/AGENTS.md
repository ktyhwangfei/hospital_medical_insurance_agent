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
14. [共享通用层（Shared / Common）](#14-共享通用层-shared--common)
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
| 发现证据 | `DiscoveryEvidence` | **Value Object** | Pydantic `BaseModel` | 可追溯到政策文档、单元与提取记录的结构化证据；同一来源重复观测需幂等合并 |
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

#### 业务规则

- AI 输出必须携带 `citations` 来源引用，或声明 `uncertainties` — 禁止无来源的确定性结论
- 错误码知识库支持 PostgreSQL 和内存两种存储，通过配置切换
- 知识资产使用 `VisibilityScope` 控制可见性（角色 + 租户 + 院区）
- `Citation` 在 `src/domain/common/models.py` 和 `src/knowledge_extension/common/models.py` 各有一份，需要注意区分
- 结构化字段与政策 Knowledge 字段是两类权威来源，通过 `MetricSourceBinding` 多对一汇聚到同一标准指标；不得分别建立平行指标体系
- 新指标、来源值映射和标准值提案默认均为 `draft`，只有语义层独立审核动作可以发布
- 一条规范规则必须由 `subject + conditions + result + evidence` 独立表达完整业务语义；规则主体细化不得自动扩张语义层指标，比例结果仍复用基础 `payment_ratio`

#### 生命周期

```
用户提问/系统触发 → KnowledgeEnhancementService
    → RAGPipeline（检索 + 重排）
    → 错误码知识 / 规则解释 / 提示模板
    → 结果 + Citation 引用 → AgentResponse
```

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
| `CommonInputSpec` | 公共输入 | SkillTool | Value Object |
| `ComplianceScore` | 合规评分 | AuditRisk | Value Object |
| `ConflictDiagnosis` | 冲突诊断 | Knowledge | Value Object |
| `ConflictPartitionEvidence` | 冲突分区证据 | Knowledge | Value Object |
| `CompileRun` | 编译运行 | Knowledge | Aggregate Root |
| `CompileStep` | 编译步骤 | Knowledge | Entity |
| `Consumable` | 耗材 | OrderFee | Value Object |
| `CanonicalRule` | 规范规则 | Knowledge | Entity |
| `ContextComposer` | 上下文编排器 | Runtime | Domain Service |
| `ContextNeed` | 上下文需求 | Runtime | Value Object |
| `ContextPlanner` | 上下文规划器 | Runtime | Domain Service |
| `DataQualityStatus` | 数据质量状态 | Shared | Value Object |
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
| `Order` | 医嘱 | OrderFee | Aggregate Root |
| `Patient` | 患者 | Patient | Entity |
| `PaymentRate` | 支付费率 | DrgDip | Value Object |
| `PolicyExpression` | 政策表达式 | Knowledge | Value Object |
| `PolicyFact` | 政策事实 | Knowledge | Value Object |
| `PreAuditPort` | 事前审核适配器端口 | AuditRisk | Domain Service |
| `ProfitLoss` | 盈亏分析 | DrgDip | Value Object |
| `PromptTemplate` | 提示模板 | Knowledge | Entity |
| `RAGPipeline` | RAG 管线 | Knowledge | Domain Service |
| `ReasoningState` | 推理状态 | Runtime | Entity |
| `ReasoningStateManager` | 推理状态管理器 | Runtime | Domain Service |
| `ReasoningStep` | 推理步骤 | Runtime | Entity |
| `ReasoningStep.kind` | 推理步骤类型 | Runtime | Value Object |
| `RiskControlService` | 风控服务 | Security | Domain Service |
| `RiskFlag` | 风险标记 | AuditRisk | Entity |
| `Role` | 角色 | Shared | Value Object |
| `RuleExplanation` | 规则解释 | Knowledge | Entity |
| `RuleHit` | 规则命中 | AuditRisk | Value Object |
| `RuntimeTask` | 运行时任务 | Shared | DTO |
| `Skill` | 技能 | SkillTool | Aggregate Root |
| `SkillAIGenerationResponse` | AI 生成提案 | SkillTool | DTO |
| `SkillCandidateArtifact` | Skill 候选制品 | SkillTool | Value Object |
| `SkillDraft(source_type=AI_GENERATED)` | AI 草稿 | SkillTool | Entity |
| `SkillExecutionEngine` | 技能执行引擎 | SkillTool | Domain Service |
| `SkillExecutionContract` | 技能执行契约 | SkillTool | Value Object |
| `SkillEvalSuite` | 技能测评集 | SkillTool | Entity |
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
| `Treatment` | 诊疗项目 | OrderFee | Value Object |
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
