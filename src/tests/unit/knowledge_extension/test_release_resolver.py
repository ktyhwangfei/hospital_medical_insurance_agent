"""统一 release resolver 单元测试（Issue #33 P0-1）。

覆盖：active release 优先、集合缺失/为空/指针失败/Milvus 探测失败四类回退、
facts 集合解析、uri 拆分。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture()
def resolver(monkeypatch):
    from src.knowledge_extension.rule_explanation import release_resolver

    monkeypatch.setattr(release_resolver, "_store", None)
    return release_resolver


def _patch_store(resolver, monkeypatch, release) -> None:
    monkeypatch.setattr(
        resolver, "_get_store", lambda: SimpleNamespace(get_active_release=lambda: release)
    )


def _patch_milvus(
    resolver,
    monkeypatch,
    existing=("policy_rules_REL_A", "policy_facts_REL_A"),
    row_count=10,
) -> None:
    class FakeMilvusClient:
        def __init__(self, uri=None, **_kwargs) -> None:
            pass

        def list_collections(self):
            return list(existing)

        def get_collection_stats(self, _name):
            return {"row_count": row_count}

    monkeypatch.setattr(resolver, "MilvusClient", FakeMilvusClient)


_RELEASE = SimpleNamespace(
    rules_collection="policy_rules_REL_A",
    facts_collection="policy_facts_REL_A",
)


def test_active_release_ready_returns_release_collection(resolver, monkeypatch) -> None:
    _patch_store(resolver, monkeypatch, _RELEASE)
    _patch_milvus(resolver, monkeypatch)

    assert resolver.resolve_rules_collection() == "policy_rules_REL_A"
    assert resolver.resolve_facts_collection() == "policy_facts_REL_A"


def test_no_active_release_falls_back(resolver, monkeypatch) -> None:
    _patch_store(resolver, monkeypatch, None)

    assert resolver.resolve_rules_collection() == "policy_rules_v2"
    assert resolver.resolve_facts_collection() == "policy_facts"


def test_missing_collection_falls_back(resolver, monkeypatch) -> None:
    _patch_store(resolver, monkeypatch, _RELEASE)
    _patch_milvus(resolver, monkeypatch, existing=())

    assert resolver.resolve_rules_collection() == "policy_rules_v2"


def test_empty_collection_falls_back(resolver, monkeypatch) -> None:
    _patch_store(resolver, monkeypatch, _RELEASE)
    _patch_milvus(resolver, monkeypatch, row_count=0)

    assert resolver.resolve_rules_collection() == "policy_rules_v2"


def test_store_failure_falls_back(resolver, monkeypatch) -> None:
    class UnavailableStore:
        def get_active_release(self):
            raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(resolver, "_get_store", lambda: UnavailableStore())

    assert resolver.resolve_rules_collection() == "policy_rules_v2"


def test_milvus_probe_failure_falls_back(resolver, monkeypatch) -> None:
    _patch_store(resolver, monkeypatch, _RELEASE)

    class ExplodingClient:
        def __init__(self, uri=None, **_kwargs) -> None:
            raise RuntimeError("milvus unavailable")

    monkeypatch.setattr(resolver, "MilvusClient", ExplodingClient)

    assert resolver.resolve_rules_collection() == "policy_rules_v2"


def test_smaller_release_collection_is_still_complete(resolver, monkeypatch) -> None:
    """删除型发布行数低于主集合也合法：不再与 policy_rules_v2 比较行数。"""
    _patch_store(resolver, monkeypatch, _RELEASE)
    _patch_milvus(resolver, monkeypatch, row_count=1)

    assert resolver.resolve_rules_collection() == "policy_rules_REL_A"


def test_split_milvus_uri(resolver) -> None:
    assert resolver.split_milvus_uri("http://127.0.0.1:19530") == ("127.0.0.1", "19530")
    assert resolver.split_milvus_uri("10.0.0.2:19531") == ("10.0.0.2", "19531")
    assert resolver.split_milvus_uri("http://milvus") == ("milvus", "19530")
