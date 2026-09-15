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
    supply = _FakeSupply([])
    provider = SemanticSettlementDataProvider(supply=supply, registry=_registry())

    await provider.list_settlements_by_date_range(
        "2025-08-01", "2025-08-31", limit=10, patient_key="10065478600S"
    )

    sql, params = supply.last_connection.last_cursor.executed[0]
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
