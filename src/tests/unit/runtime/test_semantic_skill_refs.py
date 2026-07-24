"""技能引用计数回归测试。

skill_manifest.yaml 的 needed_objects 与语义层编码统一后（zydyxx.* 物理编码），
_compute_skill_metric_refs 按 {object_code}.{metric} 直接匹配 metric_code（单策略）。
"""
import pytest

from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.runtime.api import semantic_routes as sr


@pytest.fixture
def fresh_registry(monkeypatch):
    """注入全新种子的内存注册表，并清除引用计数缓存，保证测试隔离。"""
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    reg = SemanticRegistry(store)
    monkeypatch.setattr(sr, "get_registry", lambda: reg)
    monkeypatch.setattr(sr, "_skill_refs_cache", None)
    # 规避 summary 内发现扫描读取 PostgreSQL（测试环境无 DB，5s 超时拖慢测试）
    monkeypatch.setattr(sr, "_get_discovery_store", lambda: type(
        "Stub", (), {"get_latest_result": lambda self: None})())
    return reg


def test_compute_refs_counts_referenced_metrics(fresh_registry):
    """needed_objects 声明的指标应被计为被引用。"""
    refs = sr._compute_skill_metric_refs()
    assert refs.get("zydyxx.bcqfje", 0) >= 1
    assert refs.get("zyfdxx.bdtczf", 0) >= 1


def test_summary_skill_references_nonzero(fresh_registry):
    """引用计数应大于 0，且 domain_progress 至少一个域有引用。"""
    summary = sr.get_semantic_summary()
    assert summary.skill_references > 0
    assert any(d.skill_refs > 0 for d in summary.domain_progress)


def test_get_metric_usage_count_nonzero(fresh_registry):
    """指标详情的 usage_count 应反映静态技能引用数。"""
    detail = sr.get_metric("zydyxx.bcqfje")
    assert detail.usage_count >= 1


def test_list_metrics_carries_usage_count(fresh_registry):
    """list_metrics 须返回 usage_count，供对象页发布校验判断引用。"""
    items = sr.list_metrics("zydyxx")
    assert items, "list_metrics 应返回种子指标"
    assert any(it.usage_count >= 1 for it in items)


def test_list_metrics_returns_all_when_no_object_code(fresh_registry):
    """不传 object_code 应返回全部指标（回归：曾误返回空列表）。

    [来源: P7 验证发现 GET /semantic/metrics 不传 object_code 时返回 []，
    导致前端 metric 列表页显示空。根因 semantic_routes.list_metrics 的
    `if object_code else []` 分支错误。]
    """
    items = sr.list_metrics(object_code=None)
    assert len(items) > 1, "不传 object_code 应返回全部指标，而非空列表"
    # 对比：传具体 object_code 只返回该对象的指标
    zydyxx_only = sr.list_metrics(object_code="zydyxx")
    assert all(it.object_code == "zydyxx" for it in zydyxx_only)
    assert len(items) > len(zydyxx_only), "全部指标应多于单对象指标"


def test_metric_code_strategy_matches_manifest(monkeypatch):
    """needed_objects 的 {object_code}.{metric} 直接匹配语义层 metric_code。

    即使不依赖种子数据（手动构造 store），只要 manifest 声明的编码与 store 一致即命中。
    """
    from src.semantic_layer.models import Metric
    store = InMemoryRegistryStore()
    store.save_metric(Metric(
        metric_code="zydyxx.bcqfje", object_code="zydyxx", name="起付线",
        metric_type="Atomic", source_field="yb_dyxxzy.bcqfje",
    ))
    store.save_metric(Metric(
        metric_code="zyfdxx.bdtczf", object_code="zyfdxx", name="统筹自付",
        metric_type="Atomic", source_field="yb_zyfdxx.bdtczf",
    ))
    monkeypatch.setattr(sr, "get_registry", lambda: SemanticRegistry(store))
    monkeypatch.setattr(sr, "_skill_refs_cache", None)

    refs = sr._compute_skill_metric_refs()
    assert refs.get("zydyxx.bcqfje", 0) >= 1
    assert refs.get("zyfdxx.bdtczf", 0) >= 1


def test_compute_skill_locks_parses_manifest():
    """阶段4：_compute_skill_locks 扫描 manifest 的 locked_versions。"""
    locks = sr._compute_skill_locks()
    assert "zydyxx" in locks
    assert any(l["skill_id"] == "settlement_explain_skill" and l["locked_version"] is None
               for l in locks["zydyxx"])
