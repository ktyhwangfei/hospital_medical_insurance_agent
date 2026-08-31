# 门诊医保近实时数据底座 P1 验证记录

## 结论

截至 2026-08-31，当前测试环境已满足本轮唯一接入成功条件：SQL Server 三张门诊表及 117 个契约字段可读，PostgreSQL 门诊结构可直接初始化并通过事务读写；页面显示“数据底座可用”。同步任务仍为未启动草稿，尚无真实批次和延迟样本，因此整个 P1 近实时同步里程碑仍为 `impl_done`；Firefox 独立生产态浏览器复验也尚未完成。[来源: `docs/superpowers/plans/2026-08-28-outpatient-p1-near-real-time-data-foundation.md` §1、Task 8；`docs/superpowers/specs/2026-08-31-outpatient-test-environment-readiness-amendment.md`]

## 代码与环境

- 分支：`feature/outpatient-p0-data-contract`；P1 Task 1–7 提交：`d0d70c4`、`1520e61`、`d90966f`、`6f9d6b7`、`62eefdb`、`891961b`、`386ac69`；数据治理中心 Task 1–8 提交：`41c72bf`、`a1820bd`、`f41f65b`、`33e5c65`、`ff9a3eb`、`e296183`、`6c58ca4`、`7d569a2`、`75c0d5e`；Task 9 为本文所在提交。
- 本地环境：Windows，Python 3.12.12，SQL Server `bjybdb`，PostgreSQL `127.0.0.1:5432/hospital_mcp`；凭据来自既有 gitignored 测试配置，未写入报告。
- 固定 capture instance：`dbo_o_Trade`、`dbo_o_FeeItem`、`dbo_o_Diagnose`。[来源: `src/adapters/insurance_interface/outpatient_cdc.py`]
- 本地 PostgreSQL 已执行幂等初始化，随后 `python scripts/bootstrap_outpatient_store.py --check` 返回 `outpatient store: ready`。

## 自动验证证据

| 层级 | 命令/范围 | 结果 |
|---|---|---|
| T1 | P1 计划列出的 8 个单元测试文件 | 28 passed |
| T2a | `src/tests/integration/api`（计划中的单一 OpenAPI 契约文件在当前仓库不存在，改跑现有 API 全集） | 290 passed |
| T2b | `src/tests/integration/flow/test_outpatient_sync_flow.py` | 1 passed |
| 模块回归 | `src/tests/unit/data_platform src/tests/unit/adapters src/tests/unit/semantic_layer` | 486 passed，15 个既有 Redis `setex` 弃用 warning |
| 静态编译 | `python -m compileall -q src scripts` | 通过 |
| 最新全量 Unit | `src/tests/unit` | 1977 passed，2 skipped |
| 最新全量 API | `src/tests/integration/api` | 301 passed |
| 最新全量 Flow | `src/tests/integration/flow` | 140 passed，1 skipped |
| Portal | Vitest + `next build` | 368 passed；TypeScript 与 38 个路由构建通过 |
| Portal E2E | 数据源、双模式任务、运行记录、只读权限与密码不落 storage | Chromium、WebKit 通过；Firefox 被本机 Next dev HMR WebSocket 环境阻断，待生产态环境复验 |
| 历史项目级收尾（本轮增强前） | `python -m pytest -q --tb=short` | 2409 passed，3 skipped，0 failed；98 个既有 warning |

Flow 覆盖 snapshot、insert/update/delete、同 LSN 重放、诊断主项变化、退款链、自动脱敏核验报告和批次元数据；事务中间观察点只看到上一完整状态。[来源: `src/tests/integration/flow/test_outpatient_sync_flow.py`]

## 目标环境证据

| 项目 | 当前结果 |
|---|---|
| source_id | `bjybdb` |
| SQL Server 门诊源 | 3 张固定表、117 个契约字段可读，三表均有数据 |
| PostgreSQL store | 门诊结构与事务读写 ready，探针已清理 |
| 数据治理主密钥 | 已在 gitignored 根 `.env` 配置，未输出密钥值 |
| worker 控制面 | ready；本地 `total_jobs=1`、`due_jobs=0`，定时 SQL 草稿未启动 |
| 页面 | 概览显示“数据底座可用”；数据源显示三表可读、PG 就绪、CDC 等待 DBA |
| 源快照 | 未执行；本轮只验证接入就绪，不擅自启动数据同步 |
| LSN 范围 / batch_id | 无，不伪造 |
| 语义版本 | 无新发布；发布脚本要求至少一个真实 published batch |
| 非空增量样本数 / P95 | 0 / 样本不足；心跳不计入 |
| CDC 开通人 | 当前库未开启；仅采用 CDC 时再由 DBA 执行 |

当前启动脚本从工作区 `.env` 与主检出目录 `deploy/docker/.env` 读取既有测试凭据，幂等登记并验证 `bjybdb`。端点变更或上次启动中断导致凭据绑定失效时，自动配置使用数据库中的当前 revision 重绑，不回显秘密。[来源: `start-servers.ps1`、`scripts/bootstrap_outpatient_governance.py`]

## 待目标环境执行

1. 经办或运维在页面确认定时 SQL 参数后人工启动，记录首个真实 batch_id；未确认前保持草稿。
2. 仅当医院允许 CDC 时，由 DBA 审核执行 `scripts/enable_outpatient_cdc.sql`，确认 SQL Server Agent、三天 retention 和 `outpatient_cdc_reader` 最小权限。
3. 采用 CDC 时再记录真实 capture instance 与 LSN；采用定时 SQL 时记录时间窗口检查点。
4. 累积至少 100 个非空增量批次后，确认 `published_at - source_committed_at` P95 ≤ 300 秒；不足 100 个只记录样本不足。
5. 运行 `scripts/generate_outpatient_reconciliation.py --batch-id <batch_id>`，由医院核验脱敏差异摘要。

## 回滚

1. 先停止独立 sync worker。
2. 将 `mzjyxx` 活动版本切回目标环境原 v3；保留 PostgreSQL 事件、批次和投影用于审计，不删表。
3. 源 CDC 仅由 DBA 在确认无消费者后禁用。
4. 代码按 Task 8→Task 1 逆序逐提交 `git revert`，不改写历史。
