import json
from datetime import UTC, datetime
from typing import Any

from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.postgresql.models import workflows as workflows_table
from src.runtime.runtime_state.models import StepState, WorkflowInstance


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _step_to_dict(step: StepState) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "status": step.status,
        "input_refs": step.input_refs,
        "output_refs": step.output_refs,
        "error": step.error,
        "audit_refs": step.audit_refs,
    }


def _row_to_workflow(row: dict[str, Any]) -> WorkflowInstance:
    steps_data = json.loads(row["steps"]) if isinstance(row["steps"], str) else (row["steps"] or [])
    audit_refs = json.loads(row["audit_refs"]) if isinstance(row["audit_refs"], str) else (row["audit_refs"] or [])
    knowledge_events = json.loads(row["knowledge_events"]) if isinstance(row["knowledge_events"], str) else (row["knowledge_events"] or [])
    knowledge_degradation_reasons = (
        json.loads(row["knowledge_degradation_reasons"])
        if isinstance(row["knowledge_degradation_reasons"], str)
        else (row["knowledge_degradation_reasons"] or [])
    )
    return WorkflowInstance(
        workflow_id=row["workflow_id"],
        scenario=row["scenario"],
        status=row["status"],
        current_step=row.get("current_step"),
        steps=[StepState(**s) for s in steps_data],
        audit_refs=audit_refs,
        knowledge_events=knowledge_events,
        knowledge_degradation_reasons=knowledge_degradation_reasons,
        session_id=row.get("session_id"),
        patient_id=row.get("patient_id"),
    )


_CREATE_SQL = """
create table if not exists workflows (
    workflow_id varchar(128) primary key,
    scenario varchar(64) not null,
    status varchar(32) not null,
    current_step varchar(128),
    steps jsonb not null default '[]'::jsonb,
    audit_refs jsonb not null default '[]'::jsonb,
    knowledge_events jsonb not null default '[]'::jsonb,
    knowledge_degradation_reasons jsonb not null default '[]'::jsonb,
    session_id varchar(128),
    patient_id varchar(64),
    created_at timestamptz not null default current_timestamp,
    updated_at timestamptz not null default current_timestamp
)
"""


class PostgreSQLWorkflowStore:
    """PostgreSQL-backed workflow store matching RuntimeStateStore interface."""

    def __init__(self, client: PostgreSQLClient):
        self._client = client

    def ensure_tables(self) -> None:
        """Create the workflows table if it does not exist."""
        self._client.execute("create table if not exists workflows (workflow_id varchar(128) primary key, scenario varchar(64) not null, status varchar(32) not null, current_step varchar(128), steps jsonb not null default '[]'::jsonb, audit_refs jsonb not null default '[]'::jsonb, knowledge_events jsonb not null default '[]'::jsonb, knowledge_degradation_reasons jsonb not null default '[]'::jsonb, session_id varchar(128), patient_id varchar(64), created_at timestamptz not null default current_timestamp, updated_at timestamptz not null default current_timestamp)")

    def save_workflow(self, workflow: WorkflowInstance) -> WorkflowInstance:
        """Insert or update a workflow."""
        steps_json = json.dumps([_step_to_dict(s) for s in workflow.steps], ensure_ascii=False, sort_keys=True)
        audit_refs_json = json.dumps(workflow.audit_refs, ensure_ascii=False, sort_keys=True)
        knowledge_events_json = json.dumps(workflow.knowledge_events, ensure_ascii=False, sort_keys=True)
        knowledge_degradation_reasons_json = json.dumps(workflow.knowledge_degradation_reasons, ensure_ascii=False, sort_keys=True)
        now = _now()

        sql = """insert into workflows (workflow_id, scenario, status, current_step, steps, audit_refs, knowledge_events, knowledge_degradation_reasons, session_id, patient_id, created_at, updated_at)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (workflow_id) do update set
    scenario = excluded.scenario,
    status = excluded.status,
    current_step = excluded.current_step,
    steps = excluded.steps,
    audit_refs = excluded.audit_refs,
    knowledge_events = excluded.knowledge_events,
    knowledge_degradation_reasons = excluded.knowledge_degradation_reasons,
    session_id = excluded.session_id,
    patient_id = excluded.patient_id,
    updated_at = excluded.updated_at"""
        try:
            self._client.execute(
                sql,
                (
                    workflow.workflow_id,
                    workflow.scenario,
                    workflow.status,
                    workflow.current_step,
                    steps_json,
                    audit_refs_json,
                    knowledge_events_json,
                    knowledge_degradation_reasons_json,
                    workflow.session_id,
                    workflow.patient_id,
                    now,
                    now,
                ),
            )
        except RuntimeError:
            pass
        return workflow

    def get_workflow(self, workflow_id: str) -> WorkflowInstance | None:
        """Retrieve a workflow by ID."""
        try:
            rows = self._client.execute("select * from workflows where workflow_id = %s", (workflow_id,))
            if not rows:
                return None
            return _row_to_workflow(rows[0])
        except RuntimeError:
            return None

    def list_workflows(self) -> list[WorkflowInstance]:
        """List all workflows."""
        try:
            rows = self._client.execute("select * from workflows order by created_at desc")
            return [_row_to_workflow(r) for r in rows]
        except RuntimeError:
            return []
