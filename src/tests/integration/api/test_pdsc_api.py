"""PDSC API 集成测试：鉴权、线索接入、裁决、适用关系与 Skill 解析入口。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.pdsc import (
    InMemoryPdscStore,
    PdscService,
    PolicyUnitEvidence,
)
from src.runtime.api.app import create_app
from src.semantic_layer.models import BusinessObject, Metric, ValueDomain
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry

PREFIX = "/api/v1/medical-insurance-ai-agent/semantic/pdsc"
JWT_SECRET = "pdsc-test-secret"


def _review_token(user_id: str = "pdsc-reviewer", permissions: list[str] | None = None) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "roles": ["information_department"],
        "permissions": ["semantic:review"] if permissions is None else permissions,
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = base64.urlsafe_b64encode(hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()).decode().rstrip("=")
    return f"{signing_input}.{signature}"


def _review_headers(**kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {_review_token(**kwargs)}"}


@pytest.fixture(autouse=True)
def _signed_token_secret(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)


class FakeCorpus:
    def find_unit_evidence(self, concept, aliases, values):
        return [
            PolicyUnitEvidence(
                doc_id="doc_1", unit_id="u1", excerpt="支持原文",
                found_values=list(values), concept_matched=True,
            ),
        ]


def _service() -> PdscService:
    store = InMemoryRegistryStore()
    store.save_object(BusinessObject(object_code="zcgz", domain_code="policy", name="政策规则"))
    store.save_object(BusinessObject(object_code="djxx", domain_code="ybdy", name="参保人登记"))
    store.save_value_domain(ValueDomain(domain_code="POLICY_HOSP", name="政策机构类别",
                                        standard_values=["三级医院"]))
    store.save_value_domain(ValueDomain(domain_code="HOSP_TYPE", name="机构类别",
                                        standard_values=["三级医院"]))
    store.save_metric(Metric(metric_code="zcgz.hosp_type", object_code="zcgz",
                             name="机构类别", semantic_type="Enum",
                             value_domain="POLICY_HOSP", status="published"))
    store.save_metric(Metric(metric_code="djxx.hosp_type", object_code="djxx",
                             name="医疗机构类别", semantic_type="Enum",
                             value_domain="HOSP_TYPE", source_field="category",
                             status="published"))
    return PdscService(SemanticRegistry(store), InMemoryPdscStore(), FakeCorpus())


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    from src.runtime.api import pdsc_routes

    # 固定单实例：每次新建会让内存存储互不可见
    service = _service()
    monkeypatch.setattr(pdsc_routes, "_get_service", lambda: service)
    return TestClient(create_app())


def _signal_payload(source_ref: str = "t1") -> dict:
    return {
        "signal": {
            "trigger_source": "EXTRACTION_UNKNOWN",
            "evidence": {
                "source_ref": source_ref,
                "evidence_kind": "policy",
                "doc_id": "doc_1",
                "unit_id": "unit_1",
                "extraction_id": "ext_1",
                "excerpt": "三级医院住院支付比例",
                "sample_values": ["三级医院"],
            },
            "concept": "医疗机构类别",
            "semantic_type": "Enum",
            "metric_code": "zcgz.hosp_type",
        },
        "policy_values": ["三级医院"],
    }


def test_pdsc_requires_authentication(client: TestClient) -> None:
    response = client.post(f"{PREFIX}/signals", json=_signal_payload())
    assert response.status_code == 401


def test_pdsc_requires_review_permission(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/signals", json=_signal_payload(),
        headers=_review_headers(permissions=["other:permission"]),
    )
    assert response.status_code == 403


def test_full_governance_flow_over_api(client: TestClient) -> None:
    # 1. 线索接入
    response = client.post(f"{PREFIX}/signals", json=_signal_payload(), headers=_review_headers())
    assert response.status_code == 201
    cluster = response.json()
    cluster_id = cluster["cluster_id"]
    assert cluster["status"] == "pending"

    # 2. 调整方案绑定业务指标（需理由）
    adjust = client.post(f"{PREFIX}/clusters/{cluster_id}/adjust", json={
        "reason": "确认业务字段角色",
        "business_metric_code": "djxx.hosp_type",
    }, headers=_review_headers())
    assert adjust.status_code == 200

    # 无理由调整被拒
    assert client.post(f"{PREFIX}/clusters/{cluster_id}/adjust", json={
        "reason": " ", "policy_values": ["三级医院"],
    }, headers=_review_headers()).status_code == 400

    # 3. 刷新：交叉验证 + 评分 + 值域对齐
    refresh = client.post(f"{PREFIX}/clusters/{cluster_id}/refresh", json={
        "database_values": [
            {"value": "三级医院", "definition": "三级定点"},
        ],
    }, headers=_review_headers())
    assert refresh.status_code == 200
    refreshed = refresh.json()
    assert refreshed["cross_validation"]["counts"]["supporting"] == 1
    assert refreshed["score"]["total"] > 0
    assert refreshed["value_alignment"]["alignment_score"] is not None

    # 4. 一屏决策包
    package = client.get(f"{PREFIX}/clusters/{cluster_id}/decision-package",
                         headers=_review_headers())
    assert package.status_code == 200
    assert package.json()["recommended_business_metric_code"] == "djxx.hosp_type"
    assert "unit_1" in package.json()["affected_unit_ids"]

    # 4b. 决策包携带候选业务指标与库画像字段（内存模式画像为 None，字段存在即可）
    pkg = package.json()
    assert "business_metric_candidates" in pkg
    assert "business_field_profile" in pkg
    # 已绑定指标的簇：绑定项应出现在候选首位
    assert pkg["business_metric_candidates"][0]["metric_code"] == "djxx.hosp_type"
    assert pkg["business_metric_candidates"][0]["match_reasons"]

    # 5. 裁决：接受完整方案（无需理由）
    decide = client.post(f"{PREFIX}/clusters/{cluster_id}/decide", json={
        "action": "accept_full_plan",
    }, headers=_review_headers())
    assert decide.status_code == 200
    assert decide.json()["status"] == "accepted"

    # 6. 构建并发布适用关系
    relation = client.post(f"{PREFIX}/clusters/{cluster_id}/relation", json={},
                           headers=_review_headers())
    assert relation.status_code == 201
    relation_id = relation.json()["relation_id"]

    published = client.post(f"{PREFIX}/relations/{relation_id}/publish",
                            headers=_review_headers())
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    # 7. Skill 运行时解析（免审核权限）
    resolve = client.post(f"{PREFIX}/resolve-policy-filters", json={
        "business_metric_code": "djxx.hosp_type",
        "business_standard_value": "三级医院",
    })
    assert resolve.status_code == 200
    assert resolve.json() == [{"policy_metric_code": "zcgz.hosp_type", "policy_value": "三级医院"}]


def test_not_issue_requires_reason_and_blocks_refingerprint(client: TestClient) -> None:
    response = client.post(f"{PREFIX}/signals", json=_signal_payload(), headers=_review_headers())
    cluster_id = response.json()["cluster_id"]

    rejected = client.post(f"{PREFIX}/clusters/{cluster_id}/decide", json={
        "action": "not_issue",
    }, headers=_review_headers())
    assert rejected.status_code == 400

    archived = client.post(f"{PREFIX}/clusters/{cluster_id}/decide", json={
        "action": "not_issue", "reason": "文字相似但业务角色不同",
    }, headers=_review_headers())
    assert archived.status_code == 200
    assert archived.json()["status"] == "not_issue"

    # 同指纹信号再次进入 → 直接返回归档簇，不产生新簇
    again = client.post(f"{PREFIX}/signals", json=_signal_payload("t1-rerun"),
                        headers=_review_headers())
    assert again.json()["cluster_id"] == cluster_id


def test_conflict_blocks_accept_over_api(client: TestClient) -> None:
    service_response = client.post(f"{PREFIX}/signals", json=_signal_payload(), headers=_review_headers())
    cluster_id = service_response.json()["cluster_id"]
    # corpus 无冲突时刷新后直接接受
    client.post(f"{PREFIX}/clusters/{cluster_id}/adjust", json={
        "reason": "绑定", "business_metric_code": "djxx.hosp_type",
    }, headers=_review_headers())
    decide = client.post(f"{PREFIX}/clusters/{cluster_id}/decide", json={
        "action": "accept_full_plan",
    }, headers=_review_headers())
    assert decide.status_code == 200


def test_list_clusters_sorted_by_score(client: TestClient) -> None:
    client.post(f"{PREFIX}/signals", json=_signal_payload(), headers=_review_headers())
    response = client.get(f"{PREFIX}/clusters", headers=_review_headers())
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_missing_cluster_returns_404(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/clusters/sdc_missing", headers=_review_headers())
    assert response.status_code == 404


def test_split_over_api(client: TestClient) -> None:
    from src.tests.unit.knowledge_extension.test_pdsc_phase2 import _signal
    from src.runtime.api import pdsc_routes

    svc = pdsc_routes._get_service()
    svc.intake_signal(_signal("t1"), policy_values=["三级医院"])
    svc.intake_signal(_signal("t2"), policy_values=["三级医院"])
    cluster = svc.list_clusters()[0]

    response = client.post(f"{PREFIX}/clusters/{cluster.cluster_id}/split", json={
        "source_refs": ["t1"], "reason": "按时间拆分",
    }, headers=_review_headers())
    assert response.status_code == 200
    assert len(response.json()["evidence"]) == 1


def test_activate_over_api_reports_failure_steps(client: TestClient, monkeypatch) -> None:
    from src.tests.unit.knowledge_extension.test_pdsc_phase2 import (
        ActivationPorts, StubCompileChecker, StubReextractor,
    )
    from src.runtime.api import pdsc_routes

    svc = pdsc_routes._get_service()
    from src.knowledge_extension.rule_explanation.semantic_alignment import DiscoverySignal

    cluster = svc.intake_signal(DiscoverySignal(
        trigger_source="EXTRACTION_UNKNOWN",
        evidence={
            "source_ref": "t1", "evidence_kind": "policy", "doc_id": "doc_1",
            "unit_id": "unit_1", "extraction_id": "ext_1",
            "excerpt": "三级医院住院支付比例", "sample_values": ["三级医院"],
        },
        concept="医疗机构类别", semantic_type="Enum",
        metric_code="zcgz.hosp_type", object_code="zcgz",
    ), policy_values=["三级医院"])
    svc.adjust_cluster(cluster.cluster_id, "r", "绑定",
                       business_metric_code="djxx.hosp_type")
    svc.decide(cluster.cluster_id, "accept_full_plan", "reviewer", reason="单源补理由")
    svc.build_applicability_relation(cluster.cluster_id, "reviewer")

    monkeypatch.setattr(pdsc_routes, "_activation_ports", lambda: ActivationPorts(
        reextractor=StubReextractor(), compile_checker=StubCompileChecker(fail=True),
    ))

    response = client.post(
        f"{PREFIX}/clusters/{cluster.cluster_id}/activate", headers=_review_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["failed_step"] == "compile"
    # 关系保持 draft（活动版本未变）
    assert svc.list_relations()[0].status == "draft"

    # 激活记录可查
    activation_id = body["activation_id"]
    fetched = client.get(f"{PREFIX}/activations/{activation_id}", headers=_review_headers())
    assert fetched.status_code == 200


def test_scan_endpoint_intakes_detected_signals(client: TestClient, monkeypatch) -> None:
    extractions = [{
        "extraction_id": "e1", "doc_id": "d1", "unit_id": "u1",
        "source_text": "医疗机构起付标准",
        "extracted_fields": {"hosp_type": "四级医院"},
    }]

    class FakePipelineStore:
        def list_extractions(self, page=1, page_size=20, doc_id="", status=""):
            return {"items": extractions, "total": 1}

    monkeypatch.setattr(
        "src.knowledge_extension.rule_explanation.pipeline_store.PipelineStore",
        FakePipelineStore,
    )

    response = client.post(f"{PREFIX}/scan", headers=_review_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["scanned_extractions"] == 1
    violation = next(d for d in body["detectors"] if d["detector"] == "value_domain_violation")
    assert violation["signals"] == 1
    assert body["intaked_clusters"] >= 1
    # 扫描产生的簇在列表中可见（概念为干净业务名，诊断句在 diagnosis）
    clusters = client.get(f"{PREFIX}/clusters", headers=_review_headers()).json()
    assert any("值域外取值" in (c["diagnosis"] or "") for c in clusters)