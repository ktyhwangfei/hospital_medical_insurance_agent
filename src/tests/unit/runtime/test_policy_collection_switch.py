"""P0.3 政策问答读入口 collection 切换开关（灰度预留）。

政策问答的两个生产读入口（PolicyRulesSearchEngine / StructuredPolicyRuleRetriever）
必须能经环境变量 POLICY_RULES_COLLECTION 切换 collection，默认保持旧名
`policy_rules`——保证灰度切换前（P10.1）生产行为零变化。

依据：docs/steering/政策知识管线开发计划.md P0.3 / P10.1。
"""
from __future__ import annotations


def test_default_resolves_to_legacy_name(monkeypatch):
    """未设环境变量时，解析为旧名 policy_rules（零行为变化）。"""
    monkeypatch.delenv("POLICY_RULES_COLLECTION", raising=False)
    from src.runtime.policy_qa.policy_rules_search import (
        resolve_policy_rules_collection,
    )

    assert resolve_policy_rules_collection() == "policy_rules"


def test_env_var_switches_to_new_collection(monkeypatch):
    """设 POLICY_RULES_COLLECTION=policy_rules_v2 后解析为新 collection（灰度入口）。"""
    monkeypatch.setenv("POLICY_RULES_COLLECTION", "policy_rules_v2")
    from src.runtime.policy_qa.policy_rules_search import (
        resolve_policy_rules_collection,
    )

    assert resolve_policy_rules_collection() == "policy_rules_v2"


def test_explicit_arg_overrides_env(monkeypatch):
    """显式传入的 collection 名优先级最高（便于测试/临时指定）。"""
    monkeypatch.setenv("POLICY_RULES_COLLECTION", "policy_rules_v2")
    from src.runtime.policy_qa.policy_rules_search import (
        resolve_policy_rules_collection,
    )

    assert resolve_policy_rules_collection("policy_rules") == "policy_rules"


def test_default_constant_documented():
    """旧名常量公开导出，供写入侧 / 文档引用。"""
    from src.runtime.policy_qa.policy_rules_search import (
        DEFAULT_POLICY_RULES_COLLECTION,
    )

    assert DEFAULT_POLICY_RULES_COLLECTION == "policy_rules"
