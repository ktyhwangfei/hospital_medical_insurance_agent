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


def test_zcgz_seed_marks_core_dimensions_indexed(registry):
    """zcgz 核心检索维度应标注 indexed=True + extraction_hint；详情字段 indexed=False。

    [依据: docs/steering/政策知识管线设计文档.md §3.1 / §3.3（核心维度进固定 schema）]
    """
    seed_semantic_layer(registry._store)

    # 核心检索维度：indexed=True，且有 extraction_hint
    for code in ("zcgz.rule_type", "zcgz.insu_type", "zcgz.med_type",
                 "zcgz.hosp_lv", "zcgz.psn_type", "zcgz.setl_type"):
        m = registry.get_metric(code)
        assert m is not None, f"种子缺失 {code}"
        assert m.indexed is True, f"{code} 应为核心检索维度 (indexed=True)"
        assert m.extraction_hint, f"{code} 缺少 extraction_hint"

    # 详情字段：indexed=False（走 Milvus dynamic field）
    payment = registry.get_metric("zcgz.payment_ratio")
    assert payment is not None
    assert payment.indexed is False

    # 仍为 draft（发布流程在 P4 质量门禁）
    assert registry.get_metric("zcgz.insu_type").status == "draft"
