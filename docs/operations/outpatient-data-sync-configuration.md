# 门诊数据治理与同步配置手册

## 1. 适用范围与当前状态

本手册适用于一家医院的门诊结算单、费用明细和诊断数据同步。源端为 SQL Server `dbo.o_Trade`、`dbo.o_FeeItem`、`dbo.o_Diagnose`，目标端为 PostgreSQL；同步可选 CDC 或受控定时 SQL，不允许页面录入任意 SQL。[来源: `src/adapters/insurance_interface/outpatient_source.py`、`src/apps/portal/app/data-governance/sync-jobs/page.tsx`]

截至 2026-08-31，本工作区状态如下：

| 项目 | 实测结果 |
|---|---|
| 本地主密钥 | 已写入 gitignored 项目根 `.env`；未输出密钥值 |
| PostgreSQL | `scripts/bootstrap_outpatient_store.py --check` 返回 `outpatient store: ready` |
| worker 控制面 | 可读取，当前 `total_jobs=0`、`due_jobs=0` |
| 页面验收 | Portal 367 passed、38 路由构建通过；Chromium/WebKit E2E 通过，Firefox 待无开发态 HMR 干扰的环境复验 |
| 目标医院 SQL Server | **待目标医院 DBA 执行**；当前无真实连接凭据 |
| 真实 LSN / batch_id / P95 | 无，不伪造；须完成院方验收后记录 |

## 2. 页面配置与权限

所有启停必须从 Orca 工作区父目录的中央脚本进入：

```powershell
..\ws.ps1 up outpatient-p0-data-contract
..\ws.ps1 list
..\ws.ps1 url all
```

打开 Portal 的“数据治理”后按以下顺序操作：

1. “数据源”页新增 SQL Server：医院、端点、数据库、只读用户名、凭据 ID 和密码。密码只在提交时传输，不回显、不进入浏览器 storage。
2. 点击“测试连接”；连接通过后下载 CDC 脚本，交 DBA 审核执行。
3. DBA 完成后点击“重新检测 CDC”。只有数据库、三个 capture instance、捕获列和 4320 分钟 retention 全部一致才显示“CDC 已就绪”。
4. “同步任务”页选择 CDC 或定时 SQL，保存后启动。立即执行只表示进入 worker 队列，是否成功以“运行记录”为准。
5. “运行概览”页查看连接、CDC、任务、质量、批次和延迟状态。

`data_governance:read` 可查看状态；`data_governance:write` 才能新增/修改数据源、提交凭据、检测、配置和启停任务。Portal 会隐藏只读用户的写按钮，后端仍执行最终鉴权。[来源: `src/runtime/api/data_governance_routes.py`]

本地启动脚本用 `AUTH_JWT_SECRET` 签发 8 小时开发令牌并注入 Portal；生产环境必须由医院身份系统签发主体和权限，不能沿用开发令牌。[来源: `start-servers.ps1`；建议]

## 3. SQL Server CDC 开通

### 3.1 DBA 前置检查

- 确认目标数据库和三张 `dbo` 源表存在，并核对门诊字段语义。
- 确认 SQL Server Agent 正常运行；CDC capture/cleanup job 可执行。
- 由具备 CDC 管理权限的 DBA 执行脚本，应用账号只授予读取权限。
- 确认源库日志、Agent 和三天 retention 的容量能够承受峰值门诊量。

页面下载的 `scripts/enable_outpatient_cdc.sql` 是唯一受控模板。它幂等开启数据库 CDC，并创建：

- `dbo_o_Trade`
- `dbo_o_FeeItem`
- `dbo_o_Diagnose`

脚本使用 `@supports_net_changes = 0`、角色 `outpatient_cdc_reader`，只捕获门诊契约白名单列，并把 cleanup retention 固定为 `4320` 分钟。[来源: `scripts/enable_outpatient_cdc.sql`]

DBA 执行后，将页面登记的只读账号加入 reader role；账号不得拥有写源表、开启/关闭 CDC 或修改 job 的权限：

```sql
ALTER ROLE outpatient_cdc_reader ADD MEMBER [院方只读账号];
```

### 3.2 验证

脚本末尾会输出数据库 CDC 状态、三个 capture instance、逐列清单和 CDC job retention。页面“重新检测 CDC”还会再次检查：

```sql
SELECT is_cdc_enabled FROM sys.databases WHERE name = DB_NAME();
SELECT capture_instance FROM cdc.change_tables;
SELECT job_type, retention FROM msdb.dbo.cdc_jobs WHERE database_id = DB_ID();
```

任何 capture、列或 retention 不一致都保持“配置异常”；连接不可用不记录虚假 LSN。

## 4. PostgreSQL 与 worker

项目默认目标库为 `postgresql://postgres:***@127.0.0.1:5432/hospital_mcp`，密码可由环境变量覆盖。[来源: `src/config/production.py`]

初始化和只读检查：

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_outpatient_store.py
.\.venv\Scripts\python.exe scripts\bootstrap_outpatient_store.py --check
.\.venv\Scripts\python.exe scripts\run_outpatient_sync_worker.py --status
```

备份示例（密码通过安全环境注入，不写命令行或文档）：

```powershell
pg_dump --format=custom --file hospital_mcp_YYYYMMDD.dump hospital_mcp
```

日常不要直接启动 worker。`..\ws.ps1 up` 会调用工作区执行层，在后端健康后隐藏启动 `scripts/run_outpatient_sync_worker.py`，并把精确 PID 写入 `.server-ports.json`；`..\ws.ps1 down` 只有在 PID 的命令行同时匹配当前 worktree 和 worker 脚本时才停止它。[来源: `start-servers.ps1`、`stop-servers.ps1`]

## 5. 模式选择与参数

| 条件 | 选择 | 默认参数 | 一致性边界 |
|---|---|---|---|
| 院方允许 CDC，Agent 与日志容量可保障 | CDC | 45 秒轮询，可配 30–60 秒 | 目标 1–5 分钟；LSN 精确增量，仍需夜间质量核验 |
| 院方不允许 CDC，但允许只读查询 | 定时 SQL | 5 分钟周期、2 小时重叠回看、每日 02:00 对账、30 天范围 | 最终一致；源数据晚到超过回看窗口时依赖每日对账 |

定时 SQL 只执行代码内固定表、固定列和参数化时间窗口；周期 1–1440 分钟、回看 1–168 小时、对账 1–365 天。首次运行建立基线，后续窗口通过主键差异生成 insert/update/delete；批次与检查点在 PostgreSQL 原子提交。[来源: `src/adapters/insurance_interface/outpatient_polling.py`、`src/data_platform/outpatient_sync.py`]

切换模式前必须暂停并在页面明确确认；切换后下次运行重建基线。医院在选择定时 SQL 前应确认 `T_TradeDate` 的业务语义、索引和峰值查询负载。[建议]

## 6. 主密钥与凭据轮换

首次配置：

```powershell
.\.venv\Scripts\python.exe scripts\configure_data_governance_local.py
```

脚本只操作项目根 `.env`，使用 Fernet 生成密钥、原子写入；已有有效密钥时文件字节不变，拒绝符号链接，不写 SQL Server 密码，也不打印秘密。[来源: `scripts/configure_data_governance_local.py`]

数据源密码轮换直接在“数据源 → 轮换凭据”提交，新 revision 以乐观锁替换旧密文。端点发生变化时必须同时重新输入密码，因为密文与 host/port/database/username 绑定。

当前版本不提供主密钥在线双读轮换。必须在维护窗口执行：暂停全部任务 → 安全备份旧 `.env` → 配置新主密钥 → 在页面重新提交每个数据源密码并测试连接 → 恢复任务；失败时恢复旧 `.env`。不要在工单、日志或版本库粘贴任何密钥/密码。[建议]

## 7. 故障恢复

| 现象 | 处理 |
|---|---|
| `cdc_retention_gap` / “需重建基线” | 暂停任务；确认 CDC job 与 4320 retention；确认模式切换到定时 SQL再切回 CDC，使 `baseline_required` 生效；重新启动并观察新基线。旧检查点不得强行前移。 |
| 连接失败 | 核对网络/防火墙/账号状态；必要时轮换凭据；页面测试连接通过后再启动。错误响应只显示安全错误码。 |
| PostgreSQL 失败 | 恢复 PostgreSQL、检查 schema 和磁盘，再重新启动/立即执行。失败批次不会推进上一检查点。 |
| 质量阻断 | 在概览查看阻断；修复源数据、字段契约或已发布语义模型后重建基线。禁止绕过质量门禁发布给问数。 |
| 模式切换异常 | 先暂停，核对当前 revision，勾选切换确认后保存；下次运行必须建立新基线。 |
| worker 无运行记录 | 执行 `..\ws.ps1 list`，核对 `.server-ports.json` 中 worker PID，再运行 `--status`；不要按进程名批量杀 Python。 |

## 8. 回滚顺序

1. 通过页面暂停同步任务，再执行 `..\ws.ps1 down outpatient-p0-data-contract`。
2. 保留 PostgreSQL 批次、检查点、尝试记录和投影用于审计；不要删表或手工推进检查点。
3. 回滚应用提交并重新启动；需要时恢复维护窗口前的 `.env`。
4. CDC 由 DBA 在确认无其他消费者后再禁用；应用侧无权直接关闭源库 CDC。
5. 重新运行 PostgreSQL `--check`、worker `--status` 和页面只读检查。

目标医院完成真实接入后，应补录 DBA、capture/列核验、首个 LSN、batch_id、至少 100 个非空批次及 P95 延迟；这些证据完成前项目保持 `impl_done`，不能标记 `complete`。[来源: `docs/superpowers/plans/2026-08-31-outpatient-data-governance-center.md` §3]
