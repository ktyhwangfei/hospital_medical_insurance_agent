from src.knowledge_extension.common.models import (
    AuditSummary,
    Citation,
    Degradation,
    KnowledgeExtensionStatus,
    VisibilityScope,
)


def test_citation_public_view_hides_internal_fields():
    citation = Citation(
        source_id="asset-policy-001",
        source_type="policy",
        title="医保结算政策说明",
        version="2026.1",
        section="第二章",
        chunk_id="chunk-001",
        evidence="结算异常需核对交易状态",
        retrieved_at="2026-05-04T00:00:00Z",
        score=0.91,
        internal_locator="D:/internal/policy.pdf#page=2",
    )

    public = citation.to_public_dict()

    assert public["source_id"] == "asset-policy-001"
    assert public["title"] == "医保结算政策说明"
    assert "internal_locator" not in public


def test_degradation_requires_status_and_reason():
    degradation = Degradation(
        status=KnowledgeExtensionStatus.NO_HIT,
        reason="未命中可用知识",
        user_message="当前知识库未找到可靠依据，建议人工复核",
    )

    assert degradation.status is KnowledgeExtensionStatus.NO_HIT
    assert "人工复核" in degradation.user_message


def test_visibility_scope_matches_role_and_tenant():
    scope = VisibilityScope(
        roles={"medical_insurance_officer"},
        tenant_ids={"tenant-a"},
        campus_ids={"north"},
    )

    assert scope.allows("medical_insurance_officer", "tenant-a", "north") is True
    assert scope.allows("doctor", "tenant-a", "north") is False


def test_audit_summary_masks_sensitive_values():
    audit = AuditSummary(
        event_type="extension_selection_denied",
        actor="u001",
        summary={"patient_name": "张三", "token": "secret", "reason": "permission_denied"},
    )

    masked = audit.masked_summary()

    assert masked["patient_name"] == "***"
    assert masked["token"] == "***"
    assert masked["reason"] == "permission_denied"
