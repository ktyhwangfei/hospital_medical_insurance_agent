"""筛查规则结果表在 bjyb（SQL Server）上的幂等 DDL。

问数按 dbo.ai_screen_* 只读。字段名与取值跟任务书一致。
condition_spec / evidence_facts 用 NVARCHAR 存 JSON，便于规则再次执行。
"""
from __future__ import annotations

SQLSERVER_SCREENING_DDL: tuple[str, ...] = (
    """
    IF OBJECT_ID(N'dbo.ai_screen_rule', N'U') IS NULL
    CREATE TABLE dbo.ai_screen_rule (
        rule_id NVARCHAR(64) NOT NULL PRIMARY KEY,
        source_doc NVARCHAR(300) NOT NULL,
        source_clause NVARCHAR(MAX) NOT NULL,
        title NVARCHAR(300) NOT NULL,
        condition_text NVARCHAR(MAX) NOT NULL,
        [class] NVARCHAR(32) NOT NULL,
        mapping_gap NVARCHAR(MAX) NULL,
        status NVARCHAR(32) NOT NULL CONSTRAINT df_ai_screen_rule_status DEFAULT N'candidate',
        condition_spec NVARCHAR(MAX) NULL,
        source_item_ref NVARCHAR(64) NULL,
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        approved_at DATETIME2 NULL,
        approved_by NVARCHAR(128) NULL
    )
    """.strip(),
    """
    IF COL_LENGTH(N'dbo.ai_screen_rule', N'source_item_ref') IS NULL
        ALTER TABLE dbo.ai_screen_rule ADD source_item_ref NVARCHAR(64) NULL
    """.strip(),
    """
    IF COL_LENGTH(N'dbo.ai_screen_rule', N'condition_spec') IS NULL
        ALTER TABLE dbo.ai_screen_rule ADD condition_spec NVARCHAR(MAX) NULL
    """.strip(),
    """
    IF OBJECT_ID(N'dbo.ai_screen_run', N'U') IS NULL
    CREATE TABLE dbo.ai_screen_run (
        run_id NVARCHAR(64) NOT NULL PRIMARY KEY,
        started_at DATETIME2 NOT NULL,
        finished_at DATETIME2 NULL,
        status NVARCHAR(32) NOT NULL CONSTRAINT df_ai_screen_run_status DEFAULT N'running',
        time_range_start DATETIME2 NOT NULL,
        time_range_end DATETIME2 NOT NULL,
        error_message NVARCHAR(MAX) NULL,
        created_by NVARCHAR(128) NOT NULL
    )
    """.strip(),
    """
    IF OBJECT_ID(N'dbo.ai_screen_run_rule', N'U') IS NULL
    CREATE TABLE dbo.ai_screen_run_rule (
        run_id NVARCHAR(64) NOT NULL,
        rule_id NVARCHAR(64) NOT NULL,
        CONSTRAINT pk_ai_screen_run_rule PRIMARY KEY (run_id, rule_id)
    )
    """.strip(),
    """
    IF OBJECT_ID(N'dbo.ai_screen_finding', N'U') IS NULL
    CREATE TABLE dbo.ai_screen_finding (
        finding_id NVARCHAR(64) NOT NULL PRIMARY KEY,
        run_id NVARCHAR(64) NOT NULL,
        rule_id NVARCHAR(64) NOT NULL,
        settlement_key NVARCHAR(64) NOT NULL,
        fee_line_id NVARCHAR(128) NULL,
        item_code NVARCHAR(128) NULL,
        item_name NVARCHAR(300) NULL,
        amount DECIMAL(18, 2) NULL,
        finding_type NVARCHAR(32) NOT NULL,
        primary_finding_id NVARCHAR(64) NOT NULL,
        evidence_clause NVARCHAR(MAX) NOT NULL,
        evidence_facts NVARCHAR(MAX) NOT NULL CONSTRAINT df_ai_screen_finding_facts DEFAULT N'{}',
        verify_status NVARCHAR(32) NOT NULL CONSTRAINT df_ai_screen_finding_verify DEFAULT N'pending',
        created_at DATETIME2 NOT NULL
    )
    """.strip(),
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'idx_ai_screen_run_status' AND object_id = OBJECT_ID(N'dbo.ai_screen_run')
    )
        CREATE INDEX idx_ai_screen_run_status ON dbo.ai_screen_run(status, started_at DESC)
    """.strip(),
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'idx_ai_screen_finding_run' AND object_id = OBJECT_ID(N'dbo.ai_screen_finding')
    )
        CREATE INDEX idx_ai_screen_finding_run ON dbo.ai_screen_finding(run_id, finding_type)
    """.strip(),
)

EXPECTED_SCREENING_TABLES = (
    "ai_screen_rule",
    "ai_screen_run",
    "ai_screen_run_rule",
    "ai_screen_finding",
)
