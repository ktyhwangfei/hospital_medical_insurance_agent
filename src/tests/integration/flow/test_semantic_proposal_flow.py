from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    InMemorySemanticAlignmentStore,
    ProposalType,
    SemanticAlignmentService,
)
from src.runtime.api.app import create_app
from src.semantic_layer.extraction_contract import build_extraction_schema
from src.semantic_layer.models import BusinessObject
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


PREFIX = "/api/v1/medical-insurance-ai-agent/semantic/alignment"


class _PipelineStore:
    def __init__(self) -> None:
        self.document = {"doc_id": "doc_flow", "title": "互助政策"}
        self.extractions: dict[str, dict] = {}

    def get_document(self, doc_id: str) -> dict | None:
        return self.document if doc_id == "doc_flow" else None

    def batch_create_extractions(self, items: list[dict]) -> int:
        for item in items:
            self.extractions[item["extraction_id"]] = {**item, "status": "draft"}
        return len(items)

    def update_extraction(self, extraction_id: str, data: dict) -> dict:
        self.extractions[extraction_id].update(data)
        return self.extractions[extraction_id]

    def get_extraction(self, extraction_id: str) -> dict | None:
        return self.extractions.get(extraction_id)


def _review_headers(secret: str) -> dict[str, str]:
    encode = lambda value: base64.urlsafe_b64encode(  # noqa: E731
        json.dumps(value, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    header = encode({"alg": "HS256", "typ": "JWT"})
    payload = encode({
        "sub": "semantic-flow-reviewer",
        "roles": ["information_department"],
        "permissions": ["semantic:review"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    })
    signing_input = f"{header}.{payload}"
    signature = base64.urlsafe_b64encode(hmac.new(
        secret.encode(), signing_input.encode(), hashlib.sha256,
    ).digest()).decode().rstrip("=")
    return {"Authorization": f"Bearer {signing_input}.{signature}"}


def test_extraction_unknown_flows_through_review_to_live_schema(monkeypatch) -> None:
    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则", status="published",
    ))
    registry = SemanticRegistry(registry_store)
    alignment = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    pipeline_store = _PipelineStore()
    orchestrator = PipelineOrchestrator(
        store=pipeline_store, alignment_service=alignment,
    )
    monkeypatch.setattr(orchestrator, "_extract_policy_facts", lambda *_args, **_kwargs: [{
        "fact_text": "大额互助起付标准为650元。",
        "rules": [{"confidence": 0.9}],
        "unknown_concepts": [{
            "concept": "大额互助起付标准",
            "concept_type": "new_metric",
            "metric_code": "zcgz.mutual_aid_deductible",
            "metric_name": "大额互助起付标准",
            "definition": "大额医疗互助年度起付金额",
            "semantic_type": "Amount",
            "unit": "元",
            "confidence": 0.9,
        }],
    }])

    extraction = orchestrator.extract_single(
        "doc_flow", "大额互助起付标准为650元。", unit_id="unit_1",
    )

    assert extraction["success"] is True
    proposal = alignment.list_proposals(ProposalType.METRIC)[0]
    assert pipeline_store.get_extraction(proposal.evidence[0].extraction_id) is not None

    from src.runtime.api import semantic_alignment_routes

    monkeypatch.setattr(semantic_alignment_routes, "_get_service", lambda: alignment)
    secret = "semantic-flow-secret"
    monkeypatch.setenv("AUTH_JWT_SECRET", secret)
    client = TestClient(create_app())
    headers = _review_headers(secret)

    assert client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/review", headers=headers,
    ).json()["status"] == "reviewing"
    assert client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/accept", headers=headers,
    ).json()["status"] == "accepted"
    assert client.post(
        f"{PREFIX}/proposals/{proposal.proposal_id}/publish", headers=headers,
    ).json()["status"] == "published"

    schema = build_extraction_schema(registry, "zcgz")
    assert "mutual_aid_deductible" in {field.code for field in schema.fields}
