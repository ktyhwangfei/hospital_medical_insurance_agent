from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.adapters.insurance_interface.outpatient_cdc import CdcRetentionGapError
from src.adapters.insurance_interface.outpatient_source import (
    CheckpointKind,
    OutpatientChange,
    OutpatientCheckpoint,
    OutpatientSourceBatch,
    OutpatientSourceMode,
)
from src.data_platform.outpatient_sync import OutpatientSyncService


NOW = datetime(2026, 8, 28, 8, tzinfo=timezone.utc)


def _change(capture: str, key: tuple[str, ...], operation: int = 2, **payload):
    key_columns = {
        "dbo_o_Trade": ("T_TradeNo",),
        "dbo_o_FeeItem": ("T_TradeNo", "ItemId", "ItemNo"),
        "dbo_o_Diagnose": ("T_TradeNo", "DiagnoseNo", "RecipeNo"),
    }[capture]
    payload.update(dict(zip(key_columns, key)))
    return OutpatientChange(
        capture_instance=capture,
        source_cursor=b"\x20" + bytes([len(key), operation]),
        operation=operation,
        commit_time=NOW,
        source_key=key,
        payload=payload,
    )


class _Source:
    def __init__(self, *, batches=(), error=None):
        self.batches = list(batches)
        self.error = error
        self.calls = []

    def read(self, checkpoint):
        self.calls.append(checkpoint)
        if self.error:
            raise self.error
        return self.batches.pop(0)


class _Store:
    def __init__(self, checkpoint=None, rows=None):
        self.checkpoint = checkpoint
        self.rows = rows or {}
        self.calls = []
        self.fail = False

    def get_checkpoint(self, source_id):
        return self.checkpoint

    def load_projection_rows(self, trade_nos):
        wanted = set(trade_nos)
        return {
            capture: tuple(
                row for row in rows
                if row.get("T_TradeNo") in wanted
                or row.get("T_OraginalTradeNo") in wanted
            )
            for capture, rows in self.rows.items()
        }

    def publish_batch(self, **kwargs):
        if self.fail:
            raise RuntimeError("store failed")
        self.calls.append(kwargs)
        self.checkpoint = kwargs["batch"].checkpoint
        return SimpleNamespace(
            batch_id=f"batch-{len(self.calls)}", published_at=NOW,
            row_count=len(kwargs["batch"].changes),
        )


class _Registry:
    def __init__(self, *, version="3", queryable=True):
        self.obj = SimpleNamespace(
            status="published" if version else "draft", current_version=version,
        ) if version else None
        self.version = SimpleNamespace(snapshot={"queryable": queryable}) if version else None

    def get_object(self, object_code):
        assert object_code == "mzjyxx"
        return self.obj

    def get_object_version(self, object_code, version):
        assert object_code == "mzjyxx"
        return self.version


def _trade(trade_no="T1", **overrides):
    payload = {
        "T_TradeNo": trade_no, "T_TradeDate": NOW,
        "T_State": 3, "NP_Settle_State": "1",
        "T_FeeAll": Decimal("100.00"), "T_FeeIn": Decimal("80.00"),
        "T_FeeOut": Decimal("20.00"), "T_FundPay": Decimal("70.00"),
        "T_SelfPayAll": Decimal("30.00"),
    }
    payload.update(overrides)
    return payload


def _snapshot(*rows):
    grouped = {"dbo_o_Trade": [], "dbo_o_FeeItem": [], "dbo_o_Diagnose": []}
    for capture, payload in rows:
        grouped[capture].append(payload)
    return OutpatientSourceBatch(
        mode=OutpatientSourceMode.CDC,
        checkpoint=OutpatientCheckpoint(CheckpointKind.LSN, "20", NOW),
        snapshot_rows={capture: tuple(items) for capture, items in grouped.items()},
        is_baseline=True,
    )


def test_run_once_uses_snapshot_and_preserves_decimal_values() -> None:
    snapshot = _snapshot(
        ("dbo_o_Trade", _trade()),
        ("dbo_o_FeeItem", {
            "T_TradeNo": "T1", "ItemId": "I1", "ItemNo": "1",
            "Fee": Decimal("100.00"), "FeeIn": Decimal("80.00"),
            "FeeOut": Decimal("20.00"),
        }),
        ("dbo_o_Diagnose", {
            "T_TradeNo": "T1", "DiagnoseNo": "D1", "RecipeNo": "R1",
            "RecipeDate": NOW, "DiagnoseCode": "Z00", "SectionCode": "S1",
        }),
    )
    source = _Source(batches=[snapshot])
    store = _Store()

    result = OutpatientSyncService(source, store, _Registry()).run_once()

    assert result.mode == "snapshot"
    assert result.semantic_version == "3"
    assert source.calls == [None]
    assert result.checkpoint.value == "20"
    trade_change = next(c for c in store.calls[0]["batch"].changes if c.capture_instance == "dbo_o_Trade")
    assert trade_change.payload["T_FeeAll"] == Decimal("100.00")
    assert not isinstance(trade_change.payload["T_FeeAll"], float)


def test_incremental_heartbeat_and_store_failure_do_not_skip_checkpoint() -> None:
    checkpoint = OutpatientCheckpoint(CheckpointKind.LSN, "20", NOW)
    empty = OutpatientSourceBatch(
        mode=OutpatientSourceMode.CDC,
        checkpoint=OutpatientCheckpoint(CheckpointKind.LSN, "22", NOW),
    )
    store = _Store(checkpoint=checkpoint)
    result = OutpatientSyncService(
        _Source(batches=[empty]), store, _Registry(),
    ).run_once()
    assert result.mode == "heartbeat"
    assert store.calls[0]["batch"].changes == ()

    store = _Store(checkpoint=OutpatientCheckpoint(CheckpointKind.LSN, "30", NOW))
    store.fail = True
    change_batch = OutpatientSourceBatch(
        mode=OutpatientSourceMode.CDC,
        checkpoint=OutpatientCheckpoint(CheckpointKind.LSN, "32", NOW),
        changes=(_change("dbo_o_Trade", ("T2",), **_trade("T2")),),
    )
    with pytest.raises(RuntimeError, match="store failed"):
        OutpatientSyncService(
            _Source(batches=[change_batch]), store, _Registry(),
        ).run_once()
    assert store.checkpoint.value == "30"


def test_refund_chain_diagnosis_fallback_and_amount_warning_are_published() -> None:
    original = _trade()
    refund = _trade(
        "R1", T_State=-3, T_OraginalTradeNo="T1", T_PartialReturnFlag="1",
        T_FeeAll=Decimal("-40.00"), T_FeeIn=Decimal("-30.00"),
        T_FeeOut=Decimal("-10.00"), T_FundPay=Decimal("-30.00"),
        T_SelfPayAll=Decimal("-10.00"),
    )
    snapshot = _snapshot(
        ("dbo_o_Trade", original), ("dbo_o_Trade", refund),
        ("dbo_o_FeeItem", {
            "T_TradeNo": "T1", "ItemId": "I1", "ItemNo": "1",
            "Fee": Decimal("99.00"), "FeeIn": Decimal("79.00"),
            "FeeOut": Decimal("20.00"),
        }),
        ("dbo_o_Diagnose", {
            "T_TradeNo": "T1", "DiagnoseNo": "D2", "RecipeNo": "R2",
            "RecipeDate": datetime(2026, 8, 29, tzinfo=timezone.utc),
            "DiagnoseCode": "B", "SectionCode": "S2", "Sectionname": "外科",
        }),
        ("dbo_o_Diagnose", {
            "T_TradeNo": "T1", "DiagnoseNo": "D1", "RecipeNo": "R1",
            "RecipeDate": NOW, "DiagnoseCode": "A", "SectionCode": "S1",
            "Sectionname": "内科", "HISSectionName": "内一科",
        }),
    )
    store = _Store()

    OutpatientSyncService(_Source(batches=[snapshot]), store, _Registry()).run_once()

    call = store.calls[0]
    metadata = call["projection_metadata"][("dbo_o_Trade", ("T1",))]
    assert metadata["settlement_chain_id"] == "T1"
    assert metadata["settlement_lifecycle"] == "partially_refunded"
    assert metadata["context_quality"] == "deterministic_fallback"
    assert metadata["diagnosis_codes"] == ["A"]
    assert metadata["section_codes"] == ["S1"]
    assert metadata["section_names"] == ["内科", "内一科"]
    assert call["quality_summary"]["status"] == "warning"
    assert "fee_detail_total_mismatch" in {
        issue["rule_code"] for issue in call["quality_summary"]["issues"]
    }
    assert next(c for c in call["batch"].changes if c.source_key == ("T1",)).payload["T_FeeAll"] == Decimal("100.00")


def test_primary_diagnosis_wins_and_tie_break_is_stable() -> None:
    snapshot = _snapshot(
        ("dbo_o_Trade", _trade()),
        ("dbo_o_Diagnose", {
            "T_TradeNo": "T1", "DiagnoseNo": "D2", "RecipeNo": "R2",
            "RecipeDate": NOW, "DiagnoseType": "1", "DiagnoseCode": "PRIMARY",
        }),
        ("dbo_o_Diagnose", {
            "T_TradeNo": "T1", "DiagnoseNo": "D1", "RecipeNo": "R1",
            "RecipeDate": NOW, "DiagnoseCode": "FALLBACK",
        }),
    )
    store = _Store()
    OutpatientSyncService(_Source(batches=[snapshot]), store, _Registry()).run_once()
    metadata = store.calls[0]["projection_metadata"][("dbo_o_Trade", ("T1",))]
    assert metadata["context_quality"] == "source_primary"
    assert metadata["diagnosis_codes"] == ["PRIMARY"]

    tied = _snapshot(
        ("dbo_o_Trade", _trade()),
        ("dbo_o_Diagnose", {
            "T_TradeNo": "T1", "DiagnoseNo": "D2", "RecipeNo": "R1",
            "RecipeDate": NOW, "DiagnoseCode": "B",
        }),
        ("dbo_o_Diagnose", {
            "T_TradeNo": "T1", "DiagnoseNo": "D1", "RecipeNo": "R9",
            "RecipeDate": NOW, "DiagnoseCode": "A",
        }),
    )
    store = _Store()
    OutpatientSyncService(_Source(batches=[tied]), store, _Registry()).run_once()
    metadata = store.calls[0]["projection_metadata"][("dbo_o_Trade", ("T1",))]
    assert metadata["diagnosis_codes"] == ["A"]


def test_structural_and_unmatched_refund_problems_block_batch() -> None:
    snapshot = _snapshot(
        ("dbo_o_Trade", _trade(
            "R1", T_State=-3, T_OraginalTradeNo="MISSING",
            T_FeeAll=Decimal("-10"), T_FeeIn=Decimal("-10"),
            T_FeeOut=Decimal("0"), T_FundPay=Decimal("-10"),
            T_SelfPayAll=Decimal("0"),
        )),
        ("dbo_o_FeeItem", {
            "T_TradeNo": "ORPHAN", "ItemId": "I1", "ItemNo": "1", "Fee": Decimal("1"),
        }),
    )
    store = _Store()

    result = OutpatientSyncService(_Source(batches=[snapshot]), store, _Registry()).run_once()

    assert result.quality_status == "blocked"
    codes = {issue["rule_code"] for issue in store.calls[0]["quality_summary"]["issues"]}
    assert {"unmatched_negative", "orphan_fee_item"} <= codes


def test_retention_gap_fails_closed_and_unpublished_model_blocks_queryability() -> None:
    gap = CdcRetentionGapError("cdc_retention_gap")
    store = _Store(checkpoint=OutpatientCheckpoint(CheckpointKind.LSN, "01", NOW))
    with pytest.raises(CdcRetentionGapError):
        OutpatientSyncService(_Source(error=gap), store, _Registry()).run_once()
    assert store.calls == []
    assert store.checkpoint.value == "01"

    store = _Store()
    result = OutpatientSyncService(
        _Source(batches=[_snapshot(("dbo_o_Trade", _trade()))]),
        store,
        _Registry(version=None),
    ).run_once()
    assert result.semantic_version is None
    assert result.quality_status == "blocked"
    assert store.calls[0]["semantic_version"] is None
    assert "semantic_model_unavailable" in {
        issue["rule_code"] for issue in store.calls[0]["quality_summary"]["issues"]
    }
