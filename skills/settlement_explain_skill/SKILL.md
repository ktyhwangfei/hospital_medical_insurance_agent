---
name: policy-fee-explanation
description: >
  Use this skill when the user asks why a medical insurance settlement
  fee item exists, what a fee item means, how it was calculated,
  or which policy and settlement data support it.
  Trigger words include: 统筹自付, 起付线, 大额自付, 统筹支付,
  个人自付, 自付2, 医保外费用, 封顶线, 报销比例, 为什么这么多, 怎么算.
scope: project
version: "2.0.0"
---

# 医保费用解释 Skill（policy-fee-explanation）

## 概述

本 skill 是自包含的医保费用解释能力包。它不依赖产品页面的硬编码逻辑，
而是通过 MCP 完成真实结算数据查询、结构化政策规则查询、政策证据组装、
可回答性判断和最终解释生成。

支持的费用项（按 target_fee_item 路由）：
| target_fee_item | 目标字段 | 说明 |
|---|---|---|
| `pooling_self_pay` | `basic_pooling_self_pay` | 统筹自付 |
| `deductible` | `deductible` | 起付线 |
| `large_amount_self_pay` | `large_amount_self_pay` | 大额自付 |
| `pooling_payment` | `basic_pooling_payment` | 统筹支付 |
| `personal_total_pay` | `personal_total_pay` | 个人总支付 |
| `out_of_scope` | — | 医保外费用 |

## Required MCP Capabilities

本 skill 依赖以下 MCP。产品层必须已在运行时注册这些 MCP。

| MCP ID | 用途 | 必要 |
|---|---|---|
| `settlement-data` | 查询真实结算数据（SQL Server） | ✅ 必须 |
| `structured-policy-rule` | 结构化政策规则查询（Milvus 标量） | ✅ 必须 |
| `policy-vector-search` | 向量语义检索兜底（Milvus 向量） | 可选 |
| `audit-trace` | 审计链路事件记录 | 可选 |

详细的 MCP 配置见 `agents/openai.yaml`。

## 执行流程

### 1. 意图识别（Intent Detection）
- 输入：用户自然语言问题
- 分析：从问题中识别目标费用项（target_fee_item）
- 输出：target_fee_item（如 `pooling_self_pay`、`deductible`）

### 2. 费用字段识别（Fee Item Identification）
- 输入：target_fee_item
- 映射：`pooling_self_pay` → `basic_pooling_self_pay` 字段
- 加载：读取 schemas/input.schema.json 确认输入结构
- 加载：references/settlement_field_mapping.md 获取字段定义

### 3. 真实结算数据查询（Settlement Data Query）
- MCP：`settlement-data`
- 输入：settlement_id
- 查询：SQL Server（yb_zyfdxx, yb_dyxxzy, yb_dyxxnd, yb_brdjxx, yb_zyjyxx）
- 输出：SettlementContext 对象（含全部结算字段、人员类别、险种、医院等级等）

### 4. 结算上下文标准化（Context Normalization）
- 脚本：`scripts/normalize_fee_context.py`
- 输入：原始 SettlementContext
- 处理：将 SQL 字段映射到 Milvus 查询字段
- 输出：标准化 NormalizedPolicyContext

### 5. 政策查询计划生成（Policy Query Plan Generation）
- 输入：target_fee_item + NormalizedPolicyContext
- 规则：`references/policy_query_patterns.md` 定义各费用项的查询模式
- 输出：StructuredPolicyQuery 列表（query_name, filters, required 等）

### 6. 结构化政策规则查询（Structured Policy Query）
- MCP：`structured-policy-rule`
- 输入：StructuredPolicyQuery 列表
- 查询：Milvus policy_rules 集合，标量字段过滤
- 输出：StructuredPolicyEvidence 列表

### 7. 可选向量兜底（Vector Fallback — Optional）
- MCP：`policy-vector-search`
- 触发条件：结构化查询未返回足够结果时
- 查询：Milvus 向量相似度搜索
- 输出：补充的 PolicyEvidence 列表

### 8. 政策证据组装（Policy Evidence Assembly）
- 输入：StructuredPolicyEvidence 列表
- 处理：去重、排序、添加 applied_reason
- 输出：policy_evidence 字典列表
- 结构：`schemas/policy_evidence.schema.json`

### 9. 政策完整性判断（Policy Completeness Judgment）
- 输入：policy_evidence
- 规则：`references/answer_quality_standard.md`
- 判断：是否已匹配足够政策规则来解释该费用项
- 输出：evidence_completeness（full_policy_ratio_matched / partial / none）

### 10. 可回答性判断（Answerability Judgment）
- 输入：SettlementContext + policy_evidence + evidence_completeness
- 规则：
  - 有真实数据 + 有政策规则 → `can_answer = true`
  - 有真实数据但无政策 → `can_answer = true, partial_answer = true`
  - 无真实数据 → `can_answer = false`
- 输出：can_answer, partial_answer

### 11. 患者视角生成（Patient View Generation）
- 模板：`templates/patient_view.md`
- 输入：SettlementContext + policy_evidence + extracted_ratios
- 生成：患者可理解的自然语言解释，包含政策依据引用
- 如果 can_answer=false：使用 `templates/cannot_answer.md`
- 如果 partial_answer：使用 `templates/partial_answer.md`

### 12. 医保办视角生成（Office View Generation）
- 模板：`templates/office_view.md`
- 输入：SettlementContext + policy_evidence + extracted_ratios
- 生成：专业口径的解释，包含字段来源、政策规则、比例推导

### 13. 输出校验（Output Validation）
- 脚本：`scripts/validate_skill_result.py`
- 校验规则（来自 answer_quality_standard.md）：
  - 禁止模板代码泄漏（if t., undefined, null, NaN）
  - 禁止 raw JSON / rule_id / embedding_text
  - 必须包含政策依据引用
  - 必须说明金额与起付线/大额自付的区别

### 14. 返回结果（Return Result）
- 格式：`schemas/output.schema.json`
- 包含：skill_id, target_fee_item, target_field, data_source,
  can_answer, partial_answer, case_context, policy_evidence,
  evidence_completeness, patient_answer, office_answer,
  warnings, trace_events, validation

## 输入 Schema

见 `schemas/input.schema.json`。

必填字段：`question`, `settlement_id`

## 输出 Schema

见 `schemas/output.schema.json`。

核心字段：
| 字段 | 类型 | 说明 |
|------|------|------|
| `skill_id` | string | `policy-fee-explanation` |
| `target_fee_item` | string | 如 `pooling_self_pay` |
| `target_field` | string | 如 `basic_pooling_self_pay` |
| `data_source` | string | `REAL_DB` |
| `mock_used` | boolean | `false` |
| `can_answer` | boolean | 是否可以回答 |
| `partial_answer` | boolean | 是否部分回答 |
| `case_context` | object | 结算上下文 |
| `policy_evidence` | array | 政策证据列表 |
| `evidence_completeness` | object | 证据完整性 |
| `recalculation_completeness` | object | 逐分段复算完整性 |
| `patient_answer` | string | 患者视角解释 |
| `office_answer` | string | 医保办视角解释 |
| `warnings` | array | 警告信息 |
| `trace_events` | array | 执行链路事件 |
| `validation` | object | 校验结果 |

## 跟踪事件

每次执行生成一系列 trace_events，格式见 `schemas/trace_event.schema.json`。
每个事件包含：`step_id`, `step_name`, `status`（running/done/error）, `duration_ms`, `detail`。

## 产品层调用方式

```python
from src.skill_infra.skill_router import get_assembler

assembler = get_assembler("settlement_explain_skill")
result = assembler.execute(
    question="我的统筹自付为什么这么多",
    settlement_id="1671213",
)
# result 包含 patient_answer, office_answer, policy_evidence, trace_events, ...
```

## 约束

1. **不写死文案**：解释文案由模板生成，不硬编码在 Python/TypeScript 产品代码中
2. **不写死比例**：三级医院分段比例 85/90/95、退休人员 60% 从 Milvus 动态查询
3. **不写死查询计划**：政策查询由各费用项的 query_patterns.md 定义
4. **不做 UI**：skill 只负责数据查询→计算→生成解释，前端渲染由 Portal 负责
5. **不做 HTTP 直接调用**：所有外部访问通过 MCP 封装
