from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, func

metadata = MetaData()

workflows = Table(
    "workflows",
    metadata,
    Column("workflow_id", String(128), primary_key=True),
    Column("scenario", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("current_step", String(128), nullable=True),
    Column("steps", JSON, nullable=False, server_default="[]"),
    Column("audit_refs", JSON, nullable=False, server_default="[]"),
    Column("knowledge_events", JSON, nullable=False, server_default="[]"),
    Column("knowledge_degradation_reasons", JSON, nullable=False, server_default="[]"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
)

tasks = Table(
    "tasks",
    metadata,
    Column("task_id", String(128), primary_key=True),
    Column("task_type", String(64), nullable=False),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("description", Text, nullable=True),
    Column("responsible_role", String(64), nullable=True),
    Column("workflow_id", String(128), nullable=True),
    Column("confirmed_by", String(64), nullable=True),
    Column("confirmed_at", String(32), nullable=True),
    Column("reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_type", String(64), nullable=False),
    Column("workflow_id", String(128), nullable=True),
    Column("step_id", String(128), nullable=True),
    Column("payload", JSON, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

sessions = Table(
    "sessions",
    metadata,
    Column("session_id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("role", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("last_active", DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
)
