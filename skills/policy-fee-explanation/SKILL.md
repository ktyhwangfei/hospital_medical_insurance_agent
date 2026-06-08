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
  - id: search_policy_rules
    tool: search_policy_rules
    depends_on: [query_sql_data]
    type: KNOWLEDGE
    label: 检索政策规则
  - id: calculate_explanation
    tool: calculate_fee_explanation
    depends_on: [query_sql_data, search_policy_rules]
    type: SKILL
    label: 费用计算
  - id: generate_explanation
    tool: generate_policy_explanation
    depends_on: [query_sql_data, search_policy_rules, calculate_explanation]
    type: MCP
    label: 生成解释
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

1. SQL 查询：从 SQL Server 获取患者结算数据（待遇分解、费用明细、年度累计、住院信息、患者登记）
2. 政策检索：按 target_fee_item 定向检索 Milvus 政策规则库
3. 费用计算：config.yaml 路由到对应计算器，执行分段计算
4. LLM 解释：流式生成患者视角 + 院端视角两份解释
