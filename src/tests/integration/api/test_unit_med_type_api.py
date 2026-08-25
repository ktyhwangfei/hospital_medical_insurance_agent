"""Issue #19 API：构建单元医疗类别读取与人工修正。

覆盖 3 个端点：
- GET  /knowledge-build/eligible-units — 单元携带 med_type / med_type_source
- POST /knowledge-build/unit-med-types — 人工修正覆盖自动分类
- DELETE /knowledge-build/unit-med-types/{doc_id}/{unit_id} — 恢复自动分类
"""
from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app

PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"


def _headers(*, permissions: list[str] | None = None, subject: str = "policy-reviewer"):
    payload = {
        "sub": subject,
        "roles": ["information_department"],
        "permissions": permissions or [],
        "exp": 4102444800,
    }
    token = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return {"Authorization": f"Bearer test.{token}.signature"}


class _WorkbenchStub:
    def get_document(self, doc_id: str, include_knowledge: bool = True):
        from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
            ApprovedUnit,
        )
        return type("Doc", (), {
            "doc_id": doc_id,
            "doc_title": "医保待遇政策",
            "contract_version": "v1",
            "units": [
                ApprovedUnit(
                    unit_id="u_hosp",
                    doc_id="doc_1",
                    doc_title="医保待遇政策",
                    path=["第三章", "第十二条"],
                    source_text="在职职工住院费用，统筹基金支付85%。",
                    order_no=0,
                    status="reviewed",
                    knowledge_count=0,
                    knowledge=[],
                ),
            ],
        })()

    def list_document_ids(self):
        return ["doc_1"]


@pytest.fixture()
def client(monkeypatch):
    from src.runtime.api import policy_workbench_routes
    from src.knowledge_extension.rule_explanation.change_set_store import (
        InMemoryChangeSetStore,
    )
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_service import (
        KnowledgeBuildService,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        InMemoryKnowledgeBuildStore,
    )
    from src.knowledge_extension.rule_explanation.unit_med_type_store import (
        InMemoryUnitMedTypeStore,
    )

    med_store = InMemoryUnitMedTypeStore()
    service = KnowledgeBuildService(
        _WorkbenchStub(),  # type: ignore[arg-type]
        ChangeSetService(_WorkbenchStub(), InMemoryChangeSetStore()),  # type: ignore[arg-type]
        InMemoryKnowledgeBuildStore(),
        med_type_store=med_store,
    )
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_service", service)
    monkeypatch.setattr(policy_workbench_routes, "_unit_med_type_store", med_store)
    return TestClient(create_app())


def test_eligible_units_carry_auto_med_type(client):
    resp = client.get(f"{PREFIX}/knowledge-build/eligible-units")
    assert resp.status_code == 200, resp.text
    units = resp.json()
    assert len(units) == 1
    assert units[0]["med_type"] == "住院"
    assert units[0]["med_type_source"] == "auto"


def test_manual_override_and_reset(client):
    # 人工修正：住院 → 门诊特殊病
    resp = client.post(f"{PREFIX}/knowledge-build/unit-med-types", json={
        "doc_id": "doc_1",
        "unit_id": "u_hosp",
        "med_type": "门诊特殊病",
        "updated_by": "forged-client-actor",
    }, headers=_headers(permissions=["semantic:review"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["med_type"] == "门诊特殊病"
    assert resp.json()["updated_by"] == "policy-reviewer"

    units = client.get(f"{PREFIX}/knowledge-build/eligible-units").json()
    assert units[0]["med_type"] == "门诊特殊病"
    assert units[0]["med_type_source"] == "manual"

    # 重置：恢复自动分类
    reset = client.delete(
        f"{PREFIX}/knowledge-build/unit-med-types/doc_1/u_hosp",
        headers=_headers(permissions=["semantic:review"]),
    )
    assert reset.status_code == 200
    units = client.get(f"{PREFIX}/knowledge-build/eligible-units").json()
    assert units[0]["med_type"] == "住院"
    assert units[0]["med_type_source"] == "auto"


def test_override_rejects_blank_med_type(client):
    resp = client.post(f"{PREFIX}/knowledge-build/unit-med-types", json={
        "doc_id": "doc_1",
        "unit_id": "u_hosp",
        "med_type": "   ",
    }, headers=_headers(permissions=["semantic:review"]))
    assert resp.status_code == 422


def test_override_requires_permission_and_rejects_unknown_target_or_category(client):
    body = {"doc_id": "doc_1", "unit_id": "u_hosp", "med_type": "门诊"}
    assert client.post(f"{PREFIX}/knowledge-build/unit-med-types", json=body).status_code == 401
    forbidden = client.post(
        f"{PREFIX}/knowledge-build/unit-med-types",
        json=body,
        headers=_headers(permissions=["policy:read"]),
    )
    assert forbidden.status_code == 403

    invalid = client.post(
        f"{PREFIX}/knowledge-build/unit-med-types",
        json={**body, "med_type": "任意自造类别"},
        headers=_headers(permissions=["semantic:review"]),
    )
    assert invalid.status_code == 422

    missing = client.post(
        f"{PREFIX}/knowledge-build/unit-med-types",
        json={**body, "unit_id": "missing"},
        headers=_headers(permissions=["semantic:review"]),
    )
    assert missing.status_code == 404
