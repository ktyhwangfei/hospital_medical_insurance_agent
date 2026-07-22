# 回答质量标准

每个 skill 输出的解释必须满足以下质量标准。

## 禁止事项

### 禁止模板代码泄漏

以下内容不得出现在 patient_answer 或 office_answer 中：

- `if t.` — Python 条件表达式
- `else` — 模板分支代码
- `undefined` / `null` / `None` / `NaN` — 空值占位符
- `{"ratio"` — raw JSON
- `yb_zyfdxx.bdtczf` — raw SQL 列名
- `yb_dyxxzy.*` — raw SQL 列名
- `rule_id` / `clause_id` — 内部 ID
- `embedding_text` — 向量检索中间产物
- `Milvus score` — 检索得分
- `结构化政策规则库` — 内部数据源名（患者视角禁用）

### 禁止模糊引用

- ❌ "根据政策" — 必须写明 "根据已匹配到的三级医院住院分段支付比例规则"
- ❌ "医保规定" — 必须写明具体条款内容

## 必须包含

### 统筹自付解释

- 三级医院分段比例：85%、90%、95%
- 职工个人支付比例：15%、10%、5%
- 退休人员折算规则：60%
- 退休人员实际比例：9%、6%、3%
- 与起付线的区别说明
- 与大额自付的区别说明
- 金额不包含医保外费用和目录先行自付

### 起付线解释

- 三级医院起付线标准金额
- 起付线以下不纳入统筹段
- 起付线按次/按年累计规则

## 完整性判断

| 级别 | 条件 |
|------|------|
| `full_policy_ratio_matched` | 三类核心规则全部匹配（分段比例 + 退休折算 + 起付线/封顶线） |
| `partial_policy_matched` | 部分规则匹配，部分缺失 |
| `real_data_only` | 仅有真实结算数据，无政策匹配 |
| `no_policy_matched` | 无政策依据 |

## 输出校验

每次生成后运行以下检查：

1. 扫描 forbidden_text 列表 — 任一命中则标记 validation.passed = false
2. 检查 required_contains 列表 — 缺失则标记 warning
3. 检查金额是否一致 — patient_answer 和 office_answer 的金额必须一致
4. 检查溯源完整性 — trace_events 必须包含 14 个步骤
