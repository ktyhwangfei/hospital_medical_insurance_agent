from __future__ import annotations

import pytest

from src.runtime.policy_qa.settlement_data_provider import (
    SemanticSettlementDataProvider,
    SettlementListItem,
    SettlementNotFoundError,
    mask_id_no,
)
from src.semantic_layer.query_planner import QueryEvidence, SemanticQueryResult
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import publish_seed_query_object, seed_semantic_layer


class _FakeQueryService:
    def __init__(self, result: SemanticQueryResult) -> None:
        self.result = result
        self.query = None

    def execute(self, query):
        self.query = query
        return self.result


def _registry() -> SemanticRegistry:
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    publish_seed_query_object(registry)
    return registry


def _result(*, quality_status: str = "complete", rows=None, anchor_count=1, segment_count=2, matched=2):
    return SemanticQueryResult(
        rows=rows or [],
        model_version="1",
        result_grain=["inpatient_admission"],
        query_scope="whole_admission",
        quality_status=quality_status,
        evidence=QueryEvidence(
            plan_hash="plan-1",
            datasets_used=["benefit_segments", "payment_segments"],
            anchor_count=anchor_count,
            segment_count=segment_count,
            matched_segment_count=matched,
            stay_start_date="2025-01-01",
            stay_end_date="2025-04-15",
        ),
    )


@pytest.mark.asyncio
async def test_provider_queries_whole_admission_and_maps_all_segments():
    service = _FakeQueryService(_result(rows=[{
        "total_amount": 3000,
        "medical_insurance_inner_amount": 2600,
        "deductible": 500,
        "basic_pooling_payment": 1800,
        "basic_pooling_self_pay": 300,
        "large_amount_payment": 100,
        "large_amount_self_pay": 50,
        "personal_total_pay": 1100,
        "yearly_cycle_count": 2,
        "person_type": "2",
        "insurance_type": "3",
        "service_type": "21",
    }]))
    provider = SemanticSettlementDataProvider(service=service, registry=_registry())

    context = await provider.get_settlement_context("1671213")

    assert service.query.scope.anchor.value == "1671213"
    assert service.query.scope.query_scope == "whole_admission"
    assert context.total_amount == 3000
    assert context.person_type == "退休人员"
    assert service.result.rows[0]["person_type"] == "退休人员"
    assert context.query_scope == "whole_admission"
    assert context.segment_count == 2
    assert context.matched_segment_count == 2
    assert context.stay_start_date == "2025-01-01"
    assert context.stay_end_date == "2025-04-15"
    assert context.amounts_reliable is True


@pytest.mark.asyncio
async def test_provider_withholds_amounts_when_segment_coverage_is_partial():
    service = _FakeQueryService(_result(
        quality_status="partial",
        rows=[{"total_amount": 3000}],
        segment_count=2,
        matched=1,
    ))
    provider = SemanticSettlementDataProvider(service=service, registry=_registry())

    context = await provider.get_settlement_context("1671213")

    assert context.coverage_status == "partial"
    assert context.amounts_reliable is False
    assert context.total_amount is None


@pytest.mark.asyncio
async def test_provider_reports_missing_admission():
    service = _FakeQueryService(_result(
        quality_status="unavailable",
        anchor_count=0,
        segment_count=0,
        matched=0,
    ))
    provider = SemanticSettlementDataProvider(service=service, registry=_registry())

    with pytest.raises(SettlementNotFoundError):
        await provider.get_settlement_context("missing")


@pytest.mark.asyncio
async def test_provider_preserves_null_and_explicit_zero_and_runs_capability_query():
    service = _FakeQueryService(_result(rows=[{
        "total_amount": None,
        "deductible": 0,
    }]))
    provider = SemanticSettlementDataProvider(service=service, registry=_registry())

    context = await provider.get_settlement_context("S-1")
    direct_result = await provider.run_semantic_query(service.query)

    assert context.total_amount is None
    assert context.deductible == 0.0
    assert direct_result.quality_status == "complete"


class _FakeCursor:
    def __init__(self, rows, description=None):
        self._rows = rows
        self._fetched = False
        # lookup 查询返回的列名与列表查询不同，按需覆盖
        self.description = description or [
            ("settlement_id",),
            ("person_type_code",),
            ("insurance_type_code",),
            ("service_type_code",),
            ("total_amount",),
            ("settlement_date",),
        ]
        # 记录 execute 入参，供过滤参数断言
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        if self._fetched:
            return None
        self._fetched = True
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, rows, description=None):
        self._rows = rows
        self._description = description
        self.last_cursor: _FakeCursor | None = None

    def cursor(self):
        cursor = _FakeCursor(self._rows, self._description)
        self.last_cursor = cursor
        return cursor

    def close(self):
        pass


class _FakeSupply:
    def __init__(self, rows, description=None):
        self._rows = rows
        self._description = description
        self.last_connection: _FakeConnection | None = None

    def connect(self, datasource_id):
        connection = _FakeConnection(self._rows, self._description)
        self.last_connection = connection
        return connection


@pytest.mark.asyncio
async def test_list_settlements_by_date_range_maps_and_resolves_domains():
    rows = [
        ("1671213", "2", "3", "21", 12386.40, "2025-04-15"),
        ("1671218", "1", "2", "11", 1240.00, "2025-04-16"),
    ]
    provider = SemanticSettlementDataProvider(supply=_FakeSupply(rows), registry=_registry())

    items = await provider.list_settlements_by_date_range("2025-04-01", "2025-04-30", limit=10)

    assert len(items) == 2
    assert items[0].settlement_id == "1671213"
    assert items[0].person_type == "退休人员"
    assert items[0].insurance_type == "城镇职工"
    assert items[0].service_type == "普通住院"
    assert items[0].total_amount == 12386.40
    assert items[0].settlement_date == "2025-04-15"

    assert items[1].settlement_id == "1671218"
    assert items[1].person_type == "在职人员"
    assert items[1].insurance_type == "2"
    assert items[1].service_type == "普通门诊"


@pytest.mark.asyncio
async def test_list_settlements_by_date_range_validates_date_format():
    provider = SemanticSettlementDataProvider(supply=_FakeSupply([]), registry=_registry())

    with pytest.raises(ValueError, match="date_from"):
        await provider.list_settlements_by_date_range("2025/04/01", "2025-04-30")


@pytest.mark.asyncio
async def test_list_settlements_by_date_range_requires_data_supply_connection():
    provider = SemanticSettlementDataProvider(service=_FakeQueryService(_result()), registry=_registry())
    with pytest.raises(RuntimeError, match="数据供给连接"):
        await provider.list_settlements_by_date_range("2025-04-01", "2025-04-30")


# ── 患者定位（临时方案：正式由登录态取代）──────────────────────

_LOOKUP_DESCRIPTION = [
    ("kh",), ("sfz",), ("xm",), ("xb",), ("csrq",), ("djh",),
]


def test_mask_id_no():
    assert mask_id_no("110103194203280937") == "110***********0937"
    # 非 18 位原样返回（不制造伪脱敏）
    assert mask_id_no("12345") == "12345"
    assert mask_id_no("") == ""


@pytest.mark.asyncio
async def test_lookup_patient_masks_id_and_maps_gender():
    from datetime import datetime as dt

    row = ("10065478600S", "110103194203280937", "张三", "1", dt(1942, 3, 28), 1671213)
    supply = _FakeSupply([row], description=_LOOKUP_DESCRIPTION)
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    summary = await provider.lookup_patient("110103194203280937")

    assert summary is not None
    assert summary.card_no == "10065478600S"
    assert summary.id_no_masked == "110***********0937"
    assert summary.name == "张三"
    assert summary.gender == "男"
    assert summary.birth_date == "1942-03-28"
    assert summary.registration_id == "1671213"
    # SQL 参数：sfz / kh 双路径同键
    sql, params = supply.last_connection.last_cursor.executed[0]
    assert "sfz = ? OR kh = ?" in sql
    assert params == ("110103194203280937", "110103194203280937")


@pytest.mark.asyncio
async def test_lookup_patient_miss_returns_none():
    supply = _FakeSupply([], description=_LOOKUP_DESCRIPTION)
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    assert await provider.lookup_patient("NOT-EXIST") is None


@pytest.mark.asyncio
async def test_lookup_patient_rejects_blank_key():
    provider = SemanticSettlementDataProvider(supply=_FakeSupply([]), registry=_registry())
    with pytest.raises(ValueError, match="key 不能为空"):
        await provider.lookup_patient("   ")


@pytest.mark.asyncio
async def test_list_settlements_by_date_range_with_patient_key_filters_sql():
    # patient_key 提供时共三次查询：住院列表 → o_Trade 门诊 → 门特登记按人直查
    supply = _SequentialFakeSupply([([], None), ([], None), ([], _SPECIAL_LIST_DESCRIPTION)])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    await provider.list_settlements_by_date_range(
        "2025-08-01", "2025-08-31", limit=10, patient_key="10065478600S"
    )

    sql, params = supply.connections[0].last_cursor.executed[0]
    assert "AND (r.sfz = ? OR r.kh = ?)" in sql
    assert params == (10, "10065478600S", "10065478600S", "2025-08-01", "2025-08-31")


@pytest.mark.asyncio
async def test_list_settlements_by_date_range_without_patient_key_has_no_filter():
    supply = _FakeSupply([])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    await provider.list_settlements_by_date_range("2025-08-01", "2025-08-31", limit=10)

    sql, params = supply.last_connection.last_cursor.executed[0]
    assert "r.sfz = ?" not in sql
    assert params == (10, "2025-08-01", "2025-08-31")


# ── 门诊链路（Issue #78：门诊患者身份/交易只在 o_Trade，yb_brdjxx 无门诊登记）──

class _SequentialFakeSupply:
    """按 connect 调用次序返回不同结果集（住院未命中 → o_Trade 回退等两段查询）。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.connections: list[_FakeConnection] = []

    def connect(self, datasource_id):
        rows, description = self._responses.pop(0)
        connection = _FakeConnection(rows, description)
        self.connections.append(connection)
        return connection


_OTRADE_LOOKUP_DESCRIPTION = [
    ("P_Name",), ("P_Sex",), ("P_Birthday",), ("P_IDNo",), ("P_CardNo",),
]

_SPECIAL_LIST_DESCRIPTION = [
    ("settlement_id",), ("settlement_date",), ("total_amount",), ("fund_type",),
]

_OTRADE_LIST_DESCRIPTION = [
    ("T_TradeNo",), ("T_TradeDate",), ("T_FeeAll",), ("P_FundType",),
    ("T_CureType",), ("reg_djh",), ("reg_yllb",), ("setl_date",), ("setl_amount",),
]


@pytest.mark.asyncio
async def test_lookup_patient_falls_back_to_otrade_when_registration_misses():
    from datetime import datetime as dt

    otrade_row = ("李四", "2", dt(1987, 5, 10), "132201198705101616", "MZ0001")
    supply = _SequentialFakeSupply([
        ([], _LOOKUP_DESCRIPTION),                 # yb_brdjxx 未命中
        ([otrade_row], _OTRADE_LOOKUP_DESCRIPTION),  # o_Trade 回退命中
    ])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    summary = await provider.lookup_patient("132201198705101616")

    assert summary is not None
    assert summary.name == "李四"
    assert summary.gender == "女"
    assert summary.birth_date == "1987-05-10"
    assert summary.card_no == "MZ0001"
    # 身份证号脱敏（前 3 后 4），不回显原文
    assert summary.id_no_masked == "132***********1616"
    assert "132201198705101616" not in summary.model_dump_json()
    # 门诊交易无住院登记号
    assert summary.registration_id == ""
    sql, params = supply.connections[1].last_cursor.executed[0]
    assert "o_Trade" in sql
    assert "P_IDNo = ? OR P_ICNo = ? OR P_CardNo = ?" in sql
    assert "T_TradeDate DESC" in sql
    assert params == ("132201198705101616",) * 3


@pytest.mark.asyncio
async def test_lookup_patient_returns_none_when_both_sources_miss():
    supply = _SequentialFakeSupply([
        ([], _LOOKUP_DESCRIPTION),
        ([], _OTRADE_LOOKUP_DESCRIPTION),
    ])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    assert await provider.lookup_patient("NOBODY") is None
    assert len(supply.connections) == 2


@pytest.mark.asyncio
async def test_lookup_patient_registration_hit_skips_otrade_fallback():
    from datetime import datetime as dt

    row = ("10065478600S", "110103194203280937", "张三", "1", dt(1942, 3, 28), 1671213)
    supply = _FakeSupply([row], description=_LOOKUP_DESCRIPTION)
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    summary = await provider.lookup_patient("110103194203280937")

    assert summary is not None
    executed = supply.last_connection.last_cursor.executed
    assert len(executed) == 1
    assert "o_Trade" not in executed[0][0]


@pytest.mark.asyncio
async def test_list_settlements_merges_outpatient_trades_when_patient_key():
    inpatient_rows = [("1671213", "2", "3", "21", 12386.40, "2025-08-10")]
    otrade_rows = [
        # 普通门诊交易
        ("T1001", "2025-08-20", 52.50, "3", "11", None, None, None, None),
        # 门特（yllb='12' → 登记号 djh + special 分解链；日期/金额取 mzjyxx 结算口径）
        ("T1002", "2025-08-25", 100.00, "3", "17", "DJH9001", "12", "2025-08-25", 100.00),
    ]
    supply = _SequentialFakeSupply([
        (inpatient_rows, None),
        (otrade_rows, _OTRADE_LIST_DESCRIPTION),
        ([], _SPECIAL_LIST_DESCRIPTION),
    ])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    items = await provider.list_settlements_by_date_range(
        "2025-08-01", "2025-08-31", limit=10, patient_key="132201198705101616"
    )

    by_id = {item.settlement_id: item for item in items}
    outpatient = by_id["T1001"]
    assert outpatient.service_type == "门诊"
    assert outpatient.decomposition_chain == "outpatient"
    assert outpatient.insurance_type == "城镇职工"
    assert outpatient.person_type == ""
    assert outpatient.total_amount == 52.50
    special = by_id["DJH9001"]
    assert special.service_type == "门诊特殊病"
    assert special.decomposition_chain == "special"
    inpatient = by_id["1671213"]
    assert inpatient.decomposition_chain is None
    # 门诊 SQL：身份 OR 子句 + [date_from, date_to+1) 窗口
    sql, params = supply.connections[1].last_cursor.executed[0]
    assert "o_Trade" in sql
    assert "t.P_IDNo = ? OR t.P_ICNo = ? OR t.P_CardNo = ?" in sql
    assert "yb_mzjyxx" in sql and "SETL_ID" in sql
    assert params == ("132201198705101616",) * 3 + ("2025-08-01", "2025-09-01")
    # 合并后按日期 DESC
    dates = [item.settlement_date for item in items]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_list_settlements_merged_result_sorted_desc_and_truncated_to_limit():
    inpatient_rows = [("1671213", "2", "3", "21", 100.0, "2025-08-05")]
    otrade_rows = [
        ("T1001", "2025-08-20", 52.50, "3", "11", None, None, None, None),
        ("T1002", "2025-08-25", 100.00, "3", "17", None, None, None, None),
    ]
    supply = _SequentialFakeSupply([
        (inpatient_rows, None),
        (otrade_rows, _OTRADE_LIST_DESCRIPTION),
        ([], _SPECIAL_LIST_DESCRIPTION),
    ])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    items = await provider.list_settlements_by_date_range(
        "2025-08-01", "2025-08-31", limit=2, patient_key="132201198705101616"
    )

    assert [item.settlement_id for item in items] == ["T1002", "T1001"]


@pytest.mark.asyncio
async def test_list_settlements_special_deduped_by_djh_with_mzjyxx_amounts():
    """门特粒度是 yb_mzjyxx 的 djh 行：多笔 HIS 交易汇入同一 djh 只出一条，
    日期/金额取结算口径（m.jyrq/m.zje），非交易行口径。"""
    otrade_rows = [
        # 同一门特 djh 的 2 笔 HIS 交易（活库实测同一 djh 重复 20 次）
        ("T2001", "2025-08-20", 10.0, "3", "17", "DJH9001", "12", "2025-08-21", 500.0),
        ("T2002", "2025-08-20", 20.0, "3", "17", "DJH9001", "12", "2025-08-21", 500.0),
        # 同一 djh 关联到多行 mzjyxx（理论唯一）：取最新 jyrq 一条
        ("T2003", "2025-08-22", 30.0, "3", "17", "DJH9001", "12", "2025-08-23", 600.0),
        # 普通门诊交易保持交易行粒度
        ("T3001", "2025-08-24", 52.5, "3", "11", None, None, None, None),
    ]
    supply = _SequentialFakeSupply([
        ([], None),
        (otrade_rows, _OTRADE_LIST_DESCRIPTION),
        # 按人直查同一 djh 得到更早的结算日期：不得覆盖交易路关联到的最新结算
        ([("DJH9001", "2025-08-21", 500.0, "3")], _SPECIAL_LIST_DESCRIPTION),
    ])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    items = await provider.list_settlements_by_date_range(
        "2025-08-01", "2025-08-31", limit=10, patient_key="132201198705101616"
    )

    special_items = [item for item in items if item.decomposition_chain == "special"]
    assert len(special_items) == 1
    special = special_items[0]
    assert special.settlement_id == "DJH9001"
    # 结算口径：最新 jyrq + zje，而非交易行的 T_TradeDate/T_FeeAll
    assert special.settlement_date == "2025-08-23"
    assert special.total_amount == 600.0
    outpatient_items = [item for item in items if item.decomposition_chain == "outpatient"]
    assert [item.settlement_id for item in outpatient_items] == ["T3001"]


@pytest.mark.asyncio
async def test_list_settlements_without_patient_key_never_queries_otrade():
    supply = _FakeSupply([])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    await provider.list_settlements_by_date_range("2025-08-01", "2025-08-31", limit=10)

    executed = supply.last_connection.last_cursor.executed
    assert len(executed) == 1
    assert "o_Trade" not in executed[0][0]


@pytest.mark.asyncio
async def test_list_settlements_same_day_sorted_by_trade_time_desc():
    """同日多笔按真实交易时刻倒序：settlement_date 保留到秒（#78 展示重构）。

    改动前日期被截断到日（[:10]），同一天内退化为合并顺序（住院在前）。"""
    from datetime import datetime as dt

    inpatient_rows = [("1671213", "2", "3", "21", 100.0, dt(2025, 8, 20, 0, 0, 0))]
    otrade_rows = [
        ("T1001", dt(2025, 8, 20, 9, 0, 0), 52.50, "3", "11", None, None, None, None),
        ("T1002", dt(2025, 8, 20, 15, 30, 0), 100.00, "3", "17", None, None, None, None),
    ]
    supply = _SequentialFakeSupply([
        (inpatient_rows, None),
        (otrade_rows, _OTRADE_LIST_DESCRIPTION),
        ([], _SPECIAL_LIST_DESCRIPTION),
    ])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    items = await provider.list_settlements_by_date_range(
        "2025-08-01", "2025-08-31", limit=10, patient_key="132201198705101616"
    )

    assert [item.settlement_id for item in items] == ["T1002", "T1001", "1671213"]
    assert items[0].settlement_date == "2025-08-20 15:30:00"


@pytest.mark.asyncio
async def test_special_found_by_person_when_trade_number_does_not_match_setl_id():
    """活库 1937486：o_Trade.T_FeeNo 是 HIS 费用单号，yb_mzjyxx.SETL_ID 是医保结算号，
    交易号关联必然为空；门特结算必须按 yb_brdjxx 身份直查补齐，否则整单定位不到。"""
    otrade_rows = [
        ("011100030X250612005772", "2025-06-12 10:58:48", 50.00, "3", "17", None, None, None, None),
        ("011100030X250612006045", "2025-06-12 11:14:47", 27.48, "3", "11", None, None, None, None),
    ]
    special_rows = [("1937486", "2025-06-12 11:14:01", 184.79, "3")]
    supply = _SequentialFakeSupply([
        ([], None),
        (otrade_rows, _OTRADE_LIST_DESCRIPTION),
        (special_rows, _SPECIAL_LIST_DESCRIPTION),
    ])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    items = await provider.list_settlements_by_date_range(
        "2025-06-01", "2025-06-30", limit=10, patient_key="210281198010043026"
    )

    by_id = {item.settlement_id: item for item in items}
    assert "1937486" in by_id
    special = by_id["1937486"]
    assert special.decomposition_chain == "special"
    assert special.service_type == "门诊特殊病"
    assert special.settlement_date == "2025-06-12 11:14:01"
    assert special.total_amount == 184.79
    # 门特直查 SQL：身份走登记表，日期用结算口径 m.jyrq
    sql, params = supply.connections[2].last_cursor.executed[0]
    assert "yb_brdjxx" in sql and "yb_mzjyxx" in sql and "yllb = '12'" in sql
    assert params == ("210281198010043026", "210281198010043026", "2025-06-01", "2025-07-01")
