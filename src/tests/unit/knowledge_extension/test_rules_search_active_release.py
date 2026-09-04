"""检索默认 collection 解析测试：激活发布接管检索（评审 B2 / P0-1，Issue #33 统一 resolver）。

RulesSearchService 的默认 collection 经统一 release resolver 解析：
跟随 policy_active_release（含存在且非空校验），无激活或不可用时回退
policy_rules_v2 / policy_facts（向后兼容）。
"""
from __future__ import annotations


class _FakeMilvusClient:
    def __init__(self, uri=None, timeout=None, **kw):
        pass


def _patch_client(monkeypatch, rss) -> None:
    monkeypatch.setattr(rss, "MilvusClient", _FakeMilvusClient)


def test_default_collections_follow_active_release(monkeypatch):
    from src.knowledge_extension.rule_explanation import rules_search_service as rss

    _patch_client(monkeypatch, rss)
    monkeypatch.setattr(
        rss, "resolve_rules_collection", lambda _host, _port: "policy_rules_REL_X"
    )
    monkeypatch.setattr(
        rss, "resolve_facts_collection", lambda _host, _port: "policy_facts_REL_X"
    )
    svc = rss.RulesSearchService()
    assert svc._rules_col == "policy_rules_REL_X"
    assert svc._facts_col == "policy_facts_REL_X"


def test_fallback_to_v2_when_no_active_release(monkeypatch):
    from src.knowledge_extension.rule_explanation import rules_search_service as rss

    _patch_client(monkeypatch, rss)
    monkeypatch.setattr(
        rss, "resolve_rules_collection", lambda _host, _port: "policy_rules_v2"
    )
    monkeypatch.setattr(
        rss, "resolve_facts_collection", lambda _host, _port: "policy_facts"
    )
    svc = rss.RulesSearchService()
    assert svc._rules_col == "policy_rules_v2"
    assert svc._facts_col == "policy_facts"


def test_explicit_col_names_win(monkeypatch):
    from src.knowledge_extension.rule_explanation import rules_search_service as rss

    _patch_client(monkeypatch, rss)

    def _explode(*_args, **_kwargs):
        raise AssertionError("显式 collection 名时不应触发 resolver")

    monkeypatch.setattr(rss, "resolve_rules_collection", _explode)
    monkeypatch.setattr(rss, "resolve_facts_collection", _explode)
    svc = rss.RulesSearchService(rules_col_name="my_rules", facts_col_name="my_facts")
    assert svc._rules_col == "my_rules"
    assert svc._facts_col == "my_facts"
