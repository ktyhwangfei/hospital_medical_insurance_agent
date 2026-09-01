# 门诊数据治理中心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有门诊 P1 数据底座上增加独立数据治理中心，使医院可以安全配置 SQL Server 数据源、查看 PostgreSQL 落地状态，并在 CDC 与受控定时 SQL 两种同步方式之间选择、运行和审计。

**Architecture:** 先把现有 CDC 专用批次收口为来源中立契约，再增加 PostgreSQL 控制面、加密凭据、定时 SQL 适配器和常驻 worker。FastAPI 只暴露受控配置与状态 API，Portal 新增独立 `/data-governance` 工作台；两种同步模式最终仍走同一个确定性加工和原子发布服务。

**Tech Stack:** Python 3.12+、FastAPI、Pydantic v2、pyodbc、cryptography/Fernet、PostgreSQL、Next.js 16、React 19、TypeScript、Vitest、Playwright、pytest；不新增依赖。

---

## 0. 实施边界与成功标准

- 设计基线：`docs/superpowers/specs/2026-08-31-outpatient-data-governance-center-design.md`，四部分设计及书面规格均已确认。
- 工作区：`D:/project/hospital_medical_insurance_agent/.worktrees/outpatient-p0-data-contract`；在现有 P1 提交之后继续，不重新实现已完成的 CDC、PG 投影和语义模型。
- 风险等级：数据底座、凭据和数据库配置按 R4 验证，严格执行 Unit → API → Flow；Portal 再执行 Vitest → build → Playwright。[来源: `docs/governance/TEST-VERIFICATION-MATRIX.md`]
- 数据库级 `sp_cdc_enable_db/table` 只能由医院 DBA 执行；应用只生成脚本并检测结果。
- 页面不允许输入任意 SQL、表名、capture instance 或患者信息。
- PostgreSQL 是平台落地库，不开启逻辑复制；页面只读展示其连接和结构状态。
- 当前环境没有已验证的目标 SQL Server 凭据。代码与页面完成不等于目标医院 CDC 已开通；真实状态必须显示“待配置/待 DBA”。
- 完成时必须有独立提交、无未跟踪改动，并更新运维手册和 `PROGRESS.md`。

## 1. 文件职责图

### 新增后端文件

- `src/adapters/insurance_interface/outpatient_source.py`：来源中立的门诊读取契约、固定源表白名单和检查点类型。
- `src/adapters/insurance_interface/outpatient_polling.py`：受控定时 SQL 读取适配器。
- `src/data_platform/outpatient_governance.py`：数据源、凭据、任务、尝试和状态模型。
- `src/data_platform/storage/postgresql/outpatient_governance_store.py`：控制面 PostgreSQL DDL 与事务 CRUD。
- `src/security/data_source_credentials.py`：数据源凭据认证加密和端点绑定。
- `src/runtime/data_governance/__init__.py`：包边界。
- `src/runtime/data_governance/service.py`：数据源配置、检测、任务动作和概览应用服务。
- `src/runtime/data_governance/worker.py`：领取到期任务并执行单批。
- `src/runtime/api/data_governance_schemas.py`：公开 Pydantic API 契约。
- `src/runtime/api/data_governance_routes.py`：鉴权、错误归一化和路由。
- `scripts/run_outpatient_sync_worker.py`：常驻 worker CLI。
- `scripts/configure_data_governance_local.py`：为 gitignored `.env` 幂等生成持久主密钥，不打印秘密。

### 新增 Portal 文件

- `src/apps/portal/src/lib/data-governance-api.ts`：DTO 校验、snake_case → camelCase 和鉴权请求。
- `src/apps/portal/app/data-governance/layout.tsx`：三个页签共用布局。
- `src/apps/portal/app/data-governance/page.tsx`：运行概览。
- `src/apps/portal/app/data-governance/data-sources/page.tsx`：数据源与凭据操作。
- `src/apps/portal/app/data-governance/sync-jobs/page.tsx`：同步任务与运行记录。

### 主要修改文件

- `src/adapters/insurance_interface/outpatient_cdc.py`
- `src/data_platform/outpatient_sync.py`
- `src/data_platform/storage/postgresql/outpatient_store.py`
- `src/runtime/api/app.py`
- `src/apps/portal/app/layout.tsx`
- `src/apps/portal/app/semantic-layer/discovery/page.tsx`
- `scripts/enable_outpatient_cdc.sql`
- `start-servers.ps1`
- `stop-servers.ps1`
- `src/domain/AGENTS.md`
- `docs/operations/outpatient-data-sync-configuration.md`
- `PROGRESS.md`

---

### Task 1：将 CDC 专用批次收口为来源中立契约

**Files:**
- Create: `src/adapters/insurance_interface/outpatient_source.py`
- Modify: `src/adapters/insurance_interface/outpatient_cdc.py`
- Modify: `src/data_platform/outpatient_sync.py`
- Modify: `src/data_platform/storage/postgresql/outpatient_store.py`
- Modify: `src/tests/unit/adapters/test_outpatient_cdc.py`
- Modify: `src/tests/unit/data_platform/test_outpatient_sync.py`
- Modify: `src/tests/unit/data_platform/test_outpatient_store.py`

- [ ] **Step 1: 先写来源中立契约失败测试**

在现有三个测试文件中增加以下断言，要求 CDC 适配器不再向数据平台暴露 CDC 专用批次类：

```python
from datetime import datetime, timezone

from src.adapters.insurance_interface.outpatient_source import (
    CheckpointKind,
    OutpatientCheckpoint,
    OutpatientSourceMode,
)


def test_outpatient_checkpoint_is_source_neutral():
    checkpoint = OutpatientCheckpoint(
        kind=CheckpointKind.LSN,
        value="0000002a",
        observed_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    assert checkpoint.kind is CheckpointKind.LSN
    assert checkpoint.value == "0000002a"


def test_cdc_source_returns_neutral_batch(cdc_source):
    batch = cdc_source.read(None)
    assert batch.mode is OutpatientSourceMode.CDC
    assert batch.checkpoint.kind is CheckpointKind.LSN
    assert batch.snapshot_rows is not None
```

存储测试增加：检查点不再要求 `last_lsn NOT NULL`，批次用 `batch_key` 幂等，事件表名为 `outpatient_sync_events`，当前投影使用 `source_cursor` 比较新旧。

同时断言 `mz_trade` 和 `mz_fee_item` 不暴露 `quality_status='blocked'` 的交易；blocked 事件和投影仍保留用于修复与审计。

- [ ] **Step 2: 运行测试并确认先红**

Run:

```powershell
uv run python -m pytest src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/data_platform/test_outpatient_sync.py src/tests/unit/data_platform/test_outpatient_store.py -v --tb=short
```

Expected: `outpatient_source` 不存在，或 CDC 返回旧 `OutpatientSnapshot/OutpatientCdcBatch` 导致断言失败。

- [ ] **Step 3: 新增来源中立类型**

`outpatient_source.py` 的公开契约固定为：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class OutpatientSourceMode(StrEnum):
    CDC = "cdc"
    SCHEDULED_SQL = "scheduled_sql"


class CheckpointKind(StrEnum):
    LSN = "lsn"
    TIME_WINDOW = "time_window"


@dataclass(frozen=True)
class OutpatientCheckpoint:
    kind: CheckpointKind
    value: str
    observed_at: datetime


@dataclass(frozen=True)
class OutpatientChange:
    capture_instance: str
    source_cursor: bytes
    operation: int
    commit_time: datetime | None
    source_key: tuple[Any, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class OutpatientSourceBatch:
    mode: OutpatientSourceMode
    checkpoint: OutpatientCheckpoint
    changes: tuple[OutpatientChange, ...] = ()
    snapshot_rows: dict[str, tuple[dict[str, Any], ...]] | None = None
    scope_trade_nos: frozenset[str] = field(default_factory=frozenset)
    is_baseline: bool = False


class OutpatientSource(Protocol):
    def read(self, checkpoint: OutpatientCheckpoint | None) -> OutpatientSourceBatch:
        raise NotImplementedError
```

`OUTPATIENT_SOURCE_SPECS` 和 `OutpatientSourceSpec` 一并移入该文件；两个具体适配器只实现 `read()`。

- [ ] **Step 4: 用来源中立检查点改造 CDC 与同步服务**

CDC 适配器把 LSN 十六进制编码到检查点，把 `start_lsn + seqval` 拼成可排序的 `source_cursor`：

```python
def _cdc_cursor(start_lsn: bytes, seqval: bytes) -> bytes:
    return start_lsn + seqval


def _lsn_checkpoint(value: bytes, observed_at: datetime) -> OutpatientCheckpoint:
    return OutpatientCheckpoint(
        kind=CheckpointKind.LSN,
        value=value.hex(),
        observed_at=observed_at,
    )
```

`OutpatientSyncService.run_once()` 只调用 `source.read(checkpoint)`，将 `batch.snapshot_rows` 转换为确定性 change，或直接处理 `batch.changes`，最后把完整 batch 传给 store。CDC retention gap 仍由适配器在读取前关闭失败。

- [ ] **Step 5: 迁移 PostgreSQL DDL 与原子发布参数**

检查点和批次新增来源中立字段，保留旧 LSN 列为可空兼容列；新事件写入 `outpatient_sync_events`：

```sql
CREATE TABLE IF NOT EXISTS outpatient_sync_events (
    event_key VARCHAR(64) PRIMARY KEY,
    source_id VARCHAR(64) NOT NULL,
    source_mode VARCHAR(32) NOT NULL,
    capture_instance VARCHAR(128) NOT NULL,
    source_cursor BYTEA NOT NULL,
    operation INTEGER NOT NULL CHECK(operation IN (1, 2, 4)),
    commit_time TIMESTAMPTZ,
    source_key JSONB NOT NULL,
    payload JSONB NOT NULL,
    data_batch_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, source_mode, capture_instance, source_cursor, operation)
);
ALTER TABLE outpatient_sync_checkpoints ADD COLUMN IF NOT EXISTS source_mode VARCHAR(32);
ALTER TABLE outpatient_sync_checkpoints ADD COLUMN IF NOT EXISTS checkpoint_kind VARCHAR(32);
ALTER TABLE outpatient_sync_checkpoints ADD COLUMN IF NOT EXISTS checkpoint_value TEXT;
ALTER TABLE outpatient_sync_batches ADD COLUMN IF NOT EXISTS batch_key VARCHAR(64);
ALTER TABLE outpatient_sync_batches ADD COLUMN IF NOT EXISTS source_mode VARCHAR(32);
ALTER TABLE outpatient_sync_batches ADD COLUMN IF NOT EXISTS checkpoint_kind VARCHAR(32);
ALTER TABLE outpatient_sync_batches ADD COLUMN IF NOT EXISTS checkpoint_value TEXT;
```

事件键使用 Python `sha256` 计算；API 和日志不返回 `source_cursor`。当前投影新增 `source_cursor BYTEA`，UPSERT 只允许新 cursor 不小于现值。

`mz_trade` 视图增加 `quality_status <> 'blocked'`；`mz_fee_item` 固定 JOIN `outpatient_trade_current` 并应用同一交易质量过滤，避免阻断交易的明细单独进入查询模型。

- [ ] **Step 6: 再跑测试并提交**

Run:

```powershell
uv run python -m pytest src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/data_platform/test_outpatient_sync.py src/tests/unit/data_platform/test_outpatient_store.py -v --tb=short
```

Expected: PASS。

Commit:

```powershell
git add src/adapters/insurance_interface/outpatient_source.py src/adapters/insurance_interface/outpatient_cdc.py src/data_platform/outpatient_sync.py src/data_platform/storage/postgresql/outpatient_store.py src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/data_platform/test_outpatient_sync.py src/tests/unit/data_platform/test_outpatient_store.py
git commit -m "refactor: 中立化门诊同步批次契约"
```

### Task 2：建立数据源、加密凭据和同步任务控制面

**Files:**
- Create: `src/data_platform/outpatient_governance.py`
- Create: `src/data_platform/storage/postgresql/outpatient_governance_store.py`
- Create: `src/security/data_source_credentials.py`
- Create: `src/tests/unit/security/test_data_source_credentials.py`
- Create: `src/tests/unit/data_platform/test_outpatient_governance_store.py`
- Modify: `src/domain/AGENTS.md`

- [ ] **Step 1: 写凭据和控制面存储失败测试**

```python
from cryptography.fernet import Fernet
import pytest

from src.security.data_source_credentials import (
    DataSourceCredentialError,
    DataSourceCredentialVault,
)


def test_datasource_password_is_encrypted_and_endpoint_bound(monkeypatch):
    monkeypatch.setenv(
        "DATA_GOVERNANCE_MASTER_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    vault = DataSourceCredentialVault()
    credential = vault.seal(
        credential_id="credential.bjybdb",
        password="secret-value",
        endpoint="sqlserver://db.example:1433/bjybdb/readonly",
        actor="admin-1",
        revision=1,
    )
    assert "secret-value" not in credential.model_dump_json()
    assert vault.reveal(
        credential,
        endpoint="sqlserver://db.example:1433/bjybdb/readonly",
    ) == "secret-value"
    with pytest.raises(DataSourceCredentialError, match="端点"):
        vault.reveal(
            credential,
            endpoint="sqlserver://other.example:1433/bjybdb/readonly",
        )
```

存储测试用 fake `PostgreSQLClient` 断言四张表同时包含 CREATE 与 ALTER；`create_source_with_credential()` 在一个事务中写入数据源和凭据；读取数据源绝不返回密文。

- [ ] **Step 2: 运行测试并确认先红**

```powershell
uv run python -m pytest src/tests/unit/security/test_data_source_credentials.py src/tests/unit/data_platform/test_outpatient_governance_store.py -v --tb=short
```

Expected: 两个模块不存在。

- [ ] **Step 3: 定义控制面模型**

`outpatient_governance.py` 使用 Pydantic 模型和字符串枚举：

```python
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class ConnectionStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    ERROR = "error"


class CdcEnablementStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    NOT_CHECKED = "not_checked"
    WAITING_DBA = "waiting_dba"
    READY = "ready"
    INVALID = "invalid"


class SyncJobStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    DEGRADED = "degraded"
    FAILED = "failed"


class OutpatientDataSource(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    hospital_code: str = Field(min_length=1, max_length=64)
    hospital_name: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=1433, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    schema_name: str = Field(default="dbo", pattern=r"^[A-Za-z0-9_]+$")
    username: str = Field(min_length=1, max_length=128)
    credential_id: str
    credential_configured: bool = True
    connection_status: ConnectionStatus = ConnectionStatus.UNKNOWN
    cdc_status: CdcEnablementStatus = CdcEnablementStatus.NOT_CHECKED
    created_at: datetime
    updated_at: datetime
```

同文件定义 `DataSourceCredential`、`OutpatientSyncJob`、`OutpatientSyncAttempt` 和 `PostgresTargetStatus`；公开模型不包含 `encrypted_password`。

- [ ] **Step 4: 实现凭据加密边界**

`DataSourceCredentialVault` 复用项目已安装的 `cryptography.Fernet` 模式，使用 `DATA_GOVERNANCE_MASTER_KEY`，保存 `sha256` 秘密指纹与端点指纹。缺密钥、格式错误、端点变化或解密失败均抛 `DataSourceCredentialError`；错误文本不含密码、密文或连接串。

同文件提供 `data_source_endpoint(host, port, database, username)`，只生成用于端点指纹的规范字符串，不用于日志或 API 返回。

- [ ] **Step 5: 实现 PostgreSQL 控制面存储**

创建并幂等迁移以下四张表：

```sql
CREATE TABLE IF NOT EXISTS outpatient_data_sources (
    source_id VARCHAR(64) PRIMARY KEY,
    hospital_code VARCHAR(64) NOT NULL,
    hospital_name VARCHAR(128) NOT NULL,
    name VARCHAR(128) NOT NULL,
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
    database_name VARCHAR(128) NOT NULL,
    schema_name VARCHAR(64) NOT NULL DEFAULT 'dbo',
    username VARCHAR(128) NOT NULL,
    credential_id VARCHAR(128) NOT NULL,
    connection_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    cdc_status VARCHAR(32) NOT NULL DEFAULT 'not_checked',
    safe_probe_message TEXT,
    last_probed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS outpatient_data_source_credentials (
    credential_id VARCHAR(128) PRIMARY KEY,
    encrypted_password TEXT NOT NULL,
    secret_fingerprint VARCHAR(64) NOT NULL,
    endpoint_fingerprint VARCHAR(64) NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    updated_by VARCHAR(128) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS outpatient_sync_jobs (
    source_id VARCHAR(64) PRIMARY KEY REFERENCES outpatient_data_sources(source_id),
    source_mode VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    cdc_poll_interval_seconds INTEGER NOT NULL DEFAULT 45,
    schedule_interval_minutes INTEGER NOT NULL DEFAULT 5,
    lookback_hours INTEGER NOT NULL DEFAULT 2,
    reconcile_time TIME NOT NULL DEFAULT '02:00:00',
    reconcile_days INTEGER NOT NULL DEFAULT 30,
    revision INTEGER NOT NULL DEFAULT 1,
    baseline_required BOOLEAN NOT NULL DEFAULT TRUE,
    next_run_at TIMESTAMPTZ,
    run_once_requested_at TIMESTAMPTZ,
    active_attempt_id VARCHAR(64),
    last_started_at TIMESTAMPTZ,
    last_succeeded_at TIMESTAMPTZ,
    last_reconciled_at TIMESTAMPTZ,
    last_error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS outpatient_sync_attempts (
    attempt_id VARCHAR(64) PRIMARY KEY,
    source_id VARCHAR(64) NOT NULL REFERENCES outpatient_data_sources(source_id),
    source_mode VARCHAR(32) NOT NULL,
    run_kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    safe_error_code VARCHAR(64),
    safe_message VARCHAR(256),
    row_count INTEGER NOT NULL DEFAULT 0,
    batch_id VARCHAR(64)
);
```

每个 CREATE 字段都补对应的 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 迁移语句。实现 `ensure_schema`、`create_source_with_credential`、`list_sources`、`get_source`、`update_source`、`get_credential`、`rotate_credential`、`get_job`、`save_job` 和 `list_attempts`；创建数据源与凭据、轮换凭据与 revision 校验都必须使用现有 `PostgreSQLClient.transaction()`。不引入存储 Protocol 或内存生产回退，测试通过构造器注入 fake client。

- [ ] **Step 6: 更新通用语言并验证**

在 `src/domain/AGENTS.md` 增加“门诊数据源、同步任务、同步尝试、来源检查点”唯一命名，禁止后续再出现 `pipeline/source job/import task` 等同义模型。

Run:

```powershell
uv run python -m pytest src/tests/unit/security/test_data_source_credentials.py src/tests/unit/data_platform/test_outpatient_governance_store.py -v --tb=short
```

Expected: PASS。

Commit:

```powershell
git add src/data_platform/outpatient_governance.py src/data_platform/storage/postgresql/outpatient_governance_store.py src/security/data_source_credentials.py src/tests/unit/security/test_data_source_credentials.py src/tests/unit/data_platform/test_outpatient_governance_store.py src/domain/AGENTS.md
git commit -m "feat: 建立门诊数据源安全控制面"
```

### Task 3：实现 SQL Server 连接检测与 CDC 开通控制

**Files:**
- Modify: `scripts/enable_outpatient_cdc.sql`
- Modify: `src/adapters/insurance_interface/outpatient_cdc.py`
- Create: `src/runtime/data_governance/__init__.py`
- Create: `src/runtime/data_governance/service.py`
- Modify: `src/tests/unit/adapters/test_outpatient_cdc_sql.py`
- Modify: `src/tests/unit/adapters/test_outpatient_cdc.py`
- Create: `src/tests/unit/runtime/test_data_governance_service.py`

- [ ] **Step 1: 写 CDC 脚本、探测和秘密不回显失败测试**

CDC 脚本测试增加以下约束：

```python
def test_cdc_script_targets_current_validated_database(script_text):
    assert "DB_NAME() <> N'bjyb'" not in script_text
    assert "Required outpatient source tables are missing" in script_text
    assert "sys.sp_cdc_enable_db" in script_text
    assert "sys.sp_cdc_enable_table" in script_text
    assert "DROP " not in script_text.upper()
```

适配器 fake cursor 返回数据库、capture instance、捕获列和 cleanup job；测试断言探测结果只含结构化状态：

```python
def test_probe_cdc_reports_waiting_dba_without_raw_error(source_without_cdc):
    result = source_without_cdc.probe_cdc()
    assert result.database_enabled is False
    assert result.status == "waiting_dba"
    assert result.safe_message == "数据库尚未开启 CDC"
```

服务测试创建数据源后断言 `model_dump_json()` 不含提交密码，连接失败只返回 `authentication_failed/timeout/source_contract_mismatch/connection_failed` 之一。

- [ ] **Step 2: 运行测试并确认先红**

```powershell
uv run python -m pytest src/tests/unit/adapters/test_outpatient_cdc_sql.py src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/runtime/test_data_governance_service.py -v --tb=short
```

Expected: 硬编码数据库检查仍存在，`probe_cdc` 和治理服务不存在。

- [ ] **Step 3: 修正受控 CDC 脚本**

删除对数据库名称 `bjyb` 的硬编码，只允许 DBA 在当前已连接数据库执行，并保留三表/字段前置校验。脚本仍固定 capture instance、捕获列、reader role 和 4320 分钟 retention；末尾输出数据库 CDC 状态、capture instance、捕获列和 job retention，不增加关闭或删除语句。

- [ ] **Step 4: 实现类型化 CDC 探测**

在 `outpatient_cdc.py` 增加只读结果：

```python
@dataclass(frozen=True)
class OutpatientCdcProbe:
    status: str
    database_enabled: bool
    ready_captures: tuple[str, ...]
    missing_captures: tuple[str, ...]
    retention_minutes: int | None
    safe_message: str
    checked_at: datetime
```

`probe_cdc()` 只执行固定查询：`sys.databases`、`cdc.change_tables`、`cdc.captured_columns`、`msdb.dbo.cdc_jobs`。三实例、捕获列和 retention 全部匹配才返回 `ready`；权限不足或查询失败转换为 `invalid` 与安全消息。

- [ ] **Step 5: 实现数据治理应用服务**

`DataGovernanceService` 构造器注入 `OutpatientGovernanceStore`、`OutpatientPostgresStore` 和连接工厂。具体职责：

```python
@dataclass(frozen=True)
class CreateDataSourceCommand:
    source_id: str
    hospital_code: str
    hospital_name: str
    name: str
    host: str
    port: int
    database: str
    schema_name: str
    username: str
    credential_id: str
    password: str


class DataGovernanceService:
    def create_source(
        self,
        command: CreateDataSourceCommand,
        actor: str,
    ) -> OutpatientDataSource:
        now = datetime.now(timezone.utc)
        endpoint = data_source_endpoint(
            command.host,
            command.port,
            command.database,
            command.username,
        )
        credential = self._vault.seal(
            credential_id=command.credential_id,
            password=command.password,
            endpoint=endpoint,
            actor=actor,
            revision=1,
        )
        source = OutpatientDataSource(
            source_id=command.source_id,
            hospital_code=command.hospital_code,
            hospital_name=command.hospital_name,
            name=command.name,
            host=command.host,
            port=command.port,
            database=command.database,
            schema_name=command.schema_name,
            username=command.username,
            credential_id=command.credential_id,
            credential_configured=True,
            created_at=now,
            updated_at=now,
        )
        return self._store.create_source_with_credential(source, credential)

    def cdc_script_path(self) -> Path:
        return Path(__file__).resolve().parents[3] / "scripts" / "enable_outpatient_cdc.sql"
```

连接检测和 CDC 检测从 store 取加密凭据、校验端点指纹、建立一次短连接、保存安全状态后关闭连接。不得把 pyodbc 原异常写入返回 DTO。

- [ ] **Step 6: 验证并提交**

```powershell
uv run python -m pytest src/tests/unit/adapters/test_outpatient_cdc_sql.py src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/runtime/test_data_governance_service.py -v --tb=short
```

Expected: PASS。

Commit:

```powershell
git add scripts/enable_outpatient_cdc.sql src/adapters/insurance_interface/outpatient_cdc.py src/runtime/data_governance/__init__.py src/runtime/data_governance/service.py src/tests/unit/adapters/test_outpatient_cdc_sql.py src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/runtime/test_data_governance_service.py
git commit -m "feat: 增加门诊CDC配置检测"
```

### Task 4：实现受控定时 SQL 与窗口差异同步

**Files:**
- Create: `src/adapters/insurance_interface/outpatient_polling.py`
- Modify: `src/data_platform/outpatient_sync.py`
- Modify: `src/data_platform/storage/postgresql/outpatient_store.py`
- Create: `src/tests/unit/adapters/test_outpatient_polling.py`
- Modify: `src/tests/unit/data_platform/test_outpatient_sync.py`
- Modify: `src/tests/unit/data_platform/test_outpatient_store.py`

- [ ] **Step 1: 写固定 SQL、窗口和差异失败测试**

```python
from datetime import datetime, timedelta, timezone

from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode


def test_polling_source_uses_parameterized_trade_window(polling_source, cursor):
    end = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    batch = polling_source.read_time_window(end - timedelta(hours=2), end)
    trade_sql, params = cursor.executions[1]
    assert "[T_TradeDate] >= ?" in trade_sql
    assert "[T_TradeDate] < ?" in trade_sql
    assert params == (end - timedelta(hours=2), end)
    assert batch.mode is OutpatientSourceMode.SCHEDULED_SQL


def test_snapshot_diff_detects_insert_update_and_scoped_delete():
    current = rows(trade("T1", fee="10"), trade("T2", fee="20"))
    incoming = rows(trade("T1", fee="11"), trade("T3", fee="30"))
    changes = build_snapshot_changes(current, incoming, {"T1", "T2", "T3"})
    assert {(c.source_key, c.operation) for c in changes} == {
        (("T1",), 4),
        (("T2",), 1),
        (("T3",), 2),
    }
```

测试还要断言：首次无检查点读取受控基线；费用和诊断按交易号分块参数化查询；重复窗口和相同 payload 不生成变更；窗口外 PG 行不会被标记删除；Decimal 和 datetime 比较稳定。

- [ ] **Step 2: 运行测试并确认先红**

```powershell
uv run python -m pytest src/tests/unit/adapters/test_outpatient_polling.py src/tests/unit/data_platform/test_outpatient_sync.py src/tests/unit/data_platform/test_outpatient_store.py -v --tb=short
```

Expected: polling 适配器、窗口读取和差异函数不存在。

- [ ] **Step 3: 实现固定参数化读取适配器**

`SqlServerOutpatientPollingSource` 只使用 `OUTPATIENT_SOURCE_SPECS`。窗口查询固定形态：

```python
trade_sql = (
    f"SELECT {trade_columns} FROM [dbo].[o_Trade] "
    "WHERE [T_TradeDate] >= ? AND [T_TradeDate] < ? "
    "ORDER BY [T_TradeDate], [T_TradeNo]"
)
cursor.execute(trade_sql, window_start, window_end)
```

费用与诊断按不超过 500 个 `T_TradeNo` 分块，`?` 占位符数量由分块长度生成；表、schema、列名仍只能来自代码常量。首次基线默认全表读取，应用服务可提供经审核的历史起始时间以限制范围。

- [ ] **Step 4: 实现确定性窗口差异**

在 `outpatient_sync.py` 增加纯函数 `build_snapshot_changes(current, incoming, scope_trade_nos, observed_at)`：

- 源键只来自 `spec.key_columns`；
- payload 经统一 JSON 规范化后比较；
- incoming 新键为 operation 2，变更键为 operation 4；
- 只有 `scope_trade_nos` 内 current 缺失键生成 operation 1；
- `source_cursor = observed_at` 微秒大端字节 + capture 序号 + 行序号；
- 按 capture instance 和源键稳定排序，保证同输入产生同事件键。

为 store 增加 `load_projection_rows_for_window(start, end)`，只读取该窗口的交易及其费用/诊断；基线使用 `load_all_projection_rows()`。

- [ ] **Step 5: 将 scheduled batch 接入同一原子发布**

`OutpatientSyncService` 在 `snapshot_rows` 非空时调用差异函数，然后继续复用 `_build_state()`、`_apply_changes()`、质量规则和 `publish_batch()`。scheduled checkpoint 使用 `CheckpointKind.TIME_WINDOW` 与 UTC ISO 8601 `value`；失败时 store 不写批次和检查点。

- [ ] **Step 6: 验证并提交**

```powershell
uv run python -m pytest src/tests/unit/adapters/test_outpatient_polling.py src/tests/unit/data_platform/test_outpatient_sync.py src/tests/unit/data_platform/test_outpatient_store.py -v --tb=short
```

Expected: PASS。

Commit:

```powershell
git add src/adapters/insurance_interface/outpatient_polling.py src/data_platform/outpatient_sync.py src/data_platform/storage/postgresql/outpatient_store.py src/tests/unit/adapters/test_outpatient_polling.py src/tests/unit/data_platform/test_outpatient_sync.py src/tests/unit/data_platform/test_outpatient_store.py
git commit -m "feat: 支持门诊定时SQL同步"
```

### Task 5：实现持久化任务调度与常驻 worker

**Files:**
- Modify: `src/data_platform/storage/postgresql/outpatient_governance_store.py`
- Create: `src/runtime/data_governance/worker.py`
- Create: `scripts/run_outpatient_sync_worker.py`
- Create: `src/tests/unit/runtime/test_data_governance_worker.py`
- Create: `src/tests/unit/data_platform/test_outpatient_sync_worker_cli.py`

- [ ] **Step 1: 写任务状态、领取和失败恢复测试**

```python
from datetime import datetime, timezone


def test_worker_executes_claimed_job_and_records_success(worker, store):
    store.due_jobs.append(cdc_job(source_id="bjybdb"))
    result = worker.run_one(now=datetime(2026, 8, 31, tzinfo=timezone.utc))
    assert result.status == "success"
    assert store.attempts[-1].batch_id == "batch-1"
    assert store.jobs["bjybdb"].status == "running"
    assert store.jobs["bjybdb"].next_run_at is not None


def test_worker_failure_keeps_data_checkpoint(worker, store, data_store):
    store.due_jobs.append(scheduled_job(source_id="hospital-a"))
    data_store.checkpoint = "2026-08-31T09:00:00+00:00"
    worker.sync_service_error = RuntimeError("driver-secret-text")
    result = worker.run_one(now=datetime(2026, 8, 31, tzinfo=timezone.utc))
    assert result.status == "failure"
    assert data_store.checkpoint == "2026-08-31T09:00:00+00:00"
    assert "driver-secret-text" not in store.attempts[-1].safe_message
```

存储测试断言 `claim_due_job()` 在事务内使用 `FOR UPDATE SKIP LOCKED`，同一任务不能被两个 worker 同时领取；暂停任务不可领取；`run_once_requested_at` 可把未来任务变为立即到期。

- [ ] **Step 2: 运行测试并确认先红**

```powershell
uv run python -m pytest src/tests/unit/runtime/test_data_governance_worker.py src/tests/unit/data_platform/test_outpatient_sync_worker_cli.py src/tests/unit/data_platform/test_outpatient_governance_store.py -v --tb=short
```

Expected: worker 和领取方法不存在。

- [ ] **Step 3: 实现原子领取和状态转换**

控制面 store 在一个事务中执行：

```sql
SELECT source_id
FROM outpatient_sync_jobs
WHERE status IN ('ready', 'running')
  AND COALESCE(run_once_requested_at, next_run_at) <= %s
ORDER BY COALESCE(run_once_requested_at, next_run_at), source_id
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

领取后立即写 `active_attempt_id` 和 `last_started_at`。成功时写 attempt、清空 run-once 请求并计算下次执行；首次成功基线清除 `baseline_required`；到达本地对账时间且当天未对账时，scheduled job 使用 `run_kind='reconciliation'` 和 `reconcile_days` 范围并更新 `last_reconciled_at`。失败时写安全错误码，数据检查点保持不变。CDC retention gap 映射 `degraded`，一般连接/读取失败映射 `failed`。

- [ ] **Step 4: 实现 worker composition**

`OutpatientSyncWorker.run_one(now)`：

1. 领取一个任务；无任务返回 `idle`；
2. 从治理 service 解密一次连接凭据；
3. 根据 `source_mode` 创建 `SqlServerOutpatientCdcSource` 或 `SqlServerOutpatientPollingSource`；
4. 创建现有 `OutpatientSyncService` 并执行一个批次；
5. 保存类型化 attempt 和下次执行时间；
6. 在 finally 中关闭 SQL Server 连接。

模式选择使用两个明确分支，不增加插件注册表或通用 factory。

- [ ] **Step 5: 实现 CLI**

`run_outpatient_sync_worker.py` 支持：

```text
--once             领取并执行至多一个到期任务
--poll-interval 10 常驻模式空闲等待秒数，允许 5～60
--status           只输出任务数量、到期数量和最近 attempt，不输出连接信息
```

SIGINT/SIGTERM 只在当前批次结束后退出。循环捕获单任务异常并继续服务其他医院。

- [ ] **Step 6: 验证并提交**

```powershell
uv run python -m pytest src/tests/unit/runtime/test_data_governance_worker.py src/tests/unit/data_platform/test_outpatient_sync_worker_cli.py src/tests/unit/data_platform/test_outpatient_governance_store.py -v --tb=short
```

Expected: PASS。

Commit:

```powershell
git add src/data_platform/storage/postgresql/outpatient_governance_store.py src/runtime/data_governance/worker.py scripts/run_outpatient_sync_worker.py src/tests/unit/runtime/test_data_governance_worker.py src/tests/unit/data_platform/test_outpatient_sync_worker_cli.py
git commit -m "feat: 增加门诊同步任务worker"
```

### Task 6：提供数据治理鉴权 API

**Files:**
- Create: `src/runtime/api/data_governance_schemas.py`
- Create: `src/runtime/api/data_governance_routes.py`
- Modify: `src/runtime/api/app.py`
- Create: `src/tests/integration/api/test_data_governance_api.py`

- [ ] **Step 1: 写未认证、只读、写入和秘密脱敏失败测试**

```python
def test_data_governance_requires_signed_token(client):
    response = client.get(f"{PREFIX}/data-governance/overview")
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "AUTH_REQUIRED"


def test_read_permission_cannot_create_datasource(client, read_headers):
    response = client.post(
        f"{PREFIX}/data-governance/data-sources",
        headers=read_headers,
        json=valid_source_payload(),
    )
    assert response.status_code == 403


def test_create_datasource_never_echoes_password(client, write_headers):
    payload = valid_source_payload(password="password-never-returned")
    response = client.post(
        f"{PREFIX}/data-governance/data-sources",
        headers=write_headers,
        json=payload,
    )
    assert response.status_code == 201
    assert "password-never-returned" not in response.text
    assert response.json()["result"]["credential_configured"] is True
```

同文件覆盖设计规格中的 15 个端点、状态码、依赖注入、CDC 脚本下载 content-type、run-once 只入队不在请求线程执行，以及数据库异常不泄漏。

- [ ] **Step 2: 运行测试并确认先红**

```powershell
uv run python -m pytest src/tests/integration/api/test_data_governance_api.py -v --tb=short
```

Expected: 路由返回 404。

- [ ] **Step 3: 定义公开 Pydantic 契约**

输入契约必须使用 `SecretStr`：

```python
from typing import Literal
from pydantic import BaseModel, Field, SecretStr

from src.runtime.api.schemas import AgentResponse


class DataSourceCredentialInput(BaseModel):
    credential_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    password: SecretStr = Field(min_length=1, max_length=4096)


class RotateDataSourceCredentialRequest(DataSourceCredentialInput):
    expected_revision: int = Field(ge=1)


class SaveSyncJobRequest(BaseModel):
    source_mode: Literal["cdc", "scheduled_sql"]
    expected_revision: int = Field(ge=1)
    confirm_mode_switch: bool = False
    cdc_poll_interval_seconds: int = Field(default=45, ge=30, le=60)
    schedule_interval_minutes: int = Field(default=5, ge=1, le=1440)
    lookback_hours: int = Field(default=2, ge=1, le=168)
    reconcile_days: int = Field(default=30, ge=1, le=365)


class CreateDataSourceRequest(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    hospital_code: str = Field(min_length=1, max_length=64)
    hospital_name: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=1433, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    schema_name: Literal["dbo"] = "dbo"
    username: str = Field(min_length=1, max_length=128)
    credential: DataSourceCredentialInput


class DataGovernanceOverviewResponse(AgentResponse):
    scenario: Literal["data_governance"] = "data_governance"
    status: Literal["success"] = "success"
    result: DataGovernanceOverview
```

为 source、PG status、job、run list 分别定义类型化 response；不得让 `result` 回退为裸字典。

- [ ] **Step 4: 实现签名 JWT 权限依赖与安全错误映射**

```python
def require_data_governance_permission(
    permission: str,
    authorization: str | None,
) -> DataGovernancePrincipal:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth_result = authenticator.validate_signed_token(authorization)
    if not auth_result.is_success:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_INVALID", auth_result.error_message or "凭据无效"),
        )
    permitted = authenticator.check_permission(auth_result, permission)
    if not permitted.is_success:
        raise HTTPException(
            status_code=403,
            detail=error_detail("AUTH_FORBIDDEN", permitted.error_message or "权限不足"),
        )
    return DataGovernancePrincipal(user_id=auth_result.user_id)
```

读取端点要求 `data_governance:read`，写入、检测、下载脚本、任务动作要求 `data_governance:write`。领域错误映射为固定 `DATA_SOURCE_NOT_FOUND`、`DATA_SOURCE_CONFLICT`、`DATA_SOURCE_SECRET_UNAVAILABLE`、`CDC_NOT_READY`、`SYNC_JOB_INVALID_STATE` 和 `DATA_GOVERNANCE_UNAVAILABLE`。

- [ ] **Step 5: 实现路由并注册 app**

所有端点通过 `get_data_governance_service` 依赖注入；API 测试 override 该函数。创建端点把 `SecretStr` 解包成 `CreateDataSourceCommand` 后立即交给 service，不记录 command。`run-once` 只调用 `request_run_once(source_id, actor)`。下载 CDC 脚本前调用 `mark_waiting_dba(source_id, actor)`，再用 `FileResponse` 返回静态文件。模式变更只允许 paused/draft job，且必须 `confirm_mode_switch=true`；保存后设置 `baseline_required=true`，下一次 worker 先建立新模式基线。将 router 以 `/api/v1/medical-insurance-ai-agent/data-governance` 前缀注册到 `create_app()`。

- [ ] **Step 6: 验证并提交**

```powershell
uv run python -m pytest src/tests/integration/api/test_data_governance_api.py -v --tb=short
```

Expected: PASS。

Commit:

```powershell
git add src/runtime/api/data_governance_schemas.py src/runtime/api/data_governance_routes.py src/runtime/api/app.py src/tests/integration/api/test_data_governance_api.py
git commit -m "feat: 提供门诊数据治理API"
```

### Task 7：建立独立数据治理中心与真实运行概览

**Files:**
- Create: `src/apps/portal/src/lib/data-governance-api.ts`
- Create: `src/apps/portal/app/data-governance/layout.tsx`
- Create: `src/apps/portal/app/data-governance/page.tsx`
- Modify: `src/apps/portal/app/layout.tsx`
- Create: `src/apps/portal/src/tests/data-governance-overview.test.tsx`

- [ ] **Step 1: 写导航、状态和空态失败测试**

```tsx
it('renders real overview status and no fabricated rows', async () => {
  mockFetchOverview({
    data_source_count: 1,
    running_job_count: 1,
    issue_count: 0,
    latest_latency_seconds: 42,
    sources: [sourceStatus({ hospital_name: '示例医院门诊' })],
    issues: [],
  })
  render(<DataGovernanceOverviewPage />)
  expect(await screen.findByText('示例医院门诊')).toBeInTheDocument()
  expect(screen.getByText('42 秒')).toBeInTheDocument()
  expect(screen.queryByText('暂无数据源，请先新增')).not.toBeInTheDocument()
})


it('shows explicit empty state when backend returns no sources', async () => {
  mockFetchOverview(emptyOverview())
  render(<DataGovernanceOverviewPage />)
  expect(await screen.findByText('暂无数据源，请先新增')).toBeInTheDocument()
})
```

测试还要断言顶级侧栏出现“数据治理”、三个页签可访问、API 错误显示安全提示、页面卸载后停止轮询。

- [ ] **Step 2: 运行测试并确认先红**

```powershell
Push-Location src/apps/portal
try { npm test -- src/tests/data-governance-overview.test.tsx } finally { Pop-Location }
```

Expected: 页面和 API client 不存在。

- [ ] **Step 3: 实现 Portal API client**

`data-governance-api.ts` 读取 sessionStorage 的 `data-governance-token`；非生产环境可回退 `NEXT_PUBLIC_DATA_GOVERNANCE_TOKEN`。所有请求添加 Bearer token，解析统一 error envelope，并把后端 snake_case DTO 显式转换为 camelCase view model：

```typescript
export async function getDataGovernanceOverview(): Promise<DataGovernanceOverview> {
  const response = await dataGovernanceRequest<OverviewResponse>(`${API_BASE}/overview`)
  return {
    dataSourceCount: response.result.data_source_count,
    runningJobCount: response.result.running_job_count,
    issueCount: response.result.issue_count,
    latestLatencySeconds: response.result.latest_latency_seconds,
    sources: response.result.sources.map(mapSourceStatus),
    issues: response.result.issues.map(mapIssue),
  }
}
```

API client 不定义 password 响应字段，也不向 localStorage 写入任何数据。

- [ ] **Step 4: 实现布局和概览**

根侧栏新增 `DatabaseZap` 图标的“数据治理”。子布局使用三个 Link 页签。概览页面：

- 加载时 skeleton；
- 失败时安全错误卡和重试；
- 无源时明确空态与“新增数据源”入口；
- 有源时显示四张状态卡、医院同步状态、待处理项、最近运行记录；
- 每 15 秒重新读取 overview；
- 使用 `<table>`、`<button>`、`aria-live` 和可聚焦状态，不增加图表库。

- [ ] **Step 5: 验证并提交**

```powershell
Push-Location src/apps/portal
try { npm test -- src/tests/data-governance-overview.test.tsx } finally { Pop-Location }
```

Expected: PASS。

Commit:

```powershell
git add src/apps/portal/src/lib/data-governance-api.ts src/apps/portal/app/data-governance/layout.tsx src/apps/portal/app/data-governance/page.tsx src/apps/portal/app/layout.tsx src/apps/portal/src/tests/data-governance-overview.test.tsx
git commit -m "feat: 增加数据治理运行概览"
```

### Task 8：实现数据源与同步任务页面操作

**Files:**
- Create: `src/apps/portal/app/data-governance/data-sources/page.tsx`
- Create: `src/apps/portal/app/data-governance/sync-jobs/page.tsx`
- Modify: `src/apps/portal/src/lib/data-governance-api.ts`
- Modify: `src/apps/portal/app/semantic-layer/discovery/page.tsx`
- Modify: `src/runtime/api/semantic_routes.py`
- Modify: `src/runtime/discovery/service.py`
- Modify: `src/tests/unit/runtime/test_discovery_multi_source.py`
- Create: `src/apps/portal/src/tests/data-governance-data-sources.test.tsx`
- Create: `src/apps/portal/src/tests/data-governance-sync-jobs.test.tsx`
- Modify: `src/apps/portal/src/tests/semantic-governance-writers.test.tsx`

- [ ] **Step 1: 写凭据、CDC 流程和定时 SQL 配置失败测试**

```tsx
it('submits password once and never renders it after save', async () => {
  const user = userEvent.setup()
  render(<DataSourcesPage />)
  await user.click(screen.getByRole('button', { name: '新增数据源' }))
  await user.type(screen.getByLabelText('数据源 ID'), 'bjybdb')
  await user.type(screen.getByLabelText('医院名称'), '示例医院')
  await user.type(screen.getByLabelText('主机'), 'db.example')
  await user.type(screen.getByLabelText('数据库'), 'bjybdb')
  await user.type(screen.getByLabelText('用户名'), 'readonly')
  await user.type(screen.getByLabelText('密码'), 'secret-value')
  await user.click(screen.getByRole('button', { name: '保存数据源' }))
  expect(await screen.findByText('凭据已配置')).toBeInTheDocument()
  expect(screen.queryByDisplayValue('secret-value')).not.toBeInTheDocument()
})


it('shows scheduled sql consistency warning and fixed controls', async () => {
  render(<SyncJobsPage />)
  await userEvent.selectOptions(screen.getByLabelText('同步方式'), 'scheduled_sql')
  expect(screen.getByLabelText('执行周期（分钟）')).toHaveValue(5)
  expect(screen.getByLabelText('回看窗口（小时）')).toHaveValue(2)
  expect(screen.getByText(/最终一致/)).toBeInTheDocument()
  expect(screen.queryByLabelText('SQL')).not.toBeInTheDocument()
})
```

另测：CDC 未 ready 时启动按钮禁用；下载脚本后显示“等待 DBA”；重新检测 ready 后可启用；运行中不能修改模式；暂停后切换模式需要确认；立即执行只显示“已请求”。

后端 discovery 测试增加：请求体含 `source_config` 时 422；只传健康 `datasource_id` 时服务拿到受控连接；扫描任务持久化内容不含连接字段或凭据。

- [ ] **Step 2: 运行测试并确认先红**

```powershell
Push-Location src/apps/portal
try { npm test -- src/tests/data-governance-data-sources.test.tsx src/tests/data-governance-sync-jobs.test.tsx src/tests/semantic-governance-writers.test.tsx } finally { Pop-Location }
uv run python -m pytest src/tests/unit/runtime/test_discovery_multi_source.py -v --tb=short
```

Expected: 两个页面不存在，语义发现仍保存 localStorage 密码。

- [ ] **Step 3: 实现数据源页**

页面使用原生 input/select 和现有 Button/Card：

- 列表显示医院、脱敏端点、凭据状态、连接状态、CDC 状态和最近检测；
- 新增抽屉要求完整凭据；编辑抽屉只允许非敏感字段；端点变化后 UI 必须同时要求重新输入密码；
- “轮换凭据”单独弹窗，成功后清空组件 state；
- “测试连接”“下载 CDC 脚本”“重新检测 CDC”分别调用明确 API；
- PostgreSQL 卡只读显示连接和结构状态。

禁止把表单对象、响应、密码或连接串写入 localStorage、sessionStorage 或 console。

- [ ] **Step 4: 实现同步任务页**

CDC 模式字段只有 30～60 秒轮询间隔；scheduled SQL 字段只有 1～1440 分钟周期、1～168 小时回看、1～365 天对账范围和本地对账时间。启动、暂停、立即执行和模式切换均显示后端返回状态，不做前端乐观伪造。

运行记录表显示开始/结束时间、模式、结果、安全错误、行数和批次 ID；不显示 LSN、source key、SQL 或 payload。

- [ ] **Step 5: 退役语义发现 localStorage 数据源密码**

删除 `discovery_datasource_config` 的读取/写入和 `DataSourceConfigForm`。发现中心改为调用数据治理数据源列表，只允许选择已配置且连接健康的数据源 ID；扫描请求只传 `datasource_id` 和 sample limit，不再传 host/user/password。

后端 `DiscoveryScanRequest` 改为 `ConfigDict(extra='forbid')`，只接受 `datasource_id/scope/sample_limit`；出现旧 `source_config` 直接 422。discovery service 按 `datasource_id` 通过 `DataGovernanceService` 获取一次受控连接，不再从扫描任务、`policy_datasource.connection_config` 或历史结果读取密码。

- [ ] **Step 6: 验证并提交**

```powershell
Push-Location src/apps/portal
try { npm test -- src/tests/data-governance-data-sources.test.tsx src/tests/data-governance-sync-jobs.test.tsx src/tests/semantic-governance-writers.test.tsx } finally { Pop-Location }
uv run python -m pytest src/tests/unit/runtime/test_discovery_multi_source.py -v --tb=short
```

Expected: PASS。

Commit:

```powershell
git add src/apps/portal/app/data-governance/data-sources/page.tsx src/apps/portal/app/data-governance/sync-jobs/page.tsx src/apps/portal/src/lib/data-governance-api.ts src/apps/portal/app/semantic-layer/discovery/page.tsx src/runtime/api/semantic_routes.py src/runtime/discovery/service.py src/tests/unit/runtime/test_discovery_multi_source.py src/apps/portal/src/tests/data-governance-data-sources.test.tsx src/apps/portal/src/tests/data-governance-sync-jobs.test.tsx src/apps/portal/src/tests/semantic-governance-writers.test.tsx
git commit -m "feat: 完成数据治理配置页面"
```

### Task 9：接通本地服务、运维文档与端到端验收（`impl_done`，Firefox 环境项待复验）

**Files:**
- Create: `scripts/configure_data_governance_local.py`
- Create: `src/tests/unit/scripts/__init__.py`
- Create: `src/tests/unit/scripts/test_configure_data_governance_local.py`
- Modify: `start-servers.ps1`
- Modify: `stop-servers.ps1`
- Create: `docs/operations/outpatient-data-sync-configuration.md`
- Create: `src/tests/integration/flow/test_outpatient_data_governance_flow.py`
- Create: `src/tests/e2e/pages/portal/data-governance.page.ts`
- Create: `src/tests/e2e/flows/portal/data-governance.flow.ts`
- Modify: `docs/reviews/2026-08-28-outpatient-p1-verification.md`
- Modify: `docs/superpowers/plans/2026-08-27-outpatient-medical-insurance-assistant-plan-index.md`
- Modify: `PROGRESS.md`

- [x] **Step 1: 写完整双模式 Flow 与 Portal E2E**

后端 Flow 使用 fake SQL Server 与事务 fake PostgreSQL，覆盖：

```text
创建数据源和加密凭据
→ CDC 检测 waiting_dba
→ 切换 scheduled_sql
→ 首次基线
→ 重叠窗口 insert/update/delete
→ 重放去重
→ 暂停
→ 切换 CDC 并检测 ready
→ LSN 增量
→ retention gap 进入 degraded
→ PG 中途失败保持上一检查点
```

Playwright 流程使用 API stub 或本地测试数据，断言管理员能新增源、选择模式、启停和查看运行记录；只读用户看得到状态但没有写按钮；浏览器 storage 不出现测试密码。

同时先创建本任务列出的本地主密钥和启停脚本文本契约测试；实现脚本前测试必须失败。

- [x] **Step 2: 运行 Flow 并确认先红**

```powershell
uv run python -m pytest src/tests/unit/scripts/test_configure_data_governance_local.py -v --tb=short
uv run python -m pytest src/tests/integration/flow/test_outpatient_data_governance_flow.py -v --tb=short
```

Expected: Unit 测试因 `configure_data_governance_local.py` 不存在、启停脚本没有 worker 生命周期而 FAIL；Flow 可以同时暴露跨层契约缺口，但不得用放宽断言通过。

- [x] **Step 3: 增加持久本地主密钥配置脚本**

`configure_data_governance_local.py`：

- 只接受项目根 `.env`；
- 已存在有效 `DATA_GOVERNANCE_MASTER_KEY` 时不改文件；
- 不存在时用 `Fernet.generate_key()` 原子写入；
- 控制台只输出“已配置/已存在”，绝不打印 key；
- 拒绝符号链接和项目根之外路径；
- 不写 SQL Server 密码。

先用临时项目目录测试：首次运行只新增一个有效 Fernet key；第二次运行文件字节不变；符号链接和根目录外路径被拒绝；stdout/stderr 不包含生成 key。

同一测试文件读取 `start-servers.ps1/stop-servers.ps1`，断言启动命令包含 `run_outpatient_sync_worker.py` 与 `-WindowStyle Hidden`，停止逻辑同时核对 worker 脚本名和当前 worktree 路径，禁止出现按 Python 进程名批量终止。

执行：

```powershell
uv run python scripts/configure_data_governance_local.py
```

Expected: `.env` 获得持久主密钥，终端不出现秘密值。

- [x] **Step 4: 让中央启动链托管 worker**

`start-servers.ps1` 在加载 `.env` 后：

- 要求 `DATA_GOVERNANCE_MASTER_KEY` 存在；
- 本地签发含 `data_governance:read/write` 的短期 JWT，注入 `NEXT_PUBLIC_DATA_GOVERNANCE_TOKEN`；
- 后端健康后用 hidden `Start-Process` 启动 `scripts/run_outpatient_sync_worker.py`；
- 把 worker PID 写入 `.server-ports.json`。

`stop-servers.ps1` 读取 worker PID，先核对 CommandLine 同时包含当前 worktree 路径和 `run_outpatient_sync_worker.py`，再停止该进程；不按名称批量杀 Python。所有实际启停仍从 `..\ws.ps1 up/down` 进入。[来源: 项目 `AGENTS.md`]

完成后运行：

```powershell
uv run python -m pytest src/tests/unit/scripts/test_configure_data_governance_local.py src/tests/integration/flow/test_outpatient_data_governance_flow.py -v --tb=short
```

Expected: PASS。

- [x] **Step 5: 编写运维手册并记录真实状态**

`docs/operations/outpatient-data-sync-configuration.md` 必须包含：

1. 页面配置步骤和权限；
2. SQL Server CDC 前置检查、脚本执行、Agent、reader role、capture instance、捕获列和 retention 验证；
3. PostgreSQL 初始化、备份、结构检查和 worker 健康；
4. CDC/定时 SQL 选择标准、默认周期、回看和一致性上限；
5. 主密钥和凭据轮换；
6. retention gap、连接失败、PG 失败、质量阻断和模式切换恢复；
7. 回滚顺序；
8. 当前环境实测状态。

没有真实 SQL Server 连接时继续记录“待目标医院执行”，不写虚假 LSN、延迟或成功批次。

- [x] **Step 6: 严格执行 Unit → API → Flow**

Unit：

```powershell
uv run python -m pytest src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/adapters/test_outpatient_cdc_sql.py src/tests/unit/adapters/test_outpatient_polling.py src/tests/unit/security/test_data_source_credentials.py src/tests/unit/data_platform/test_outpatient_store.py src/tests/unit/data_platform/test_outpatient_sync.py src/tests/unit/data_platform/test_outpatient_governance_store.py src/tests/unit/data_platform/test_outpatient_sync_worker_cli.py src/tests/unit/runtime/test_data_governance_service.py src/tests/unit/runtime/test_data_governance_worker.py -v --tb=short
uv run python -m pytest src/tests/unit/scripts/test_configure_data_governance_local.py -v --tb=short
```

Expected: PASS。失败即停止。

API：

```powershell
uv run python -m pytest src/tests/integration/api/test_data_governance_api.py -v --tb=short
```

Expected: PASS。失败即停止。

Flow：

```powershell
uv run python -m pytest src/tests/integration/flow/test_outpatient_sync_flow.py src/tests/integration/flow/test_outpatient_data_governance_flow.py -v --tb=short
```

Expected: PASS。

- [ ] **Step 7: 执行 Portal 测试、构建和浏览器验证**

```powershell
Push-Location src/apps/portal
try {
    npm test
    if ($LASTEXITCODE -ne 0) { throw "Portal tests failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Portal build failed" }
} finally {
    Pop-Location
}
```

Expected: PASS。

在承载该分支的 Orca 管理工作区通过中央 `ws.ps1` 启动服务后，进入 E2E 目录运行现有 runner：

```powershell
Push-Location src/tests/e2e
try { npm test -- flows/portal/data-governance.flow.ts } finally { Pop-Location }
```

Expected: Chromium、Firefox、WebKit 均通过；`run-playwright.mjs` 从该工作区 `.server-ports.json` 读取实际端口，不能手工猜端口。

实测：Portal 48 文件 367 passed，生产构建 38 个路由通过；数据治理 E2E 在 Chromium、WebKit 通过。Playwright Firefox 在本机访问 Next.js 开发态时持续无法建立 `/_next/webpack-hmr` WebSocket，服务端直连握手为 101，且无头/有头、代理绕过和 HMR mock 均未解决；该环境项不改业务代码，保留待独立生产态浏览器环境复验。

- [x] **Step 8: 全仓回归、状态更新与提交**

```powershell
uv run python -m pytest -q --tb=short
uv run python -m compileall -q src scripts
git diff --check
```

Expected: 全部通过，零新增错误。更新 P1 验证记录、计划索引和 `PROGRESS.md`：代码与本地页面验证完成写 `impl_done`；只有目标医院真实 CDC/定时 SQL 验收和延迟证据完成后才写 `complete`。

Commit:

```powershell
git add scripts/configure_data_governance_local.py src/tests/unit/scripts/__init__.py src/tests/unit/scripts/test_configure_data_governance_local.py start-servers.ps1 stop-servers.ps1 docs/operations/outpatient-data-sync-configuration.md src/tests/integration/flow/test_outpatient_data_governance_flow.py src/tests/e2e/pages/portal/data-governance.page.ts src/tests/e2e/flows/portal/data-governance.flow.ts docs/reviews/2026-08-28-outpatient-p1-verification.md docs/superpowers/plans/2026-08-27-outpatient-medical-insurance-assistant-plan-index.md PROGRESS.md
git commit -m "test: 验证门诊数据治理双模式同步"
```

---

## 2. 任务依赖与提交边界

```text
Task 1 来源中立契约
  → Task 2 安全控制面
  → Task 3 CDC 检测
  → Task 4 定时 SQL
  → Task 5 worker
  → Task 6 API
  → Task 7 概览
  → Task 8 配置页面
  → Task 9 Flow/运维/验收
```

每个任务一个提交。前一任务测试未通过时不得开始后一任务；不得把 Task 9 的文档和回归证据提前混入功能提交。

## 3. 目标环境外部验收

代码完成后仍需医院提供以下外部动作：

1. 系统管理员通过页面录入真实 SQL Server 只读账号并测试连接；
2. 若选择 CDC，DBA 审核并执行下载脚本，再由页面重新检测；
3. 若选择定时 SQL，DBA 确认 `T_TradeDate` 的实际语义和索引，并同意默认查询负载；
4. 观察至少 100 个非空 CDC 批次后记录 P95；定时 SQL 记录周期内成功率与夜间对账差异；
5. 医保办核验脱敏抽样和金额勾稽结果。

外部动作未完成不阻止代码达到 `impl_done`，但阻止项目状态标记 `complete`。

## 4. Ponytail 约束

- 复用现有 `PostgreSQLClient`、Fernet 模式、Gateway Auth、Portal Card/Button 和门诊加工服务；不增加消息代理、调度依赖或 UI 组件库。
- 只有两个实际 source mode，因此 worker 使用两个明确分支，不建设插件注册、反射 factory 或通用 pipeline DSL。
- PostgreSQL 同时承担配置、任务和领取锁；只有实测多实例吞吐或隔离需求出现时才引入 Celery。
- 定时 SQL 只支持当前三张门诊表和固定时间窗口；新业务域到来时新增独立已审核模板，不提前建设任意 SQL 平台。
