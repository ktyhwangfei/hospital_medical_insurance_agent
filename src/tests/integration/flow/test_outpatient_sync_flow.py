from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from scripts.generate_outpatient_reconciliation import build_reconciliation_report
from src.adapters.insurance_interface.outpatient_cdc import (
    OUTPATIENT_SOURCE_SPECS,
    OutpatientCdcBatch,
    OutpatientCdcChange,
    OutpatientSnapshot,
)
from src.data_platform.outpatient_sync import OutpatientSyncService
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


NOW = datetime(2026, 8, 28, 8, tzinfo=timezone.utc)


class _MemorySource:
    def __init__(self, snapshot, batches) -> None:
        self.snapshot = snapshot
        self.batches = list(batches)

    def read_snapshot(self):
        return self.snapshot

    def read_changes(self, _last_lsn):
        return self.batches.pop(0)


class _AtomicStore:
    def __init__(self) -> None:
        self.checkpoint = None
        self.rows = {capture: {} for capture in OUTPATIENT_SOURCE_SPECS}
        self.metadata = {}
        self.batches = []
        self.by_identity = {}
        self.atomic_observations = []

    def get_checkpoint(self, _source_id):
        return self.checkpoint

    def load_projection_rows(self, trade_nos):
        return {
            capture: tuple(
                deepcopy(row) for row in rows.values()
                if row.get("T_TradeNo") in trade_nos
                or row.get("T_OraginalTradeNo") in trade_nos
            )
            for capture, rows in self.rows.items()
        }

    def publish_batch(self, **batch):
        identity = (batch["source_id"], batch["from_lsn"], batch["to_lsn"], batch["mode"])
        if identity in self.by_identity:
            return self.by_identity[identity]

        old_visible = self.signature()
        staged_rows = deepcopy(self.rows)
        staged_metadata = deepcopy(self.metadata)
        for change in batch["changes"]:
            spec = OUTPATIENT_SOURCE_SPECS[change.capture_instance]
            key = tuple(change.payload[column] for column in spec.key_columns)
            if change.operation == 1:
                staged_rows[change.capture_instance].pop(key, None)
            else:
                staged_rows[change.capture_instance][key] = deepcopy(change.payload)

        batch_id = f"batch-{len(self.batches) + 1}"
        for (capture, source_key), metadata in batch["projection_metadata"].items():
            if capture != "dbo_o_Trade":
                continue
            staged_metadata[source_key[0]] = deepcopy(metadata)
            trade = staged_rows[capture].get(source_key)
            if trade is not None:
                trade.update(metadata)
                trade["data_batch_id"] = batch_id
        self.atomic_observations.append((old_visible, self.signature()))

        self.rows = staged_rows
        self.metadata = staged_metadata
        self.checkpoint = SimpleNamespace(last_lsn=batch["to_lsn"], last_batch_id=batch_id)
        record = {
            "batch_id": batch_id,
            "from_lsn": batch["from_lsn"],
            "to_lsn": batch["to_lsn"],
            "semantic_version": batch["semantic_version"],
            "quality_status": batch["quality_summary"]["status"],
        }
        self.batches.append(record)
        published = SimpleNamespace(batch_id=batch_id, published_at=NOW, row_count=len(batch["changes"]))
        self.by_identity[identity] = published
        return published

    def signature(self):
        return (
            len(self.rows["dbo_o_Trade"]),
            len(self.rows["dbo_o_FeeItem"]),
            len(self.rows["dbo_o_Diagnose"]),
            self.checkpoint.last_batch_id if self.checkpoint else None,
        )

    def reconciliation_rows(self, batch_id):
        values = []
        fees = self.rows["dbo_o_FeeItem"].values()
        for (trade_no,), trade in self.rows["dbo_o_Trade"].items():
            if trade.get("data_batch_id") != batch_id:
                continue
            values.append({
                "T_TradeNo": trade_no,
                "data_batch_id": batch_id,
                "trade_date": trade.get("T_TradeDate"),
                "section": (trade.get("section_codes") or ["unknown"])[0],
                "cure_type": trade.get("T_CureType"),
                "fund_type": trade.get("P_FundType"),
                "settlement_lifecycle": trade.get("settlement_lifecycle"),
                "quality_status": trade.get("quality_status"),
                "fee_all": trade.get("T_FeeAll"),
                "fee_item_total": sum(
                    (fee.get("Fee", Decimal("0")) for fee in fees if fee["T_TradeNo"] == trade_no),
                    Decimal("0"),
                ),
            })
        return values


def _trade(trade_no="T1", **changes):
    value = {
        "T_TradeNo": trade_no, "T_TradeDate": NOW, "T_State": 3,
        "NP_Settle_State": "1", "P_FundType": "3", "T_CureType": "11",
        "T_FeeAll": Decimal("100"), "T_FeeIn": Decimal("80"),
        "T_FeeOut": Decimal("20"), "T_FundPay": Decimal("70"),
        "T_SelfPayAll": Decimal("30"),
    }
    value.update(changes)
    return value


def _change(capture, operation, sequence, **payload):
    spec = OUTPATIENT_SOURCE_SPECS[capture]
    return OutpatientCdcChange(
        capture_instance=capture, start_lsn=b"\x30", seqval=bytes([sequence]),
        operation=operation, commit_time=NOW,
        source_key=tuple(payload[column] for column in spec.key_columns), payload=payload,
    )


def test_outpatient_snapshot_increment_replay_reconciliation_flow() -> None:
    snapshot = OutpatientSnapshot(
        checkpoint_lsn=b"\x20",
        min_lsn_by_capture={capture: b"\x10" for capture in OUTPATIENT_SOURCE_SPECS},
        rows_by_capture={
            "dbo_o_Trade": (_trade(),),
            "dbo_o_FeeItem": ({
                "T_TradeNo": "T1", "ItemId": "I1", "ItemNo": "1",
                "Fee": Decimal("100"), "FeeIn": Decimal("80"), "FeeOut": Decimal("20"),
            },),
            "dbo_o_Diagnose": ({
                "T_TradeNo": "T1", "DiagnoseNo": "D1", "RecipeNo": "R1",
                "RecipeDate": NOW, "DiagnoseType": "1", "DiagnoseCode": "A",
                "SectionCode": "S1",
            },),
        },
    )
    changes = (
        _change("dbo_o_Trade", 4, 1, **_trade(
            T_FeeAll=Decimal("120"), T_FeeIn=Decimal("96"), T_FeeOut=Decimal("24"),
            T_FundPay=Decimal("84"), T_SelfPayAll=Decimal("36"),
        )),
        _change(
            "dbo_o_FeeItem", 4, 2, T_TradeNo="T1", ItemId="I1", ItemNo="1",
            Fee=Decimal("119"), FeeIn=Decimal("95"), FeeOut=Decimal("24"),
        ),
        _change(
            "dbo_o_Diagnose", 1, 3, T_TradeNo="T1", DiagnoseNo="D1", RecipeNo="R1",
        ),
        _change(
            "dbo_o_Diagnose", 2, 4, T_TradeNo="T1", DiagnoseNo="D2", RecipeNo="R2",
            RecipeDate=NOW, DiagnoseType="1", DiagnoseCode="B", SectionCode="S2",
        ),
        _change("dbo_o_Trade", 2, 5, **_trade(
            "R1", T_State=-3, T_OraginalTradeNo="T1", T_PartialReturnFlag="1",
            T_FeeAll=Decimal("-20"), T_FeeIn=Decimal("-16"), T_FeeOut=Decimal("-4"),
            T_FundPay=Decimal("-14"), T_SelfPayAll=Decimal("-6"),
        )),
    )
    incremental = OutpatientCdcBatch(
        from_lsn=b"\x21", to_lsn=b"\x30", min_lsn_by_capture={}, changes=changes,
    )
    source = _MemorySource(snapshot, [incremental, incremental])
    store = _AtomicStore()
    registry_store = InMemoryRegistryStore()
    seed_semantic_layer(registry_store)
    registry = SemanticRegistry(registry_store)
    registry.publish_object("mzjyxx")
    service = OutpatientSyncService(source, store, registry)

    snapshot_result = service.run_once()
    assert snapshot_result.mode == "snapshot"
    assert store.metadata["T1"]["diagnosis_codes"] == ["A"]
    complete_snapshots = {store.signature()}

    incremental_result = service.run_once()
    assert incremental_result.mode == "incremental"
    assert store.metadata["T1"]["diagnosis_codes"] == ["B"]
    assert store.metadata["T1"]["settlement_lifecycle"] == "partially_refunded"
    complete_snapshots.add(store.signature())

    replay_result = service.run_once()
    assert replay_result.batch_id == incremental_result.batch_id
    assert len(store.batches) == 2
    assert all(old == during for old, during in store.atomic_observations)
    assert {during for _old, during in store.atomic_observations} <= complete_snapshots | {(0, 0, 0, None)}

    report = build_reconciliation_report(
        incremental_result.batch_id,
        store.reconciliation_rows(incremental_result.batch_id),
    )
    assert report.sample_count == 2
    assert report.sample_insufficient is True
    assert all(case.data_batch_id == incremental_result.batch_id for case in report.cases)
    assert store.batches[-1]["semantic_version"] == "1"
    assert store.batches[-1]["to_lsn"] == b"\x30"
