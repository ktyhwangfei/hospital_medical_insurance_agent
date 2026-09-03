# 门诊查询模型·66 个待中文化字段清单（issue-35 数据侧，供知识口径审阅）

由 live 语义注册表（mzjyxx 对象, name 纯英文的 66 字段）直接导出，含数据侧当前权威元数据。
约定：金额实付/记账口径、枚举档位，凡注册表未登记一律标"需SQL字典"，数据侧不猜档位。已治理的 T_State/T_FeeAll/T_FundPay/T_SelfPayAll 不在此列。


## 前缀 Count（1 字段）
- `Count` 类型=Count 聚合=sum 值域=- 来源=o_FeeItem.Count
    定义: 门诊费用明细字段：Count

## 前缀 FeeItem（2 字段）
- `FeeItem_SelfPay2` 类型=Amount 聚合=sum 值域=- 来源=o_FeeItem.SelfPay2
    定义: 门诊费用明细字段：SelfPay2
- `FeeItem_State` 类型=Enum 聚合=max 值域=- 来源=o_FeeItem.State
    定义: 门诊费用明细字段：State

## 前缀 FeeType（1 字段）
- `FeeType` 类型=Enum 聚合=max 值域=- 来源=o_FeeItem.FeeType
    定义: 门诊费用明细字段：FeeType

## 前缀 ItemCode（1 字段）
- `ItemCode` 类型=String 聚合=max 值域=- 来源=o_FeeItem.ItemCode
    定义: 门诊费用明细字段：ItemCode

## 前缀 ItemType（1 字段）
- `ItemType` 类型=Enum 聚合=max 值域=- 来源=o_FeeItem.ItemType
    定义: 门诊费用明细字段：ItemType

## 前缀 NP（1 字段）
- `NP_Settle_State` 类型=Enum 聚合=max 值域=- 来源=o_Trade.NP_Settle_State
    定义: 门诊交易字段：NP_Settle_State

## 前缀 NT（8 字段）
- `NT_AgencySumPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.NT_AgencySumPay
    定义: 门诊交易字段：NT_AgencySumPay
- `NT_AllSelfPayFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.NT_AllSelfPayFlag
    定义: 门诊交易字段：NT_AllSelfPayFlag
- `NT_BasicPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.NT_BasicPay
    定义: 门诊交易字段：NT_BasicPay
- `NT_CivilPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.NT_CivilPay
    定义: 门诊交易字段：NT_CivilPay
- `NT_OtherPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.NT_OtherPay
    定义: 门诊交易字段：NT_OtherPay
- `NT_OUT2_PRICE` 类型=Amount 聚合=max 值域=- 来源=o_Trade.NT_OUT2_PRICE
    定义: 门诊交易字段：NT_OUT2_PRICE
- `NT_OUT2_SCALE` 类型=Ratio 聚合=max 值域=- 来源=o_Trade.NT_OUT2_SCALE
    定义: 门诊交易字段：NT_OUT2_SCALE
- `NT_ReTradeFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.NT_ReTradeFlag
    定义: 门诊交易字段：NT_ReTradeFlag

## 前缀 P（5 字段）
- `P_CivilFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.P_CivilFlag
    定义: 门诊交易字段：P_CivilFlag
- `P_CivilType` 类型=Enum 聚合=max 值域=- 来源=o_Trade.P_CivilType
    定义: 门诊交易字段：P_CivilType
- `P_HospFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.P_HospFlag
    定义: 门诊交易字段：P_HospFlag
- `P_Official` 类型=Enum 聚合=max 值域=- 来源=o_Trade.P_Official
    定义: 门诊交易字段：P_Official
- `P_retirementflag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.P_retirementflag
    定义: 门诊交易字段：P_retirementflag

## 前缀 PN（7 字段）
- `PN_ChronicCode` 类型=String 聚合=max 值域=- 来源=o_Trade.PN_ChronicCode
    定义: 门诊交易字段：PN_ChronicCode
- `PN_ChronicFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.PN_ChronicFlag
    定义: 门诊交易字段：PN_ChronicFlag
- `PN_IsChronicHosp` 类型=Enum 聚合=max 值域=- 来源=o_Trade.PN_IsChronicHosp
    定义: 门诊交易字段：PN_IsChronicHosp
- `PN_NationFundType` 类型=Enum 聚合=max 值域=NATIONAL_FUND_TYPE 来源=o_Trade.PN_NationFundType
    定义: 门诊交易字段：PN_NationFundType
- `PN_NoRightReason` 类型=Enum 聚合=max 值域=- 来源=o_Trade.PN_NoRightReason
    定义: 门诊交易字段：PN_NoRightReason
- `PN_OutTransaction` 类型=Enum 聚合=max 值域=- 来源=o_Trade.PN_OutTransaction
    定义: 门诊交易字段：PN_OutTransaction
- `PN_PersonCount` 类型=Amount 聚合=max 值域=- 来源=o_Trade.PN_PersonCount
    定义: 门诊交易字段：PN_PersonCount

## 前缀 RETIRE（1 字段）
- `RETIRE_OFFICER_FLAG` 类型=Enum 聚合=max 值域=- 来源=o_Trade.RETIRE_OFFICER_FLAG
    定义: 门诊交易字段：RETIRE_OFFICER_FLAG

## 前缀 SETL（1 字段）
- `SETL_DATE` 类型=Date 聚合=max 值域=- 来源=o_Trade.SETL_DATE
    定义: 门诊交易字段：SETL_DATE

## 前缀 StandardCode（1 字段）
- `StandardCode` 类型=String 聚合=max 值域=- 来源=o_FeeItem.StandardCode
    定义: 门诊费用明细字段：StandardCode

## 前缀 T（11 字段）
- `T_BeyondBig` 类型=Amount 聚合=max 值域=- 来源=o_Trade.T_BeyondBig
    定义: 门诊交易字段：T_BeyondBig
- `T_CompHospFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.T_CompHospFlag
    定义: 门诊交易字段：T_CompHospFlag
- `T_DiagType` 类型=Enum 聚合=max 值域=- 来源=o_Trade.T_DiagType
    定义: 门诊交易字段：T_DiagType
- `T_GFBelongFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.T_GFBelongFlag
    定义: 门诊交易字段：T_GFBelongFlag
- `T_HasRefundmented` 类型=Enum 聚合=max 值域=- 来源=o_Trade.T_HasRefundmented
    定义: 门诊交易字段：T_HasRefundmented
- `T_OraginalTradeDate` 类型=Date 聚合=max 值域=- 来源=o_Trade.T_OraginalTradeDate
    定义: 门诊交易字段：T_OraginalTradeDate
- `T_OraginalTradeNo` 类型=String 聚合=max 值域=- 来源=o_Trade.T_OraginalTradeNo
    定义: 门诊交易字段：T_OraginalTradeNo
- `T_PartialReturnFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.T_PartialReturnFlag
    定义: 门诊交易字段：T_PartialReturnFlag
- `T_PersonCountAfter` 类型=Amount 聚合=max 值域=- 来源=o_Trade.T_PersonCountAfter
    定义: 门诊交易字段：T_PersonCountAfter
- `T_pneno` 类型=String 聚合=max 值域=- 来源=o_Trade.T_pneno
    定义: 门诊交易字段：T_pneno
- `T_SpSetlFlag` 类型=Enum 聚合=max 值域=- 来源=o_Trade.T_SpSetlFlag
    定义: 门诊交易字段：T_SpSetlFlag

## 前缀 TA（12 字段）
- `TA_BeyondFeeIn` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_BeyondFeeIn
    定义: 门诊交易字段：TA_BeyondFeeIn
- `TA_BigillComm` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_BigillComm
    定义: 门诊交易字段：TA_BigillComm
- `TA_BigillPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_BigillPay
    定义: 门诊交易字段：TA_BigillPay
- `TA_BigPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_BigPay
    定义: 门诊交易字段：TA_BigPay
- `TA_BigPayL1` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_BigPayL1
    定义: 门诊交易字段：TA_BigPayL1
- `TA_CivilComm` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_CivilComm
    定义: 门诊交易字段：TA_CivilComm
- `TA_CivilPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_CivilPay
    定义: 门诊交易字段：TA_CivilPay
- `TA_FeeAfterBig` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_FeeAfterBig
    定义: 门诊交易字段：TA_FeeAfterBig
- `TA_FeeAfterBigL1` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_FeeAfterBigL1
    定义: 门诊交易字段：TA_FeeAfterBigL1
- `TA_FeeIn` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_FeeIn
    定义: 门诊交易字段：TA_FeeIn
- `TA_FeeInL1` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TA_FeeInL1
    定义: 门诊交易字段：TA_FeeInL1
- `TA_MZTimes` 类型=Count 聚合=max 值域=- 来源=o_Trade.TA_MZTimes
    定义: 门诊交易字段：TA_MZTimes

## 前缀 TB（12 字段）
- `TB_BeyondFeeIn` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_BeyondFeeIn
    定义: 门诊交易字段：TB_BeyondFeeIn
- `TB_BigillComm` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_BigillComm
    定义: 门诊交易字段：TB_BigillComm
- `TB_BigillPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_BigillPay
    定义: 门诊交易字段：TB_BigillPay
- `TB_BigPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_BigPay
    定义: 门诊交易字段：TB_BigPay
- `TB_BigPayL1` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_BigPayL1
    定义: 门诊交易字段：TB_BigPayL1
- `TB_CivilComm` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_CivilComm
    定义: 门诊交易字段：TB_CivilComm
- `TB_CivilPay` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_CivilPay
    定义: 门诊交易字段：TB_CivilPay
- `TB_FeeAfterBig` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_FeeAfterBig
    定义: 门诊交易字段：TB_FeeAfterBig
- `TB_FeeAfterBigL1` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_FeeAfterBigL1
    定义: 门诊交易字段：TB_FeeAfterBigL1
- `TB_FeeIn` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_FeeIn
    定义: 门诊交易字段：TB_FeeIn
- `TB_FeeInL1` 类型=Amount 聚合=max 值域=- 来源=o_Trade.TB_FeeInL1
    定义: 门诊交易字段：TB_FeeInL1
- `TB_MZTimes` 类型=Count 聚合=max 值域=- 来源=o_Trade.TB_MZTimes
    定义: 门诊交易字段：TB_MZTimes

## 前缀 UnitPrice（1 字段）
- `UnitPrice` 类型=Amount 聚合=max 值域=- 来源=o_FeeItem.UnitPrice
    定义: 门诊费用明细字段：UnitPrice

## 待数据侧补枚举/口径（需 SQL Server 门诊源字典，不猜测）
- Enum 需拉字典档位(23): FeeItem_State, FeeType, ItemType, NP_Settle_State, NT_AllSelfPayFlag, NT_ReTradeFlag, P_CivilFlag, P_CivilType, P_HospFlag, PN_ChronicFlag, PN_IsChronicHosp, PN_NationFundType, PN_NoRightReason, PN_OutTransaction, P_Official, P_retirementflag, RETIRE_OFFICER_FLAG, T_CompHospFlag, T_DiagType, T_GFBelongFlag, T_HasRefundmented, T_PartialReturnFlag, T_SpSetlFlag

- Amount(32): 金额字段需标注实付/记账口径来源 → FeeItem_SelfPay2, NT_AgencySumPay, NT_BasicPay, NT_CivilPay, NT_OtherPay, NT_OUT2_PRICE, PN_PersonCount, TA_BeyondFeeIn, TA_BigillComm, TA_BigillPay, TA_BigPay, TA_BigPayL1, TA_CivilComm, TA_CivilPay, TA_FeeAfterBig, TA_FeeAfterBigL1, TA_FeeIn, TA_FeeInL1, TB_BeyondFeeIn, TB_BigillComm, TB_BigillPay, TB_BigPay, TB_BigPayL1, TB_CivilComm, TB_CivilPay, T_BeyondBig, TB_FeeAfterBig, TB_FeeAfterBigL1, TB_FeeIn, TB_FeeInL1, T_PersonCountAfter, UnitPrice