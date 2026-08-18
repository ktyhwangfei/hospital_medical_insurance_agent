"""Issue #19 API 集成：extract-leaf 提取入库携带单元医疗类别。

链路：POST /policy-pipeline/documents → GET structure 取叶子 unit_id →
POST /documents/{id}/extract-leaf（LLM 桩）→ GET /extractions 验证
extracted_fields.unit_med_type 与 rules[].med_type 已按医疗类别区分。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app

PREFIX = "/api/v1/medical-insurance-ai-agent/policy-pipeline"

CONTENT = "第一条 参保人员在定点医疗机构发生的住院医疗费用，统筹基金支付85%。"


class _FakeStore:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.extractions: dict[str, dict] = {}
        self._seq = 0
        self._lock = threading.RLock()

    def create_document(self, body):
        with self._lock:
            self._seq += 1
            doc = {
                "doc_id": f"doc_{self._seq}",
                "title": body.get("title", ""),
                "content_text": body.get("content_text", ""),
                "status": "raw",
            }
            self.docs[doc["doc_id"]] = doc
            return doc

    def get_document(self, doc_id):
        return self.docs.get(doc_id)

    def claim_extraction_run(self, doc_id, run_token):
        return True

    @contextmanager
    def commit_extraction_run(self, doc_id, run_token):
        yield True

    def is_extraction_run_current(self, doc_id, run_token):
        return True

    def finish_extraction_run(self, doc_id, run_token, data):
        return True

    def list_extractions(self, page=1, page_size=20, doc_id="", status=""):
        items = [
            item for item in self.extractions.values()
            if (not doc_id or item["doc_id"] == doc_id)
            and item.get("status") != "archived"
        ]
        return {"items": items, "total": len(items), "page": page, "page_size": page_size}

    def batch_create_extractions(self, items):
        for item in items:
            self.extractions[item["extraction_id"]] = {**item, "status": "draft"}
        return len(items)


class _Alignment:
    def intake_signal(self, signal):
        pass

    def intake_conflict_report(self, report, **context):
        pass


def _first_leaf(node: dict) -> dict:
    if not node.get("children"):
        return node
    return _first_leaf(node["children"][0])


@pytest.fixture()
def client(monkeypatch):
    from src.runtime.api import policy_pipeline_routes
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )

    store = _FakeStore()
    orch = PipelineOrchestrator(store=store, alignment_service=_Alignment())
    monkeypatch.setattr(
        orch,
        "_extract_policy_facts",
        lambda *a, **k: [{
            "fact_text": "参保人员住院医疗费用统筹基金支付85%。",
            "rules": [{"confidence": 0.9, "payment_ratio": "85%"}],
        }],
    )
    monkeypatch.setattr(policy_pipeline_routes, "_store", store)
    monkeypatch.setattr(policy_pipeline_routes, "_orchestrator", orch)
    return TestClient(create_app())


def test_extract_leaf_persists_med_type(client):
    created = client.post(f"{PREFIX}/documents", json={
        "title": "住院待遇政策",
        "content_text": CONTENT,
    })
    assert created.status_code == 200, created.text
    doc_id = created.json()["doc_id"]

    structure = client.get(f"{PREFIX}/documents/{doc_id}/structure")
    assert structure.status_code == 200
    leaf = _first_leaf(structure.json()["root"])
    assert leaf["level"] != "document"

    resp = client.post(
        f"{PREFIX}/documents/{doc_id}/extract-leaf",
        json={"unit_id": leaf["node_id"], "source_text": leaf["text"]},
    )
    assert resp.status_code == 200, resp.text

    listing = client.get(f"{PREFIX}/extractions", params={"doc_id": doc_id})
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert items, "提取后应有提取记录"
    fields = items[0]["extracted_fields"]
    # 单元分类 + 规则继承（Issue #19：所有单元区分医疗类别）
    assert fields["unit_med_type"] == "住院"
    assert fields["rules"][0]["med_type"] == "住院"
