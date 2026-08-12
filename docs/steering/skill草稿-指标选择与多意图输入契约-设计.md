# Skill 草稿第三步：执行契约 + 指标依赖选择器设计规范

> **状态：设计定稿版**  
> **适用范围：** `/skills/new` 第三步「输入输出契约」改造、`structured_config` 扩展、后端契约校验、AI 辅助配置、Skill 编辑器复用  
> **关联设计：** `docs/superpowers/specs/[2026-08-06-skill-management-workbench-design.md](http://2026-08-06-skill-management-workbench-design.md)` §5  
> **核心原则：** Skill 的数据依赖必须显式、可验证、可治理；AI 只能在运行时可获取的数据集合中推荐，不允许通过自由文本构造不存在或不可执行的输入指标。

---

# 1. 背景

当前 `/skills/new` 第三步主要用于配置 Skill 输入输出契约，但现状存在两个核心问题。

## 1.1 输入指标不可治理

当前页面通过自由文本输入：

```text
inputMetrics = "metric_a, metric_b, metric_c"

```

存在以下问题：

- 用户可以填写不存在的 `metric_code`；
- 可以填写尚未发布的指标；
- 可以填写没有查询实现的指标；
- 无法确认指标来自哪个业务对象；
- 无法确认指标运行时能否真正取到；
- AI 推荐与人工配置使用的合法指标集合不一致；
- 当前 `submit()` 甚至未完整提交 inputs。

这导致：

> Skill 声明了输入，不代表 Runtime 真正可以获取这些输入。

---

## 1.2 Skill 不同执行场景需要不同数据

一个 Skill 内可能包含多个高度相关的业务执行场景。

例如：

```text
医保结算费用解释 Skill
├── 起付线解释
├── 统筹自付解释
├── 大额自付解释
└── 目录外费用解释

```

这些场景：

- 属于同一个业务能力；
- 使用相似执行流程；
- 输出结构基本一致；

但所依赖的数据并不完全相同。

例如：

```text
起付线解释
→ 需要起付金额、人员类别、医院等级、住院次数

统筹自付解释
→ 需要统筹自付金额、医保范围内费用、支付比例

大额自付解释
→ 需要大额自付金额、大额基金支付金额

```

如果全部平铺在：

```text
structured_config.inputs

```

会导致：

- 每次 Skill 执行都获取所有指标；
- 输入规模越来越大；
- Prompt 上下文膨胀；
- SQL 查询复杂；
- Skill 内各场景的数据依赖关系不可见；
- 后续无法判断某个指标究竟服务哪个执行逻辑。

因此需要引入：

# Skill Execution Contract

即：

> 明确定义 Skill 在不同执行场景下需要什么上下文和什么数据依赖。

---

# 2. 设计目标

本次改造实现以下目标。

## 2.1 输入不再允许自由填写 metric_code

所有 Metric Input 必须来自：

```text
Semantic Layer

```

且必须满足：

```text
当前可运行时解析 Runtime Resolvable

```

---

## 2.2 不再把所有输入平铺在 Skill 一级

支持：

```text
公共输入
+
不同执行场景专属输入

```

运行时只获取：

```text
公共输入
∪
当前执行场景所需输入

```

---

## 2.3 区分不同性质的输入

不再默认：

```text
Skill Input = Metric

```

至少区分：

```text
Runtime Context
Metric Dependency
Knowledge Dependency

```

第一阶段主要正式建模：

```text
Context Input
Metric Input

```

知识依赖暂由现有 Policy / Knowledge 配置体系承载，不混入指标输入契约。

---

## 2.4 AI 只能推荐合法依赖

AI 不应该看到：

```text
未发布指标
不可查询指标
没有 Resolver 的指标

```

推荐集合必须由后端提前过滤。

原则：

> 能通过数据边界限制的问题，不依赖 Prompt 约束。

---

## 2.5 输入契约成为唯一真相

输入定义不能同时存在：

```text
InputSpec
JSON Schema
Prompt 文本
代码默认值

```

多套互相可能不一致的真相。

因此：

> Input Contract 是 Skill 输入定义的唯一 Source of Truth。

运行时 JSON Schema 自动从 Input Contract 派生。

---

# 3. 术语定义

本方案不继续使用“Intent + Input Profile”作为核心模型。

原因是系统内已有：

```text
supported_intents
business_action
keywords

```

且现有 `supported_intents` 实际接近路由关键词，语义已经存在历史债务。

因此正式采用以下术语。

---

# 4. Skill Execution Contract

中文：

# Skill 执行契约

定义：

> 描述 Skill 在运行期间需要哪些上下文、指标依赖，以及不同执行场景之间数据依赖差异的结构化契约。

整体结构：

```text
SkillExecutionContract
│
├── Common Inputs
│   ├── Context Inputs
│   └── Metric Inputs
│
├── Execution Profiles
│   ├── Profile A
│   │   ├── Routing Hints
│   │   ├── Context Inputs
│   │   └── Metric Inputs
│   │
│   └── Profile B
│
└── Output Contract

```

---

# 5. Execution Profile

后台专业名：

```text
ExecutionProfile

```

中文产品名称：

# 执行场景

定义：

> 同一个 Skill 内，在核心业务能力和主要执行流程不变的情况下，由于用户问题或执行目标不同，而产生的一种运行配置。

例如：

```text
Skill：医保结算费用解释

ExecutionProfile：
- 起付线解释
- 统筹自付解释
- 大额自付解释

```

Execution Profile 不是独立 Skill，也不是纯用户意图。

其核心职责是：

> 定义当前执行路径需要哪些特定数据依赖。

---

# 6. Execution Profile 与 Skill 的边界

必须明确防止：

```text
一个 Skill 无限增加 Profile

```

最终成为“大 Skill”。

判断规则：

> 如果只是“需要哪些数据不同”，优先使用 Execution Profile。

> 如果“要完成的业务能力本身已经不同”，应拆分成不同 Skill。

---

## 6.1 适合放在同一个 Skill

例如：

```text
医保费用解释 Skill

├── 起付线解释
├── 统筹自付解释
├── 大额自付解释
└── 目录外费用解释

```

因为它们：

- 都属于医保费用解释；
- 主要执行流程一致；
- 输出结构相似；
- 差异主要在输入指标。

---

## 6.2 应拆成不同 Skill

例如：

```text
起付线解释
异地备案资格判断
慢特病申请流程

```

虽然都属于医保业务，但：

- 业务目标不同；
- 工具不同；
- 数据依赖不同；
- Policy 检索方式不同；
- 输出结构不同。

因此不应只是三个 Execution Profile。

---

# 7. 输入类型设计

本次必须区分：

```text
Context Input
Metric Input

```

未来预留：

```text
Knowledge Requirement
Tool Requirement

```

但暂不全部放进本次范围。

---

# 8. Context Input

Context Input 表示：

> Runtime 已知、用户传入、会话产生或上游 Skill 提供的运行上下文。

例如：

```text
question
settlement_id
patient_id
visit_id
hospital_id

```

这些字段不一定属于“指标”。

例如：

```text
settlement_id

```

它的主要用途是：

> 查询定位键。

不应该为了方便统一而人为建成 Metric。

---

# 9. Metric Input

Metric Input 表示：

> Skill 执行时需要从语义层解析并获取的业务指标。

例如：

```text
deductible_amount
fund_payment_amount
personal_payment_amount
inside_insurance_amount

```

它必须来自 Metric Registry。

并且必须满足：

```text
runtime_resolvable = true

```

---

# 10. Knowledge Requirement

例如：

```text
适用政策
政策依据
医保目录规则
待遇规则

```

不属于 Metric Input。

它们应由：

```text
Policy Search
Knowledge Search
Canonical Policy Rule

```

等知识系统提供。

因此原方案中的：

```text
适用政策规则与来源 → Base Inputs

```

正式删除。

原则：

> 数据输入和知识依赖不能混成一个 inputs 数组。

---

# 11. “可选指标”的统一定义

原方案：

```text
status == published
AND
source_field != null OR default_value != null

```

不再作为前端业务规则。

真正业务定义：

# Runtime Resolvable Metric

即：

> 当前 Runtime 能够为该 Metric 生成合法的数据获取计划。

---

# 12. runtime_resolvable

建议由后端统一计算。

示例：

```json
{
  "metric_code": "Settlement.deductible_amount",
  "status": "published",

  "runtime_resolvable": true,

  "resolution_type": "source_field",

  "unavailable_reason": null
}

```

不可用：

```json
{
  "metric_code": "Policy.external_rule",

  "status": "published",

  "runtime_resolvable": false,

  "resolution_type": null,

  "unavailable_reason": "NO_RUNTIME_RESOLVER"
}

```

---

# 13. 为什么不用 source_type 直接判断

现在的实现可能只有：

```text
source_field
default_value
policy_or_external

```

未来可能增加：

```text
SQL Expression
Derived Metric
Formula Resolver
API Resolver
Tool Resolver
Aggregation Resolver
Materialized Metric

```

因此 UI 不应写：

```typescript
source_type !== "policy_or_external"

```

而只应该消费：

```text
runtime_resolvable

```

---

# 14. runtime_resolvable 判定职责

由后端：

```text
SkillInputService
或
MetricRuntimeCapabilityService

```

统一判断。

前端、AI Authoring、Draft Validator、Runtime 统一复用同一结果。

禁止四套规则：

```text
前端判断一遍
AI prompt 判断一遍
validator 判断一遍
runtime 再判断一遍

```

---

# 15. Metric Resolution Type

建议返回：

```text
SOURCE_FIELD
DEFAULT_VALUE
SQL_EXPRESSION
DERIVED
API
TOOL
UNKNOWN

```

V1 实际支持：

```text
SOURCE_FIELD
DEFAULT_VALUE

```

但模型提前预留扩展。

---

# 16. structured_config 版本设计

不直接重定义旧：

```text
structured_config.inputs

```

的语义。

新版本正式引入：

```text
structured_config.execution_contract

```

或：

```text
structured_config.input_contract

```

推荐统一叫：

# execution_contract

因为未来除了 Input，还可能承载：

```text
routing
outputs
tools
knowledge
validation

```

---

# 17. 推荐结构

```json
{
  "basic": {
    "skill_id": "...",
    "skill_name": "...",
    "description": "...",
    "owner": "..."
  },

  "business_mounting": {
    "business_action": "explain",
    "business_object": "settlement",
    "keywords": []
  },

  "execution_contract": {
    "version": 2,

    "common": {
      "context_inputs": [],
      "metric_inputs": []
    },

    "profiles": []
  },

  "schemas": {
    "output": {}
  }
}

```

---

# 18. Execution Contract 示例

```json
{
  "execution_contract": {
    "version": 2,

    "common": {
      "context_inputs": [
        {
          "code": "settlement_id",
          "alias": "结算标识",
          "required": true,
          "purpose": "定位本次医保结算"
        }
      ],

      "metric_inputs": [
        {
          "metric_code": "Settlement.person_type",
          "alias": "人员类别",
          "required": true,
          "purpose": "确定待遇适用人群"
        }
      ]
    },

    "profiles": [
      {
        "profile_id": "deductible-explanation",
        "name": "起付线解释",

        "purpose": "解释本次医保结算起付线金额及来源",

        "routing_hints": [
          "起付线",
          "门槛费",
          "为什么扣650"
        ],

        "context_inputs": [],

        "metric_inputs": [
          {
            "metric_code": "zcgz.deductible_amount",
            "alias": "政策起付金额",
            "required": true,
            "purpose": "获取适用待遇标准中的起付金额"
          },

          {
            "metric_code": "zydyxx.bcqfje",
            "alias": "本次起付金额",
            "required": true,
            "purpose": "获取本次结算实际使用的起付金额"
          }
        ]
      },

      {
        "profile_id": "copayment-explanation",

        "name": "统筹自付解释",

        "purpose": "解释本次统筹自付金额形成原因",

        "routing_hints": [
          "统筹自付",
          "为什么自付这么多"
        ],

        "metric_inputs": [
          {
            "metric_code": "zyfdxx.bdtczf",
            "alias": "统筹自付金额",
            "required": true,
            "purpose": "获取本次统筹自付金额"
          }
        ]
      }
    ]
  }
}

```

---

# 19. ContextInputSpec

建议模型：

```text
ContextInputSpec

```

字段：

```text
code
alias
required
purpose
description

```

其中：

```text
code

```

必须来自 Runtime Context Registry 或固定上下文枚举，而不是任意自由文本。

第一阶段可支持：

```text
question
settlement_id
person_id
visit_id
hospital_id

```

---

# 20. MetricInputSpec

现有 `InputSpec` 建议改名为：

```text
MetricInputSpec

```

或保留旧类做兼容，新模型内部使用更明确的名字。

字段：

```text
metric_code
alias
required
purpose

```

可选扩展：

```text
query_role
fallback_policy

```

V1 暂不增加。

---

# 21. ExecutionProfileSpec

建议：

```text
ExecutionProfileSpec

```

字段：

```text
profile_id
name
purpose
routing_hints
context_inputs
metric_inputs

```

---

# 22. profile_id 规范

建议：

```text
kebab-case

```

例如：

```text
deductible-explanation
copayment-explanation
out-of-pocket-explanation

```

要求：

- Skill 内唯一；
- 不可为空；
- 发布后原则上不自动修改；
- 显示名称 `name` 可以修改。

---

# 23. Routing Hints

不使用：

```text
routing_triggers

```

改用：

```text
routing_hints

```

因为这些词只是：

> 路由辅助线索。

不是决定性规则。

例如：

```json
{
  "routing_hints": [
    "起付线",
    "门槛费",
    "为什么扣650"
  ]
}

```

Runtime 最终选择 Execution Profile 可以综合：

```text
用户问题
routing_hints
Business Action
LLM Router
上下文

```

不能只通过字符串 contains 决定。

---

# 24. supported_intents 的处理

现有：

```text
supported_intents

```

本质上由关键词生成，已经有历史语义债务。

V1 不继续扩展其业务含义。

兼容策略：

```text
business_mounting.keywords
execution_contract.profiles[].routing_hints

```

可继续聚合生成旧：

```text
supported_intents

```

供现有 Package 使用。

但新代码禁止依赖：

```text
supported_intents

```

表达执行场景。

未来单独做 Legacy Deprecation。

---

# 25. Common Inputs

Common Inputs 表示：

> 几乎每个 Execution Profile 都需要的数据依赖。

必须克制使用。

不能因为某指标：

```text
很重要

```

就放入 Common。

应该满足：

```text
绝大多数执行场景都需要
AND
获取成本合理

```

---

# 26. Common Input 反例

例如：

```text
费用总金额
范围内金额
范围外金额
基金支付
个人账户
现金支付

```

虽然这些都是核心结算指标，但并不代表：

```text
每个解释场景都必须查询

```

如果全部放 Common：

```text
common ∪ profile

```

很快导致每次执行都拉大量数据。

从而失去 Execution Profile 的意义。

---

# 27. Common Inputs 推荐原则

优先放：

```text
查询定位键
核心上下文
低成本且几乎必需的语义字段

```

例如：

```text
settlement_id

```

至于：

```text
person_type
service_type
hospital_level

```

是否 Common，应由具体 Skill 决定。

---

# 28. 运行时有效输入

命中某个 Profile 后：

```text
Effective Inputs
=
Common Inputs
∪
Matched Profile Inputs

```

分别计算：

```text
Effective Context Inputs
Effective Metric Inputs

```

例如：

```text
起付线解释

```

最终只查询：

```text
settlement_id
person_type
deductible_amount
actual_deductible_amount

```

而不是把整个 Skill 所有指标都拉下来。

---

# 29. Input Schema 设计

不再人工维护：

```text
schemas.input

```

作为独立 Source of Truth。

因为容易产生：

```text
execution_contract 里定义 A/B/C
schemas.input 里定义 A/B/D

```

---

# 30. Input Schema 自动生成

Runtime 根据：

```text
Common
+
Matched Execution Profile

```

自动生成：

```text
EffectiveInputSchema

```

因此：

```text
execution_contract

```

成为输入唯一真相。

---

# 31. Output Schema

V1 继续保持：

```text
Skill 级 Output Contract

```

原因：

如果不同 Profile 的输出结构完全不同，需要优先判断：

> 是否实际上应该拆成不同 Skill。

因此第一阶段不引入：

```text
Profile-specific Output Schema

```

未来有明确需求后再扩展。

---

# 32. 输出契约建议

建议保持：

```text
schemas.output

```

或未来升级：

```text
execution_contract.output_contract

```

第一阶段可以先兼容现有结构。

---

# 33. 指标选择器设计

第三步不再提供：

```text
逗号分隔自由文本框

```

改为：

# Metric Dependency Selector

核心能力：

```text
搜索
筛选
浏览
选择
查看可用状态
查看指标来源
配置 required / alias / purpose

```

---

# 34. Metric Selector 后端返回

建议统一结构：

```json
{
  "business_domain": "医保结算",

  "objects": [
    {
      "object_code": "Settlement",
      "object_name": "结算",

      "current_version": "v1",

      "metrics": [
        {
          "metric_code": "Settlement.deductible_amount",
          "metric_name": "起付金额",

          "status": "published",

          "runtime_resolvable": true,

          "resolution_type": "SOURCE_FIELD",

          "unavailable_reason": null
        }
      ]
    }
  ]
}

```

---

# 35. Metric Selector 可选条件

UI 不自己判断。

唯一规则：

```text
runtime_resolvable == true

```

并且后端已经隐含保证：

```text
published
+
object active/published
+
resolver valid

```

---

# 36. 不可选指标展示策略

最终决策：

> 默认隐藏不可选指标。

页面增加：

```text
[ ] 显示不可用指标

```

开启后：

- 不可选指标置灰；
- 显示原因；
- 允许查看；
- 不允许添加。

例如：

```text
医保政策原文
未配置运行时解析器
暂不可作为 Skill Metric Input

```

这样同时兼顾：

```text
界面整洁
+
治理教育

```

---

# 37. 不可用原因标准化

建议：

```text
NOT_PUBLISHED
OBJECT_NOT_PUBLISHED
NO_RUNTIME_RESOLVER
INVALID_MAPPING
RESOLVER_DISABLED
VERSION_UNAVAILABLE

```

前端根据 code 显示中文说明。

不要只返回一段自由文本。

---

# 38. AI 推荐机制

按钮：

```text
AI 推荐输入依赖

```

或：

```text
AI 推荐当前执行场景

```

AI 只收到：

```text
runtime_resolvable=true

```

的指标集合。

禁止把不可选指标发给 AI，再靠 Prompt 说：

> 不要推荐。

---

# 39. AI 输入

示例：

```json
{
  "skill": {
    "name": "医保结算费用解释",
    "purpose": "解释患者本次医保结算结果"
  },

  "profile": {
    "name": "起付线解释",
    "purpose": "解释起付金额来源"
  },

  "available_metrics": [
    {
      "metric_code": "zcgz.deductible_amount",
      "name": "起付金额",
      "description": "...",
      "business_object": "待遇规则"
    }
  ]
}

```

---

# 40. AI 输出

AI 返回：

```text
Candidate Diff

```

而不是直接写入最终配置。

例如：

```json
{
  "recommended": [
    {
      "metric_code": "zcgz.deductible_amount",
      "required": true,
      "purpose": "获取当前待遇条件对应起付金额",

      "reason": "该指标直接表达政策起付标准",

      "references": [
        {
          "type": "metric_registry",
          "metric_code": "zcgz.deductible_amount"
        }
      ]
    }
  ]
}

```

---

# 41. AI 推荐确认流程

```text
AI 推荐
↓
Candidate
↓
Diff
↓
用户确认
↓
写入 Execution Contract

```

禁止：

```text
AI推荐
↓
自动覆盖

```

---

# 42. AI Recommendation Reference

原稿里的：

```text
citations

```

容易让人理解为 RAG 文档引用。

这里更建议叫：

```text
recommendation_references

```

或：

```text
evidence

```

内容主要引用：

```text
Metric Registry
Business Object
Resolver Status
Metric Description

```

而不是政策文档 Citation。

---

# 43. 页面结构

第三步产品名称继续保持：

# 输入输出契约

后台模型使用：

```text
Execution Contract

```

---

# 44. 推荐布局

不采用顶部大量 Tab 作为长期主结构。

推荐：

```text
┌──────────────────────────────────────────────────────────────────┐
│ 第三步 · 输入输出契约                                             │
├──────────────┬────────────────────────────┬──────────────────────┤
│ 执行场景      │ 当前场景输入契约            │ 指标选择器            │
│              │                            │                      │
│ 公共输入      │ 起付线解释                  │ 🔍 搜索指标            │
│              │                            │                      │
│ 起付线解释    │ 用途                       │ 可选指标               │
│ 统筹自付解释  │ 解释本次起付金额来源        │                      │
│ 大额自付解释  │                            │ 医保结算               │
│              │ 路由线索                    │  └ 结算               │
│ + 新建场景    │ 起付线 / 门槛费             │    ✓ 起付金额          │
│              │                            │    ✓ 人员类别          │
│              │ Context Inputs             │                      │
│              │ Metric Inputs              │ [显示不可用指标]       │
│              │                            │                      │
│              │ [AI 推荐输入依赖]           │                      │
└──────────────┴────────────────────────────┴──────────────────────┘

```

---

# 45. 为什么不用域→对象→指标作为唯一主交互

Skill 可能跨业务域依赖 Metric。

用户更可能知道：

```text
我要“起付金额”

```

而不是：

```text
它在哪个业务域 / 哪个业务对象下面

```

因此：

> 搜索应该是一等入口。

域→对象→指标适合作为：

```text
浏览方式

```

而不是强制路径。

---

# 46. 左侧执行场景区

固定第一项：

```text
公共输入

```

下面为：

```text
Execution Profiles

```

例如：

```text
公共输入

起付线解释
统筹自付解释
大额自付解释

+ 新建执行场景

```

---

# 47. 当前执行场景编辑

配置：

```text
名称
用途
Routing Hints
Context Inputs
Metric Inputs

```

支持：

```text
改名
复制
删除
排序

```

---

# 48. Metric Input 卡片

建议显示：

```text
指标名
metric_code
业务对象
Resolver 状态
required
alias
purpose

```

示例：

```text
起付金额
zcgz.deductible_amount

来源：待遇规则
Resolver：SOURCE_FIELD

必填：是
别名：政策起付金额
用途：获取当前待遇条件对应起付标准

```

---

# 49. Context Input UI

Context Input 不通过 Metric Selector。

单独使用：

```text
Context Selector

```

例如：

```text
✓ settlement_id
✓ question
○ visit_id
○ person_id

```

Context 列表来自：

```text
RuntimeContextRegistry

```

如果 V1 暂时没有 Registry，可由后端固定枚举提供。

---

# 50. 后端领域模型

建议新增：

```text
SkillExecutionContract
ExecutionProfileSpec
ContextInputSpec
MetricInputSpec

```

---

# 51. SkillExecutionContract

```text
version
common
profiles

```

---

# 52. CommonInputSpec

```text
context_inputs
metric_inputs

```

---

# 53. ExecutionProfileSpec

```text
profile_id
name
purpose
routing_hints
context_inputs
metric_inputs

```

---

# 54. 后端校验

Validator 必须验证以下内容。

---

## 54.1 Contract Version

```text
version

```

必须是支持版本。

---

## 54.2 Profile ID

检查：

```text
非空
kebab-case
Skill 内唯一

```

---

## 54.3 Metric 合法性

每个：

```text
metric_code

```

必须：

```text
存在
已发布
runtime_resolvable

```

---

## 54.4 Metric 去重

同一 Profile 内不能重复。

---

## 54.5 Common 与 Profile 重复

若 Metric 已在 Common：

```text
Profile 不重复声明

```

除非未来设计 Override 机制。

V1 不支持 Override。

---

## 54.6 Context Input 合法性

必须来自：

```text
RuntimeContextRegistry

```

---

## 54.7 Routing Hint

允许空。

但：

```text
不能完全依赖 routing_hints 决定 profile

```

该原则属于 Runtime 路由规范。

---

# 55. Runtime Resolving 校验

保存时：

```text
validate

```

发布前：

```text
validate

```

Runtime 执行前仍应：

```text
validate / check resolver availability

```

防止指标后来被下线或 Resolver 失效。

---

# 56. 后端主要改动

## `domain/skill/draft_[models.py](http://models.py)`

新增：

```text
SkillExecutionContract
CommonInputSpec
ExecutionProfileSpec
ContextInputSpec
MetricInputSpec

```

旧：

```text
InputSpec

```

暂做兼容。

---

## `runtime/skill_management/skill_input_[service.py](http://service.py)`

新增或扩展：

```text
get_runtime_resolvable_metrics()
validate_metric_inputs()
build_effective_input_contract()
build_query_plan()

```

核心：

> runtime_resolvable 的判断只存在一处。

---

## `runtime/skill_management/draft_[validator.py](http://validator.py)`

增加：

```text
execution_contract
profile
context
metric
重复
resolver

```

校验。

---

## `runtime/skill_management/ai_authoring/[schemas.py](http://schemas.py)`

增加：

```text
SkillExecutionContract
ExecutionProfile

```

AI 生成新 Skill 时可以生成：

```text
执行场景候选
+
指标依赖候选

```

但最终仍需用户确认。

---

## `runtime/skill_management/ai_authoring/[prompts.py](http://prompts.py)`

Prompt 不需要告诉 AI：

> 不要选不可查询指标。

因为 AI 输入集合本身已经经过过滤。

Prompt 只需要说明：

```text
请从 available_metrics 中选择。
不得生成不存在的 metric_code。

```

---

## `runtime/skill_management/package_[generator.py](http://generator.py)`

`needed_objects` 改为：

```text
common.metric_inputs
∪
profiles[].metric_inputs

```

聚合。

旧：

```text
supported_intents

```

继续兼容生成，但不作为新执行契约的数据源。

---

## `runtime/api/semantic_[routes.py](http://routes.py)`

指标选择器响应增加：

```text
runtime_resolvable
resolution_type
unavailable_reason

```

---

# 57. 前端共用组件

建议抽：

```text
ExecutionContractEditor

```

内部：

```text
ProfileNavigator
ContextInputEditor
MetricDependencyList
MetricSelector
AIRecommendationPanel

```

---

# 58. 共用范围

组件同时用于：

```text
/skills/new

```

第三步和：

```text
/skills/[skillId]/edit

```

避免两套 Input Contract UI 继续分叉。

---

# 59. 新建 Skill 第三步

第三步不再只是：

```text
Input / Output

```

而是主要帮助用户回答三个问题：

```text
这个 Skill 有哪些执行场景？

每个执行场景需要什么上下文？

每个执行场景需要哪些语义指标？

```

---

# 60. 提交逻辑

当前：

```text
submit()

```

漏传 inputs 属于明确 Bug。

改造后提交：

```text
structured_config.execution_contract

```

必须完整保存。

---

# 61. 编辑器兼容

旧：

```text
输入指标契约

```

区域替换为：

```text
ExecutionContractEditor

```

对于旧 Skill：

```text
legacy inputs

```

显示为：

```text
旧版输入契约

```

并提供：

```text
升级为执行契约

```

---

# 62. 向后兼容策略

旧数据：

```json
{
  "inputs": [...]
}

```

不立即删除。

读取时通过：

```text
LegacySkillInputAdapter

```

映射为：

```text
ExecutionContract V1 Compatible View

```

---

# 63. 不应该把旧 inputs 自动解释成 Common Inputs

因为旧语义是：

> Skill 所有输入。

而新 Common 的语义是：

> 每个 Execution Profile 都需要的输入。

两者不是完全等价。

因此不能静默迁移。

---

# 64. 旧 Skill 升级策略

如果：

```text
无 execution_contract

```

Runtime 继续按旧逻辑执行。

编辑页面提示：

```text
当前 Skill 使用旧版输入契约

```

用户点击升级后：

```text
旧 inputs
↓
作为“默认执行场景”的 Metric Inputs

```

而不是自动转成 Common。

例如：

```text
ExecutionProfile:
legacy-default

```

这样语义更安全。

---

# 65. DB 迁移

由于：

```text
structured_config

```

是 JSON / dict：

> 无需物理 ALTER TABLE。

但存在：

# Contract Migration

因此不能表述为：

```text
零迁移

```

更准确：

> 无数据库 Schema Migration，但存在应用层契约版本迁移。

---

# 66. Execution Contract Version

建议：

```json
{
  "execution_contract": {
    "version": 2
  }
}

```

后续可以显式升级。

---

# 67. AI 创建 Skill

AI 创建时建议分两步。

第一步：

```text
AI 提议 Execution Profiles

```

例如：

```text
起付线解释
统筹自付解释

```

用户确认。

第二步：

```text
AI 推荐每个 Profile 所需 Metric Inputs

```

用户确认。

不要一次性生成完整复杂契约并直接保存。

---

# 68. AI 优化 Skill

`optimizeSkillAIDraft` 需要理解：

```text
Execution Contract

```

Diff 粒度至少支持：

```text
新增 Profile
删除 Profile
修改 Routing Hint
新增 Metric Input
删除 Metric Input
修改 required
修改 purpose

```

---

# 69. 前置指标盘点

正式进入开发前必须做一次：

# Runtime Resolvable Metric Inventory

不是简单查：

```text
有哪些 Metric。

```

而是：

```text
Metric
Published?
Object Published?
Resolver Type?
Runtime Resolvable?
Unavailable Reason?

```

---

# 70. 盘点输出

建议：

```text
metric_code
metric_name
business_domain
business_object
status
resolution_type
runtime_resolvable
reason

```

---

# 71. 对业务输入需求做 Gap Analysis

例如：

```text
业务需要：统筹自付金额
语义层：存在
已发布：是
Resolver：SOURCE_FIELD
结果：可用

```

或者：

```text
业务需要：异地结算状态
语义层：不存在
结果：缺失

```

从而形成：

```text
Semantic Gap

```

---

# 72. 为什么盘点是前置条件

否则第三步页面即使开发完成，可能出现：

```text
指标选择器里几乎没东西可选

```

此时问题不是 Skill 页面。

而是：

```text
语义层尚未完成 Runtime Ready

```

---

# 73. V1 范围

本次正式支持：

```text
Execution Contract
Common Inputs
Execution Profiles
Context Inputs
Metric Inputs
Runtime Resolvable Selector
AI Candidate Recommendation
Input Validation
Output Skill-level Schema
Legacy Adapter

```

---

# 74. V1 暂不支持

不做：

```text
Profile 独立 Output Schema
Profile 独立 Tool Contract
Profile 独立 Policy Contract
输入之间复杂条件逻辑
动态 Profile 嵌套
Profile 继承
Metric Input Override
可视化流程编排
复杂 Intent DSL

```

---

# 75. 关键设计原则

## 原则一

> Metric Input 必须来自语义层，禁止自由文本 metric_code。

---

## 原则二

> 只有 Runtime Resolvable Metric 才能进入 Skill 正式执行契约。

---

## 原则三

> runtime_resolvable 由后端统一判断，前端不复制业务逻辑。

---

## 原则四

> AI 只能看到可选指标集合。

---

## 原则五

> Runtime Context 与 Metric Dependency 必须分开。

---

## 原则六

> Policy Knowledge 不是 Metric Input。

---

## 原则七

> 公共输入必须少，不能把“重要”误认为“每次都需要”。

---

## 原则八

> Execution Profile 只解决“同一能力、不同数据依赖”，不能成为无限膨胀 Skill 的理由。

---

## 原则九

> Input Contract 是输入定义唯一 Source of Truth。

---

## 原则十

> AI 推荐永远是 Candidate，不自动覆盖人工契约。

---

# 76. 推荐的数据流

```text
Semantic Layer
      │
      ▼
Runtime Resolvable Metrics
      │
      ├─────────────┐
      │             │
      ▼             ▼
Metric Selector   AI Authoring
      │             │
      └──────┬──────┘
             ▼
      Execution Contract
             │
             ▼
         Validation
             │
      ┌──────┴──────┐
      ▼             ▼
    PASS          BLOCK
      │
      ▼
     Publish
      │
      ▼
 Skill Runtime
      │
      ▼
Effective Inputs
=
Common + Profile
      │
      ▼
Query Plan

```

---

# 77. 页面最终形态

建议产品页面最终采用：

```text
第三步：输入输出契约

```

页面内部三个区域：

```text
左侧：执行场景

中间：当前执行场景契约

右侧：语义指标选择器

```

强调：

> 用户不是在“填 JSON”，而是在定义这个 Skill 为完成当前场景需要哪些数据。

---

# 78. 核心验收标准

## 验收 1

页面不能通过任何正常交互保存一个：

```text
不存在的 metric_code

```

---

## 验收 2

页面不能选择：

```text
runtime_resolvable = false

```

的 Metric。

---

## 验收 3

AI 不允许推荐：

```text
available_metrics

```

之外的 Metric。

---

## 验收 4

即使用户绕过前端构造请求，后端 Validator 仍然拒绝非法 Metric。

---

## 验收 5

命中不同 Execution Profile 时：

```text
build_query_plan()

```

只生成：

```text
Common
+
Matched Profile

```

需要的指标查询。

---

## 验收 6

旧 Skill 不升级也能继续运行。

---

## 验收 7

旧 Skill 升级时：

```text
旧 inputs

```

不能被静默解释为：

```text
Common Inputs

```

---

## 验收 8

AI 推荐新增依赖时必须以：

```text
Diff

```

形式展示。

---

# 79. 最小开发切片

## Phase 1：后端契约

实现：

```text
SkillExecutionContract
ExecutionProfileSpec
ContextInputSpec
MetricInputSpec

```

并建立：

```text
version = 2

```

---

## Phase 2：Runtime Resolvable

统一：

```text
metric runtime capability

```

判定。

Selector 返回：

```text
runtime_resolvable
resolution_type
unavailable_reason

```

---

## Phase 3：Validator

实现：

```text
Profile
Context
Metric
Resolver
重复
版本

```

校验。

---

## Phase 4：前端

实现：

```text
ExecutionContractEditor

```

替换第三步自由文本。

---

## Phase 5：AI 推荐

AI 只消费：

```text
runtime_resolvable metrics

```

并返回 Candidate Diff。

---

## Phase 6：Legacy Adapter

保持旧 Skill 运行，并支持：

```text
显式升级

```

---

# 80. 最终领域模型

整个 Skill 配置建议逐渐收敛为：

```text
Skill
│
├── Basic Definition
│
├── Business Mounting
│
├── Execution Contract
│   │
│   ├── Common Inputs
│   │
│   ├── Execution Profiles
│   │   ├── Context Dependencies
│   │   └── Metric Dependencies
│   │
│   └── Output Contract
│
├── Knowledge Requirements
│
├── Tool Requirements
│
└── Runtime Policy

```

本次只实现其中：

```text
Execution Contract

```

核心部分。

---

# 81. 最终结论

第三步这次改造的本质，不是：

> 把一个文本框换成一个漂亮的指标选择器。

真正目标是：

> **把 Skill 对数据的隐式依赖正式升级为显式、可验证、可治理、可执行的运行契约。**

因此最终设计从原来的：

```text
Skill
└── inputs[]

```

升级为：

```text
Skill
└── Execution Contract
     ├── Common Context
     ├── Common Metric Dependencies
     └── Execution Profiles
          ├── Context Dependencies
          └── Metric Dependencies

```

并通过：

```text
Semantic Layer
→ Runtime Resolvable
→ Execution Contract
→ Validation
→ Query Plan

```

形成完整闭环。

核心约束可以最终浓缩成一句话：

> **Skill 不声明“我想要什么字符串”，而声明“为了完成某个执行场景，我依赖哪些经过语义层治理且运行时真实可获取的数据”。**

这是本次第三步改造最终应该建立起来的产品和技术能力。