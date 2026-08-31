"""门诊数据源的来源中立批次契约。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


def _columns(value: str) -> tuple[str, ...]:
    return tuple(value.split(","))


@dataclass(frozen=True)
class OutpatientSourceSpec:
    table_name: str
    capture_instance: str
    key_columns: tuple[str, ...]
    columns: tuple[str, ...]


OUTPATIENT_SOURCE_SPECS = {
    "dbo_o_Trade": OutpatientSourceSpec(
        table_name="o_Trade",
        capture_instance="dbo_o_Trade",
        key_columns=("T_TradeNo",),
        columns=_columns(
            "T_SetTid,T_TradeNo,T_TradeDate,T_State,T_HasRefundmented,T_PartialReturnFlag,"
            "T_OraginalTradeNo,T_OraginalTradeDate,NP_Settle_State,SETL_DATE,NT_ReTradeFlag,"
            "T_DiagType,T_FeeNo,P_FundType,PN_PersonType,T_CureType,P_JCLevel,P_HospFlag,"
            "PN_OutTransaction,PN_NationFundType,PN_ChronicFlag,PN_ChronicCode,"
            "PN_IsChronicHosp,P_Official,P_retirementflag,P_CivilFlag,P_CivilType,"
            "RETIRE_OFFICER_FLAG,T_GFBelongFlag,T_CompHospFlag,T_SpSetlFlag,T_pneno,"
            "NT_AllSelfPayFlag,PN_NoRightReason,T_FeeAll,T_FeeIn,T_FeeOut,T_FirstPay,"
            "T_SelfPay1,T_SelfPay2,T_SelfPayAll,T_BigPay,T_BigSelfPay,T_BeyondBig,T_FundPay,"
            "T_PersonCountPay,T_CashPay,PN_PersonCount,T_PersonCountAfter,T_BCPay,T_JCPay,"
            "T_OfficalPay,T_BigillPay,NT_BasicPay,NT_CivilPay,NT_OtherPay,NT_AgencySumPay,"
            "RETIRE_OFFICER_PAY,NT_OUT2_SCALE,NT_OUT2_PRICE,TB_FeeIn,TA_FeeIn,TB_BigPay,"
            "TA_BigPay,TB_FeeAfterBig,TA_FeeAfterBig,TB_MZTimes,TA_MZTimes,TB_BeyondFeeIn,"
            "TA_BeyondFeeIn,TB_BigillComm,TA_BigillComm,TB_BigillPay,TA_BigillPay,"
            "TB_CivilComm,TA_CivilComm,TB_CivilPay,TA_CivilPay,TB_FeeInL1,TA_FeeInL1,"
            "TB_BigPayL1,TA_BigPayL1,TB_FeeAfterBigL1,TA_FeeAfterBigL1,PN_InsuredAreaCode,"
            "T_HospCode,T_HospCodeA"
        ),
    ),
    "dbo_o_FeeItem": OutpatientSourceSpec(
        table_name="o_FeeItem",
        capture_instance="dbo_o_FeeItem",
        key_columns=("T_TradeNo", "ItemId", "ItemNo"),
        columns=_columns(
            "T_TradeNo,ItemId,ItemNo,ItemCode,StandardCode,ItemName,ItemType,FeeType,F_LEVEL,"
            "Count,UnitPrice,Fee,FeeIn,FeeOut,SelfPay2,FEE_SP_SCALE,FEE_MEDIC_L,MEDIC_L,"
            "SPEDRUG_FLAG,State"
        ),
    ),
    "dbo_o_Diagnose": OutpatientSourceSpec(
        table_name="o_Diagnose",
        capture_instance="dbo_o_Diagnose",
        key_columns=("T_TradeNo", "DiagnoseNo", "RecipeNo"),
        columns=_columns(
            "T_TradeNo,DiagnoseNo,RecipeNo,RecipeDate,DiagnoseName,DiagnoseCode,SectionCode,"
            "Sectionname,HISSectionName,DiagnoseType"
        ),
    ),
}


class OutpatientSourceMode(StrEnum):
    CDC = "cdc"
    SCHEDULED_SQL = "scheduled_sql"


class CheckpointKind(StrEnum):
    LSN = "lsn"
    TIME_WINDOW = "time_window"


@dataclass(frozen=True)
class OutpatientCheckpoint:
    kind: CheckpointKind
    value: str
    observed_at: datetime


@dataclass(frozen=True)
class OutpatientChange:
    capture_instance: str
    source_cursor: bytes
    operation: int
    commit_time: datetime | None
    source_key: tuple[Any, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class OutpatientSourceBatch:
    mode: OutpatientSourceMode
    checkpoint: OutpatientCheckpoint
    changes: tuple[OutpatientChange, ...] = ()
    snapshot_rows: dict[str, tuple[dict[str, Any], ...]] | None = None
    scope_trade_nos: frozenset[str] = field(default_factory=frozenset)
    is_baseline: bool = False


class OutpatientSource(Protocol):
    def read(self, checkpoint: OutpatientCheckpoint | None) -> OutpatientSourceBatch:
        raise NotImplementedError
