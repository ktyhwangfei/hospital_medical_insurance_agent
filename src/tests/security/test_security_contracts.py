from src.shared.schemas.contracts import AuditEvent, Citation, ErrorDetail, RuntimeTask, StreamErrorEvent
from src.shared.schemas.responses import error_detail
from src.runtime.scheduling.service import degraded_response
from src.security.risk_control.service import build_human_confirmation_response


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


def test_high_risk_response_has_traceability_and_task():
    response = build_human_confirmation_response(["退费", "冲正"])

    assert response.status == "waiting_human_confirmation"
    assert response.tasks[0]["task_type"] == "human_confirmation"
    assert response.citations or response.uncertainties
    assert response.audit["event_type"] == "high_risk_action_blocked"
    assert "退费" in response.blocked_actions


def test_degraded_response_has_uncertainty_source_and_audit_event():
    response = degraded_response("P002", "E001", "医保接口调用失败，当前结论存在不确定性")

    assert response.status == "degraded"
    assert response.uncertainties
    assert response.citations
    assert response.audit["event_type"] == "degraded_response_returned"
