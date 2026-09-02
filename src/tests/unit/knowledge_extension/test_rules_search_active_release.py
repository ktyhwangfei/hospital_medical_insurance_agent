"""检索默认 collection 解析测试：激活发布接管检索（评审 B2 / P0-1）。

缺陷：RulesSearchService 硬编码 policy_rules_v2——治理流水线（审核/发布/血缘）
不影响线上答案，激活版形同虚设。修复：默认从 policy_active_release 解析，
无激活记录时回退 policy_rules_v2（向后兼容）。
"""
from __future__ import annotations

import pytest


class FakeActiveStore:
    """policy_active_release 读取桩。"""

    def __init__(self, release: dict | None):
        self._release = release

    def get_active_release(self):
        return self._release


def test_default_collections_follow_active_release(monkeypatch):
    from src.knowledge_extension.rule_explanation import rules_search_service as rss

    store = FakeActiveStore({
        "release_id": "REL_X",
        "facts_collection": "policy_facts_REL_X",
        "rules_collection": "policy_rules_REL_X",
    })
    captured: dict[str, str] = {}

    class FakeMilvusClient:
        def __init__(self, uri=None, timeout=None, **kw):
            pass

    monkeypatch.setattr(rss, "MilvusClient", FakeMilvusClient)
    monkeypatch.setattr(
        rss, "_resolve_active_release",
        lambda: {"rules_collection": "policy_rules_REL_X", "facts_collection": "policy_facts_REL_X"},
    )
    svc = rss.RulesSearchService()
    assert svc._rules_col == "policy_rules_REL_X"
    assert svc._facts_col == "policy_facts_REL_X"


def test_fallback_to_v2_when_no_active_release(monkeypatch):
    from src.knowledge_extension.rule_explanation import rules_search_service as rss

    class FakeMilvusClient:
        def __init__(self, uri=None, timeout=None, **kw):
            pass

    monkeypatch.setattr(rss, "MilvusClient", FakeMilvusClient)
    monkeypatch.setattr(rss, "_resolve_active_release", lambda: None)
    svc = rss.RulesSearchService()
    assert svc._rules_col == "policy_rules_v2"
    assert svc._facts_col == "policy_facts"


def test_explicit_col_names_win(monkeypatch):
    from src.knowledge_extension.rule_explanation import rules_search_service as rss

    class FakeMilvusClient:
        def __init__(self, uri=None, timeout=None, **kw):
            pass

    monkeypatch.setattr(rss, "MilvusClient", FakeMilvusClient)
    monkeypatch.setattr(rss, "_resolve_active_release", lambda: {"rules_collection": "R", "facts_collection": "F"})
    svc = rss.RulesSearchService(rules_col_name="my_rules", facts_col_name="my_facts")
    assert svc._rules_col == "my_rules"
    assert svc._facts_col == "my_facts"
