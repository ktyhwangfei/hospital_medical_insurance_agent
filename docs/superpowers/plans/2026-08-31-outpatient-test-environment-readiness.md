# Outpatient Test Environment Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用当前测试环境既有凭据自动登记门诊数据源，并以 SQL Server 三表契约可读和 PostgreSQL 可初始化/读写作为唯一总体就绪条件。

**Architecture:** 强化现有 `DataGovernanceService`，不新增第二套健康状态服务。SQL Server 固定查询放在现有门诊轮询适配器，PostgreSQL 读写探测放在现有门诊存储；启动脚本调用一个幂等引导脚本登记数据源和草稿任务，Portal 继续消费现有控制面 API。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、pyodbc、psycopg、PostgreSQL、Next.js 16、React、Vitest、Playwright、PowerShell

---

## File map

- `src/adapters/insurance_interface/outpatient_polling.py`：固定三表全字段可读探测。
- `src/runtime/data_governance/service.py`：总体就绪规则、同步启动门槛和安全消息。
- `src/data_platform/storage/postgresql/outpatient_store.py`：无残留事务读写探测。
- `src/runtime/api/data_governance_schemas.py`：概览公开总体/PG 状态。
- `scripts/bootstrap_outpatient_governance.py`：当前环境幂等登记与默认任务。
- `start-servers.ps1`：安全定位共享 gitignored Docker 凭据并执行引导。
- `src/apps/portal/src/lib/data-governance-api.ts`：前后端 DTO 映射。
- `src/apps/portal/app/data-governance/page.tsx`、`data-sources/page.tsx`：中文总体、源表、PG、CDC 独立状态。
- 对应 Unit、API、Flow、Vitest 和 Playwright 文件：最小回归证据。
- `docs/operations/outpatient-data-sync-configuration.md`、`PROGRESS.md`：真实环境结果与页面验证说明。

### Task 1: SQL Server 三表契约可读探测

**Files:**
- Modify: `src/adapters/insurance_interface/outpatient_polling.py`
- Modify: `src/runtime/data_governance/service.py`
- Test: `src/tests/unit/adapters/test_outpatient_polling.py`
- Test: `src/tests/unit/runtime/test_data_governance_service.py`

- [ ] **Step 1: 写失败测试**

在适配器测试中断言探测对三张表分别执行 `SELECT TOP 1`，SQL 包含 `OUTPATIENT_SOURCE_SPECS` 的全部列；模拟任一查询失败时抛出 `SourceContractMismatchError`，连接仍由服务关闭。在服务测试中把成功消息断言为：

```python
assert result.safe_message == "门诊 3 张源表及 117 个契约字段可读"
```

- [ ] **Step 2: 验证测试先红**

Run: `.venv\Scripts\python.exe -m pytest src/tests/unit/adapters/test_outpatient_polling.py src/tests/unit/runtime/test_data_governance_service.py -q`

Expected: FAIL，现有服务只允许 `SELECT 1`。

- [ ] **Step 3: 最小实现**

增加并复用一个固定探测函数：

```python
def probe_outpatient_readiness(connection) -> tuple[int, int]:
    cursor = connection.cursor()
    try:
        for spec in OUTPATIENT_SOURCE_SPECS.values():
            columns = ", ".join(f"[{column}]" for column in spec.columns)
            cursor.execute(
                f"SELECT TOP 1 {columns} FROM [dbo].[{spec.table_name}]"
            )
            cursor.fetchone()
    except Exception as exc:
        raise SourceContractMismatchError("门诊源表不可直接读取") from exc
    return len(OUTPATIENT_SOURCE_SPECS), sum(
        len(spec.columns) for spec in OUTPATIENT_SOURCE_SPECS.values()
    )
```

`probe_connection()` 调用该函数；只返回安全错误码和固定中文消息。

- [ ] **Step 4: 运行 Unit 并提交**

Run: `.venv\Scripts\python.exe -m pytest src/tests/unit/adapters/test_outpatient_polling.py src/tests/unit/runtime/test_data_governance_service.py -q`

Expected: PASS

Commit: `feat: 校验门诊三表可直接读取`

### Task 2: PostgreSQL 结构与事务读写及总体状态

**Files:**
- Modify: `src/data_platform/storage/postgresql/outpatient_store.py`
- Modify: `src/data_platform/outpatient_governance.py`
- Modify: `src/runtime/api/data_governance_schemas.py`
- Modify: `src/runtime/data_governance/service.py`
- Test: `src/tests/unit/data_platform/test_outpatient_store.py`
- Test: `src/tests/unit/runtime/test_data_governance_service.py`

- [ ] **Step 1: 写失败测试**

测试 `check_writable()` 在同一事务插入、读取并删除唯一探测行；测试概览只有在至少一个源 `healthy` 且 PG `healthy/schema_ready` 时 `platform_ready=True`；CDC 为 `waiting_dba` 不影响结果。测试任意同步模式在源或 PG 未就绪时不能启动，CDC 模式仍额外要求 `cdc_status=ready`。

- [ ] **Step 2: 验证测试先红**

Run: `.venv\Scripts\python.exe -m pytest src/tests/unit/data_platform/test_outpatient_store.py src/tests/unit/runtime/test_data_governance_service.py -q`

Expected: FAIL，缺少 `check_writable` 和总体状态。

- [ ] **Step 3: 最小实现**

PG 探测使用真实控制表且提交后无残留：

```python
def check_writable(self) -> bool:
    probe_id = f"__readiness__{uuid4()}"
    with self._client.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO outpatient_sync_checkpoints "
                "(source_id, source_mode, last_batch_id, updated_at) "
                "VALUES (%s, 'scheduled_sql', %s, NOW())",
                (probe_id, probe_id),
            )
            cursor.execute(
                "SELECT 1 FROM outpatient_sync_checkpoints WHERE source_id = %s",
                (probe_id,),
            )
            ready = cursor.fetchone() is not None
            cursor.execute(
                "DELETE FROM outpatient_sync_checkpoints WHERE source_id = %s",
                (probe_id,),
            )
    return ready
```

`DataGovernanceOverview` 增加：

```python
platform_ready: bool = False
postgresql: PostgresTargetStatus
```

总体就绪只计算源表与 PG；`start_job()` 复用同一门槛。

- [ ] **Step 4: 运行 Unit 并提交**

Run: `.venv\Scripts\python.exe -m pytest src/tests/unit/data_platform/test_outpatient_store.py src/tests/unit/runtime/test_data_governance_service.py -q`

Expected: PASS

Commit: `feat: 建立门诊数据底座唯一就绪判定`

### Task 3: 当前测试环境幂等自动配置

**Files:**
- Create: `scripts/bootstrap_outpatient_governance.py`
- Modify: `start-servers.ps1`
- Create: `src/tests/unit/scripts/test_bootstrap_outpatient_governance.py`
- Modify: `src/tests/unit/scripts/test_configure_data_governance_local.py`

- [ ] **Step 1: 写失败测试**

构造空内存控制面，调用 `bootstrap(service, command)` 两次，断言只创建一个 `bjybdb` 源和一个 `scheduled_sql` 草稿任务，两次均通过 SQL Server/PG 就绪检查，输出不包含密码。PowerShell 文本测试断言使用 `git rev-parse --git-common-dir` 查找主检出目录的 `deploy/docker/.env`，并在启动后端前调用引导脚本。

- [ ] **Step 2: 验证测试先红**

Run: `.venv\Scripts\python.exe -m pytest src/tests/unit/scripts/test_bootstrap_outpatient_governance.py src/tests/unit/scripts/test_configure_data_governance_local.py -q`

Expected: FAIL，脚本尚不存在。

- [ ] **Step 3: 最小实现**

脚本只读取以下既有环境变量：

```python
required = ("MSSQL_HOST", "MSSQL_DATABASE", "MSSQL_USER", "MSSQL_PASSWORD")
command = CreateDataSourceCommand(
    source_id=os.getenv("OUTPATIENT_SOURCE_ID", "bjybdb"),
    hospital_code=os.getenv("OUTPATIENT_HOSPITAL_CODE", "TEST001"),
    hospital_name=os.getenv("OUTPATIENT_HOSPITAL_NAME", "测试医院门诊"),
    name="门诊医保库",
    host=os.environ["MSSQL_HOST"],
    port=int(os.getenv("MSSQL_PORT", "1433")),
    database=os.environ["MSSQL_DATABASE"],
    schema_name="dbo",
    username=os.environ["MSSQL_USER"],
    credential_id="credential.bjybdb",
    password=os.environ["MSSQL_PASSWORD"],
)
```

首次创建源和默认草稿任务；已存在时先用加密存储中的凭据探测，只有端点变化或认证失败才更新/轮换。任何就绪检查失败时脚本非零退出，输出只含安全状态。

- [ ] **Step 4: 运行 Unit 并提交**

Run: `.venv\Scripts\python.exe -m pytest src/tests/unit/scripts/test_bootstrap_outpatient_governance.py src/tests/unit/scripts/test_configure_data_governance_local.py -q`

Expected: PASS

Commit: `feat: 自动配置当前门诊测试数据源`

### Task 4: API 与中文 Portal 状态

**Files:**
- Modify: `src/tests/integration/api/test_data_governance_api.py`
- Modify: `src/apps/portal/src/lib/data-governance-api.ts`
- Modify: `src/apps/portal/app/data-governance/page.tsx`
- Modify: `src/apps/portal/app/data-governance/data-sources/page.tsx`
- Modify: `src/apps/portal/src/tests/data-governance-overview.test.tsx`
- Modify: `src/apps/portal/src/tests/data-governance-data-sources.test.tsx`

- [ ] **Step 1: 写失败的 API 与组件测试**

API 断言 `/overview` 返回：

```json
{
  "platform_ready": true,
  "postgresql": {
    "connection_status": "healthy",
    "schema_ready": true,
    "safe_message": "PostgreSQL 门诊结构及读写已就绪"
  }
}
```

Vitest 断言页面显示“数据底座可用”“门诊源表”“门诊 3 张源表及 117 个契约字段可读”“CDC 等待 DBA”，且 PG 状态独立显示。

- [ ] **Step 2: 验证测试先红**

Run: `.venv\Scripts\python.exe -m pytest src/tests/integration/api/test_data_governance_api.py -q`

Run: `npm test -- --run src/tests/data-governance-overview.test.tsx src/tests/data-governance-data-sources.test.tsx`

Workdir: `src/apps/portal`

Expected: FAIL，DTO 和页面尚未展示总体状态。

- [ ] **Step 3: 最小实现**

API client 映射 `platform_ready` 和 `postgresql`；概览首张卡显示总体状态，表头“连接”改为“门诊源表”；数据源页在每个源下显示 `safeProbeMessage`，CDC 仍保留独立列。

- [ ] **Step 4: 运行 API、Vitest、构建并提交**

Run: `.venv\Scripts\python.exe -m pytest src/tests/integration/api/test_data_governance_api.py -q`

Run: `npm test -- --run src/tests/data-governance-overview.test.tsx src/tests/data-governance-data-sources.test.tsx`

Run: `npm run build`

Expected: 全部 PASS

Commit: `feat: 展示门诊数据底座真实就绪状态`

### Task 5: 真实 Flow、Portal/E2E、文档和全量验证

**Files:**
- Modify: `src/tests/integration/flow/test_outpatient_data_governance_flow.py`
- Modify: `src/tests/e2e/flows/portal/data-governance.flow.ts`
- Modify: `src/tests/e2e/pages/portal/data-governance.page.ts`
- Modify: `docs/operations/outpatient-data-sync-configuration.md`
- Modify: `docs/reviews/2026-08-28-outpatient-p1-verification.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 写失败 Flow/E2E 测试**

Flow 从空控制面自动登记当前环境并断言：源 `healthy`、PG `healthy/schema_ready`、CDC `waiting_dba`、默认任务 `draft/scheduled_sql`、总体 `platform_ready=True`。Playwright mock 与页面对象断言同样四个中文状态，且密码不出现在 DOM 和浏览器存储。

- [ ] **Step 2: 按硬性顺序验证**

Unit:

` .venv\Scripts\python.exe -m pytest src/tests/unit -q `

API:

` .venv\Scripts\python.exe -m pytest src/tests/integration/api -q `

Flow:

` .venv\Scripts\python.exe -m pytest src/tests/integration/flow -q `

Portal:

` npm test -- --run ` 与 `npm run build`

E2E 服务必须通过中央 `..\ws.ps1` 启停，运行 Playwright Chromium/WebKit；Firefox 若仍受当前 Next dev HMR 环境限制，必须保留独立证据，不能把它冒充功能失败。

- [ ] **Step 3: 执行当前测试环境引导和真实 API/页面验证**

通过中央脚本启动工作区。断言引导输出不含连接串和密码；PG 控制面恰有 `bjybdb`、一个草稿任务；API/页面显示总体可用、三表可读、PG 已就绪和 CDC 等待 DBA。不得自动启动全量任务。

- [ ] **Step 4: 更新文档与最终提交**

文档记录当前测试环境真实表/字段/PG 读写结果、凭据来源位置但不记录值、页面 URL、启动/停止命令、CDC 非成功门槛及 DBA 后续步骤。

Commit: `test: 验证门诊数据治理真实测试环境`
