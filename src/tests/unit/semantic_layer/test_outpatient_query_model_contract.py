import json

from src.data_platform.storage.postgresql.semantic_registry_store import (
    PostgresRegistryStore,
    _row_to_object_version,
)
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


ISSUE20_REQUIRED_METRICS = {
    "mzjyxx.T_TradeDate",
    "mzjyxx.T_State",
    "mzjyxx.P_FundType",
    "mzjyxx.PN_PersonType",
    "mzjyxx.T_CureType",
    "mzjyxx.HospitalLevel",
    "mzjyxx.P_JCLevel",
    "mzjyxx.T_FeeAll",
    "mzjyxx.T_FeeIn",
    "mzjyxx.T_FeeOut",
    "mzjyxx.T_FundPay",
    "mzjyxx.T_SelfPayAll",
    "mzjyxx.T_SelfPay1",
    "mzjyxx.T_SelfPay2",
    "mzjyxx.T_BigSelfPay",
    "mzjyxx.T_FirstPay",
    "mzjyxx.T_PersonCountPay",
    "mzjyxx.T_CashPay",
    "mzjyxx.T_BigPay",
    "mzjyxx.T_BCPay",
    "mzjyxx.T_JCPay",
    "mzjyxx.T_OfficalPay",
    "mzjyxx.T_BigillPay",
    "mzjyxx.NT_BasicPay",
    "mzjyxx.NT_CivilPay",
    "mzjyxx.NT_OtherPay",
    "mzjyxx.NT_AgencySumPay",
    "mzjyxx.RETIRE_OFFICER_PAY",
    "mzjyxx.TB_FeeIn",
    "mzjyxx.TA_FeeIn",
    "mzjyxx.TB_MZTimes",
    "mzjyxx.TA_MZTimes",
    "mzjyxx.TB_BigPay",
    "mzjyxx.TA_BigPay",
    "mzjyxx.TB_FeeAfterBig",
    "mzjyxx.TA_FeeAfterBig",
    "mzjyxx.TB_FeeInL1",
    "mzjyxx.TA_FeeInL1",
    "mzjyxx.TB_BigPayL1",
    "mzjyxx.TA_BigPayL1",
    "mzjyxx.TB_FeeAfterBigL1",
    "mzjyxx.TA_FeeAfterBigL1",
    "mzjyxx.T_BeyondBig",
    "mzjyxx.NT_OUT2_SCALE",
    "mzjyxx.NT_OUT2_PRICE",
    "mzjyxx.TB_BeyondFeeIn",
    "mzjyxx.TA_BeyondFeeIn",
    "mzjyxx.TB_BigillComm",
    "mzjyxx.TA_BigillComm",
    "mzjyxx.TB_BigillPay",
    "mzjyxx.TA_BigillPay",
    "mzjyxx.P_HospFlag",
    "mzjyxx.P_Official",
    "mzjyxx.PN_ChronicFlag",
    "mzjyxx.PN_IsChronicHosp",
    "mzjyxx.PN_ChronicCode",
    "mzjyxx.PN_NoRightReason",
    "mzjyxx.P_retirementflag",
    "mzjyxx.P_CivilFlag",
    "mzjyxx.P_CivilType",
    "mzjyxx.RETIRE_OFFICER_FLAG",
    "mzjyxx.T_GFBelongFlag",
    "mzjyxx.NT_AllSelfPayFlag",
    "mzjyxx.PN_OutTransaction",
    "mzjyxx.PN_NationFundType",
    "mzjyxx.T_CompHospFlag",
    "mzjyxx.T_SpSetlFlag",
    "mzjyxx.T_HasRefundmented",
    "mzjyxx.T_PartialReturnFlag",
    "mzjyxx.T_OraginalTradeNo",
    "mzjyxx.T_OraginalTradeDate",
    "mzjyxx.NP_Settle_State",
    "mzjyxx.SETL_DATE",
    "mzjyxx.NT_ReTradeFlag",
    "mzjyxx.T_FeeNo",
    "mzjyxx.Fee",
    "mzjyxx.FeeIn",
    "mzjyxx.FeeOut",
    "mzjyxx.FeeItem_SelfPay2",
    "mzjyxx.FEE_SP_SCALE",
    "mzjyxx.FEE_MEDIC_L",
    "mzjyxx.MEDIC_L",
    "mzjyxx.SPEDRUG_FLAG",
    "mzjyxx.ItemCode",
    "mzjyxx.StandardCode",
    "mzjyxx.ItemType",
    "mzjyxx.FeeType",
    "mzjyxx.FeeItem_State",
}


def test_mzjyxx_query_model_preserves_issue20_contract_on_publish() -> None:
    assert len(ISSUE20_REQUIRED_METRICS) == 88
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)

    assert {item.dataset_code for item in registry.list_datasets("mzjyxx")} == {
        "mz_trade",
        "mz_fee_item",
    }
    assert {
        (item.key_code, item.dataset_code, tuple(item.columns), item.key_type)
        for item in registry.list_dataset_keys(object_code="mzjyxx")
    } == {
        ("mz_trade_pk", "mz_trade", ("T_TradeNo",), "primary"),
        (
            "mz_fee_item_pk",
            "mz_fee_item",
            ("T_TradeNo", "ItemId", "ItemNo"),
            "primary",
        ),
        (
            "mz_fee_item_trade_fk",
            "mz_fee_item",
            ("T_TradeNo",),
            "foreign",
        ),
    }
    assert len(registry.list_fields(object_code="mzjyxx")) == 105
    relations = registry.list_dataset_relations("mzjyxx")
    assert len(relations) == 1
    assert relations[0].cardinality == "one_to_many"
    assert len(registry.list_quality_rules("mzjyxx")) == 4
    assert ISSUE20_REQUIRED_METRICS <= {
        item.metric_code for item in registry.get_metrics_by_object("mzjyxx")
    }
    assert registry.validate_query_model("mzjyxx") == []

    version = registry.publish_object("mzjyxx")

    assert version.snapshot["queryable"] is True
    assert len(version.datasets) == 2
    assert len(version.keys) == 3
    assert len(version.fields) == 105
    assert len(version.relations) == 1
    assert len(version.quality_rules) == 4
    assert all(item.status == "published" for item in version.datasets)
    assert ISSUE20_REQUIRED_METRICS <= {
        item.metric_code for item in version.metrics
    }


def test_postgres_query_model_schema_and_snapshot_round_trip() -> None:
    calls: list[tuple[str, tuple]] = []

    class _FakeClient:
        def execute(self, sql: str, params: tuple = ()) -> list[dict]:
            calls.append((sql, params))
            return []

    postgres = PostgresRegistryStore.__new__(PostgresRegistryStore)
    postgres._client = _FakeClient()
    postgres._ensure_schema()
    ddl = "\n".join(sql for sql, _params in calls)
    assert "CREATE TABLE IF NOT EXISTS semantic_query_metadata" in ddl
    assert "ADD COLUMN IF NOT EXISTS fact_field_code" in ddl
    assert "ADD COLUMN IF NOT EXISTS query_model" in ddl

    memory = InMemoryRegistryStore()
    seed_semantic_layer(memory)
    version = SemanticRegistry(memory).publish_object("mzjyxx")
    postgres.save_object(memory.get_object("mzjyxx"))
    assert calls[-1][0].count("%s") == len(calls[-1][1])
    postgres.save_metric(memory.get_metric("mzjyxx.T_FeeAll"))
    assert calls[-1][0].count("%s") == len(calls[-1][1])
    postgres.save_object_version(version)
    params = calls[-1][1]
    restored = _row_to_object_version({
        "version_id": params[0], "object_code": params[1], "version": params[2],
        "snapshot": params[3], "metrics": params[4], "query_model": params[5],
        "published_at": params[6], "published_by": params[7], "changelog": params[8],
    })

    assert json.loads(params[5])["datasets"][0]["status"] == "published"
    assert len(restored.datasets) == 2
    assert len(restored.fields) == 105
