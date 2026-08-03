from __future__ import annotations

from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.semantic_alignment import (
    InMemorySemanticAlignmentStore,
    SemanticAlignmentService,
)
from src.runtime.api.app import create_app
from src.semantic_layer.models import BusinessObject, Metric, ValueDomain
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


PREFIX = "/api/v1/medical-insurance-ai-agent/semantic/alignment"


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

    response = client.post(f"{PREFIX}/bindings", json=binding)

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
    })

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
    })

    assert proposal_response.status_code == 201
    proposal = proposal_response.json()
    assert proposal["status"] == "draft"
    assert "灵活就业医保" not in registry_store.get_value_domain("PERSON_TYPE").standard_values  # type: ignore[union-attr]

    publish_response = client.post(
        f"{PREFIX}/standard-values/{proposal['proposal_id']}/publish",
        json={"reviewed_by": "semantic_reviewer"},
    )

    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
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
    ]})

    assert response.status_code == 200
    assert [item["status"] for item in response.json()] == ["created", "error"]
    assert response.json()[1]["error"] == "标准指标不存在: zcgz.missing"

