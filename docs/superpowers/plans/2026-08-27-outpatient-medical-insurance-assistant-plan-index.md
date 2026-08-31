# 单院门诊医保智能助手实施计划索引

**Design:** `docs/superpowers/specs/2026-08-27-outpatient-medical-insurance-assistant-design.md`

**Goal:** 按证据门禁推进单院门诊医保数据底座、门诊结算核验、运营问数和统一助手，避免在字段口径未确认时提前固化错误实现。

**Planning rule:** 每次只详细规划下一个可验证阶段。后续阶段依赖前一阶段产生的真实字段、性能和安全证据，不提前编造实现细节。

---

## 执行顺序

| 阶段 | 状态 | 计划或基线 | 进入条件 | 完成门槛 |
|---|---|---|---|---|
| P0 数据契约 | complete | `2026-08-27-outpatient-p0-data-contract.md` + [预填设计决策稿](../../reviews/2026-08-28-outpatient-p0-prefilled-design-decision.md) | `bjybdb`、v3 查询模型、主要值域和 Issue20 依赖已自主核验；D01–D12 已确认 | D01–D12 已确认；外部开通项移交实施阶段 |
| P1 近实时数据底座 | impl_done | `2026-08-28-outpatient-p1-near-real-time-data-foundation.md` | 已满足：P0 设计确认；CDC/只读账号作为实施任务而非设计问卷 | 代码与本地三层验证完成；仍须目标环境注册 `bjybdb`、启用 CDC 并取得 100 个非空批次 P95 ≤ 300 秒证据后改为 complete |
| P2 门诊结算核验 | baseline | `2026-08-26-mzsettlement-verify-skill.md` | P1 发布的数据集和内部结算锚点可用 | 九个 Profile、Decimal 勾稽、字段四态、政策证据和回归矩阵通过 |
| P3 运营受控问数 | gated | P2 通过后编写 | 五个可确定指标、五维度及可信问题口径已冻结；就诊人次保持 unavailable | 指标查询与科室→就诊下钻通过可信问题自动验收 |
| P4 统一助手与工作台 | gated | P3 通过后编写 | 后端结果契约稳定；身份上下文接口可模拟 | 同一入口完成政策咨询、门诊核验和运营问数，前端不要求结算 ID |
| P5 上线加固 | gated | 医院确认 SSO/扫码方案后编写 | 身份提供方、组织角色和数据范围接口明确 | 权限、高风险拦截、审计、准确率、性能和回滚门槛全部通过 |

## 关键覆盖关系

- Issue 20 只负责 `mzsettlement_verify_skill + mzjyxx` 的门诊核验基线，不承担运营问数或统一入口。
- `o_Trade/o_FeeItem` 是候选抽取源；P1 后的运行时只读取 PostgreSQL 的 `mz_trade/mz_fee_item` 发布批次。
- 现有 `settlement_explain_skill` 保持住院职责，不吸收门诊 Profile。
- `/policy-qa/stream` 在 P4 前仍是现行业务入口；P4 才增加 `/assistant/stream` 并保留受控兼容。
- SSO/扫码厂商未确定不阻塞 P0-P4 的可信主体接口与拒绝路径测试，但阻断 P5 生产上线。

## 当前执行点

P0 事实探查和设计确认已完成，D01–D12 全部采用。P1 Task 1–8 的代码、脱敏核验报告和本地 T1→T2a→T2b 已完成；本地 PostgreSQL 门诊表/视图已初始化。目标环境尚未解析到 `bjybdb` 注册/完整连接配置，因而没有真实批次、LSN 或 P95 证据，P1 保持 `impl_done`，P2 保持 `baseline`。下一步由目标环境管理员注册只读数据源、DBA 审核启用 CDC 后执行验收；扫码/SSO 仍是后续实施项。
