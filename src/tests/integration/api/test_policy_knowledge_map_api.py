"""知识体系全景 API（GET /policy-knowledge/knowledge-map）测试 — 迭代 22。

以 FakeMilvusClient 替换 `_resolve_knowledge_map_sources`，不连真实 Milvus。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app

PREFIX = "/api/v1/medical-insurance-ai-agent/policy-knowledge"


class FakeMilvusClient:
    """MilvusClient 假实现：预置集合行数、规则行与事实行。"""

    def __init__(self, *, stats=None, rule_rows=None, fact_rows=None, fact_error=False):
        self._stats = stats or {}
        self._rule_rows = rule_rows or []
        self._fact_rows = fact_rows or []
        self._fact_error = fact_error

    def list_collections(self):
        return list(self._stats)

    def get_collection_stats(self, name):
        return {"row_count": self._stats.get(name, 0)}

    def query(self, collection_name, filter="", output_fields=None, limit=0):
        if collection_name.startswith("policy_facts"):
            if self._fact_error:
                raise RuntimeError("facts collection not loaded")
            return self._fact_rows
        # 只返回请求的投影字段，模拟 Milvus output_fields 行为
        return [{f: row.get(f, "") for f in (output_fields or [])} for row in self._rule_rows]


def _trace(value):
    """构造 FieldTrace dict（detail 字段落 dynamic field 的真实形态）。"""
    return {"value": value, "extracted_at": "2026-09-16T00:00:00", "schema_version": 1, "confidence": 0.9}


RULE_ROWS = [
    {
        "rule_id": "rule_1", "doc_id": "doc_A", "rule_type": "支付比例",
        "insu_type": "职工医保", "med_type": "住院-普通住院", "hosp_lv": "三级",
        "psn_type": "在职职工", "setl_type": "", "region": "北京",
        "effective_date": "2024-01-01", "expiry_date": "9999-12-31",
        "publish_status": "published", "policy_version": "1.0",
        "amount_band": _trace("起付标准至3万元"), "amount_band_min": 1300,
        "amount_band_max": 30000, "admission_order": "", "priority": _trace("高"),
        "payment_ratio": _trace("85"), "personal_payment_ratio": _trace("15"),
        "deductible_amount": _trace("1300"), "cap_amount": "",
        "rule_value": _trace("统筹基金支付85%，职工支付15%"),
        "source_text": _trace("起付标准至3万元的部分，统筹基金支付85%"),
    },
    {
        "rule_id": "rule_2", "doc_id": "doc_A", "rule_type": "起付线",
        "insu_type": "居民医保", "med_type": "门诊-普通门急诊", "hosp_lv": "一级",
        "psn_type": "", "setl_type": "", "region": "北京",
        "effective_date": "1900-01-01", "expiry_date": "9999-12-31",
        "publish_status": "published", "policy_version": "1.0",
        "amount_band": "", "amount_band_min": 0, "amount_band_max": 0,
        "admission_order": "", "priority": "",
        "payment_ratio": "", "personal_payment_ratio": "",
        "deductible_amount": _trace("100"), "cap_amount": "",
        "rule_value": _trace("一级医院起付线100元"),
        "source_text": _trace("一级医院起付标准为100元"),
    },
]


def _install(monkeypatch, fake, *, rules="policy_rules_REL_2026", facts="policy_facts_REL_2026", release="REL_2026"):
    from src.runtime.api import policy_knowledge_routes as routes

    monkeypatch.setattr(
        routes,
        "_resolve_knowledge_map_sources",
        lambda: {
            "client": fake,
            "rules_collection": rules,
            "facts_collection": facts,
            "release_id": release,
        },
    )
    return TestClient(create_app())


def test_knowledge_map_lists_policy_collections_with_active_flags(monkeypatch):
    fake = FakeMilvusClient(
        stats={
            "policy_rules_REL_2026": 2,
            "policy_rules_v2": 337,
            "policy_facts_REL_2026": 269,
            "policy_facts": 269,
            "unrelated_collection": 5,
        },
    )
    client = _install(monkeypatch, fake)

    resp = client.get(f"{PREFIX}/knowledge-map")

    assert resp.status_code == 200
    body = resp.json()
    # 无关集合不计入；按名称排序；active 只标记当前读路径集合
    assert [c["name"] for c in body["collections"]] == [
        "policy_facts", "policy_facts_REL_2026", "policy_rules_REL_2026", "policy_rules_v2",
    ]
    by_name = {c["name"]: c for c in body["collections"]}
    assert by_name["policy_rules_REL_2026"] == {"name": "policy_rules_REL_2026", "kind": "rules", "row_count": 2, "active": True}
    assert by_name["policy_rules_v2"]["active"] is False
    assert by_name["policy_facts_REL_2026"] == {"name": "policy_facts_REL_2026", "kind": "facts", "row_count": 269, "active": True}
    assert by_name["policy_facts"]["active"] is False
    assert body["rules_collection"] == "policy_rules_REL_2026"
    assert body["facts_collection"] == "policy_facts_REL_2026"
    assert body["active_release_id"] == "REL_2026"


def test_knowledge_map_projects_rules_with_unpacked_details(monkeypatch):
    fake = FakeMilvusClient(stats={"policy_rules_REL_2026": 2}, rule_rows=RULE_ROWS)
    client = _install(monkeypatch, fake)

    resp = client.get(f"{PREFIX}/knowledge-map")

    assert resp.status_code == 200
    rules = resp.json()["rules"]
    assert len(rules) == 2
    first = rules[0]
    # FieldTrace 解包为裸值，再统一字符串化
    assert first["payment_ratio"] == "85"
    assert first["amount_band"] == "起付标准至3万元"
    assert first["rule_value"] == "统筹基金支付85%，职工支付15%"
    assert first["insu_type"] == "职工医保"
    assert first["amount_band_min"] == "1300"
    assert first["rule_id"] == "rule_1"


def test_knowledge_map_aggregates_facts_by_doc(monkeypatch):
    fake = FakeMilvusClient(
        stats={"policy_rules_REL_2026": 1, "policy_facts_REL_2026": 4},
        rule_rows=RULE_ROWS[:1],
        fact_rows=[{"doc_id": "doc_A"}, {"doc_id": "doc_A"}, {"doc_id": "doc_B"}, {"doc_id": ""}],
    )
    client = _install(monkeypatch, fake)

    resp = client.get(f"{PREFIX}/knowledge-map")

    assert resp.status_code == 200
    assert resp.json()["facts_by_doc"] == [
        {"doc_id": "doc_A", "count": 2},
        {"doc_id": "doc_B", "count": 1},
        {"doc_id": "", "count": 1},
    ]


def test_knowledge_map_with_empty_rules_collection(monkeypatch):
    fake = FakeMilvusClient(stats={"policy_rules_REL_2026": 0})
    client = _install(monkeypatch, fake)

    resp = client.get(f"{PREFIX}/knowledge-map")

    assert resp.status_code == 200
    body = resp.json()
    assert body["rules"] == []
    assert body["facts_by_doc"] == []


def test_knowledge_map_facts_failure_degrades_to_empty(monkeypatch):
    fake = FakeMilvusClient(stats={"policy_rules_REL_2026": 1}, rule_rows=RULE_ROWS[:1], fact_error=True)
    client = _install(monkeypatch, fake)

    resp = client.get(f"{PREFIX}/knowledge-map")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rules"]) == 1
    assert body["facts_by_doc"] == []


def test_knowledge_map_milvus_unavailable_returns_503(monkeypatch):
    from src.runtime.api import policy_knowledge_routes as routes

    def _boom():
        raise ImportError("pymilvus missing")

    monkeypatch.setattr(routes, "_resolve_knowledge_map_sources", _boom)
    client = TestClient(create_app())

    resp = client.get(f"{PREFIX}/knowledge-map")

    assert resp.status_code == 503
    assert resp.json()["detail"]["error_code"] == "MILVUS_UNAVAILABLE"
