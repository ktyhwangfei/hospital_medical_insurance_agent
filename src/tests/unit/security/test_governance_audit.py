"""治理操作审计助手测试 — Issue #75 S4（actor 取自认证主体，action/target_ref 落审计）。"""
from __future__ import annotations

from src.security.audit.governance_audit import record_governance_action


class _StubAuditLog:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record_event(self, event_type: str, **kwargs) -> dict:
        self.events.append({"event_type": event_type, **kwargs})
        return {}


class _FailingAuditLog:
    def record_event(self, event_type: str, **kwargs) -> dict:
        raise RuntimeError("audit unavailable")


def test_records_actor_action_target(monkeypatch):
    stub = _StubAuditLog()
    monkeypatch.setattr("src.security.audit.audit_log", stub)

    record_governance_action(
        user_id="workflow-admin-1",
        roles=["admin"],
        action="workflow.config.update",
        target_ref="workflow_id=wf_refund_verification",
        request_path="/api/v1/medical-insurance-ai-agent/workflow-catalog/workflows/wf_refund_verification/config",
    )

    assert len(stub.events) == 1
    event = stub.events[0]
    assert event["event_type"] == "governance_action"
    assert event["user_id"] == "workflow-admin-1"
    assert event["role"] == "admin"
    assert event["action"] == "workflow.config.update"
    assert event["target_ref"] == "workflow_id=wf_refund_verification"
    assert event["request_path"].endswith("/config")


def test_audit_failure_does_not_block_business(monkeypatch):
    monkeypatch.setattr("src.security.audit.audit_log", _FailingAuditLog())

    record_governance_action(
        user_id="u",
        roles=[],
        action="flow.publish",
        target_ref="flow_id=f1",
    )
