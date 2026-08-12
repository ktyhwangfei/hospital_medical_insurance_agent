"""指标质量分计算回归测试。

背景：发现中心「快速创建指标」走单条 POST /metrics 创建带 source_field 的指标，
但 create_metric 早期未调用 _calc_quality_from_discovery，导致 quality_score 滞留为 0。
此外，先建指标后扫描的场景缺少 on-demand 刷新入口。本测试锁定两条不变式：

1. 单条创建带 source_field 的指标，应即时写入 quality_score（与批量/更新一致）。
2. POST /metrics/refresh-quality-scores 应按最新发现扫描结果回填已映射指标的质量分。
"""
import pytest

from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.runtime.api import semantic_routes as sr
from src.runtime.api.semantic_routes import CreateMetricRequest


@pytest.fixture
def fresh_registry(monkeypatch):
    """注入全新种子的内存注册表，保证测试隔离。"""
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    reg = SemanticRegistry(store)
    monkeypatch.setattr(sr, "get_registry", lambda: reg)
    return reg


def test_create_metric_with_source_field_computes_quality(fresh_registry, monkeypatch):
    """单条创建带 source_field 的指标，应即时写入 quality_score（与批量/更新一致）。"""
    monkeypatch.setattr(sr, "_calc_quality_from_discovery", lambda sf, so=None: 42.0)
    sr.create_metric(CreateMetricRequest(
        object_code="zyfymx", name="测试质量分指标",
        source_field="yb_zyfymx.foo", source_table="yb_zyfymx",
    ), object())
    detail = sr.get_metric("zyfymx.测试质量分指标")
    assert detail.quality_score == 42.0


def test_create_metric_without_source_field_keeps_zero(fresh_registry, monkeypatch):
    """无 source_field 的指标，quality_score 保持默认 0，且不应触发质量分计算。"""
    calls = {"n": 0}

    def _fake(sf, so=None):
        calls["n"] += 1
        return 99.0

    monkeypatch.setattr(sr, "_calc_quality_from_discovery", _fake)
    sr.create_metric(CreateMetricRequest(object_code="zyfymx", name="无映射指标"), object())
    detail = sr.get_metric("zyfymx.无映射指标")
    assert detail.quality_score == 0.0
    assert calls["n"] == 0


def test_refresh_quality_scores_pulls_latest_discovery(fresh_registry, monkeypatch):
    """刷新接口应按最新发现扫描结果回填已映射指标的 quality_score。"""
    # 模拟「指标先建、扫描后到」：创建时质量分计算返回 0（发现中心暂无数据）
    monkeypatch.setattr(sr, "_calc_quality_from_discovery", lambda sf, so=None: 0.0)
    sr.create_metric(CreateMetricRequest(
        object_code="zyfymx", name="待刷新指标",
        source_field="yb_zyfymx.bar", source_table="yb_zyfymx",
    ), object())
    assert sr.get_metric("zyfymx.待刷新指标").quality_score == 0.0

    # 发现扫描完成：注入包含该字段的最新结果
    field = {
        "field_name": "bar", "table_name": "yb_zyfymx",
        "non_null_rate": 100, "description": "测试字段", "sample_value": "x",
    }
    stub_store = type("Stub", (), {"get_latest_result": lambda self: {"fields": [field]}})()
    monkeypatch.setattr(sr, "_get_discovery_store", lambda: stub_store)

    result = sr.refresh_quality_scores(object())
    assert result["status"] == "ok"
    assert result["updated"] >= 1
    assert sr.get_metric("zyfymx.待刷新指标").quality_score > 0.0


def test_refresh_quality_scores_without_scan_returns_409(fresh_registry, monkeypatch):
    """无任何发现扫描结果时，刷新接口应返回 409。"""
    stub_store = type("Stub", (), {"get_latest_result": lambda self: None})()
    monkeypatch.setattr(sr, "_get_discovery_store", lambda: stub_store)
    with pytest.raises(sr.HTTPException) as exc:
        sr.refresh_quality_scores(object())
    assert exc.value.status_code == 409
