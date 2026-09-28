"""门诊费用分解快照读取适配器单元测试（Issue #78，fake conn 模式，无数据库依赖）。

覆盖：交易定位唯一/歧义/未找到、明细完整读取（不分页）、目录批量全版本、
观测值 None≠0、退费标志组装、费用发生日期降级、meta 哈希与行数、映射覆盖扩展点。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.adapters.base.models import AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply import outpatient_decomposition_queries as q
from src.adapters.data_supply.record_query_mappings import (
    DEFAULT_RECORD_QUERY_MAPPING,
    RecordQueryMapping,
    mapping_fingerprint,
)
from src.domain.insurance.fee_decomposition import CatalogKind, RoundingMode

MODE = RoundingMode.HALF_UP

#: 默认映射下交易行的全部物理列（小写键 = _fetch_all 行键）
_TRADE_COLS = (
    "T_TradeNo", "T_TradeDate", "T_HospCode", "P_FundType", "T_CureType",
    "PN_PersonType", "P_Birthday", "TB_FeeIn",
    "T_FeeAll", "T_FeeIn", "T_FeeOut", "T_FundPay", "T_SelfPay2", "T_FirstPay",
    "T_BigPay", "T_BigSelfPay", "T_BCPay", "T_JCPay", "T_OfficalPay",
    "T_SelfPay1", "T_SelfPayAll", "T_PersonCountPay", "T_CashPay",
    "T_HasRefundmented", "T_PartialReturnFlag", "TR_OraginalTradeNo", "T_OraginalTradeNo",
)

_ITEM_COLS = (
    "ItemId", "ItemType", "ItemCode", "FeeType", "UnitPrice", "Count",
    "Fee", "FeeIn", "FeeOut", "SelfPay2", "fsrq",
)

_DRUG_COLS = (
    "ypbm", "sxrq", "jzrq", "sflb", "zfbl", "a_ypbs", "a_mzxj",
    "a_xbbl", "ypfl", "bzjg", "zzjssjg",
)

_SVC_COLS = ("xmbm", "sxrq", "jzrq", "sfxmdj", "zfbl", "djxe")


def _trade_row(**overrides) -> tuple:
    """默认映射物理列序的交易行；未给字段用中性默认值。"""
    base = dict(
        T_TradeNo="T001", T_TradeDate="2024-06-01", T_HospCode="H001",
        P_FundType="11", T_CureType="11", PN_PersonType="11", P_Birthday="1980-01-01",
        TB_FeeIn="0.00",
        T_FeeAll="3000.00", T_FeeIn="3000.00", T_FeeOut="0.00", T_FundPay="1080.00",
        T_SelfPay2="0.00", T_FirstPay="1800.00", T_BigPay="1080.00",
        T_BigSelfPay="120.00", T_BCPay="0.00", T_JCPay="0.00", T_OfficalPay="0.00",
        T_SelfPay1="1920.00", T_SelfPayAll="1920.00", T_PersonCountPay="0.00",
        T_CashPay="1920.00",
        T_HasRefundmented=0, T_PartialReturnFlag="", TR_OraginalTradeNo="",
        T_OraginalTradeNo="",
    )
    base.update(overrides)
    return tuple(base[c] for c in _TRADE_COLS)


def _item_row(**overrides) -> tuple:
    base = dict(
        ItemId="L1", ItemType="0", ItemCode="D001", FeeType="无自付",
        UnitPrice="100.00", Count="30", Fee="3000.00", FeeIn="3000.00",
        FeeOut="0.00", SelfPay2="0.00", fsrq="2024-05-20",
    )
    base.update(overrides)
    return tuple(base[c] for c in _ITEM_COLS)


def _drug_row(**overrides) -> tuple:
    base = dict(
        ypbm="D001", sxrq="2024-01-01", jzrq="2024-12-31", sflb="无自付",
        zfbl=None, a_ypbs="0", a_mzxj=None, a_xbbl=None, ypfl=None,
        bzjg=None, zzjssjg=None,
    )
    base.update(overrides)
    return tuple(base[c] for c in _DRUG_COLS)


class _RoutingCursor:
    """按 SQL 中表名分发的游标桩；routes: {表名片段: (cols, rows)}。"""

    def __init__(self, routes):
        self._routes = routes
        self._active = ((), [])
        self.executed: list[tuple[str, list]] = []

    def execute(self, sql, params):
        self.executed.append((sql, list(params)))
        for fragment, spec in self._routes.items():
            if fragment in sql:
                self._active = spec
                return
        self._active = ((), [])

    @property
    def description(self):
        return [(c,) for c in self._active[0]]

    def fetchall(self):
        return self._active[1]

    def close(self):
        pass


class _RoutingConn:
    def __init__(self, routes):
        self.cursor_instance = _RoutingCursor(routes)

    def cursor(self):
        return self.cursor_instance


def _conn_with_trade(trade_rows, **kwargs) -> _RoutingConn:
    routes = {
        "o_FeeItem": (_ITEM_COLS, kwargs.get("item_rows", [_item_row()])),
        "yb_ypzdml": (_DRUG_COLS, kwargs.get("drug_rows", [_drug_row()])),
        "yb_xzzlfwxm": (_SVC_COLS, kwargs.get("svc_rows", [])),
        "m_institution": (("HospCode", "H_LEVEL"), kwargs.get("inst_rows", [("H001", "14")])),
        "o_Trade": (_TRADE_COLS, trade_rows),
    }
    return _RoutingConn(routes)


# ── 交易定位 ──────────────────────────────────────────────────


def test_locate_trade_unique_match_parameterized() -> None:
    conn = _conn_with_trade([_trade_row()])
    result = q.locate_outpatient_trade(conn, "T001", "H001")
    assert result.status == AdapterCallStatus.SUCCESS
    assert result.data["match_status"] == "unique_match"
    assert result.data["trade_row"]["t_tradeno"] == "T001"
    sql, params = conn.cursor_instance.executed[0]
    assert params == ["T001", "H001"]  # 参数化防注入
    assert "T001" not in sql


def test_locate_trade_not_found() -> None:
    result = q.locate_outpatient_trade(_conn_with_trade([]), "T999", "H001")
    assert result.data["match_status"] == "not_found"
    assert result.data["trade_row"] is None
    assert result.data_quality == DataQualityStatus.MISSING


def test_locate_trade_ambiguous_never_takes_first() -> None:
    rows = [_trade_row(), _trade_row()]
    result = q.locate_outpatient_trade(_conn_with_trade(rows), "T001", "H001")
    assert result.data["match_status"] == "ambiguous"
    assert result.data["trade_row"] is None  # 歧义数据异常，不取首条
    assert result.data["row_count"] == 2


def test_locate_trade_query_error_returns_failed() -> None:
    class _BoomCursor:
        def execute(self, sql, params):
            raise RuntimeError("db down")

        def close(self):
            pass

    class _BoomConn:
        def cursor(self):
            return _BoomCursor()

    result = q.locate_outpatient_trade(_BoomConn(), "T001", "H001")
    assert result.status == AdapterCallStatus.FAILED
    assert result.error_type == "DATASOURCE_QUERY_FAILED"


# ── 明细完整读取 ──────────────────────────────────────────────


def test_load_fee_items_full_read_no_pagination() -> None:
    conn = _conn_with_trade([_trade_row()], item_rows=[_item_row(), _item_row(ItemId="L2")])
    result = q.load_outpatient_fee_items(conn, "T001")
    assert result.status == AdapterCallStatus.SUCCESS
    assert result.data["row_count"] == 2
    sql, params = conn.cursor_instance.executed[0]
    assert "TOP" not in sql.upper() and "LIMIT" not in sql.upper()  # 禁止分页截断
    assert params == ["T001"]


def test_load_fee_items_duplicate_line_keys_kept() -> None:
    """重复行键原样带出，不静默去重（内核判 DUPLICATE_LINE_KEY 数据异常）。"""
    dup = [_item_row(ItemId="L1", Fee="100.00"), _item_row(ItemId="L1", Fee="200.00")]
    result = q.load_outpatient_fee_items(_conn_with_trade([_trade_row()], item_rows=dup), "T001")
    assert result.data["row_count"] == 2
    fees = [r["fee"] for r in result.data["item_rows"]]
    assert fees == ["100.00", "200.00"]


# ── 目录批量全版本读取 ────────────────────────────────────────


def test_load_drug_catalog_all_versions_no_date_filter() -> None:
    rows = [
        _drug_row(jzrq="2023-12-31"),  # 已失效版本也读出
        _drug_row(sxrq="2024-01-01", jzrq=None),  # 空截止日期行保留
    ]
    conn = _conn_with_trade([_trade_row()], drug_rows=rows)
    result = q.load_drug_catalog(conn, ["D001", "D001", "D002"])
    assert result.status == AdapterCallStatus.SUCCESS
    assert result.data["row_count"] == 2
    sql, params = conn.cursor_instance.executed[0]
    assert "IN (?, ?)" in sql  # 编码去重后参数化
    assert params == ["D001", "D002"]
    # 有效期筛选留给内核：WHERE 不含生效/截止日期条件
    assert "sxrq" not in sql.split("WHERE", 1)[1]
    assert "jzrq" not in sql.split("WHERE", 1)[1]


def test_load_service_and_material_catalog_share_table() -> None:
    conn = _conn_with_trade(
        [_trade_row()], svc_rows=[("X001", "2024-01-01", None, "1", None, None)])
    svc = q.load_service_catalog(conn, ["X001"])
    mat = q.load_material_catalog(conn, ["X001"])
    assert svc.data["row_count"] == 1 and mat.data["row_count"] == 1
    # 材料候选与诊疗同表（是否完整包含待确认），两条 SQL 都指向 yb_xzzlfwxm
    sqls = [s for s, _ in conn.cursor_instance.executed]
    assert all("yb_xzzlfwxm" in s for s in sqls)


def test_load_catalog_empty_codes_short_circuits() -> None:
    conn = _conn_with_trade([_trade_row()])
    result = q.load_drug_catalog(conn, [])
    assert result.data["row_count"] == 0
    assert conn.cursor_instance.executed == []  # 空编码不发 SQL


# ── 机构等级 ──────────────────────────────────────────────────


def test_load_institution_level_hit_and_miss() -> None:
    hit = q.load_institution_level(_conn_with_trade([_trade_row()]), "H001")
    assert hit.data["h_level"] == "14"
    miss = q.load_institution_level(_conn_with_trade([_trade_row()], inst_rows=[]), "H404")
    assert miss.data["h_level"] is None
    assert "未命中" in miss.data["note"]
    dup = q.load_institution_level(
        _conn_with_trade([_trade_row()], inst_rows=[("H001", "14"), ("H001", "1")]), "H001")
    assert dup.data["h_level"] is None  # 歧义不取首条
    assert "歧义" in dup.data["note"]


# ── 纯组装 build_snapshot ──────────────────────────────────────


def _rows_as_dicts(cols, rows) -> list[dict]:
    return [dict(zip([c.lower() for c in cols], r)) for r in rows]


def _build(trade_row, **kwargs):
    return q.build_snapshot(
        trade_row=_rows_as_dicts(_TRADE_COLS, [trade_row])[0],
        item_rows=_rows_as_dicts(_ITEM_COLS, kwargs.get("items", [_item_row()])),
        drug_catalog_rows=_rows_as_dicts(_DRUG_COLS, kwargs.get("drugs", [_drug_row()])),
        service_catalog_rows=_rows_as_dicts(_SVC_COLS, kwargs.get("svcs", [])),
        material_catalog_rows=_rows_as_dicts(_SVC_COLS, kwargs.get("mats", [])),
        institution_h_level=kwargs.get("h_level", "14"),
        rounding_mode=MODE,
        **{k: v for k, v in kwargs.items() if k in (
            "mapping", "insurance_type", "medical_category", "prior_in_scope_fee_is_pre_trade",
            "prior_fund_payment", "prior_fund_payment_is_pre_trade", "in_scope_basis_aligned")},
    )


def test_build_snapshot_observed_none_is_not_zero() -> None:
    """观测值 None≠0：账面缺失列保持 None，不按零处理。"""
    snapshot, _ = _build(_trade_row(T_FeeOut=None, T_BCPay=None))
    assert snapshot.observed.fee_out is None
    assert snapshot.observed.bc_pay is None
    assert snapshot.observed.fee_all == Decimal("3000.00")  # 正常列仍为 Decimal


def test_build_snapshot_decimal_not_via_float() -> None:
    snapshot, _ = _build(_trade_row(), items=[_item_row(Fee="0.10", UnitPrice="0.10", Count="1")])
    assert snapshot.items[0].fee == Decimal("0.10")
    assert isinstance(snapshot.items[0].fee, Decimal)


def test_build_snapshot_reversal_flags_assembled() -> None:
    snap1, _ = _build(_trade_row(TR_OraginalTradeNo="T000"))
    assert snap1.trade.original_trade_no == "T000"
    snap2, _ = _build(_trade_row(T_HasRefundmented=1))
    assert snap2.trade.is_reversal is True
    snap3, _ = _build(_trade_row(T_PartialReturnFlag="1"))
    assert snap3.trade.is_reversal is True


def test_build_snapshot_person_unmapped_fields_stay_none() -> None:
    """资格字段无确认来源一律 None（禁止金额反推资格）；出生日期仅入内部值对象。"""
    snapshot, _ = _build(_trade_row())
    p = snapshot.person
    assert p.person_type_code == "11"
    assert p.birth_date == date(1980, 1, 1)
    assert p.retirement_category is None
    assert p.is_disabled_veteran is None
    assert p.public_medical_eligible is None
    assert p.retire_supplement_enroll_date is None


def test_build_snapshot_defaults_unknown_profile_and_unconfirmed_accumulation() -> None:
    """险种/医疗类别默认 unknown 不猜测；TB_FeeIn 交易前口径默认未确认。"""
    snapshot, _ = _build(_trade_row())
    assert snapshot.insurance_type == "unknown"
    assert snapshot.medical_category == "unknown"
    assert snapshot.accumulation.prior_in_scope_fee == Decimal("0.00")
    assert snapshot.accumulation.prior_in_scope_fee_is_pre_trade is False
    assert snapshot.has_other_fund_channels is None  # 基金渠道穷尽性未知


def test_build_snapshot_fee_date_fallback_noted() -> None:
    """真实库 o_FeeItem 无费用发生日期列：默认映射下一律降级用交易日期并留痕；
    映射到实际存在的列时按列取值、不降级。"""
    snapshot, notes = _build(_trade_row(), items=[_item_row(fsrq=None)])
    assert snapshot.items[0].fee_occurrence_date == date(2024, 6, 1)  # 降级用交易日期
    assert any("FEE_OCCURRENCE_DATE_FALLBACK" in n for n in notes)
    # 默认映射无发生日期列（映射值为空串）：即使夹具带了 fsrq 也不读取，同样降级
    snapshot_default, notes_default = _build(_trade_row())
    assert snapshot_default.items[0].fee_occurrence_date == date(2024, 6, 1)
    assert any("FEE_OCCURRENCE_DATE_FALLBACK" in n for n in notes_default)
    # 列值存在且映射到该列时不降级
    mapping = RecordQueryMapping(columns={"opf_fee_date": "fsrq"})
    snapshot2, notes2 = _build(_trade_row(), mapping=mapping)
    assert snapshot2.items[0].fee_occurrence_date == date(2024, 5, 20)
    assert not any("FEE_OCCURRENCE_DATE_FALLBACK" in n for n in notes2)


def test_build_snapshot_catalog_kind_from_item_type_dict() -> None:
    """ItemType→目录类别按院内字典 k10（决策记录 D1）：0=药品 1/2=诊疗 3=材料；未覆盖取值不猜测。"""
    snapshot, _ = _build(_trade_row(), items=[
        _item_row(),
        _item_row(ItemId="L2", ItemType="1"),
        _item_row(ItemId="L3", ItemType="3"),
        _item_row(ItemId="L4", ItemType="9"),
    ])
    assert snapshot.items[0].catalog_kind == CatalogKind.DRUG
    assert snapshot.items[1].catalog_kind == CatalogKind.SERVICE
    assert snapshot.items[2].catalog_kind == CatalogKind.MATERIAL
    assert snapshot.items[3].catalog_kind == CatalogKind.UNKNOWN


def test_build_snapshot_catalog_entries_preserve_all_versions() -> None:
    drugs = [
        _drug_row(jzrq="2023-12-31"),
        _drug_row(sxrq="2024-01-01", jzrq=None),  # 空截止保留，内核判 VALIDITY_UNKNOWN
    ]
    snapshot, _ = _build(_trade_row(), drugs=drugs)
    assert len(snapshot.drug_catalog) == 2
    assert snapshot.drug_catalog[1].expiry_date is None  # 空截止不默认永久有效


def test_build_snapshot_material_exception_flags_noted() -> None:
    _, notes = _build(_trade_row(), mats=[("X001", "2024-01-01", None, "1", None, None)])
    assert any("MATERIAL_EXCEPTION_FLAGS_UNMAPPED" in n for n in notes)


def test_build_snapshot_missing_trade_date_raises() -> None:
    with pytest.raises(ValueError, match="交易日期"):
        _build(_trade_row(T_TradeDate=None))


def test_build_snapshot_missing_item_fee_raises() -> None:
    with pytest.raises(ValueError, match="账面费用"):
        _build(_trade_row(), items=[_item_row(Fee=None)])


# ── 读元数据 ──────────────────────────────────────────────────


def test_hash_rows_deterministic_and_order_sensitive_only_to_content() -> None:
    rows = _rows_as_dicts(_ITEM_COLS, [_item_row()])
    h1 = q.hash_rows(rows)
    h2 = q.hash_rows(_rows_as_dicts(_ITEM_COLS, [_item_row()]))
    assert h1 == h2  # 同内容同哈希（回放一致性）
    h3 = q.hash_rows(_rows_as_dicts(_ITEM_COLS, [_item_row(Fee="999.00")]))
    assert h1 != h3
    assert len(h1) == 64  # sha256 hex


def test_assemble_read_meta_counts_and_fingerprint() -> None:
    meta = q.assemble_read_meta(
        row_counts={"trade": 1, "fee_items": 2},
        content_hash=q.hash_rows([{"a": 1}]),
        mapping=DEFAULT_RECORD_QUERY_MAPPING,
        notes=("n1",),
    )
    assert meta.row_counts == {"trade": 1, "fee_items": 2}
    assert meta.source_system == "hospital_record_store"
    assert meta.mapping_fingerprint == mapping_fingerprint(DEFAULT_RECORD_QUERY_MAPPING)
    assert meta.notes == ("n1",)
    assert meta.read_at  # 读取时间非空


def test_mapping_fingerprint_changes_with_override() -> None:
    fp1 = mapping_fingerprint(DEFAULT_RECORD_QUERY_MAPPING)
    fp2 = mapping_fingerprint(RecordQueryMapping(columns={"op_fee_all": "TOTAL_FEE"}))
    assert fp1 != fp2


def test_custom_mapping_changes_sql_and_row_keys() -> None:
    """多院扩展点：换列名后 SQL 与结果键随映射变化，代码零改动。"""
    mapping = RecordQueryMapping(columns={"op_fee_all": "TOTAL_FEE", "op_trade_no": "JYH"})
    conn = _RoutingConn({"o_Trade": (("JYH", "T_TradeDate", "T_HospCode", "TOTAL_FEE"),
                                     [("T001", "2024-06-01", "H001", "3000.00")])})
    result = q.locate_outpatient_trade(conn, "T001", "H001", mapping)
    assert result.data["match_status"] == "unique_match"
    assert result.data["trade_row"]["total_fee"] == "3000.00"
    sql, _ = conn.cursor_instance.executed[0]
    assert "[JYH]" in sql and "[TOTAL_FEE]" in sql
