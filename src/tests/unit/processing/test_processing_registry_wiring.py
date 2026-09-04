"""批次二静态 T1：加工注册表接线（口径句 v4 签核门禁 + 语义层可引用）。

派工单: docs/processing/batch2-registry.md
断言依据: docs/processing/registry.yaml + src/semantic_layer/seed.py
            ensure_outpatient_processed_view_metrics

⑤ 缺签核口径句→拒绝：注册表/语义指标缺少 口径句v4 即拒绝登记；⑥ med_type
空档边界为活库断言（见 test_outpatient_processed_view_t2a.py），此处仅锁
注册表 4 字段定义完整性。
"""
from pathlib import Path

import pytest
import yaml

from src.semantic_layer.data_query import MetricDataQueryService
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import (
    VIEW_PROCESSED_口径句_V4,
    ensure_outpatient_processed_view_metrics,
    seed_semantic_layer,
)

REGISTRY_YAML = Path(__file__).resolve().parents[4] / "docs/processing/registry.yaml"
MZJYXX = "mzjyxx"
VIEW_CODE = "v_op_outpatient_processed"

# ── 注册表文件（registry.yaml）签核门禁 ─────────────────────────

def _validate_registry(data: dict) -> list[str]:
    """缺签核口径句→拒绝：返回校验问题列表（空=通过）。"""
    issues: list[str] = []
    fields = (data.get("registry") or {}).get("fields") or {}
    if not fields:
        issues.append("registry.fields 缺失")
        return issues
    for code, entry in fields.items():
        for key in ("名称", "算子", "来源字段", "口径句v4", "去重键", "物化策略", "签核状态"):
            if not entry.get(key):
                issues.append(f"{code} 缺 {key}")
        if entry.get("口径句v4") and entry.get("签核状态") != "已过":
            issues.append(f"{code} 签核状态非已过（缺签核口径句→拒绝）")
    return issues


def test_registry_yaml_四字段_口径句v4_签核已过():
    """registry.yaml 必须含 4 字段，每字段口径句 v4 承接批一 SQL 且签核已过。"""
    data = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))
    issues = _validate_registry(data)
    assert issues == [], f"注册表校验未过: {issues}"
    fields = data["registry"]["fields"]
    assert set(fields) == {
        "op_valid_settle_count", "op_total_fee", "op_fund_pay", "op_self_pay",
    }
    for entry in fields.values():
        assert entry["签核状态"] == "已过"
        assert "T_State IN (2,3)" in entry["口径句v4"]
        assert "(T_CureType IN (11,17,18,19) OR T_CureType IS NULL)" in entry["口径句v4"]
    assert fields["op_valid_settle_count"]["算子"] == "COUNT(DISTINCT {T_TradeNo})"
    assert fields["op_total_fee"]["算子"] == "SUM({T_FeeAll})"
    assert fields["op_fund_pay"]["算子"] == "SUM({T_FundPay})"
    assert fields["op_self_pay"]["算子"] == "SUM({T_SelfPayAll})"
    assert fields["op_valid_settle_count"]["去重键"] == "T_TradeNo（跨险种同 trade_no 只计 1 笔）"


def test_缺签核口径句_拒绝():
    """缺 口径句v4 或签核非已过的条目不通过校验（⑤）。"""
    good = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))
    lacking = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))
    del lacking["registry"]["fields"]["op_total_fee"]["口径句v4"]
    assert _validate_registry(lacking) != []

    unsigned = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))
    unsigned["registry"]["fields"]["op_total_fee"]["签核状态"] = "draft"
    assert _validate_registry(unsigned) != []
    assert _validate_registry(good) == []


# ── 语义层接线：view 挂指标注册（受控问数可引用）────────────────

@pytest.fixture
def seeded_registry():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    return SemanticRegistry(store)


def test_语义层登记_四view指标_口径句v4发布(seeded_registry):
    """ensure_outpatient_processed_view_metrics 幂等登记 4 指标并携带口径句 v4。"""
    reg = seeded_registry
    codes = [
        f"{MZJYXX}.op_valid_settle_count", f"{MZJYXX}.op_total_fee",
        f"{MZJYXX}.op_fund_pay", f"{MZJYXX}.op_self_pay",
    ]
    metrics = [reg.get_metric(c) for c in codes]
    assert all(m is not None for m in metrics)
    assert all(m.status == "published" for m in metrics)
    assert all(VIEW_PROCESSED_口径句_V4 in m.definition for m in metrics)
    assert [m.aggregation for m in metrics] == ["count", "sum", "sum", "sum"]
    assert all(m.source_object == VIEW_CODE for m in metrics)
    assert [m.source_field for m in metrics] == [
        "bjybdb.v_op_outpatient_processed.op_valid_settle_count",
        "bjybdb.v_op_outpatient_processed.op_total_fee",
        "bjybdb.v_op_outpatient_processed.op_fund_pay",
        "bjybdb.v_op_outpatient_processed.op_self_pay",
    ]


def test_幂等_重复ensure不覆盖():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    ensure_outpatient_processed_view_metrics(store)
    m = store.get_metric(f"{MZJYXX}.op_total_fee")
    assert m is not None and VIEW_PROCESSED_口径句_V4 in m.definition


def test_缺口径句的既有指标_拒绝覆盖(monkeypatch):
    """⑤：同名指标已存在但 definition 无口径句 v4 → 拒绝注册。"""
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    from src.semantic_layer.models import Metric
    store.save_metric(Metric(
        metric_code=f"{MZJYXX}.op_total_fee", object_code=MZJYXX,
        name="门诊总费用", definition="未经签核的定义", semantic_type="Amount",
    ))
    with pytest.raises(ValueError, match="缺签核口径句"):
        ensure_outpatient_processed_view_metrics(store)


def test_受控问数可解析四view指标(seeded_registry):
    """MetricDataQueryService 能解析 4 指标（mapped、指向视图表）。"""
    reg = seeded_registry
    svc = MetricDataQueryService()
    svc._registry = reg  # 内存单例注入，避免 PG 连接
    codes = [c for c in [
        f"{MZJYXX}.op_valid_settle_count", f"{MZJYXX}.op_total_fee",
        f"{MZJYXX}.op_fund_pay", f"{MZJYXX}.op_self_pay",
    ]]
    resolved = svc.resolve_metrics(codes)
    assert len(resolved) == 4
    assert all(not info.get("unmapped") for info in resolved.values())
    assert all(
        info["source_field"].startswith("bjybdb.v_op_outpatient_processed.")
        for info in resolved.values()
    )