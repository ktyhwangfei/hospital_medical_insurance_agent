---
name: policy-fee-explanation
description: "解释医保费用构成，回答统筹自付、个人应付、起付线、报销比例、药品自付、医保外费用等'为什么这笔钱是这个数'类问题"
scope: project
version: "1.0.0"
tools:
  - query_sql_settlement_data     # MCP: SQL Server 查结算数据
  - search_policy_rules           # MCP: Milvus 检索政策规则
  - calculate_fee_explanation     # SKILL: 费用计算（config.yaml 路由）
  - generate_policy_explanation   # MCP: LLM 生成解释
steps:
  - id: query_sql_data
    tool: query_sql_settlement_data
    depends_on: []
    type: MCP
    label: 查询结算数据
    purpose: "获取患者基本信息（险种、人员类型、医疗类别）和结算数据，为后续问题精准化和费用计算提供上下文"
  - id: search_policy_rules
    tool: search_policy_rules
    depends_on: [query_sql_data]
    type: KNOWLEDGE
    label: 检索政策规则
    purpose: "按目标费用项从知识库检索对应的政策规则（分段比例、起付线、封顶线、药品目录等），作为费用计算和解释的参数依据"
  - id: calculate_explanation
    tool: calculate_fee_explanation
    depends_on: [query_sql_data, search_policy_rules]
    type: SKILL
    label: 费用计算
    purpose: "根据结算数据和政策规则，执行分段计算、对账校准，生成结构化的费用分解结果"
  - id: generate_explanation
    tool: generate_policy_explanation
    depends_on: [query_sql_data, search_policy_rules, calculate_explanation]
    type: MCP
    label: 生成解释
    purpose: "基于费用计算结果和政策依据，流式生成患者视角和院端视角两份自然语言解释"
config_file: config.yaml
---

# 医保费用解释 Skill

## 概述

根据意图识别确定的目标费用项（target_fee_item），自动查询结算数据、检索对应政策规则、计算费用构成、生成双视角解释。

## 适用场景

- 统筹自付为什么这么高
- 个人应付怎么计算
- 起付线是多少
- 甲类药为什么还要自付
- 医保外费用（特需等）为什么这么多
- 报销比例相关问题

## 执行流程

### Step 1: 查询结算数据（MCP）
从 SQL Server 获取患者基本信息（险种、人员类型、医疗类别、年度累计）和本次结算数据（待遇分解、费用明细、住院信息）。
**目的**：获取患者上下文，为后续问题重写和费用计算提供数据基础。例如，险种是"城镇职工"还是"城乡居民"、人员类型是"在职"还是"退休"，直接影响分段计算的人员系数。

### Step 2: 检索政策规则（KNOWLEDGE）
按 target_fee_item 从 Milvus 知识库检索对应的政策规则。config.yaml 中的 `policy_filters` 控制检索范围——例如统筹自付需要检索支付比例、起付线、封顶线三类规则。
**目的**：获取计算所需的参数依据（分段比例、起付线金额、封顶线金额等），避免"为了查而查"。

### Step 3: 费用计算（SKILL）
config.yaml 路由到对应计算器，根据结算数据和政策规则执行计算。例如统筹自付的分段计算（Σ 各分段金额 × 各分段自付比例 × 人员系数），并与结算系统中的权威金额对账。
**目的**：将原始数据和政策规则转化为可解释的费用分解结果。

### Step 4: 生成解释（MCP）
基于费用计算结果和政策依据，通过 LLM 流式生成患者视角和院端视角两份自然语言解释。
**目的**：让患者和医院工作人员都能理解费用构成，而不是只给一串数字。
