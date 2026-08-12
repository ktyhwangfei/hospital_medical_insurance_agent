from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.semantic_alignment import (
    DiscoveryEvidence,
    DiscoverySignal,
    InMemorySemanticAlignmentStore,
    ProposalStatus,
    SemanticAlignmentService,
    SourceValueMappingDraft,
    StandardValueProposalDraft,
    TriggerSource,
)
from src.runtime.api.app import create_app
from src.semantic_layer.extraction_contract import build_extraction_schema
from src.semantic_layer.models import BusinessObject, Metric, ValueDomain
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


PREFIX = "/api/v1/medical-insurance-ai-agent/semantic/alignment"
JWT_SECRET = "semantic-review-test-secret"


def _review_token(
    user_id: str = "semantic-reviewer",
    permissions: list[str] | None = None,
    *,
    expired: bool = False,
    claim_overrides: dict[str, object] | None = None,
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "roles": ["information_department"],
        "permissions": ["semantic:review"] if permissions is None else permissions,
        "exp": (
            datetime.now(timezone.utc) + timedelta(minutes=-5 if expired else 5)
        ).timestamp(),
    }
    payload.update(claim_overrides or {})
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = base64.urlsafe_b64encode(hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()).decode().rstrip("=")
    return f"{signing_input}.{signature}"


def _review_headers(**token_kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {_review_token(**token_kwargs)}"}


@pytest.fixture(autouse=True)
def _signed_token_secret(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)


def _service() -> tuple[SemanticAlignmentService, InMemoryRegistryStore]:
    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz",
        domain_code="policy",
        name="政策规则",
    ))
    registry_store.save_value_domain(ValueDomain(
        domain_code="PERSON_TYPE",
        name="人员类别",
        standard_values=["职工医保"],
    ))
    registry_store.save_metric(Metric(
        metric_code="zcgz.person_type",
        object_code="zcgz",
        name="参保人员类别",
        semantic_type="Enum",
        value_domain="PERSON_TYPE",
        status="published",
    ))
    return (
        SemanticAlignmentService(
            SemanticRegistry(registry_store),
            InMemorySemanticAlignmentStore(),
        ),
        registry_store,
    )


def test_bind_existing_metric_and_create_policy_metric_draft(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, _store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    client = TestClient(create_app())
    binding = {
        "metric_code": "zcgz.person_type",
        "source_type": "policy_knowledge",
        "source_ref": "doc_1/unit_1/kn_1",
        "source_field": "psn_type",
        "source_version": "contract-2",
        "evidence": "政策原文：城镇职工",
    }

    response = client.post(f"{PREFIX}/bindings", json=binding, headers=_review_headers())

    assert response.status_code == 201
    assert response.json()["status"] == "draft"

    metric_response = client.post(f"{PREFIX}/metrics", json={
        "metric_code": "zcgz.special_population",
        "object_code": "zcgz",
        "name": "特殊人群",
        "semantic_type": "Enum",
        "value_domain": "PERSON_TYPE",
        "source_binding": {
            **binding,
            "metric_code": "zcgz.special_population",
            "source_field": "special_population",
        },
    }, headers=_review_headers())

    assert metric_response.status_code == 201
    assert metric_response.json()["status"] == "draft"


def test_new_standard_value_requires_separate_review_action(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, registry_store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    client = TestClient(create_app())

    proposal_response = client.post(f"{PREFIX}/standard-values", json={
        "domain_code": "PERSON_TYPE",
        "standard_value": "灵活就业医保",
        "evidence": "政策知识出现灵活就业人员",
        "source_ref": "doc_1/unit_2/kn_2",
    }, headers=_review_headers())

    assert proposal_response.status_code == 201
    proposal = proposal_response.json()
    assert proposal["status"] == "draft"
    assert "灵活就业医保" not in registry_store.get_value_domain("PERSON_TYPE").standard_values  # type: ignore[union-attr]

    publish_response = client.post(
        f"{PREFIX}/standard-values/{proposal['proposal_id']}/publish",
        json={"reviewed_by": "semantic_reviewer"},
        headers=_review_headers(user_id="token-reviewer"),
    )

    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
    assert publish_response.json()["reviewed_by"] == "token-reviewer"
    assert "灵活就业医保" in registry_store.get_value_domain("PERSON_TYPE").standard_values  # type: ignore[union-attr]


def test_batch_bind_returns_item_level_results(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, _store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    client = TestClient(create_app())

    response = client.post(f"{PREFIX}/bindings/batch", json={"items": [
        {
            "metric_code": "zcgz.person_type",
            "source_type": "structured_field",
            "source_ref": "his.patient",
            "source_field": "person_type",
            "source_version": "v3",
            "evidence": "HIS 字段",
        },
        {
            "metric_code": "zcgz.missing",
            "source_type": "policy_knowledge",
            "source_ref": "doc_1/unit_1/kn_9",
            "source_field": "missing",
            "source_version": "contract-2",
            "evidence": "政策字段",
        },
    ]}, headers=_review_headers())

    assert response.status_code == 200
    assert [item["status"] for item in response.json()] == ["created", "error"]
    assert response.json()[1]["error"] == "标准指标不存在: zcgz.missing"


def _intake_metric(service: SemanticAlignmentService, concept: str = "大额互助起付标准"):
    return service.intake_signal(DiscoverySignal(
        trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
        concept=concept,
        metric_code="zcgz.mutual_aid_deductible",
        metric_name=concept,
        semantic_type="Amount",
        unit="元",
        evidence=DiscoveryEvidence(
            source_ref="doc-1/unit-1/ext-1",
            doc_id="doc-1",
            unit_id="unit-1",
            extraction_id="ext-1",
            excerpt=f"{concept} 650 元",
        ),
        confidence=0.8,
    ))


def _intake_value(service: SemanticAlignmentService):
    return service.intake_signal(DiscoverySignal(
        trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
        concept="灵活就业医保",
        axis_metric_code="zcgz.person_type",
        domain_code="PERSON_TYPE",
        suggested_mappings=[SourceValueMappingDraft(
            metric_code="zcgz.person_type",
            domain_code="PERSON_TYPE",
            source_value="灵活就业",
            standard_value="灵活就业医保",
        )],
        evidence=DiscoveryEvidence(
            source_ref="doc-2/unit-2/ext-2",
            doc_id="doc-2",
            unit_id="unit-2",
            extraction_id="ext-2",
            excerpt="灵活就业医保参照职工医保执行",
        ),
        confidence=0.7,
    ))


def test_proposal_api_requires_semantic_review_permission(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, _store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    client = TestClient(create_app())

    assert client.get(f"{PREFIX}/proposals").status_code == 401
    assert client.get(
        f"{PREFIX}/proposals", headers=_review_headers(expired=True)
    ).status_code == 401
    assert client.get(
        f"{PREFIX}/proposals", headers=_review_headers(permissions=[])
    ).status_code == 403
    forged = _review_token()
    forged = f"{forged.rsplit('.', 1)[0]}.bogus-signature"
    assert client.get(
        f"{PREFIX}/proposals", headers={"Authorization": f"Bearer {forged}"}
    ).status_code == 401
    header, payload, signature = _review_token().split(".")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    decoded["sub"] = "forged-reviewer"
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps(decoded).encode()
    ).decode().rstrip("=")
    assert client.get(
        f"{PREFIX}/proposals",
        headers={"Authorization": f"Bearer {header}.{tampered_payload}.{signature}"},
    ).status_code == 401
    for claim_overrides in (
        {"exp": "invalid"},
        {"exp": float("nan")},
        {"exp": float("inf")},
        {"permissions": {"semantic:review": False}},
        {"permissions": "semantic:review"},
        {"roles": "information_department"},
    ):
        assert client.get(
            f"{PREFIX}/proposals",
            headers=_review_headers(claim_overrides=claim_overrides),
        ).status_code == 401


def test_proposal_list_filters_metric_and_value_tabs(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, _store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    metric = _intake_metric(service)
    value = _intake_value(service)
    client = TestClient(create_app())

    metric_response = client.get(
        f"{PREFIX}/proposals",
        params={"proposal_type": "metric", "status": "proposed"},
        headers=_review_headers(),
    )
    value_response = client.get(
        f"{PREFIX}/proposals",
        params={"proposal_type": "value"},
        headers=_review_headers(),
    )

    assert metric_response.status_code == 200
    assert [item["proposal_id"] for item in metric_response.json()] == [metric.proposal_id]
    assert [item["proposal_id"] for item in value_response.json()] == [value.proposal_id]


def test_metric_proposal_review_accept_publish_uses_token_principal(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, registry_store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    proposal = _intake_metric(service)
    client = TestClient(create_app())
    headers = _review_headers(user_id="reviewer-from-token")

    detail = client.get(f"{PREFIX}/proposals/{proposal.proposal_id}", headers=headers)
    opened = client.post(f"{PREFIX}/proposals/{proposal.proposal_id}/review", headers=headers)
    accepted = client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/accept",
        json={"reviewed_by": "body-must-not-win"},
        headers=headers,
    )
    published = client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/publish", headers=headers
    )

    assert detail.status_code == 200
    assert detail.json()["status"] == "proposed"
    assert opened.status_code == 200
    assert opened.json()["status"] == "reviewing"
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["reviewed_by"] == "reviewer-from-token"
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    metric = registry_store.get_metric("zcgz.mutual_aid_deductible")
    assert metric is not None and metric.status == "published"
    extraction_schema = build_extraction_schema(service._registry, "zcgz")
    assert "mutual_aid_deductible" in {
        field.code for field in extraction_schema.fields
    }


def test_value_proposal_publish_updates_domain_and_runtime_mapping(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, registry_store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    proposal = _intake_value(service)
    client = TestClient(create_app())
    headers = _review_headers()

    assert client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/review", headers=headers
    ).status_code == 200
    assert client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/accept", headers=headers
    ).status_code == 200
    published = client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/publish", headers=headers
    )

    assert published.status_code == 200
    assert published.json()["status"] == "published"
    domain = registry_store.get_value_domain("PERSON_TYPE")
    assert domain is not None and "灵活就业医保" in domain.standard_values
    assert service._registry.resolve_value("PERSON_TYPE", "灵活就业") == "灵活就业医保"


def test_rejected_value_proposal_requires_reason_and_does_not_land(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, registry_store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    proposal = _intake_value(service)
    client = TestClient(create_app())
    headers = _review_headers()
    client.post(f"{PREFIX}/proposals/{proposal.proposal_id}/review", headers=headers)

    blank = client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/reject",
        json={"reason": "   "},
        headers=headers,
    )
    rejected = client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/reject",
        json={"reason": "与现有职工医保语义重复"},
        headers=headers,
    )
    publish = client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/publish", headers=headers
    )

    assert blank.status_code == 400
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert publish.status_code == 409
    assert "灵活就业医保" not in registry_store.get_value_domain("PERSON_TYPE").standard_values  # type: ignore[union-attr]


def test_sensitive_signal_is_not_listable(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, _store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    with pytest.raises(ValueError, match="敏感"):
        _intake_metric(service, concept="身份证 110101199001011234")
    client = TestClient(create_app())

    response = client.get(f"{PREFIX}/proposals", headers=_review_headers())

    assert response.status_code == 200
    assert response.json() == []


def test_proposal_list_and_detail_redact_historical_phi_without_mutating_store(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, _store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    proposal = _intake_metric(service)
    original_proposal_id = proposal.proposal_id
    proposal.proposal_id = "proposal-110101199001011234"
    proposal.fingerprint = "fingerprint-110101199001011234"
    proposal.object_code = "object-110101199001011234"
    proposal.metric_draft.metric_code = "zcgz.110101199001011234"  # type: ignore[union-attr]
    proposal.concept = "患者姓名：张三"
    proposal.metric_draft.name = "患者姓名：张三"  # type: ignore[union-attr]
    proposal.evidence[0].source_ref = (
        "doc-110101199001011234/unit-110101199001011234/ext-110101199001011234"
    )
    proposal.evidence[0].doc_id = "doc-110101199001011234"
    proposal.evidence[0].unit_id = "unit-110101199001011234"
    proposal.evidence[0].extraction_id = "ext-110101199001011234"
    proposal.evidence[0].excerpt = (
        "患者姓名：张三，身份证 110101199001011234，"
        "手机号 13800138000，病历号：MR-9988，住院号：ZY20260812"
    )
    service._store.proposals.pop(original_proposal_id)  # type: ignore[attr-defined]
    service._store.save_proposal(proposal)
    client = TestClient(create_app())

    listed = client.get(f"{PREFIX}/proposals", headers=_review_headers())
    detail = client.get(
        f"{PREFIX}/proposals/{proposal.proposal_id}", headers=_review_headers()
    )

    assert listed.status_code == detail.status_code == 200
    for payload in (listed.json()[0], detail.json()):
        serialized = json.dumps(payload, ensure_ascii=False)
        for secret in (
            "张三", "110101199001011234", "13800138000", "MR-9988", "ZY20260812"
        ):
            if secret != "110101199001011234":
                assert secret not in serialized
        assert payload["proposal_id"] == "proposal-110101199001011234"
        assert payload["fingerprint"] == "fingerprint-110101199001011234"
        assert payload["object_code"] == "object-110101199001011234"
        assert payload["metric_draft"]["metric_code"] == "zcgz.110101199001011234"
        assert payload["evidence"][0]["source_ref"] == (
            "doc-110101199001011234/unit-110101199001011234/ext-110101199001011234"
        )
        assert payload["evidence"][0]["doc_id"] == "doc-110101199001011234"
        assert payload["evidence"][0]["unit_id"] == "unit-110101199001011234"
        assert payload["evidence"][0]["extraction_id"] == "ext-110101199001011234"
        assert payload["evidence"][0]["excerpt"]
        assert "身份证 [已脱敏:身份证号]" in payload["evidence"][0]["excerpt"]
    stored = service.get_proposal(proposal.proposal_id)
    assert stored is not None and "张三" in stored.concept
    assert "110101199001011234" in (stored.evidence[0].excerpt or "")


@pytest.mark.parametrize("status", [
    ProposalStatus.REVIEWING,
    ProposalStatus.ACCEPTED,
    ProposalStatus.PUBLISHED,
    ProposalStatus.REJECTED,
])
def test_repeated_review_redacts_historical_phi_in_every_non_proposed_state(
    monkeypatch, status: ProposalStatus
) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, _store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    proposal = _intake_metric(service)
    proposal.status = status
    proposal.evidence[0].excerpt = "患者姓名：张三，手机号 13800138000"
    service._store.save_proposal(proposal)
    client = TestClient(create_app())

    response = client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/review",
        headers=_review_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == status
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert "张三" not in serialized
    assert "13800138000" not in serialized
    assert response.json()["evidence"][0]["source_ref"] == "doc-1/unit-1/ext-1"


def test_legacy_publish_requires_review_permission_and_cannot_mutate(monkeypatch) -> None:
    from src.runtime.api import semantic_alignment_routes

    service, registry_store = _service()
    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: service)
    client = TestClient(create_app())
    proposal = service.propose_standard_value(StandardValueProposalDraft(
        domain_code="PERSON_TYPE",
        standard_value="未授权新值",
        evidence="政策证据",
        source_ref="doc-unauthorized",
    ))

    response = client.post(
        f"{PREFIX}/standard-values/{proposal.proposal_id}/publish",
        json={"reviewed_by": "attacker"},
    )

    assert response.status_code == 401
    domain = registry_store.get_value_domain("PERSON_TYPE")
    assert domain is not None and "未授权新值" not in domain.standard_values

