# 单院门诊医保智能助手实施计划索引

**Design:** `docs/superpowers/specs/2026-08-27-outpatient-medical-insurance-assistant-design.md`

**Goal:** 按证据门禁推进单院门诊医保数据底座、门诊结算核验、运营问数和统一助手，避免在字段口径未确认时提前固化错误实现。

**Planning rule:** 每次只详细规划下一个可验证阶段。后续阶段依赖前一阶段产生的真实字段、性能和安全证据，不提前编造实现细节。

---

## 执行顺序

| 阶段 | 状态 | 计划或基线 | 进入条件 | 完成门槛 |
|---|---|---|---|---|
| P0 数据契约 | ready | `2026-08-27-outpatient-p0-data-contract.md` | 已有 SQL Server 只读画像权限 | 键、关系、金额、游标、容量和字段依赖均有脱敏证据并获业务/数据负责人确认 |
| P1 近实时数据底座 | gated | P0 通过后编写 | 明细源和可靠增量游标已冻结 | PostgreSQL 单一路径刷新 P95 不超过 5 分钟，批次原子发布，`mzjyxx.queryable=true` |
| P2 门诊结算核验 | baseline | `2026-08-26-mzsettlement-verify-skill.md` | P1 发布的数据集和内部结算锚点可用 | 九个 Profile、Decimal 勾稽、字段四态、政策证据和回归矩阵通过 |
| P3 运营受控问数 | gated | P2 通过后编写 | 六指标、五维度及可信问题口径已冻结 | 指标查询与科室→就诊下钻通过可信问题自动验收 |
| P4 统一助手与工作台 | gated | P3 通过后编写 | 后端结果契约稳定；身份上下文接口可模拟 | 同一入口完成政策咨询、门诊核验和运营问数，前端不要求结算 ID |
| P5 上线加固 | gated | 医院确认 SSO/扫码方案后编写 | 身份提供方、组织角色和数据范围接口明确 | 权限、高风险拦截、审计、准确率、性能和回滚门槛全部通过 |

## 关键覆盖关系

- Issue 20 只负责 `mzsettlement_verify_skill + mzjyxx` 的门诊核验基线，不承担运营问数或统一入口。
- `o_Trade/o_FeeItem` 是候选抽取源；P1 后的运行时只读取 PostgreSQL 的 `mz_trade/mz_fee_item` 发布批次。
- 现有 `settlement_explain_skill` 保持住院职责，不吸收门诊 Profile。
- `/policy-qa/stream` 在 P4 前仍是现行业务入口；P4 才增加 `/assistant/stream` 并保留受控兼容。
- SSO/扫码厂商未确定不阻塞 P0-P4 的可信主体接口与拒绝路径测试，但阻断 P5 生产上线。

## 当前执行点

只执行 P0。P0 未证明可靠增量游标时，不开始每分钟同步开发；未证明 `o_FeeItem` 金额口径时，不发布该明细源；未证明候选键唯一时，不创建可查询语义版本。
