# Semantic Layer 设计文档

## 一、设计目标

Semantic Layer（语义层）是医保 AI 系统的核心业务抽象层。

其职责是在大模型、Agent、Skill、SQL、政策规则之间建立统一的业务语义体系，实现：

```text
用户问题
    ↓
业务概念识别
    ↓
指标定位
    ↓
数据获取
    ↓
政策关联
    ↓
结果解释
```

而不是：

```text
用户问题
    ↓
直接生成SQL
```

语义层的目标是让 AI 理解业务，而不是理解数据库。

---

# 二、设计原则

## 原则1：业务优先

语义层面向业务概念构建，而不是面向数据库表构建。

例如：

业务对象：

* 参保人
* 结算单
* 医疗机构
* 费用明细

而不是：

* yb_jsxx
* yb_zyfd
* yb_mx

---

## 原则2：指标驱动

所有查询最终必须映射到指标。

例如：

```text
我的起付线是多少
```

最终映射：

```text
Metric:
deductible
```

---

## 原则3：可解释优先

每个指标必须具备完整血缘。

能够回答：

```text
这个数从哪里来的？
```

能够输出：

```text
指标值
↓
计算过程
↓
数据来源
↓
政策依据
```

---

## 原则4：与政策解耦

语义层维护政策引用关系。

政策内容由 Policy Center 管理。

---

## 原则5：面向Agent

语义层不是数据仓库组件。

语义层是 Agent 的业务知识基础设施。

---

# 三、总体架构

语义层由五个核心中心组成：

```text
Entity Center
      ↓
Concept Center
      ↓
Metric Center
      ↓
Lineage Center
      ↓
Policy Center
```

最终形成：

```text
Entity
    ↓
Concept
    ↓
Metric
    ↓
Lineage
    ↓
Policy
    ↓
Skill
```

---

# 四、Entity Center（业务实体中心）

## 目标

统一管理医保业务对象。

帮助 AI 建立业务世界模型。

---

## 核心实体

### 参保人

```text
insured_person
```

---

### 结算单

```text
settlement
```

---

### 医疗机构

```text
hospital
```

---

### 费用明细

```text
fee_detail
```

---

### 药品

```text
drug
```

---

### 诊疗项目

```text
medical_service
```

---

### 诊断信息

```text
diagnosis
```

---

## 实体关系

```text
参保人
   │
   └──结算单
          │
          ├──费用明细
          │
          ├──药品
          │
          └──诊疗项目

结算单
   │
   └──医疗机构
```

---

## Entity职责

提供：

* 业务对象定义
* 主键定义
* 数据源映射
* 实体关系定义

---

# 五、Concept Center（业务概念中心）

## 目标

统一管理医保业务语言。

解决用户表达与系统指标之间的映射问题。

---

## 示例

用户表达：

```text
起付线
起付标准
门槛费
起付金额
```

统一映射：

```text
Concept:
deductible
```

---

## Concept职责

提供：

* 同义词管理
* 业务术语管理
* 意图标准化
* Concept → Metric映射

---

# 六、Metric Center（指标中心）

## 目标

统一管理医保业务指标。

Metric 是语义层核心对象。

---

## Metric分类

### 费用指标

```text
total_cost

covered_cost

non_covered_cost

self_pay_cost
```

---

### 基金支付指标

```text
pooling_payment

major_disease_payment

account_payment
```

---

### 个人负担指标

```text
deductible

pooling_self_pay

out_of_pocket
```

---

### 维度指标

```text
hospital_level

insurance_type

fund_type
```

---

## Metric标准属性

每个指标必须包含：

```text
metric_code

metric_name

entity

description

metric_type

unit

source

lineage_ref

policy_ref
```

---

## Metric职责

提供：

* 指标定义
* 指标分类
* 字段映射
* SQL生成入口
* Skill路由入口

---

# 七、Lineage Center（指标血缘中心）

## 目标

实现指标可追溯、可解释。

这是医保问答解释能力的基础。

---

## 血缘层级

### 一级血缘

依赖关系血缘

例如：

```text
统筹支付

依赖：

起付线
医保目录金额
医院等级
报销比例
```

---

### 二级血缘

公式血缘

例如：

```text
统筹支付

=
第一段基金支付
+
第二段基金支付
+
第三段基金支付
```

---

### 三级血缘

SQL血缘

例如：

```text
来源SQL模板：

pooling_payment_query.sql
```

---

### 四级血缘

政策血缘

例如：

```text
依据：

三级医院住院待遇政策
```

---

## Lineage职责

支持：

```text
指标值
↓
公式
↓
数据
↓
政策
```

的完整解释链。

---

# 八、Policy Center

Policy Center 已独立建设。

语义层仅保存引用关系。

例如：

```text
pooling_payment

关联：

inpatient_level3_policy
```

---

# 九、Skill集成

Skill 不直接面向数据库。

Skill 面向 Metric。

例如：

```text
pooling_payment_explain
```

依赖：

```text
Metric:
pooling_payment
```

Skill执行流程：

```text
Metric
↓
Lineage
↓
Policy
↓
SQL
↓
Explanation
```

---

# 十、标准解析流程

示例：

用户提问：

```text
为什么统筹支付是91759.51元？
```

解析过程：

```text
Question

↓

Intent

↓

Concept
（统筹支付）

↓

Metric
（pooling_payment）

↓

Lineage

↓

Policy

↓

Skill

↓

SQL

↓

Answer
```

---

# 十一、目录结构

```text
src/semantic_layer

├── entities
├── concepts
├── metrics
├── lineages
├── registries
├── resolvers
├── models
├── cache
├── tests
└── docs
```

推荐：

```text
entities/
    settlement.yaml
    hospital.yaml

concepts/
    deductible.yaml
    pooling_payment.yaml

metrics/
    deductible.yaml
    pooling_payment.yaml

lineages/
    deductible_lineage.yaml
    pooling_payment_lineage.yaml
```

---

# 十二、当前阶段建设范围

当前阶段仅建设：

```text
Entity Center
Concept Center
Metric Center
Lineage Center
```

Policy Center 已建设完成。

Knowledge Graph、Ontology、Reasoning Engine 暂不纳入范围。

---

# 十三、后续演进路线

Phase-1

```text
Entity
Concept
Metric
Lineage
```

Phase-2

```text
Policy Integration
Skill Integration
```

Phase-3

```text
Semantic SQL Generation
```

Phase-4

```text
Knowledge Graph
Ontology
Reasoning Engine
```

最终形成医保 AI 的统一业务语义底座。
