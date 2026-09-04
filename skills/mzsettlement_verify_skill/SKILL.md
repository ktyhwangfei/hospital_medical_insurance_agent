---
name: mzsettlement_verify_skill
description: 核验并解释门诊结算金额、待遇条件、费用明细及交易状态，输出可追溯证据和不确定性。
---

# 门诊结算结果核验

仅处理已经发生的门诊结算事实核验，不办理异地备案、慢特病认定、退费、冲正或重新结算。

## 执行约束

1. 先把 `settlement_id` 作为门诊交易号（`T_TradeNo`）查询已发布的 `mzjyxx` 语义对象，再按问题选择最小 Profile。
2. 零值、缺失、不适用、非零必须分开表达；不得把零值解释为无待遇资格。
3. 金额关系允许 0.01 元四舍五入差；比例、起付线、封顶线只有在政策证据匹配险种、人员、医疗类别、机构与日期后才能解释。
4. 每条政策结论必须返回来源，每个金额字段解释还必须携带字段级 `citations`；证据不足时返回 `uncertainties`，不猜测政策公式。
5. 退费、冲正、撤销结算、重新结算属于高风险写操作，必须转人工确认。
6. “统筹自付”按本系统口径单独计算为 `个人自付一 + 个人自付二`，不得与“个人支付总金额”混用；继续用医保内金额与基金支付分解自付一，用费用明细先自付合计分解自付二。
7. 政策查询先做结构化适用性过滤；个人负担场景的险种和医疗类别不得用空维度规则兜底。结构化候选不相关时使用稠密向量召回和 BM25 重排，但混合检索不得绕过适用性条件。

## 结果状态

- `complete`：数据完整、金额勾稽通过且政策证据满足问题需要。
- `partial`：可说明结算事实，但存在缺字段、金额差异或政策证据不足。
- `unavailable`：无法定位交易，或对应场景没有可用核心数据。

各 Profile 的路由词、指标和核心金额声明位于 `skill_manifest.yaml`；语义映射与展示名称位于 `config.yaml`；政策规则类型位于 `policy_queries.yaml`。装配器只负责委托给 `strategies/profile.py`。

八份官方政策、语义 v3 与知识发布的可迁移基线见 `references/policy_knowledge_baseline.yaml`，迁移与能力缺口见 `references/policy_knowledge_release.md`。可在仓库根目录运行 `uv run python -m skills.mzsettlement_verify_skill.scripts.check_policy_baseline` 做只读核验。
