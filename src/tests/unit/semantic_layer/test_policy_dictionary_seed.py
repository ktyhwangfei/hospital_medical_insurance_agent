"""值域 seed 覆盖回归测试。

缺陷：ensure_policy_dictionaries 每次进程启动用 _POLICY_DICTIONARY_VALUES
硬编码值 UPSERT 覆盖 5 个政策域（hosp_lv/psn_type/...），任何值域治理新增
（如 hosp_lv 增补「社区」）重启即丢。
"""
from __future__ import annotations

from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import (
    _POLICY_DICTIONARY_VALUES,
    ensure_policy_dictionaries,
)
from src.semantic_layer.models import ValueDomain


def test_ensure_policy_dictionaries_preserves_extended_values():
    store = InMemoryRegistryStore()
    registry = SemanticRegistry(store)
    # 首次灌入
    ensure_policy_dictionaries(store)
    # 值域治理新增（语义发现/人工裁决路径）
    dom = store.get_value_domain("hosp_lv")
    extended = ValueDomain(domain_code="hosp_lv", name=dom.name,
                           standard_values=dom.standard_values + ["社区"])
    store.save_value_domain(extended)
    # 进程重启再次 ensure：新增值不得丢失
    ensure_policy_dictionaries(store)
    after = store.get_value_domain("hosp_lv")
    assert "社区" in after.standard_values


def test_ensure_policy_dictionaries_creates_missing_domain():
    store = InMemoryRegistryStore()
    ensure_policy_dictionaries(store)
    dom = store.get_value_domain("hosp_lv")
    seed_values = _POLICY_DICTIONARY_VALUES["hosp_lv"][1]
    assert dom is not None
    assert set(seed_values) <= set(dom.standard_values)
