---
name: settlement-compare
description: >
  Use this skill when the user asks to compare two or more medical insurance
  settlements, why this settlement differs from a previous one, or how much
  the difference is.
  Trigger words include: 对比, 比较, 差异, 不一样, 为什么这次, 跟上次, 差多少.
scope: project
version: "1.0.0"
---

# 结算对比解释 Skill（settlement-compare）

## 概述

本 skill 是自包含的结算对比能力包。对 2~N 张住院结算单逐项比对费用字段差异，
通过**确定性归因规则**（YAML 配置，业务逻辑不硬编码）解释差异原因，
逐项附政策依据引用（citations）；未命中规则的差异声明 uncertainties。

约定：输入结算单列表的**第一张为基准（baseline）**，其余每张与基准两两对比。

## Required MCP Capabilities

| MCP ID | 用途 | 必要 |
|---|---|---|
| `settlement-data` | 查询真实结算数据（SQL Server） | ✅ 必须（由产品层供给 SettlementContext） |
| `structured-policy-rule` | 结构化政策规则查询（Milvus 标量） | ✅ 必须（由产品层供给归因政策证据） |
| `policy-vector-search` | 向量语义检索兜底 | 可选 |
| `audit-trace` | 审计链路事件记录 | 可选 |

## 执行流程

1. **输入校验**：settlement_ids（2~5 张），去重后不足 2 张则不可答
2. **逐单取数**：产品层对每张单走既有结算数据查询，得到 SettlementContext
3. **逐字段 diff**：`diff_engine.diff_contexts()` 基准 vs 每张对比单，产出 FieldDiff 列表
4. **归因匹配**：`strategies/compare/strategy.py` 加载 `attribution_rules.yaml`，
   对每个差异字段按优先级匹配规则；未命中走 fallback（声明 uncertainty）
5. **归因证据**：按命中规则的 policy_topic 生成结构化政策查询（产品层执行检索），
   逐项附 citations
6. **模板渲染**：`answer_template.yaml` 生成逐项差异 + 归因的对比解释
7. **可答性判断**：全部差异有归因且有政策证据 → complete 输入；
   存在 fallback 项 → partial；无差异或数据缺失 → cannot_answer
8. **返回结果**：见 `schemas/output.schema.json`

## 输入 Schema

见 `schemas/input.schema.json`。必填字段：`settlement_ids`（2~5 张，首张为基准）。

## 输出 Schema

见 `schemas/output.schema.json`。核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill_id` | string | `settlement-compare` |
| `baseline_settlement_id` | string | 基准结算单号 |
| `diff_items` | array | 逐项字段差异（FieldDiff） |
| `attributions` | array | 逐项归因（见 `schemas/attribution.schema.json`） |
| `can_answer` | boolean | 是否可以回答 |
| `partial_answer` | boolean | 是否部分回答（存在未归因差异） |
| `answer` | string | 模板化对比解释 |
| `warnings` | array | 警告信息 |

## 产品层调用方式

```python
from src.skill_infra.skill_router import get_assembler

assembler = get_assembler("settlement_compare_skill")
result = assembler.execute(
    settlement_contexts=[ctx_a, ctx_b],   # 首个为基准
    policy_evidence_by_id={"A": [...], "B": [...]},
    policy_status="full_policy_matched",
)
# result 包含 answer、diff_items（经 calculation_trace）、warnings 等
```

## 约束

1. **skill 自包含**：不 import 其他 skill 的模块；单结算数据由产品层供给
2. **归因规则配置化**：归因规则全部在 `strategies/compare/attribution_rules.yaml`，
   新增规则不改 Python 代码
3. **确定性 diff**：字段比对为纯函数，无 LLM、无 IO
4. **来源可追溯**：命中归因必须附政策 citations；未命中必须声明 uncertainties
5. **不做 UI**：前端渲染由 Portal 负责
