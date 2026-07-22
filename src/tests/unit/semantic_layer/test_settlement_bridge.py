"""A-重：settlement_bridge 语义层数据桥接测试。"""
from dataclasses import dataclass

import pytest

import src.semantic_layer.registry as reg_mod
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.semantic_layer.settlement_bridge import (
    settlement_context_to_adapter_data, build_settlement_facts,
)


@dataclass
class FakeSettlementContext:
    """模拟 SettlementContext（settlement_data_provider 的输出，语义名字段）。"""
    settlement_id: str = "S001"
    deductible: float = 1300.0
    medical_insurance_inner_amount: float = 35000.0
    basic_pooling_payment: float = 28560.0
    basic_pooling_self_pay: float = 4520.0
    large_amount_payment: float = 5000.0
    large_amount_self_pay: float = 800.0
    personal_total_pay: float = 5820.0
    person_type: str = "退休人员"
    insurance_type: str = "城镇职工"
    service_type: str = "普通住院"


@pytest.fixture
def registry(monkeypatch):
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    reg = SemanticRegistry(store)
    monkeypatch.setattr(reg_mod, "get_semantic_registry", lambda: reg)
    return reg


class TestSettlementBridge:
    def test_context_to_adapter_data(self):
        """SettlementContext（语义名）→ 嵌套 adapter data（表.列）。"""
        data = settlement_context_to_adapter_data(FakeSettlementContext())
        assert data["yb_dyxxzy"]["bcqfje"] == 1300.0
        assert data["yb_zyfdxx"]["bdtczfje"] == 28560.0
        assert data["yb_zyfdxx"]["bdtczf"] == 4520.0
        assert data["yb_zyjyxx"]["PER_TYPE"] == "退休人员"
        assert data["yb_brdjxx"]["FUND_TYPE"] == "城镇职工"

    def test_build_facts_with_published_objects(self, registry):
        """已发布对象 → facts 含数据（经版本锁定）。"""
        for obj in ["zydyxx", "zyfdxx", "zyjyxx", "djxx"]:
            registry.publish_object(obj)
        facts = build_settlement_facts(FakeSettlementContext())
        assert facts["zydyxx"]["bcqfje"] == 1300.0
        assert facts["zyfdxx"]["bdtczfje"] == 28560.0
        assert facts["zyfdxx"]["bdtczf"] == 4520.0
        assert facts["zyfdxx"]["bdgryf"] == 5820.0

    def test_build_facts_unpublished_returns_empty(self, registry):
        """未发布对象 → facts 为空（锁定生效，skill 拿不到数据）。"""
        facts = build_settlement_facts(FakeSettlementContext())
        assert facts.get("zydyxx", {}) == {}
        assert facts.get("zyfdxx", {}) == {}

    def test_build_facts_partial_publish(self, registry):
        """部分发布 → 只有已发布对象有 facts。"""
        registry.publish_object("zydyxx")
        facts = build_settlement_facts(FakeSettlementContext())
        assert facts["zydyxx"]["bcqfje"] == 1300.0
        assert facts.get("zyfdxx", {}) == {}  # 未发布
