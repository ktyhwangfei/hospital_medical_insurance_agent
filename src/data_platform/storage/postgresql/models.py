from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, MetaData, String, Table, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

workflows = Table(
    "workflows",
    metadata,
    Column("workflow_id", String(128), primary_key=True),
    Column("scenario", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("current_step", String(128), nullable=True),
    Column("steps", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("audit_refs", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("knowledge_events", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("knowledge_degradation_reasons", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("session_id", String(128), nullable=True),
    Column("patient_id", String(64), nullable=True),
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
    Column("confirmed_at", DateTime(timezone=True), nullable=True),
    Column("reason", Text, nullable=True),
    Column("executor_type", String(64), nullable=True),
    Column("input_data", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("output_data", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("step_id", String(128), nullable=True),
    Column("error_message", Text, nullable=True),
    Column("duration_ms", Integer, nullable=True),
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
    # v3.0 网关审计字段
    Column("user_id", String(64), nullable=True),
    Column("session_id", String(128), nullable=True),
    Column("role", String(32), nullable=True),
    Column("request_path", String(512), nullable=True),
    Column("request_method", String(16), nullable=True),
    Column("request_summary", JSONB, nullable=True),
    Column("response_status", Integer, nullable=True),
    Column("response_summary", JSONB, nullable=True),
    Column("client_ip", String(64), nullable=True),
    Column("user_agent", String(512), nullable=True),
    Column("duration_ms", Integer, nullable=True),
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

# 规划中已实现的表 - 风控事件
risk_control_events = Table(
    "risk_control_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("rule_id", String(128)),
    Column("event_type", String(64), nullable=False, default="blocked"),
    Column("user_id", String(64)),
    Column("patient_id", String(64)),
    Column("encounter_id", String(64)),
    Column("action_pattern", Text),
    Column("risk_level", String(32), nullable=False, default="HIGH"),
    Column("blocked", Boolean, nullable=False, default=False),
    Column("reason", Text),
    Column("result", String(32)),
    Column("workflow_id", String(128)),
    Column("context", JSON, default={}),
    Column("created_at", DateTime(timezone=True), nullable=False, default=func.now()),
)

# 规划中已实现的表 - 风险控制规则
risk_control_rules = Table(
    "risk_control_rules", metadata,
    Column("rule_id", String(64), primary_key=True),
    Column("rule_name", String(128), nullable=False),
    Column("action_pattern", String(256), nullable=False),
    Column("risk_level", String(32), nullable=False, default="HIGH"),
    Column("description", Text),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("metadata", JSON, default={}),
    Column("created_at", DateTime(timezone=True), nullable=False, default=func.now()),
)

# 规划中已实现的表 - LangGraph 检查点
langgraph_checkpoints = Table(
    "langgraph_checkpoints", metadata,
    Column("thread_id", String(128), primary_key=True),
    Column("checkpoint_ns", String(128), primary_key=True, default=""),
    Column("checkpoint_id", String(128), primary_key=True),
    Column("parent_checkpoint_id", String(128)),
    Column("state", JSON, nullable=False),
    Column("metadata", JSON, default={}),
    Column("created_at", DateTime(timezone=True), nullable=False, default=func.now()),
)

# 规划中已实现的表 - 规则解释库
rule_explanations = Table(
    "rule_explanations", metadata,
    Column("rule_id", String(128), primary_key=True),
    Column("rule_name", String(256), nullable=False),
    Column("rule_category", String(64)),
    Column("source", String(128)),
    Column("description", Text),
    Column("explanation", Text),
    Column("applicable_scenarios", JSON, default=[]),
    Column("references", JSON, default=[]),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("metadata", JSON, default={}),
    Column("created_at", DateTime(timezone=True), nullable=False, default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
)

# 规划中已实现的表 - 知识资产
knowledge_assets = Table(
    "knowledge_assets", metadata,
    Column("asset_id", String(128), primary_key=True),
    Column("title", String(512), nullable=False),
    Column("asset_type", String(64), nullable=False),
    Column("source", String(256)),
    Column("version", String(32)),
    Column("status", String(32), nullable=False, default="published"),
    Column("summary", Text),
    Column("index_status", String(32), default="pending"),
    Column("visibility", JSON, default={}),
    Column("metadata", JSON, default={}),
    Column("imported_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
)

# 规划中已实现的表 - 知识切片
knowledge_chunks = Table(
    "knowledge_chunks", metadata,
    Column("chunk_id", String(128), primary_key=True),
    Column("asset_id", String(128), nullable=False),
    Column("section", String(256)),
    Column("title", String(512)),
    Column("text", Text, nullable=False),
    Column("summary", Text),
    Column("asset_type", String(64)),
    Column("asset_version", String(32)),
    Column("tags", JSON, default=[]),
    Column("scenario_tags", JSON, default=[]),
    Column("metadata", JSON, default={}),
    Column("created_at", DateTime(timezone=True), nullable=False, default=func.now()),
)

# 规划中已实现的表 - 申诉模板
appeal_templates = Table(
    "appeal_templates", metadata,
    Column("template_id", String(128), primary_key=True),
    Column("template_name", String(256), nullable=False),
    Column("template_type", String(64)),
    Column("denial_reason_pattern", String(256)),
    Column("content", Text, nullable=False),
    Column("required_evidence", JSON, default=[]),
    Column("applicable_scenarios", JSON, default=[]),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("metadata", JSON, default={}),
    Column("created_at", DateTime(timezone=True), nullable=False, default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
)

# 规划中已实现的表 - 提示词模板
prompt_templates = Table(
    "prompt_templates", metadata,
    Column("template_id", String(128), primary_key=True),
    Column("template_name", String(256), nullable=False),
    Column("template_type", String(64), nullable=False),
    Column("scenario", String(64)),
    Column("role", String(64)),
    Column("system_prompt", Text),
    Column("user_prompt_template", Text),
    Column("variables", JSON, default=[]),
    Column("output_format", JSON, default={}),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("metadata", JSON, default={}),
    Column("created_at", DateTime(timezone=True), nullable=False, default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
)
