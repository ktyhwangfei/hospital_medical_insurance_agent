from src.shared.schemas.contracts import AuditEvent, Citation, ErrorDetail, RuntimeTask, StreamErrorEvent
from src.shared.schemas.responses import error_detail


def test_contract_models_dump_to_api_compatible_dicts():
    citation = Citation(source_type="risk_control_policy", source_id="HIGH_RISK_ACTIONS", summary="高风险动作黑名单")
    audit = AuditEvent(event_type="high_risk_action_blocked", workflow_id="wf-001", step_id="risk_control")
    task = RuntimeTask(task_id="task-001", task_type="human_confirmation", status="pending", description="请人工确认高风险动作")
    stream_error = StreamErrorEvent(error_code="MODEL_STREAM_ERROR", message="模型流式响应失败", audit_event=audit)

    assert citation.model_dump()["source_type"] == "risk_control_policy"
    assert audit.model_dump()["event_type"] == "high_risk_action_blocked"
    assert task.model_dump()["status"] == "pending"
    assert stream_error.model_dump()["audit_event"]["workflow_id"] == "wf-001"


def test_error_detail_uses_standard_error_model():
    detail = error_detail("PERMISSION_DENIED", "角色无权访问该场景", {"event_type": "permission_denied"})

    assert detail == {
        "error_code": "PERMISSION_DENIED",
        "message": "角色无权访问该场景",
        "audit_event": {"event_type": "permission_denied"},
    }
    assert ErrorDetail(**detail).error_code == "PERMISSION_DENIED"
