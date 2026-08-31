# 门诊医保近实时数据底座 P1 验证记录

## 结论

截至 2026-08-31，P1 Task 1–8 的代码、脱敏核验和本地三层验证完成，状态为 `impl_done`；目标环境验收未完成，不能标记 `complete`。[来源: `docs/superpowers/plans/2026-08-28-outpatient-p1-near-real-time-data-foundation.md` §1、Task 8]

## 代码与环境

- 分支：`feature/outpatient-p0-data-contract`；Task 1–7 提交：`d0d70c4`、`1520e61`、`d90966f`、`6f9d6b7`、`62eefdb`、`891961b`、`386ac69`；Task 8 为本文所在提交。
- 本地环境：Windows，Python 3.12.12，PostgreSQL `127.0.0.1:5432/hospital_mcp`。
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
| 项目级收尾 | `python -m pytest -q --tb=short` | 2364 passed，2 skipped，0 failed；99 个既有 warning |

Flow 覆盖 snapshot、insert/update/delete、同 LSN 重放、诊断主项变化、退款链、自动脱敏核验报告和批次元数据；事务中间观察点只看到上一完整状态。[来源: `src/tests/integration/flow/test_outpatient_sync_flow.py`]

## 目标环境证据

| 项目 | 当前结果 |
|---|---|
| source_id | `bjybdb` |
| PostgreSQL store | ready |
| 源快照 | 未执行成功；在连接前返回“数据源未注册、未启用或缺少连接配置” |
| LSN 范围 / batch_id | 无，不伪造 |
| 语义版本 | 无新发布；发布脚本要求至少一个真实 published batch |
| 非空增量样本数 / P95 | 0 / 样本不足；心跳不计入 |
| CDC 开通人 | 未提供，待目标环境 DBA 指派 |

当前 `.env` 仅存在 `MSSQL_HOST`、`MSSQL_DRIVER` 相关键，Semantic Registry 未解析到可用的 `bjybdb` connection config。该失败发生在源查询之前，未写入批次。[来源: 2026-08-31 本地 `run_outpatient_cdc_sync.py --source-id bjybdb --once/--status` 实测]

## 待目标环境执行

1. 数据源管理员在现有 `policy_datasource` 注册并启用 `bjybdb` 的完整只读连接配置；不在代码或报告中保存凭据。
2. DBA 审核执行 `scripts/enable_outpatient_cdc.sql`，确认 SQL Server Agent、三天 retention 和 `outpatient_cdc_reader` 最小权限。
3. 依次执行 store check、单次快照、status、语义发布；记录真实 capture instance、LSN、batch_id 与语义版本。
4. 累积至少 100 个非空增量批次后，确认 `published_at - source_committed_at` P95 ≤ 300 秒；不足 100 个只记录样本不足。
5. 运行 `scripts/generate_outpatient_reconciliation.py --batch-id <batch_id>`，由医院核验脱敏差异摘要。

## 回滚

1. 先停止独立 sync worker。
2. 将 `mzjyxx` 活动版本切回目标环境原 v3；保留 PostgreSQL 事件、批次和投影用于审计，不删表。
3. 源 CDC 仅由 DBA 在确认无消费者后禁用。
4. 代码按 Task 8→Task 1 逆序逐提交 `git revert`，不改写历史。
