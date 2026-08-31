SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.o_Trade', N'U') IS NULL
   OR OBJECT_ID(N'dbo.o_FeeItem', N'U') IS NULL
   OR OBJECT_ID(N'dbo.o_Diagnose', N'U') IS NULL
BEGIN
    RAISERROR(N'Required outpatient source tables are missing.', 16, 1);
    RETURN;
END;

IF (SELECT is_cdc_enabled FROM sys.databases WHERE name = DB_NAME()) = 0
    EXEC sys.sp_cdc_enable_db;

IF NOT EXISTS (
    SELECT 1 FROM cdc.change_tables WHERE capture_instance = N'dbo_o_Trade'
)
    EXEC sys.sp_cdc_enable_table
        @source_schema = N'dbo',
        @source_name = N'o_Trade',
        @capture_instance = N'dbo_o_Trade',
        @role_name = N'outpatient_cdc_reader',
        @supports_net_changes = 0,
        @captured_column_list = N'T_SetTid,T_TradeNo,T_TradeDate,T_State,T_HasRefundmented,T_PartialReturnFlag,T_OraginalTradeNo,T_OraginalTradeDate,NP_Settle_State,SETL_DATE,NT_ReTradeFlag,T_DiagType,T_FeeNo,P_FundType,PN_PersonType,T_CureType,P_JCLevel,P_HospFlag,PN_OutTransaction,PN_NationFundType,PN_ChronicFlag,PN_ChronicCode,PN_IsChronicHosp,P_Official,P_retirementflag,P_CivilFlag,P_CivilType,RETIRE_OFFICER_FLAG,T_GFBelongFlag,T_CompHospFlag,T_SpSetlFlag,T_pneno,NT_AllSelfPayFlag,PN_NoRightReason,T_FeeAll,T_FeeIn,T_FeeOut,T_FirstPay,T_SelfPay1,T_SelfPay2,T_SelfPayAll,T_BigPay,T_BigSelfPay,T_BeyondBig,T_FundPay,T_PersonCountPay,T_CashPay,PN_PersonCount,T_PersonCountAfter,T_BCPay,T_JCPay,T_OfficalPay,T_BigillPay,NT_BasicPay,NT_CivilPay,NT_OtherPay,NT_AgencySumPay,RETIRE_OFFICER_PAY,NT_OUT2_SCALE,NT_OUT2_PRICE,TB_FeeIn,TA_FeeIn,TB_BigPay,TA_BigPay,TB_FeeAfterBig,TA_FeeAfterBig,TB_MZTimes,TA_MZTimes,TB_BeyondFeeIn,TA_BeyondFeeIn,TB_BigillComm,TA_BigillComm,TB_BigillPay,TA_BigillPay,TB_CivilComm,TA_CivilComm,TB_CivilPay,TA_CivilPay,TB_FeeInL1,TA_FeeInL1,TB_BigPayL1,TA_BigPayL1,TB_FeeAfterBigL1,TA_FeeAfterBigL1,PN_InsuredAreaCode,T_HospCode,T_HospCodeA';

IF NOT EXISTS (
    SELECT 1 FROM cdc.change_tables WHERE capture_instance = N'dbo_o_FeeItem'
)
    EXEC sys.sp_cdc_enable_table
        @source_schema = N'dbo',
        @source_name = N'o_FeeItem',
        @capture_instance = N'dbo_o_FeeItem',
        @role_name = N'outpatient_cdc_reader',
        @supports_net_changes = 0,
        @captured_column_list = N'T_TradeNo,ItemId,ItemNo,ItemCode,StandardCode,ItemName,ItemType,FeeType,F_LEVEL,Count,UnitPrice,Fee,FeeIn,FeeOut,SelfPay2,FEE_SP_SCALE,FEE_MEDIC_L,MEDIC_L,SPEDRUG_FLAG,State';

IF NOT EXISTS (
    SELECT 1 FROM cdc.change_tables WHERE capture_instance = N'dbo_o_Diagnose'
)
    EXEC sys.sp_cdc_enable_table
        @source_schema = N'dbo',
        @source_name = N'o_Diagnose',
        @capture_instance = N'dbo_o_Diagnose',
        @role_name = N'outpatient_cdc_reader',
        @supports_net_changes = 0,
        @captured_column_list = N'T_TradeNo,DiagnoseNo,RecipeNo,RecipeDate,DiagnoseName,DiagnoseCode,SectionCode,Sectionname,HISSectionName,DiagnoseType';

EXEC sys.sp_cdc_change_job
    @job_type = N'cleanup',
    @retention = 4320;

SELECT name, is_cdc_enabled
FROM sys.databases
WHERE name = DB_NAME();

SELECT
    ct.capture_instance,
    SCHEMA_NAME(source_table.schema_id) AS source_schema,
    source_table.name AS source_table,
    sys.fn_varbintohexstr(ct.start_lsn) AS start_lsn
FROM cdc.change_tables AS ct
JOIN sys.tables AS source_table ON source_table.object_id = ct.source_object_id
WHERE ct.capture_instance IN (N'dbo_o_Trade', N'dbo_o_FeeItem', N'dbo_o_Diagnose')
ORDER BY ct.capture_instance;

SELECT
    ct.capture_instance,
    captured.column_ordinal,
    captured.column_name
FROM cdc.change_tables AS ct
JOIN cdc.captured_columns AS captured ON captured.object_id = ct.object_id
WHERE ct.capture_instance IN (N'dbo_o_Trade', N'dbo_o_FeeItem', N'dbo_o_Diagnose')
ORDER BY ct.capture_instance, captured.column_ordinal;

SELECT job_type, retention
FROM msdb.dbo.cdc_jobs
WHERE database_id = DB_ID()
ORDER BY job_type;
