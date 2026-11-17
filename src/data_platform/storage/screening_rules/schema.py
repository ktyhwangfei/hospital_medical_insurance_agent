"""筛查规则结果表 DDL — issue #86。

与 bjyb 门诊落地数据同一 PostgreSQL 库（问数侧按表名只读直查）。
遵循 CREATE + ALTER 双写约定（AGENTS.md 已知陷阱：旧库加列只靠
CREATE TABLE IF NOT EXISTS 不会补列，INSERT 报 UndefinedColumn）。
可重复执行；scripts/create_screening_rule_tables.py 为同一 DDL 的
独立可重复执行脚本入口。
"""
from __future__ import annotations

AI_SCREEN_RULE_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ai_screen_rule (
        rule_id VARCHAR(64) PRIMARY KEY,
        source_doc TEXT NOT NULL,
        source_clause TEXT NOT NULL,
        title TEXT NOT NULL,
        condition_text TEXT NOT NULL,
        class VARCHAR(32) NOT NULL,
        mapping_gap TEXT,
        status VARCHAR(32) NOT NULL DEFAULT 'candidate',
        condition_spec JSONB,
        source_item_ref VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        approved_at TIMESTAMPTZ,
        approved_by VARCHAR(128)
    )""",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS rule_id VARCHAR(64)",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS source_doc TEXT",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS source_clause TEXT",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS title TEXT",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS condition_text TEXT",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS class VARCHAR(32)",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS mapping_gap TEXT",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'candidate'",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS condition_spec JSONB",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS source_item_ref VARCHAR(64)",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
    "ALTER TABLE ai_screen_rule ADD COLUMN IF NOT EXISTS approved_by VARCHAR(128)",
    "CREATE INDEX IF NOT EXISTS idx_ai_screen_rule_status ON ai_screen_rule(status)",
    "CREATE INDEX IF NOT EXISTS idx_ai_screen_rule_class ON ai_screen_rule(class)",
)

AI_SCREEN_RUN_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ai_screen_run (
        run_id VARCHAR(64) PRIMARY KEY,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        status VARCHAR(32) NOT NULL DEFAULT 'running',
        time_range_start TIMESTAMPTZ NOT NULL,
        time_range_end TIMESTAMPTZ NOT NULL,
        error_message TEXT,
        created_by VARCHAR(128) NOT NULL
    )""",
    "ALTER TABLE ai_screen_run ADD COLUMN IF NOT EXISTS run_id VARCHAR(64)",
    "ALTER TABLE ai_screen_run ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
    "ALTER TABLE ai_screen_run ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ",
    "ALTER TABLE ai_screen_run ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'running'",
    "ALTER TABLE ai_screen_run ADD COLUMN IF NOT EXISTS time_range_start TIMESTAMPTZ",
    "ALTER TABLE ai_screen_run ADD COLUMN IF NOT EXISTS time_range_end TIMESTAMPTZ",
    "ALTER TABLE ai_screen_run ADD COLUMN IF NOT EXISTS error_message TEXT",
    "ALTER TABLE ai_screen_run ADD COLUMN IF NOT EXISTS created_by VARCHAR(128)",
    "CREATE INDEX IF NOT EXISTS idx_ai_screen_run_status ON ai_screen_run(status, started_at DESC)",
)

AI_SCREEN_RUN_RULE_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ai_screen_run_rule (
        run_id VARCHAR(64) NOT NULL REFERENCES ai_screen_run(run_id),
        rule_id VARCHAR(64) NOT NULL REFERENCES ai_screen_rule(rule_id),
        PRIMARY KEY (run_id, rule_id)
    )""",
    "ALTER TABLE ai_screen_run_rule ADD COLUMN IF NOT EXISTS run_id VARCHAR(64)",
    "ALTER TABLE ai_screen_run_rule ADD COLUMN IF NOT EXISTS rule_id VARCHAR(64)",
)

AI_SCREEN_FINDING_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ai_screen_finding (
        finding_id VARCHAR(64) PRIMARY KEY,
        run_id VARCHAR(64) NOT NULL REFERENCES ai_screen_run(run_id),
        rule_id VARCHAR(64) NOT NULL REFERENCES ai_screen_rule(rule_id),
        settlement_key TEXT NOT NULL,
        fee_line_id VARCHAR(128),
        item_code VARCHAR(128),
        item_name TEXT,
        amount NUMERIC(14, 4),
        finding_type VARCHAR(32) NOT NULL,
        primary_finding_id VARCHAR(64) NOT NULL,
        evidence_clause TEXT NOT NULL,
        evidence_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
        verify_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL
    )""",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS finding_id VARCHAR(64)",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS run_id VARCHAR(64)",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS rule_id VARCHAR(64)",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS settlement_key TEXT",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS fee_line_id VARCHAR(128)",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS item_code VARCHAR(128)",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS item_name TEXT",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS amount NUMERIC(14, 4)",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS finding_type VARCHAR(32)",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS primary_finding_id VARCHAR(64)",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS evidence_clause TEXT",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS evidence_facts JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS verify_status VARCHAR(32) DEFAULT 'pending'",
    "ALTER TABLE ai_screen_finding ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_ai_screen_finding_run ON ai_screen_finding(run_id, finding_type)",
    "CREATE INDEX IF NOT EXISTS idx_ai_screen_finding_rule ON ai_screen_finding(rule_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_screen_finding_settlement ON ai_screen_finding(settlement_key)",
)

SCREENING_TABLE_SCHEMAS = (
    AI_SCREEN_RULE_TABLE_SCHEMA,
    AI_SCREEN_RUN_TABLE_SCHEMA,
    AI_SCREEN_RUN_RULE_TABLE_SCHEMA,
    AI_SCREEN_FINDING_TABLE_SCHEMA,
)
