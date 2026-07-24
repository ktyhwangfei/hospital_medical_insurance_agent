"""P7.2a source_field 三段式解析 + resolve_metric 输出 datasource_id。

三段式 ds.table.column 让指标声明它属于哪个数据源（多源路由地基）；
两段式 table.column 向后兼容（datasource_id=None，走默认源）。

[依据: docs/steering/政策知识管线设计.md §7.6；开发计划 P7.2]
"""
from src.runtime.discovery.semantic_source import SemanticDataSource, parse_source_field
from src.semantic_layer.models import BusinessDomain, BusinessObject, Metric
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


# ── parse_source_field 纯函数 ──────────────────────────────

def test_parse_three_segments():
    assert parse_source_field("ds1.yb_settlement.set_no") == ("ds1", "yb_settlement", "set_no")


def test_parse_three_segments_with_schema():
    """四段 ds.dbo.table.column：第一段=ds，末段=column，中间归 table。"""
    assert parse_source_field("ds1.dbo.yb_settlement.set_no") == ("ds1", "dbo.yb_settlement", "set_no")


def test_parse_two_segments_backward_compatible():
    """两段式：无 datasource 前缀，datasource_id=None（向后兼容）。"""
    assert parse_source_field("yb_settlement.set_no") == (None, "yb_settlement", "set_no")


def test_parse_single_segment():
    """单段裸字段：datasource_id=None，table=column=字段名。"""
    assert parse_source_field("set_no") == (None, "set_no", "set_no")


# ── resolve_metric 输出 datasource_id ──────────────────────

def _make_source_with(metrics: list[Metric]):
    """构造 SemanticDataSource（跳过 __init__ 副作用），注入内存 registry。"""
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_domain(BusinessDomain(domain_code="d", name="d"))
    store.save_object(BusinessObject(object_code="o", domain_code="d", name="o"))
    for m in metrics:
        store.save_metric(m)
    src = SemanticDataSource.__new__(SemanticDataSource)
    src._registry = reg
    return src


def test_resolve_metric_three_part_has_datasource_id():
    src = _make_source_with([Metric(
        metric_code="o.m1", object_code="o", name="结算号",
        source_field="ds1.yb_settlement.set_no",
    )])
    r = src.resolve_metric("o.m1")
    assert r["unmapped"] is False
    assert r["datasource_id"] == "ds1"
    assert r["table"] == "yb_settlement"
    assert r["column"] == "set_no"


def test_resolve_metric_two_part_datasource_id_none():
    """两段式指标：datasource_id=None，保持现有行为（向后兼容）。"""
    src = _make_source_with([Metric(
        metric_code="o.m2", object_code="o", name="金额",
        source_field="zyfdxx.bdtczfje",
    )])
    r = src.resolve_metric("o.m2")
    assert r["datasource_id"] is None
    assert r["table"] == "zyfdxx"
    assert r["column"] == "bdtczfje"


def test_resolve_metric_no_source_field_unmapped():
    src = _make_source_with([Metric(
        metric_code="o.m3", object_code="o", name="无源",
    )])
    r = src.resolve_metric("o.m3")
    assert r["unmapped"] is True

def test_build_query_plan_groups_by_datasource():
    """不同 datasource_id 的指标应分成不同组；同 ds 同表合并。"""
    src = _make_source_with([
        Metric(metric_code="o.m1", object_code="o", name="a", source_field="ds1.t1.c1"),
        Metric(metric_code="o.m2", object_code="o", name="b", source_field="ds1.t1.c2"),
        Metric(metric_code="o.m3", object_code="o", name="c", source_field="ds2.t2.c3"),
    ])
    plan = src.build_query_plan(["o.m1", "o.m2", "o.m3"])
    assert len(plan["tables"]) == 2
    ds_ids = sorted(t["datasource_id"] for t in plan["tables"])
    assert ds_ids == ["ds1", "ds2"]
    # ds1.t1 合并了 c1, c2 两列
    ds1_tbl = next(t for t in plan["tables"] if t["datasource_id"] == "ds1")
    assert ds1_tbl["table"] == "t1"
    assert sorted(ds1_tbl["columns"]) == ["c1", "c2"]


def test_build_query_plan_single_source_datasource_id_none():
    """两段式指标（无 ds 前缀）：tables 项 datasource_id=None（向后兼容）。"""
    src = _make_source_with([
        Metric(metric_code="o.m1", object_code="o", name="a", source_field="t1.c1"),
    ])
    plan = src.build_query_plan(["o.m1"])
    assert len(plan["tables"]) == 1
    assert plan["tables"][0]["datasource_id"] is None
    assert plan["tables"][0]["table"] == "t1"


# ── 多源连接路由（P7.2b 执行层）──────────────────────────

class _FakeMeta:
    """PolicyMetaStore 替身：只实现 get_datasource。"""
    def __init__(self, ds_map):
        self.ds_map = ds_map
    def get_datasource(self, ds_id):
        return self.ds_map.get(ds_id)


def _make_source_with_meta(meta):
    src = SemanticDataSource.__new__(SemanticDataSource)
    src._meta_store = meta
    return src


def test_resolve_connection_returns_ds_config():
    meta = _FakeMeta({"ds1": {"id": "ds1", "enabled": True,
                              "connection_config": {"host": "h1", "database": "d1"}}})
    src = _make_source_with_meta(meta)
    cfg = src._resolve_datasource_connection("ds1")
    assert cfg == {"host": "h1", "database": "d1"}


def test_resolve_connection_disabled_returns_none():
    meta = _FakeMeta({"ds1": {"enabled": False, "connection_config": {"host": "h1"}}})
    src = _make_source_with_meta(meta)
    assert src._resolve_datasource_connection("ds1") is None


def test_resolve_connection_unknown_returns_none():
    src = _make_source_with_meta(_FakeMeta({}))
    assert src._resolve_datasource_connection("no_such") is None


def test_resolve_connection_none_ds_falls_back():
    """ds_id=None 回退默认源配置（_resolve_source_config）。"""
    src = _make_source_with_meta(_FakeMeta({}))
    cfg = src._resolve_datasource_connection(None)
    assert isinstance(cfg, dict)


# ── _query_flat 多源执行（P7.2b）──────────────────────────

class _FakeConn:
    def cursor(self):
        return _FakeCursor()
    def close(self):
        pass


class _FakeCursor:
    def execute(self, sql, *args):
        pass
    def fetchone(self):
        return None  # 不返回值，仅验证连接选择


def test_query_flat_multi_source_uses_per_ds_connection():
    """多源：两个不同 ds 的指标 → 连接两个不同数据源。"""
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_domain(BusinessDomain(domain_code="d", name="d"))
    store.save_object(BusinessObject(object_code="o", domain_code="d", name="o"))
    store.save_metric(Metric(metric_code="o.m1", object_code="o", name="a", source_field="ds1.t1.c1"))
    store.save_metric(Metric(metric_code="o.m2", object_code="o", name="b", source_field="ds2.t2.c2"))
    src = _make_source_with_meta(_FakeMeta({
        "ds1": {"enabled": True, "connection_config": {"host": "h1", "database": "d1", "schema": "dbo"}},
        "ds2": {"enabled": True, "connection_config": {"host": "h2", "database": "d2", "schema": "dbo"}},
    }))
    src._registry = reg
    connected: list[str] = []
    src._connect = lambda cfg: (connected.append(cfg["host"]), _FakeConn())[1]
    src.query(["o.m1", "o.m2"], context={"djh": 1})
    assert set(connected) == {"h1", "h2"}


def test_query_flat_skips_group_with_no_connection():
    """某 ds 未注册/禁用 → 跳过该组，不报错。"""
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_domain(BusinessDomain(domain_code="d", name="d"))
    store.save_object(BusinessObject(object_code="o", domain_code="d", name="o"))
    store.save_metric(Metric(metric_code="o.m1", object_code="o", name="a", source_field="ds_ok.t1.c1"))
    store.save_metric(Metric(metric_code="o.m2", object_code="o", name="b", source_field="ds_missing.t2.c2"))
    src = _make_source_with_meta(_FakeMeta({
        "ds_ok": {"enabled": True, "connection_config": {"host": "h1", "database": "d1"}},
    }))
    src._registry = reg
    connected: list[str] = []
    src._connect = lambda cfg: (connected.append(cfg["host"]), _FakeConn())[1]
    src.query(["o.m1", "o.m2"], context={"djh": 1})
    assert connected == ["h1"]  # 只连了存在的源
