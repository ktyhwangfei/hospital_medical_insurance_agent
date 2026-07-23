"""Tests for seed data — 真实语义层（3 域 / 7 对象 / 22 指标）。

对齐生产 PostgreSQL 数据，编码为 zydyxx.* 物理编码（skill 依赖的唯一真源）。
"""
import pytest
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


@pytest.fixture
def registry():
    store = InMemoryRegistryStore()
    return SemanticRegistry(store)


class TestSeedSemanticLayer:
    def test_seed_creates_domains(self, registry):
        seed_semantic_layer(registry._store)
        assert registry._store.get_domain("ybdy").name == "医保待遇"
        assert registry._store.get_domain("ybjs").name == "医保结算"
        assert registry._store.get_domain("ybml").name == "医保目录"

    def test_seed_creates_objects(self, registry):
        seed_semantic_layer(registry._store)
        for code in ["djxx", "nddyxx", "ypml", "zydyxx", "zyfdxx", "zyfymx", "zyjyxx"]:
            assert registry.get_object(code) is not None, f"对象 {code} 应存在"

    def test_seed_creates_metrics(self, registry):
        seed_semantic_layer(registry._store)
        m = registry.get_metric("zydyxx.bcqfje")
        assert m is not None and m.name == "起付线"
        assert registry.get_metric("zyfdxx.bdtczf") is not None   # 统筹自付
        assert registry.get_metric("zyjyxx.rylb") is not None     # 人员类别
        assert registry.get_metric("djxx.fund_type") is not None  # 险种类型
        hl = registry.get_metric("djxx.hospital_level")  # 常量指标
        assert hl is not None and hl.default_value == "三级医院"

    def test_seed_creates_value_domains(self, registry):
        seed_semantic_layer(registry._store)
        assert registry.has_value_domain("FUND_TYPE")
        assert registry.has_value_domain("YLLB")
        assert registry.has_value_domain("PERSON_TYPE")

    def test_seed_enum_metrics_have_value_domain(self, registry):
        seed_semantic_layer(registry._store)
        rylb = registry.get_metric("zyjyxx.rylb")
        assert rylb is not None
        assert rylb.value_domain == "PERSON_TYPE"
        fund_type = registry.get_metric("djxx.fund_type")
        assert fund_type.value_domain == "FUND_TYPE"

    def test_seed_core_metrics_marked_core(self, registry):
        seed_semantic_layer(registry._store)
        for metric in registry.get_metrics_by_object("zyfdxx"):
            if metric.metric_code in (
                "zyfdxx.bdtczfje", "zyfdxx.bdtczf", "zyfdxx.bdgryf",
            ):
                assert metric.importance == "core", f"{metric.metric_code} should be core"
