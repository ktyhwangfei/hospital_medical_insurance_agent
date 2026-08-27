# 门诊数据契约核验记录（P0 Task 1–4）

## 环境

| 项目 | 核验结果 |
|---|---|
| 执行日期 | 2026-08-27（Asia/Shanghai） |
| 数据源安全别名 | bjybdb |
| SQL Server 版本 | 16.0.4255.1 / RTM / Developer Edition (64-bit) |
| ODBC 驱动 | SQL Server |
| 发现任务 ID | outpatient_p0_3eceb0a3067a485285169a0c |
| 发现任务缓存命中时间 | 2026-08-27 14:15:28.656 +08:00 至 14:15:29.035 +08:00；不是缓存快照生成时间 |
| 本次操作总时间 | 2026-08-27 14:15:20 +08:00 至 14:15:29 +08:00 |
| 统计区间 | 既有检查点中的缓存统计；快照未记录业务日期过滤口径，业务数据起止时间待后续任务验证 |
| 执行主体指纹 | SHA-256 38F144F8D609E1F6CFA0E3B2E4225EF783A0B313A98262F71FC0862BF97ACD70（不记录原登录名） |
| 权限证据执行时间 | 2026-08-27 06:34:58.5512216Z（2026-08-27 14:34:58.5512216 +08:00） |
| 数据库级权限位 | SELECT、INSERT、UPDATE、DELETE 均为已授予 |
| 两张候选表权限位 | SELECT、INSERT、UPDATE、DELETE 均为已授予 |
| 实际执行边界 | SQL Server 仅执行 SELECT 与元数据查询，未执行任何写语句 |

脱敏权限查询的对象范围固定为当前数据库、dbo.o_Trade、dbo.o_FeeItem，四类对象权限分别取 SELECT、INSERT、UPDATE、DELETE；主体只保留登录名的 SHA-256 指纹：

    SELECT
      CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(nvarchar(128), SUSER_SNAME())), 2)
        AS principal_fingerprint_sha256,
      CONVERT(varchar(40), SYSDATETIMEOFFSET(), 127) AS executed_at,
      scope_name, can_select, can_insert, can_update, can_delete
    FROM (VALUES
      ('DATABASE',
       HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'SELECT'),
       HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'INSERT'),
       HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'UPDATE'),
       HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'DELETE')),
      ('dbo.o_Trade',
       HAS_PERMS_BY_NAME('dbo.o_Trade', 'OBJECT', 'SELECT'),
       HAS_PERMS_BY_NAME('dbo.o_Trade', 'OBJECT', 'INSERT'),
       HAS_PERMS_BY_NAME('dbo.o_Trade', 'OBJECT', 'UPDATE'),
       HAS_PERMS_BY_NAME('dbo.o_Trade', 'OBJECT', 'DELETE')),
      ('dbo.o_FeeItem',
       HAS_PERMS_BY_NAME('dbo.o_FeeItem', 'OBJECT', 'SELECT'),
       HAS_PERMS_BY_NAME('dbo.o_FeeItem', 'OBJECT', 'INSERT'),
       HAS_PERMS_BY_NAME('dbo.o_FeeItem', 'OBJECT', 'UPDATE'),
       HAS_PERMS_BY_NAME('dbo.o_FeeItem', 'OBJECT', 'DELETE'))
    ) p(scope_name, can_select, can_insert, can_update, can_delete);

| 权限对象 | SELECT | INSERT | UPDATE | DELETE |
|---|:---:|:---:|:---:|:---:|
| 当前数据库 | 1 | 1 | 1 | 1 |
| dbo.o_Trade | 1 | 1 | 1 | 1 |
| dbo.o_FeeItem | 1 | 1 | 1 | 1 |

权限查询不记录账号名、数据库名、主机、连接串或凭据。该指纹对应主体的权限超出“批准的只读通道”最小权限基线，见“阻断项”。

[来源: SQL Server SERVERPROPERTY 与 HAS_PERMS_BY_NAME 元数据查询；发现任务 outpatient_p0_3eceb0a3067a485285169a0c]

## 源表

本次发现请求将 schema 固定为 dbo，表白名单固定为 o_Trade、o_FeeItem，sample_limit 固定为 5；没有扫描其他业务表。

| 源表 | 候选角色 | 发现状态 | 缓存行数 | 字段数 | 映射/未映射 | 缓存 DDL 时间 | 缓存质量分（均值/最小/最大） | 缓存平均非空率 | 检查点生成时间 | 来源任务 ID |
|---|---|---|---:|---:|---:|---|---:|---:|---|---|
| dbo.o_Trade | 交易主表（待业务确认） | completed，cached=true | 592 | 195 | 86 / 109 | 2026-07-06 02:25:25（源时区未暴露） | 60.07 / 10.00 / 70.00 | 81.96% | 2026-07-17 17:07:35.083662 +08:00 | 未知；检查点未存 task_id |
| dbo.o_FeeItem | 费用明细表（待业务确认） | completed，cached=true | 2,139 | 41 | 18 / 23 | 2021-09-24 12:23:01.663（源时区未暴露） | 59.02 / 50.00 / 60.00 | 100.00% | 2026-07-17 17:07:33.647508 +08:00 | 未知；检查点未存 task_id |
| 合计 | — | completed | 2,731 | 236 | 104 / 132 | — | — | — | — | — |

cached=true 的证明范围必须收窄：本次实时读取 INFORMATION_SCHEMA 后，当前列哈希与检查点哈希一致；该哈希只覆盖 schema/table、列名、DATA_TYPE、CHARACTER_MAXIMUM_LENGTH、IS_NULLABLE，不能据此概括完整物理定义一致。它不覆盖 NUMERIC_PRECISION、NUMERIC_SCALE。金额字段的精度与标度仅以本次独立执行的 INFORMATION_SCHEMA.COLUMNS 元数据 SELECT 为准。缓存行数、质量分、非空率和 DDL 时间不能作为“2026-08-27 重新全量画像”的证据。

[来源: src/runtime/discovery/sqlserver_source.py 的 tables 白名单与检查点逻辑；发现任务结果及表级检查点]

## 字段

已通过以下批准的元数据 SELECT 确认 236 个字段的物理定义；证据仅包含字段定义，不包含患者样例行、字段样例值或任何业务标识值。

    SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,DATA_TYPE,IS_NULLABLE,CHARACTER_MAXIMUM_LENGTH,NUMERIC_PRECISION,NUMERIC_SCALE,ORDINAL_POSITION
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME IN ('o_Trade','o_FeeItem')
    ORDER BY TABLE_NAME,ORDINAL_POSITION;

### dbo.o_FeeItem（41 字段）

| 序号 | 字段 | 物理类型 | 可空 |
|---:|---|---|:---:|
| 1 | T_TradeNo | nvarchar(22) | NO |
| 2 | ItemId | int | NO |
| 3 | ItemNo | int | NO |
| 4 | RecipeNo | nvarchar(20) | NO |
| 5 | HisCode | nvarchar(40) | NO |
| 6 | ItemCode | nvarchar(40) | NO |
| 7 | ItemName | nvarchar(100) | NO |
| 8 | ItemType | int | NO |
| 9 | UnitPrice | decimal(10,4) | NO |
| 10 | Count | numeric(10,2) | NO |
| 11 | Fee | decimal(10,4) | NO |
| 12 | FeeIn | decimal(10,4) | NO |
| 13 | FeeOut | decimal(10,4) | NO |
| 14 | SelfPay2 | decimal(10,4) | NO |
| 15 | PreferentialScale | int | NO |
| 16 | PreferentialFee | decimal(10,4) | NO |
| 17 | FeeType | nvarchar(4) | NO |
| 18 | State | int | NO |
| 19 | Dose | nvarchar(6) | NO |
| 20 | Specification | nvarchar(40) | YES |
| 21 | Unit | nvarchar(20) | YES |
| 22 | HowToUse | nvarchar(3) | YES |
| 23 | Dosage | nvarchar(20) | YES |
| 24 | packaging | nvarchar(10) | YES |
| 25 | MinPackage | nvarchar(10) | YES |
| 26 | Conversion | nvarchar(10) | YES |
| 27 | Days | decimal(8,0) | YES |
| 28 | HisName | nvarchar(100) | NO |
| 29 | ApprovalNumber | nvarchar(20) | YES |
| 30 | DecoctionOem | nvarchar(50) | YES |
| 31 | UsageMethod | nvarchar(20) | YES |
| 32 | DecoctionClass | nvarchar(1) | YES |
| 33 | DecoctionMiniPack | nvarchar(1) | YES |
| 34 | F_LEVEL | nvarchar(3) | YES |
| 35 | SP_SCALE | decimal(18,4) | YES |
| 36 | MEDIC_L | decimal(5,4) | YES |
| 37 | FEE_SP_SCALE | decimal(18,4) | YES |
| 38 | FEE_MEDIC_L | decimal(18,4) | YES |
| 39 | PACK_FLAG | nvarchar(1) | YES |
| 40 | StandardCode | varchar(40) | YES |
| 41 | SPEDRUG_FLAG | varchar(3) | YES |

### dbo.o_Trade（195 字段）

| 序号 | 字段 | 物理类型 | 可空 |
|---:|---|---|:---:|
| 1 | T_TradeNo | nvarchar(22) | NO |
| 2 | T_OraginalTradeNo | nvarchar(22) | YES |
| 3 | T_HospCode | nvarchar(10) | NO |
| 4 | T_HospCodeA | nvarchar(10) | NO |
| 5 | T_HospName | nvarchar(50) | YES |
| 6 | T_FeeNo | nvarchar(20) | YES |
| 7 | T_CureType | int | NO |
| 8 | T_IllType | int | NO |
| 9 | T_TradeDate | datetime | NO |
| 10 | T_PosNo | nvarchar(20) | YES |
| 11 | T_FeeAll | decimal(10,2) | NO |
| 12 | T_FeeIn | decimal(10,2) | NO |
| 13 | T_FeeOut | decimal(10,2) | NO |
| 14 | T_BigPay | decimal(10,2) | NO |
| 15 | T_BCPay | decimal(10,2) | NO |
| 16 | T_JCPay | decimal(10,2) | NO |
| 17 | T_SelfPay1 | decimal(10,2) | NO |
| 18 | T_FirstPay | decimal(10,2) | NO |
| 19 | T_BeyondBig | decimal(10,2) | NO |
| 20 | T_SelfPay2 | decimal(10,2) | NO |
| 21 | T_BigSelfPay | decimal(10,2) | NO |
| 22 | T_FundPay | decimal(10,2) | NO |
| 23 | T_PersonCountPay | decimal(10,2) | NO |
| 24 | T_PersonCountAfter | decimal(10,2) | NO |
| 25 | T_CashPay | decimal(10,2) | NO |
| 26 | T_SelfPayAll | decimal(10,2) | NO |
| 27 | T_Version1 | nvarchar(20) | NO |
| 28 | T_Version2 | nvarchar(22) | NO |
| 29 | P_ICNo | nvarchar(12) | NO |
| 30 | P_Name | nvarchar(50) | NO |
| 31 | P_IDNo | nvarchar(50) | YES |
| 32 | P_Sex | int | NO |
| 33 | P_Official | int | NO |
| 34 | P_OfficialCode | nvarchar(50) | YES |
| 35 | P_Birthday | datetime | NO |
| 36 | P_FundType | int | NO |
| 37 | P_FromHosp | nvarchar(8) | YES |
| 38 | P_FromHospDate | datetime | YES |
| 39 | P_SpecHospCode | nvarchar(50) | YES |
| 40 | P_IsYT | int | NO |
| 41 | P_JCLevel | int | NO |
| 42 | P_HospFlag | int | NO |
| 43 | PN_ChronicCode | nvarchar(50) | NO |
| 44 | PN_PersonType | int | NO |
| 45 | PN_HospState | int | NO |
| 46 | PN_IsChronicHosp | nvarchar(2) | NO |
| 47 | PN_ChronicFlag | nvarchar(2) | NO |
| 48 | PN_IsInRedList | int | NO |
| 49 | PN_RedListState | int | NO |
| 50 | PN_PersonCount | decimal(10,2) | NO |
| 51 | TB_Year | int | NO |
| 52 | TB_MZTimes | int | NO |
| 53 | TB_FeeIn | decimal(10,2) | NO |
| 54 | TB_BigPay | decimal(10,2) | NO |
| 55 | TB_FeeAfterBig | decimal(10,2) | NO |
| 56 | TB_GYTimes | int | NO |
| 57 | TA_Year | int | NO |
| 58 | TA_MZTimes | int | NO |
| 59 | TA_FeeIn | decimal(10,2) | NO |
| 60 | TA_BigPay | decimal(10,2) | NO |
| 61 | TA_FeeAfterBig | decimal(10,2) | NO |
| 62 | TA_GYTimes | int | NO |
| 63 | M_medicine | decimal(10,2) | NO |
| 64 | M_tmedicine | decimal(10,2) | NO |
| 65 | M_therb | decimal(10,2) | NO |
| 66 | M_examine | decimal(10,2) | NO |
| 67 | M_ct | decimal(10,2) | NO |
| 68 | M_mri | decimal(10,2) | NO |
| 69 | M_ultrasonic | decimal(10,2) | NO |
| 70 | M_oxygen | decimal(10,2) | NO |
| 71 | M_operation | decimal(10,2) | NO |
| 72 | M_treatment | decimal(10,2) | NO |
| 73 | M_xray | decimal(10,2) | NO |
| 74 | M_labexam | decimal(10,2) | NO |
| 75 | M_bloodt | decimal(10,2) | NO |
| 76 | M_orthodontics | decimal(10,2) | NO |
| 77 | M_prosthesis | decimal(10,2) | NO |
| 78 | M_psychometry | decimal(10,2) | NO |
| 79 | M_forensicexpertise | decimal(10,2) | NO |
| 80 | M_material | decimal(10,2) | NO |
| 81 | M_other | decimal(10,2) | NO |
| 82 | T_IsCapinfo | int | NO |
| 83 | T_State | int | NO |
| 84 | T_HasRefundmented | int | NO |
| 85 | T_CertID | nvarchar(150) | YES |
| 86 | T_SignInfo | nvarchar(256) | YES |
| 87 | T_RedListVersion | nvarchar(20) | YES |
| 88 | T_PlainText | nvarchar(250) | YES |
| 89 | P_CardNo | nvarchar(12) | YES |
| 90 | TT_TradeNo | char(12) | NO |
| 91 | T_Operator | nvarchar(20) | YES |
| 92 | T_FundPayLeft | decimal(10,2) | YES |
| 93 | T_OfficalPay | numeric(12,2) | YES |
| 94 | T_SignVersion | nvarchar(20) | YES |
| 95 | CheckDetailFlag | nvarchar(1) | YES |
| 96 | M_consultation | decimal(10,2) | YES |
| 97 | M_registration | decimal(10,2) | YES |
| 98 | M_feeClassType | int | YES |
| 99 | T_PerAccountDiagID | nvarchar(32) | YES |
| 100 | T_RePerAccountDiagID | nvarchar(32) | YES |
| 101 | PN_DeductionFlag | nvarchar(1) | YES |
| 102 | PN_NoRightReason | nvarchar(20) | YES |
| 103 | T_PerAccountDiagDateTime | datetime | YES |
| 104 | T_VerifyBlancePasswordId | nvarchar(1) | YES |
| 105 | TB_FeeInL1 | decimal(10,2) | YES |
| 106 | TB_BigPayL1 | decimal(10,2) | YES |
| 107 | TB_FeeAfterBigL1 | decimal(10,2) | YES |
| 108 | TA_FeeInL1 | decimal(10,2) | YES |
| 109 | TA_BigPayL1 | decimal(10,2) | YES |
| 110 | TA_FeeAfterBigL1 | decimal(10,2) | YES |
| 111 | TR_OraginalTradeNo | nvarchar(22) | YES |
| 112 | TR_RefundmentTradeNo | nvarchar(22) | YES |
| 113 | T_OraginalTradeDate | datetime | YES |
| 114 | NT_AllSelfPayFlag | varchar(3) | YES |
| 115 | NT_QG_DIAG_ID | varchar(30) | YES |
| 116 | NT_BalanceAccountFlag | varchar(3) | YES |
| 117 | NT_ReTradeFlag | varchar(3) | YES |
| 118 | PN_InsuredAreaCode | varchar(6) | YES |
| 119 | PN_NationFundType | varchar(6) | YES |
| 120 | NT_OUT2_SCALE | numeric(16,2) | YES |
| 121 | NT_OUT2_PRICE | numeric(16,2) | YES |
| 122 | NT_AgencySumPay | numeric(16,2) | YES |
| 123 | NT_BasicPay | numeric(16,2) | YES |
| 124 | NT_CivilPay | numeric(16,2) | YES |
| 125 | NT_OtherPay | numeric(16,2) | YES |
| 126 | PN_OutTransaction | nvarchar(3) | YES |
| 127 | T_DiagType | nvarchar(1) | YES |
| 128 | P_MediumType | nvarchar(3) | YES |
| 129 | P_IDType | nvarchar(3) | YES |
| 130 | P_TradeMode | nvarchar(1) | YES |
| 131 | T_PartialReturnFlag | nvarchar(1) | YES |
| 132 | T_HisInterfaceVersion | nvarchar(3) | YES |
| 133 | T_BusinessNo | nvarchar(20) | YES |
| 134 | P_EcToken | nvarchar(64) | YES |
| 135 | P_FaceTrace | nvarchar(64) | YES |
| 136 | P_FaceBizNo | nvarchar(64) | YES |
| 137 | P_FaceOutBizNo | nvarchar(64) | YES |
| 138 | T_ConfirmTime | datetime | YES |
| 139 | T_IllCode | varchar(10) | YES |
| 140 | FAMILY_DOC_FLAG | varchar(1) | YES |
| 141 | NP_Settle_State | varchar(1) | YES |
| 142 | P_Stage | varchar(1) | YES |
| 143 | NP_PMCode | varchar(30) | YES |
| 144 | T_SendMsgID | varchar(30) | YES |
| 145 | T_SetTid | varchar(30) | YES |
| 146 | T_MdtrtID | varchar(30) | YES |
| 147 | T_PwdStatus | nvarchar(1) | YES |
| 148 | T_SecretFreeAmt | decimal(10,2) | YES |
| 149 | T_HadDealFlag | nvarchar(1) | YES |
| 150 | T_HisOpt | char(10) | YES |
| 151 | T_HospConfig | char(10) | YES |
| 152 | T_PatientOpt | char(10) | YES |
| 153 | SETL_DATE | datetime | YES |
| 154 | T_HadDealTime | datetime | YES |
| 155 | TB_BigillComm | decimal(10,2) | YES |
| 156 | TB_BigillPay | decimal(10,2) | YES |
| 157 | TB_CivilComm | decimal(10,2) | YES |
| 158 | TB_CivilPay | decimal(10,2) | YES |
| 159 | TA_BigillComm | decimal(10,2) | YES |
| 160 | TA_BigillPay | decimal(10,2) | YES |
| 161 | TA_CivilComm | decimal(10,2) | YES |
| 162 | TA_CivilPay | decimal(10,2) | YES |
| 163 | T_BigillPay | decimal(10,2) | YES |
| 164 | P_CivilFlag | varchar(10) | YES |
| 165 | P_CivilType | varchar(10) | YES |
| 166 | RETIRE_OFFICER_FLAG | varchar(1) | YES |
| 167 | RETIRE_OFFICER_PAY | decimal(10,2) | YES |
| 168 | TRUM_FLAG | varchar(1) | YES |
| 169 | REL_TTP_FLAG | varchar(1) | YES |
| 170 | MDTRT_GRP_TYPE | varchar(6) | YES |
| 171 | T_SpSetlFlag | varchar(3) | YES |
| 172 | Fund_DET_Flag | varchar(1) | YES |
| 173 | TB_BeyondFeeIn | decimal(10,2) | YES |
| 174 | TA_BeyondFeeIn | decimal(10,2) | YES |
| 175 | TB_BeyondCivilPay | decimal(10,2) | YES |
| 176 | TA_BeyondCivilPay | decimal(10,2) | YES |
| 177 | T_ApproveIllCode | varchar(50) | YES |
| 178 | T_pneflag | int | YES |
| 179 | T_pneno | varchar(50) | YES |
| 180 | P_flxempeflag | int | YES |
| 181 | T_wltpay | varchar(50) | YES |
| 182 | T_wltno | varchar(50) | YES |
| 183 | T_wltsettflag | varchar(50) | YES |
| 184 | T_wltuseflag | varchar(50) | YES |
| 185 | T_GFBelongFlag | varchar(50) | YES |
| 186 | T_CompHospFlag | varchar(50) | YES |
| 187 | T_Backpayflag | varchar(50) | YES |
| 188 | P_diedate | varchar(50) | YES |
| 189 | P_diedate_datasouc | varchar(50) | YES |
| 190 | P_dietrtchk_flag | varchar(50) | YES |
| 191 | P_retirementflag | varchar(50) | YES |
| 192 | T_SyBeginDate | varchar(50) | YES |
| 193 | P_fixedfamilycode | varchar(50) | YES |
| 194 | P_fixedfamilystart | varchar(50) | YES |
| 195 | P_fixedfamilyend | varchar(50) | YES |

字段名中存在姓名、身份证件、卡号、电子凭证/人脸追踪等高敏候选字段。此处只登记物理定义；任何后续业务读取必须先建立字段白名单并经过 security/desensitization，不得以“已发现”为由直接暴露。

[来源: 本次 INFORMATION_SCHEMA.COLUMNS 元数据查询]

## 键与关系

以下仅为初步 catalog 元数据观察，不代表主从数据质量已经验证。

| 对象 | 初步元数据观察 | 状态 |
|---|---|---|
| dbo.o_Trade | 主键 PK_o_Trade：T_TradeNo；唯一索引 UNIQ_TT_TradeNo：TT_TradeNo | 两索引 is_disabled=false |
| dbo.o_Trade | 复合普通索引 IX_QUERY：T_TradeDate、T_State、T_HasRefundmented、T_Operator | is_disabled=false |
| dbo.o_Trade | 普通索引 Sy_Kh：P_ICNo；普通索引 Sy_P_FundType：P_FundType | 两索引 is_disabled=false |
| dbo.o_FeeItem | 复合主键 PK_o_FeeItem_1：T_TradeNo、ItemId | is_disabled=false |
| dbo.o_FeeItem → dbo.o_Trade | 外键 FK_o_FeeItem_o_Trade：T_TradeNo → T_TradeNo | is_disabled=false；is_not_trusted=false |
| dbo.o_Diagnose → dbo.o_Trade | 入向外键 FK_o_Diagnose_o_Trade：T_TradeNo → T_TradeNo；o_Diagnose 不在本次扫描范围 | is_disabled=false；is_not_trusted=false |

可复核的 catalog 查询口径：

    SELECT s.name AS schema_name, t.name AS table_name, i.name AS index_name,
           i.is_primary_key, i.is_unique, i.is_disabled,
           c.name AS column_name, ic.key_ordinal
    FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id=t.schema_id
    JOIN sys.indexes i ON i.object_id=t.object_id AND i.index_id>0
    JOIN sys.index_columns ic
      ON ic.object_id=i.object_id AND ic.index_id=i.index_id AND ic.key_ordinal>0
    JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
    WHERE s.name='dbo' AND t.name IN ('o_Trade','o_FeeItem')
    ORDER BY t.name,i.name,ic.key_ordinal;

    SELECT fk.name AS foreign_key_name,
           OBJECT_SCHEMA_NAME(fk.parent_object_id) AS child_schema,
           OBJECT_NAME(fk.parent_object_id) AS child_table,
           OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS parent_schema,
           OBJECT_NAME(fk.referenced_object_id) AS parent_table,
           fk.is_disabled, fk.is_not_trusted
    FROM sys.foreign_keys fk
    WHERE (OBJECT_SCHEMA_NAME(fk.parent_object_id)='dbo'
           AND OBJECT_NAME(fk.parent_object_id) IN ('o_Trade','o_FeeItem'))
       OR (OBJECT_SCHEMA_NAME(fk.referenced_object_id)='dbo'
           AND OBJECT_NAME(fk.referenced_object_id) IN ('o_Trade','o_FeeItem'))
    ORDER BY fk.name;

主从基数、孤儿记录、退款自关联与重复键的数据验证不属于 Task 1，待验证。

[来源: SQL Server sys.indexes/sys.index_columns/sys.foreign_keys 元数据查询]

### Task 2：交易、明细键和一对多关系

#### 执行证据与失败分类

| 项目 | 结果 |
|---|---|
| 文档级证据批次 ID | `outpatient_p0_t2_20260827_070052Z`；仅用于关联本文 Task 2 的结果表、只读 SQL、执行时间与主体指纹，不是数据库审计日志或外部 run_id |
| 服务器时钟锚点 | 2026-08-27 07:00:52.315；同次 `SYSDATETIMEOFFSET()` 返回 +00:00。该值只描述服务器时钟，不代表 T_TradeDate 的业务时区 |
| 完整区间 | dbo.o_Trade / dbo.o_FeeItem 全表；o_Trade.T_TradeDate 观察范围 2024-03-11 09:28:38.000 至 2026-04-17 10:41:45.000。T_TradeDate 为无时区 datetime，不转换或推断北京时间 |
| 服务器时钟观察窗口 | `[2026-07-28 07:00:52.315, 2026-08-27 07:00:52.315)`，左闭右开；查询观察值为 0。因 T_TradeDate 业务时区/时钟语义未确认，该结果不能作为可靠“最近 30 天”证据 |
| 时间字段确认 | INFORMATION_SCHEMA 实测为 datetime NOT NULL，参数化比较可执行；但物理可比较不等于业务时间口径成立，最近 30 天口径为 **BLOCKED** |
| 主体指纹 | SHA-256 38F144F8D609E1F6CFA0E3B2E4225EF783A0B313A98262F71FC0862BF97ACD70，与 Task 1 一致 |
| 安全入口 | 使用启用的数据源注册表 id/name 安全别名 bjybdb；配置只在进程内传递，不打印配置行、connection_config 或初始化输出 |
| 执行时段 | 2026-08-27 15:00:52.284–15:00:53.584、15:02:29.783–15:02:30.564、15:03:29.836–15:03:30.546（均 +08:00） |
| 超时边界 | 连接/语句超时 30 秒，LOCK_TIMEOUT 5 秒；所有聚合查询均在 34 毫秒内完成，无超时 |
| 实际 SQL Server 操作 | 仅 SELECT、INFORMATION_SCHEMA 元数据查询与会话级 SET；未执行写语句，未修改索引 |
| 查询失败分类 | 首次合并画像中的 TRY_CONVERT SELECT 返回 ProgrammingError / SQLSTATE 42000；按“一次失败即记录”未重试同一查询。后续独立元数据、日期边界和参数化比较可执行；最近 30 天仍因业务时区未确认而阻断 |

诊断勘误：上一提交的 `DATASOURCE_ALIAS_NOT_FOUND` 是控制器未加载获准进程配置所致，不是源数据或注册表阻断，已撤销。

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；本节留存只读 SQL；执行时段 2026-08-27 15:00:52.284–15:03:30.546 +08:00；执行主体指纹 SHA-256 38F144F8…ACD70]

| 查询组 | 耗时 |
|---|---:|
| 主体指纹与时间锚点 | 4.06 ms |
| T_TradeDate 元数据 / 日期边界 / 服务器时钟观察窗口显式零计数 | 15.93 / 5.30 / 4.93 ms |
| o_Trade 键摘要 / 重复摘要 | 25.67 / 12.67 ms |
| o_FeeItem 孤儿 / 复合键摘要 | 9.35 / 14.83 ms |
| 全量状态组合 / 重复键状态组合 | 7.03 / 33.13 ms |

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z 的只读查询计时；三个有界执行时段见上表]

#### 留存的只读 SQL

以下批次归并了 Task 2 实际执行的只读查询。`@as_of` 固定为证据批次实际参数 `2026-08-27T07:00:52.315`，用于复现本次服务器时钟观察值；`SYSDATETIMEOFFSET()` 只记录复核执行时的服务器当前时钟，仍不代表 T_TradeDate 的业务时区。查询只返回时间、主体哈希、状态枚举和聚合计数，不返回任何交易标识或明细键值；其中 `recent_30d` 仅是服务器时钟观察标签，业务窗口保持 BLOCKED。

```sql
SET NOCOUNT ON;
SET LOCK_TIMEOUT 5000;

DECLARE @as_of datetime2(3) = CONVERT(datetime2(3), '2026-08-27T07:00:52.315', 126);
DECLARE @window_start datetime2(3) = DATEADD(day, -30, @as_of);

SELECT
  CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(nvarchar(128), SUSER_SNAME())), 2)
    AS principal_fingerprint_sha256,
  SYSDATETIMEOFFSET() AS executed_at,
  @as_of AS as_of,
  @window_start AS window_start;

SELECT DATA_TYPE AS data_type, IS_NULLABLE AS is_nullable
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA='dbo'
  AND TABLE_NAME='o_Trade'
  AND COLUMN_NAME='T_TradeDate';

SELECT COUNT_BIG(*) AS total_rows,
       MIN(T_TradeDate) AS data_min,
       MAX(T_TradeDate) AS data_max,
       SUM(CASE WHEN T_TradeDate >= @window_start AND T_TradeDate < @as_of THEN 1 ELSE 0 END)
         AS recent_30d_rows
FROM dbo.o_Trade;

SELECT 'full' AS period,
       COUNT_BIG(*) AS total_rows,
       COALESCE(SUM(CASE WHEN T_SetTid IS NULL THEN 1 ELSE 0 END),0) AS null_settlement_ids,
       COUNT_BIG(DISTINCT T_SetTid) AS distinct_settlement_ids,
       COALESCE(SUM(CASE WHEN T_TradeNo IS NULL THEN 1 ELSE 0 END),0) AS null_trade_nos,
       COUNT_BIG(DISTINCT T_TradeNo) AS distinct_trade_nos
FROM dbo.o_Trade
UNION ALL
SELECT 'recent_30d',
       COUNT_BIG(*),
       COALESCE(SUM(CASE WHEN T_SetTid IS NULL THEN 1 ELSE 0 END),0),
       COUNT_BIG(DISTINCT T_SetTid),
       COALESCE(SUM(CASE WHEN T_TradeNo IS NULL THEN 1 ELSE 0 END),0),
       COUNT_BIG(DISTINCT T_TradeNo)
FROM dbo.o_Trade
WHERE T_TradeDate >= @window_start AND T_TradeDate < @as_of;

WITH duplicate_sets AS (
  SELECT 'full' AS period, 'T_SetTid' AS key_name, COUNT_BIG(*) AS group_rows
  FROM dbo.o_Trade
  WHERE T_SetTid IS NOT NULL
  GROUP BY T_SetTid
  HAVING COUNT_BIG(*) > 1
  UNION ALL
  SELECT 'recent_30d', 'T_SetTid', COUNT_BIG(*)
  FROM dbo.o_Trade
  WHERE T_SetTid IS NOT NULL
    AND T_TradeDate >= @window_start AND T_TradeDate < @as_of
  GROUP BY T_SetTid
  HAVING COUNT_BIG(*) > 1
  UNION ALL
  SELECT 'full', 'T_TradeNo', COUNT_BIG(*)
  FROM dbo.o_Trade
  WHERE T_TradeNo IS NOT NULL
  GROUP BY T_TradeNo
  HAVING COUNT_BIG(*) > 1
  UNION ALL
  SELECT 'recent_30d', 'T_TradeNo', COUNT_BIG(*)
  FROM dbo.o_Trade
  WHERE T_TradeNo IS NOT NULL
    AND T_TradeDate >= @window_start AND T_TradeDate < @as_of
  GROUP BY T_TradeNo
  HAVING COUNT_BIG(*) > 1
), dimensions AS (
  SELECT p.period, k.key_name
  FROM (VALUES ('full'),('recent_30d')) p(period)
  CROSS JOIN (VALUES ('T_SetTid'),('T_TradeNo')) k(key_name)
)
SELECT d.period,
       d.key_name,
       COUNT_BIG(s.group_rows) AS duplicate_groups,
       COALESCE(SUM(s.group_rows), 0) AS duplicate_rows
FROM dimensions d
LEFT JOIN duplicate_sets s ON s.period=d.period AND s.key_name=d.key_name
GROUP BY d.period, d.key_name
ORDER BY d.period, d.key_name;

SELECT COUNT_BIG(*) AS orphan_fee_items
FROM dbo.o_FeeItem fee
LEFT JOIN dbo.o_Trade trade ON trade.T_TradeNo=fee.T_TradeNo
WHERE trade.T_TradeNo IS NULL;

WITH fee_scoped AS (
  SELECT 'full' AS period, f.T_TradeNo, f.ItemId, f.ItemNo
  FROM dbo.o_FeeItem f
  UNION ALL
  SELECT 'recent_30d_parent_joined', f.T_TradeNo, f.ItemId, f.ItemNo
  FROM dbo.o_FeeItem f
  JOIN dbo.o_Trade t ON t.T_TradeNo=f.T_TradeNo
  WHERE t.T_TradeDate >= @window_start AND t.T_TradeDate < @as_of
), base AS (
  SELECT period,
         COUNT_BIG(*) AS total_rows,
         SUM(CASE WHEN T_TradeNo IS NULL THEN 1 ELSE 0 END) AS null_trade_nos,
         SUM(CASE WHEN ItemId IS NULL THEN 1 ELSE 0 END) AS null_item_ids,
         SUM(CASE WHEN ItemNo IS NULL THEN 1 ELSE 0 END) AS null_item_nos,
         SUM(CASE WHEN T_TradeNo IS NULL OR ItemId IS NULL OR ItemNo IS NULL THEN 1 ELSE 0 END)
           AS any_null_key_rows
  FROM fee_scoped
  GROUP BY period
), duplicate_keys AS (
  SELECT period, T_TradeNo, ItemId, ItemNo, COUNT_BIG(*) AS group_rows
  FROM fee_scoped
  WHERE T_TradeNo IS NOT NULL AND ItemId IS NOT NULL AND ItemNo IS NOT NULL
  GROUP BY period, T_TradeNo, ItemId, ItemNo
  HAVING COUNT_BIG(*) > 1
), duplicate_stats AS (
  SELECT period,
         COUNT_BIG(*) AS duplicate_groups,
         SUM(group_rows) AS duplicate_rows
  FROM duplicate_keys
  GROUP BY period
), periods AS (
  SELECT period FROM (VALUES ('full'),('recent_30d_parent_joined')) p(period)
)
SELECT p.period,
       COALESCE(b.total_rows,0) AS total_rows,
       COALESCE(b.null_trade_nos,0) AS null_trade_nos,
       COALESCE(b.null_item_ids,0) AS null_item_ids,
       COALESCE(b.null_item_nos,0) AS null_item_nos,
       COALESCE(b.any_null_key_rows,0) AS any_null_key_rows,
       COALESCE(d.duplicate_groups,0) AS duplicate_groups,
       COALESCE(d.duplicate_rows,0) AS duplicate_rows
FROM periods p
LEFT JOIN base b ON b.period=p.period
LEFT JOIN duplicate_stats d ON d.period=p.period
ORDER BY p.period;

SELECT period,
       T_State,
       T_HasRefundmented,
       T_PartialReturnFlag,
       NT_ReTradeFlag,
       COUNT_BIG(*) AS row_count
FROM (
  SELECT 'full' AS period,
         T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag
  FROM dbo.o_Trade
  UNION ALL
  SELECT 'recent_30d',
         T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag
  FROM dbo.o_Trade
  WHERE T_TradeDate >= @window_start AND T_TradeDate < @as_of
) s
GROUP BY period, T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag
ORDER BY period, T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag;

WITH full_set AS (
  SELECT T_SetTid
  FROM dbo.o_Trade
  WHERE T_SetTid IS NOT NULL
  GROUP BY T_SetTid
  HAVING COUNT_BIG(*) > 1
), recent_set AS (
  SELECT T_SetTid
  FROM dbo.o_Trade
  WHERE T_SetTid IS NOT NULL
    AND T_TradeDate >= @window_start AND T_TradeDate < @as_of
  GROUP BY T_SetTid
  HAVING COUNT_BIG(*) > 1
), full_trade AS (
  SELECT T_TradeNo
  FROM dbo.o_Trade
  WHERE T_TradeNo IS NOT NULL
  GROUP BY T_TradeNo
  HAVING COUNT_BIG(*) > 1
), recent_trade AS (
  SELECT T_TradeNo
  FROM dbo.o_Trade
  WHERE T_TradeNo IS NOT NULL
    AND T_TradeDate >= @window_start AND T_TradeDate < @as_of
  GROUP BY T_TradeNo
  HAVING COUNT_BIG(*) > 1
), full_fee AS (
  SELECT T_TradeNo, ItemId, ItemNo,
         ROW_NUMBER() OVER (ORDER BY T_TradeNo,ItemId,ItemNo) AS duplicate_group_id
  FROM dbo.o_FeeItem
  WHERE T_TradeNo IS NOT NULL AND ItemId IS NOT NULL AND ItemNo IS NOT NULL
  GROUP BY T_TradeNo, ItemId, ItemNo
  HAVING COUNT_BIG(*) > 1
), recent_fee AS (
  SELECT f.T_TradeNo, f.ItemId, f.ItemNo,
         ROW_NUMBER() OVER (ORDER BY f.T_TradeNo,f.ItemId,f.ItemNo) AS duplicate_group_id
  FROM dbo.o_FeeItem f
  JOIN dbo.o_Trade t ON t.T_TradeNo=f.T_TradeNo
  WHERE f.T_TradeNo IS NOT NULL AND f.ItemId IS NOT NULL AND f.ItemNo IS NOT NULL
    AND t.T_TradeDate >= @window_start AND t.T_TradeDate < @as_of
  GROUP BY f.T_TradeNo, f.ItemId, f.ItemNo
  HAVING COUNT_BIG(*) > 1
), rows_by_status AS (
  SELECT 'full' AS period, 'T_SetTid' AS key_name,
         t.T_State, t.T_HasRefundmented, t.T_PartialReturnFlag, t.NT_ReTradeFlag,
         COUNT_BIG(DISTINCT d.T_SetTid) AS duplicate_groups,
         COUNT_BIG(*) AS duplicate_rows
  FROM dbo.o_Trade t
  JOIN full_set d ON d.T_SetTid=t.T_SetTid
  GROUP BY t.T_State,t.T_HasRefundmented,t.T_PartialReturnFlag,t.NT_ReTradeFlag
  UNION ALL
  SELECT 'recent_30d', 'T_SetTid',
         t.T_State, t.T_HasRefundmented, t.T_PartialReturnFlag, t.NT_ReTradeFlag,
         COUNT_BIG(DISTINCT d.T_SetTid), COUNT_BIG(*)
  FROM dbo.o_Trade t
  JOIN recent_set d ON d.T_SetTid=t.T_SetTid
  WHERE t.T_TradeDate >= @window_start AND t.T_TradeDate < @as_of
  GROUP BY t.T_State,t.T_HasRefundmented,t.T_PartialReturnFlag,t.NT_ReTradeFlag
  UNION ALL
  SELECT 'full', 'T_TradeNo',
         t.T_State, t.T_HasRefundmented, t.T_PartialReturnFlag, t.NT_ReTradeFlag,
         COUNT_BIG(DISTINCT d.T_TradeNo), COUNT_BIG(*)
  FROM dbo.o_Trade t
  JOIN full_trade d ON d.T_TradeNo=t.T_TradeNo
  GROUP BY t.T_State,t.T_HasRefundmented,t.T_PartialReturnFlag,t.NT_ReTradeFlag
  UNION ALL
  SELECT 'recent_30d', 'T_TradeNo',
         t.T_State, t.T_HasRefundmented, t.T_PartialReturnFlag, t.NT_ReTradeFlag,
         COUNT_BIG(DISTINCT d.T_TradeNo), COUNT_BIG(*)
  FROM dbo.o_Trade t
  JOIN recent_trade d ON d.T_TradeNo=t.T_TradeNo
  WHERE t.T_TradeDate >= @window_start AND t.T_TradeDate < @as_of
  GROUP BY t.T_State,t.T_HasRefundmented,t.T_PartialReturnFlag,t.NT_ReTradeFlag
  UNION ALL
  SELECT 'full', 'FeeComposite',
         t.T_State, t.T_HasRefundmented, t.T_PartialReturnFlag, t.NT_ReTradeFlag,
         COUNT_BIG(DISTINCT d.duplicate_group_id), COUNT_BIG(*)
  FROM dbo.o_FeeItem f
  JOIN full_fee d
    ON d.T_TradeNo=f.T_TradeNo AND d.ItemId=f.ItemId AND d.ItemNo=f.ItemNo
  JOIN dbo.o_Trade t ON t.T_TradeNo=f.T_TradeNo
  GROUP BY t.T_State,t.T_HasRefundmented,t.T_PartialReturnFlag,t.NT_ReTradeFlag
  UNION ALL
  SELECT 'recent_30d', 'FeeComposite',
         t.T_State, t.T_HasRefundmented, t.T_PartialReturnFlag, t.NT_ReTradeFlag,
         COUNT_BIG(DISTINCT d.duplicate_group_id), COUNT_BIG(*)
  FROM dbo.o_FeeItem f
  JOIN recent_fee d
    ON d.T_TradeNo=f.T_TradeNo AND d.ItemId=f.ItemId AND d.ItemNo=f.ItemNo
  JOIN dbo.o_Trade t ON t.T_TradeNo=f.T_TradeNo
  WHERE t.T_TradeDate >= @window_start AND t.T_TradeDate < @as_of
  GROUP BY t.T_State,t.T_HasRefundmented,t.T_PartialReturnFlag,t.NT_ReTradeFlag
)
SELECT *
FROM rows_by_status
ORDER BY period, key_name, T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag;
```

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；执行主体指纹 SHA-256 38F144F8…ACD70；复核参数固定为该批次服务器时钟锚点]

费用明细没有独立日期字段，`recent_30d_parent_joined` 通过父交易 T_TradeDate 取得服务器时钟观察值 0。全量 T_TradeNo 无重复且全量孤儿数为 0，只能证明主从关联无歧义，不能解除 T_TradeDate 业务时区未确认造成的最近 30 天口径阻断。

#### Task 2 结果与冻结决定

| 验证项 | 完整区间 | 服务器时钟观察窗口 | 决定 |
|---|---|---|---|
| o_Trade 行数 | 592 | 0（非可靠最近 30 天证据） | [推断: 因业务时区未确认，观察窗口 **BLOCKED**，不据此判断近期无交易] |
| T_SetTid NULL / 去重数 | 11 / 257 | 0 / 0（观察值） | [推断: 全量计数不满足内部结算锚点的一对一要求] |
| T_SetTid 重复组数 / 涉及行数 | 2 / 326 | 0 / 0（观察值） | [推断: 基于全量重复证据与 Issue20 §5.2 强制内部锚点要求 **BLOCKED**，停止 `settlement_id → 单笔交易` 假设，九个执行 Profile 均阻断] |
| T_TradeNo NULL / 去重数 | 0 / 592 | 0 / 0（观察值） | [推断: 仅基于全量 592 行及物理主键，冻结为交易业务键] |
| T_TradeNo 重复组数 / 涉及行数 | 0 / 0 | 0 / 0（观察值） | [推断: 全量结论冻结，观察窗口不参与冻结] |
| o_FeeItem 行数 | 2,139 | 0（按父交易日期得到的观察值） | 不据此判断近期无明细 |
| 复合键三个分量 NULL / 任一 NULL 行 | 0 / 0 / 0；任一 NULL 0 | 均为 0（观察值） | 全量证据通过 |
| 复合键重复组数 / 涉及行数 | 0 / 0 | 0 / 0（观察值） | [推断: 仅基于全量证据冻结 `(T_TradeNo, ItemId, ItemNo)` 为费用明细幂等键] |
| o_FeeItem → o_Trade 孤儿明细数 | 0 | 未验证（时间口径阻断） | [推断: 全量 T_TradeNo 主从关系无歧义；本范围支持一笔交易对应多条费用明细] |

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；本节留存只读 SQL；执行时段 2026-08-27 15:02:29.783–15:03:30.546 +08:00]

[推断: 基于上述全量 NULL、去重、重复与孤儿计数] 三项决定：内部结算锚点 **BLOCKED**；交易业务键冻结为 T_TradeNo；费用明细幂等键冻结为 `(T_TradeNo, ItemId, ItemNo)`。T_SetTid 的 2 个重复组横跨多种状态组合，且 11 行为空，当前数据不支持把它解释为单笔交易锚点；是否属于合法批次、历史版本或其他业务对象仍需权威字典确认，不自行设计替代键，也不把重复直接认定为脏数据。

## 交易状态

服务器时钟观察窗口内状态组合查询返回 0，但因 T_TradeDate 业务时区/时钟语义未确认，不能表述为业务最近 30 天无交易。以下仅列全量状态组合；`''` 表示空字符串，`NULL` 表示数据库 NULL。

| T_State | T_HasRefundmented | T_PartialReturnFlag | NT_ReTradeFlag | 行数 |
|---:|---:|---|---|---:|
| -3 | 0 | NULL | `''` | 2 |
| -3 | 0 | `''` | NULL | 5 |
| -3 | 1 | `''` | NULL | 1 |
| -1 | 0 | `''` | NULL | 1 |
| 3 | 0 | NULL | `''` | 3 |
| 3 | 0 | `''` | NULL | 14 |
| 3 | 1 | NULL | `''` | 5 |
| 3 | 1 | NULL | `1` | 1 |
| 4 | 0 | `''` | NULL | 393 |
| 4 | 1 | `''` | NULL | 133 |
| 4 | 1 | `1` | NULL | 34 |

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；全量状态组合只读 SQL；执行时段 2026-08-27 15:02:29.783–15:02:30.564 +08:00]

T_TradeNo 和费用复合键没有重复，因此没有对应的重复键状态组合。T_SetTid 重复行的二次聚合如下；“涉及重复组数”表示该状态组合涉及全量 2 个重复组中的几个，同一组跨状态时会在多行出现，不能跨行相加。

| T_State | T_HasRefundmented | T_PartialReturnFlag | NT_ReTradeFlag | 涉及重复组数 | 重复行数 |
|---:|---:|---|---|---:|---:|
| -3 | 0 | `''` | NULL | 1 | 5 |
| -3 | 1 | `''` | NULL | 1 | 1 |
| 3 | 0 | `''` | NULL | 1 | 3 |
| 4 | 0 | `''` | NULL | 1 | 250 |
| 4 | 1 | `''` | NULL | 2 | 54 |
| 4 | 1 | `1` | NULL | 1 | 13 |

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；重复键状态组合只读 SQL；执行时段 2026-08-27 15:02:29.783–15:02:30.564 +08:00]

[推断: 基于重复键状态组合计数] 重复行在数值上集中于 T_State=4（317/326），但 T_HasRefundmented=0 仍有 258/326 行，T_PartialReturnFlag=`1` 仅 13/326 行，NT_ReTradeFlag=`1` 为 0 行。因此不能认定重复仅集中在退费、部分退费或冲正，也不能从 T_State=4 推断历史版本或任何业务终态；以上是相关性计数，不是因果结论。状态码业务含义仍需权威字典签认。

## 金额勾稽

### Task 3：金额口径与唯一费用明细源

#### 执行证据与边界

| 项目 | 结果 |
|---|---|
| 文档级证据批次 ID | `outpatient_p0_t3_20260827_073210Z`；仅用于关联本文 Task 3 的只读 SQL、聚合结果、固定执行时间与主体指纹，不是数据库审计 ID 或外部 run_id |
| 固定执行时间 | SQL Server `SYSDATETIMEOFFSET()`：2026-08-27 07:32:10.3588997 +00:00，即 2026-08-27 15:32:10.3588997 +08:00；只作为本证据批次时钟锚点 |
| 明细精度复核批次 | `outpatient_p0_t3_precision_20260827_074356Z`；文档级、非数据库审计 ID；固定执行时间 2026-08-27 07:43:56.2799893 +00:00（15:43:56.2799893 +08:00） |
| 主体指纹引用 | SHA-256 38F144F8D609E1F6CFA0E3B2E4225EF783A0B313A98262F71FC0862BF97ACD70，与 Task 1–2 相同；不记录原登录名 |
| 安全连接链 | `PolicyMetaStore(DATABASE_URL)` → `SemanticDataSource(meta_store=meta)` → `_resolve_datasource_connection('bjybdb')` → `_connect(cfg)`；worktree `.env` 仅在进程内安全加载，初始化 stdout/stderr 丢弃，未输出配置、连接 URL、主机、库名、账号或凭据 |
| 数据范围 | dbo.o_Trade 全量 592 行；dbo.o_FeeItem 全量 2,139 行；没有业务日期过滤 |
| 金额语义 | SQL Server `decimal` 运算，固定容差 0.0100 元；任一参与字段为 NULL 即计入 missing，不以 `COALESCE` 代替 0；明细 SUM 结果、ABS 差异与阈值经精度复核统一为 `decimal(28,4)` |
| 精度影响范围 | 仅 Q4 依赖明细 SUM，已重跑；Q3 交易表等式与 Q7 专项候选等式均为直接字段运算、不依赖 SUM，未重跑 |
| 关联边界 | 只用 `T_TradeNo` 聚合和关联；未使用被阻断的 `T_SetTid`，未输出 T_TradeNo 或任何行级标识 |
| 查询边界 | 连接/语句超时 30 秒，`LOCK_TIMEOUT` 5 秒；SQL Server 仅执行 SELECT/SET，失败不重试，未修改源库索引 |
| 查询失败分类 | `NONE`；原七组聚合查询均一次成功，精度修正后的明细总体及状态分层 SELECT 另一次成功；均无重试 |
| 范围外事项 | 未执行字段闭包、运营指标、增量游标、容量任务；未查询第三张业务表 |

[来源: 文档级证据批次 outpatient_p0_t3_20260827_073210Z、outpatient_p0_t3_precision_20260827_074356Z；固定执行时间分别为 2026-08-27 07:32:10.3588997、07:43:56.2799893 +00:00；执行主体指纹 SHA-256 38F144F8…ACD70]

#### 完整可复现只读 SQL

以下 SQL 汇总原始批次及精度复核批次的最终有效执行口径。固定参数为金额容差 0.0100 元、`LOCK_TIMEOUT` 5000 毫秒；驱动层语句超时固定为 30 秒。所有结果均为聚合计数、状态码或差异摘要，不返回交易号、明细键或人员字段。

```sql
SET NOCOUNT ON;
SET LOCK_TIMEOUT 5000;

-- Q1：主体指纹和固定执行时间。
SELECT
  CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(nvarchar(128), SUSER_SNAME())), 2)
    AS principal_fingerprint_sha256,
  SYSDATETIMEOFFSET() AS server_executed_at;

-- Q2：已冻结费用复合键复核。
WITH duplicate_keys AS (
  SELECT T_TradeNo, ItemId, ItemNo, COUNT_BIG(*) AS group_rows
  FROM dbo.o_FeeItem
  WHERE T_TradeNo IS NOT NULL AND ItemId IS NOT NULL AND ItemNo IS NOT NULL
  GROUP BY T_TradeNo, ItemId, ItemNo
  HAVING COUNT_BIG(*) > 1
)
SELECT
  (SELECT COUNT_BIG(*) FROM dbo.o_FeeItem) AS total_rows,
  (SELECT SUM(CASE WHEN T_TradeNo IS NULL THEN 1 ELSE 0 END) FROM dbo.o_FeeItem)
    AS null_trade_nos,
  (SELECT SUM(CASE WHEN ItemId IS NULL THEN 1 ELSE 0 END) FROM dbo.o_FeeItem)
    AS null_item_ids,
  (SELECT SUM(CASE WHEN ItemNo IS NULL THEN 1 ELSE 0 END) FROM dbo.o_FeeItem)
    AS null_item_nos,
  COUNT_BIG(*) AS duplicate_groups,
  SUM(group_rows) AS duplicate_rows
FROM duplicate_keys;

-- Q3：o_Trade 两组金额等式，全量及四状态组合分层。
WITH base AS (
  SELECT
    T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag,
    CASE
      WHEN T_FeeAll IS NULL OR T_FeeIn IS NULL OR T_FeeOut IS NULL THEN NULL
      ELSE ABS(CONVERT(decimal(19,4), T_FeeAll)
             - CONVERT(decimal(19,4), T_FeeIn)
             - CONVERT(decimal(19,4), T_FeeOut))
    END AS fee_split_abs_diff,
    CASE
      WHEN T_FeeAll IS NULL OR T_FundPay IS NULL OR T_SelfPayAll IS NULL THEN NULL
      ELSE ABS(CONVERT(decimal(19,4), T_FeeAll)
             - CONVERT(decimal(19,4), T_FundPay)
             - CONVERT(decimal(19,4), T_SelfPayAll))
    END AS fund_self_abs_diff
  FROM dbo.o_Trade
)
SELECT
  CASE WHEN GROUPING_ID(
    T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag
  ) = 15 THEN 'all' ELSE 'state' END AS scope_name,
  T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag,
  COUNT_BIG(*) AS row_count,
  SUM(CASE WHEN fee_split_abs_diff IS NULL THEN 1 ELSE 0 END) AS fee_split_missing,
  SUM(CASE WHEN fee_split_abs_diff IS NOT NULL
                AND fee_split_abs_diff <= CONVERT(decimal(19,4), 0.0100)
           THEN 1 ELSE 0 END) AS fee_split_passed,
  SUM(CASE WHEN fee_split_abs_diff IS NOT NULL
                AND fee_split_abs_diff > CONVERT(decimal(19,4), 0.0100)
           THEN 1 ELSE 0 END) AS fee_split_failed,
  MAX(fee_split_abs_diff) AS fee_split_max_abs_diff,
  SUM(fee_split_abs_diff) AS fee_split_sum_abs_diff,
  SUM(CASE WHEN fund_self_abs_diff IS NULL THEN 1 ELSE 0 END) AS fund_self_missing,
  SUM(CASE WHEN fund_self_abs_diff IS NOT NULL
                AND fund_self_abs_diff <= CONVERT(decimal(19,4), 0.0100)
           THEN 1 ELSE 0 END) AS fund_self_passed,
  SUM(CASE WHEN fund_self_abs_diff IS NOT NULL
                AND fund_self_abs_diff > CONVERT(decimal(19,4), 0.0100)
           THEN 1 ELSE 0 END) AS fund_self_failed,
  MAX(fund_self_abs_diff) AS fund_self_max_abs_diff,
  SUM(fund_self_abs_diff) AS fund_self_sum_abs_diff
FROM base
GROUP BY GROUPING SETS (
  (),
  (T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag)
)
ORDER BY
  GROUPING_ID(T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag) DESC,
  T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag;

-- Q4：o_FeeItem 按 T_TradeNo 汇总后与 o_Trade 逐交易勾稽。
-- SUM(decimal(19,4)) 先显式收窄为 decimal(28,4)，差异和阈值统一为
-- decimal(28,4)，避免 decimal(38,4) 参与减法时发生 scale 降级。
WITH detail_precision_anchor AS (
  SELECT
    CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(nvarchar(128), SUSER_SNAME())), 2)
      AS principal_fingerprint_sha256,
    SYSDATETIMEOFFSET() AS server_executed_at
),
fee_agg AS (
  SELECT
    T_TradeNo,
    CAST(SUM(CAST(Fee AS decimal(19,4))) AS decimal(28,4)) AS detail_fee,
    CAST(SUM(CAST(FeeIn AS decimal(19,4))) AS decimal(28,4)) AS detail_fee_in,
    CAST(SUM(CAST(FeeOut AS decimal(19,4))) AS decimal(28,4)) AS detail_fee_out
  FROM dbo.o_FeeItem
  GROUP BY T_TradeNo
),
joined AS (
  SELECT
    t.T_State, t.T_HasRefundmented, t.T_PartialReturnFlag, t.NT_ReTradeFlag,
    CASE WHEN t.T_TradeNo IS NULL THEN 0 ELSE 1 END AS has_trade,
    CASE WHEN f.T_TradeNo IS NULL THEN 0 ELSE 1 END AS has_detail,
    CASE
      WHEN t.T_FeeAll IS NULL OR f.detail_fee IS NULL THEN NULL
      ELSE CAST(
        ABS(CAST(t.T_FeeAll AS decimal(28,4)) - f.detail_fee)
        AS decimal(28,4)
      )
    END AS fee_abs_diff,
    CASE
      WHEN t.T_FeeIn IS NULL OR f.detail_fee_in IS NULL THEN NULL
      ELSE CAST(
        ABS(CAST(t.T_FeeIn AS decimal(28,4)) - f.detail_fee_in)
        AS decimal(28,4)
      )
    END AS fee_in_abs_diff,
    CASE
      WHEN t.T_FeeOut IS NULL OR f.detail_fee_out IS NULL THEN NULL
      ELSE CAST(
        ABS(CAST(t.T_FeeOut AS decimal(28,4)) - f.detail_fee_out)
        AS decimal(28,4)
      )
    END AS fee_out_abs_diff
  FROM dbo.o_Trade t
  FULL OUTER JOIN fee_agg f ON f.T_TradeNo = t.T_TradeNo
)
SELECT
  MAX(a.principal_fingerprint_sha256) AS principal_fingerprint_sha256,
  MAX(a.server_executed_at) AS server_executed_at,
  CASE WHEN GROUPING_ID(
    j.T_State, j.T_HasRefundmented, j.T_PartialReturnFlag, j.NT_ReTradeFlag
  ) = 15 THEN 'all' ELSE 'state' END AS scope_name,
  j.T_State, j.T_HasRefundmented, j.T_PartialReturnFlag, j.NT_ReTradeFlag,
  COUNT_BIG(*) AS comparison_entities,
  SUM(j.has_trade) AS main_rows,
  SUM(j.has_detail) AS detail_aggregate_rows,
  SUM(CASE WHEN j.has_trade = 1 AND j.has_detail = 0 THEN 1 ELSE 0 END)
    AS main_without_detail,
  SUM(CASE WHEN j.has_trade = 0 AND j.has_detail = 1 THEN 1 ELSE 0 END)
    AS detail_without_main,
  SUM(CASE WHEN j.fee_abs_diff IS NULL THEN 1 ELSE 0 END) AS fee_missing,
  SUM(CASE WHEN j.fee_abs_diff IS NOT NULL
                AND j.fee_abs_diff <= CAST(0.0100 AS decimal(28,4))
           THEN 1 ELSE 0 END) AS fee_passed,
  SUM(CASE WHEN j.fee_abs_diff IS NOT NULL
                AND j.fee_abs_diff > CAST(0.0100 AS decimal(28,4))
           THEN 1 ELSE 0 END) AS fee_failed,
  MAX(j.fee_abs_diff) AS fee_max_abs_diff,
  SUM(j.fee_abs_diff) AS fee_sum_abs_diff,
  SUM(CASE WHEN j.fee_in_abs_diff IS NULL THEN 1 ELSE 0 END) AS fee_in_missing,
  SUM(CASE WHEN j.fee_in_abs_diff IS NOT NULL
                AND j.fee_in_abs_diff <= CAST(0.0100 AS decimal(28,4))
           THEN 1 ELSE 0 END) AS fee_in_passed,
  SUM(CASE WHEN j.fee_in_abs_diff IS NOT NULL
                AND j.fee_in_abs_diff > CAST(0.0100 AS decimal(28,4))
           THEN 1 ELSE 0 END) AS fee_in_failed,
  MAX(j.fee_in_abs_diff) AS fee_in_max_abs_diff,
  SUM(j.fee_in_abs_diff) AS fee_in_sum_abs_diff,
  SUM(CASE WHEN j.fee_out_abs_diff IS NULL THEN 1 ELSE 0 END) AS fee_out_missing,
  SUM(CASE WHEN j.fee_out_abs_diff IS NOT NULL
                AND j.fee_out_abs_diff <= CAST(0.0100 AS decimal(28,4))
           THEN 1 ELSE 0 END) AS fee_out_passed,
  SUM(CASE WHEN j.fee_out_abs_diff IS NOT NULL
                AND j.fee_out_abs_diff > CAST(0.0100 AS decimal(28,4))
           THEN 1 ELSE 0 END) AS fee_out_failed,
  MAX(j.fee_out_abs_diff) AS fee_out_max_abs_diff,
  SUM(j.fee_out_abs_diff) AS fee_out_sum_abs_diff
FROM joined j
CROSS JOIN detail_precision_anchor a
GROUP BY GROUPING SETS (
  (),
  (j.T_State, j.T_HasRefundmented, j.T_PartialReturnFlag, j.NT_ReTradeFlag)
)
ORDER BY
  GROUPING_ID(j.T_State, j.T_HasRefundmented, j.T_PartialReturnFlag, j.NT_ReTradeFlag) DESC,
  j.T_State, j.T_HasRefundmented, j.T_PartialReturnFlag, j.NT_ReTradeFlag;

-- Q5：明确存在的基金候选字段 NULL/零/非零统计。
WITH fund_values AS (
  SELECT v.field_name, v.amount
  FROM dbo.o_Trade t
  CROSS APPLY (VALUES
    ('T_FundPay', CONVERT(decimal(19,4), t.T_FundPay)),
    ('T_BigPay', CONVERT(decimal(19,4), t.T_BigPay)),
    ('T_BCPay', CONVERT(decimal(19,4), t.T_BCPay)),
    ('T_JCPay', CONVERT(decimal(19,4), t.T_JCPay)),
    ('T_OfficalPay', CONVERT(decimal(19,4), t.T_OfficalPay)),
    ('NT_AgencySumPay', CONVERT(decimal(19,4), t.NT_AgencySumPay)),
    ('NT_BasicPay', CONVERT(decimal(19,4), t.NT_BasicPay)),
    ('NT_CivilPay', CONVERT(decimal(19,4), t.NT_CivilPay)),
    ('NT_OtherPay', CONVERT(decimal(19,4), t.NT_OtherPay)),
    ('T_BigillPay', CONVERT(decimal(19,4), t.T_BigillPay)),
    ('RETIRE_OFFICER_PAY', CONVERT(decimal(19,4), t.RETIRE_OFFICER_PAY))
  ) v(field_name, amount)
)
SELECT
  field_name,
  COUNT_BIG(*) AS row_count,
  SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END) AS null_count,
  SUM(CASE WHEN amount = CONVERT(decimal(19,4), 0) THEN 1 ELSE 0 END) AS zero_count,
  SUM(CASE WHEN amount IS NOT NULL
                AND amount <> CONVERT(decimal(19,4), 0) THEN 1 ELSE 0 END)
    AS nonzero_count
FROM fund_values
GROUP BY field_name
ORDER BY field_name;

-- Q6：基金候选字段共现；N=NULL、Z=0、V=非零，顺序见结果说明。
WITH signatures AS (
  SELECT CONCAT(
    CASE WHEN T_FundPay IS NULL THEN 'N'
         WHEN T_FundPay = 0 THEN 'Z' ELSE 'V' END, '|',
    CASE WHEN NT_AgencySumPay IS NULL THEN 'N'
         WHEN NT_AgencySumPay = 0 THEN 'Z' ELSE 'V' END, '|',
    CASE WHEN NT_BasicPay IS NULL THEN 'N'
         WHEN NT_BasicPay = 0 THEN 'Z' ELSE 'V' END, '|',
    CASE WHEN NT_CivilPay IS NULL THEN 'N'
         WHEN NT_CivilPay = 0 THEN 'Z' ELSE 'V' END, '|',
    CASE WHEN NT_OtherPay IS NULL THEN 'N'
         WHEN NT_OtherPay = 0 THEN 'Z' ELSE 'V' END
  ) AS amount_signature
  FROM dbo.o_Trade
)
SELECT amount_signature, COUNT_BIG(*) AS row_count
FROM signatures
GROUP BY amount_signature
ORDER BY row_count DESC, amount_signature;

-- Q7：仅验证候选 NT_AgencySumPay = NT_BasicPay + NT_CivilPay + NT_OtherPay。
WITH base AS (
  SELECT
    T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag,
    CASE
      WHEN NT_AgencySumPay IS NULL OR NT_BasicPay IS NULL
        OR NT_CivilPay IS NULL OR NT_OtherPay IS NULL THEN NULL
      ELSE ABS(CONVERT(decimal(19,4), NT_AgencySumPay)
             - CONVERT(decimal(19,4), NT_BasicPay)
             - CONVERT(decimal(19,4), NT_CivilPay)
             - CONVERT(decimal(19,4), NT_OtherPay))
    END AS agency_parts_abs_diff
  FROM dbo.o_Trade
)
SELECT
  CASE WHEN GROUPING_ID(
    T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag
  ) = 15 THEN 'all' ELSE 'state' END AS scope_name,
  T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag,
  COUNT_BIG(*) AS row_count,
  SUM(CASE WHEN agency_parts_abs_diff IS NULL THEN 1 ELSE 0 END) AS missing,
  SUM(CASE WHEN agency_parts_abs_diff IS NOT NULL
                AND agency_parts_abs_diff <= CONVERT(decimal(19,4), 0.0100)
           THEN 1 ELSE 0 END) AS passed,
  SUM(CASE WHEN agency_parts_abs_diff IS NOT NULL
                AND agency_parts_abs_diff > CONVERT(decimal(19,4), 0.0100)
           THEN 1 ELSE 0 END) AS failed,
  MAX(agency_parts_abs_diff) AS max_abs_diff,
  SUM(agency_parts_abs_diff) AS sum_abs_diff
FROM base
GROUP BY GROUPING SETS (
  (),
  (T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag)
)
ORDER BY
  GROUPING_ID(T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag) DESC,
  T_State, T_HasRefundmented, T_PartialReturnFlag, NT_ReTradeFlag;
```

[来源: Q1–Q3、Q5–Q7 为文档级证据批次 outpatient_p0_t3_20260827_073210Z；修正后的 Q4 为文档级证据批次 outpatient_p0_t3_precision_20260827_074356Z。每个 SELECT 均一次执行成功，未重试]

#### o_Trade 金额等式

“缺/通/败”分别为任一参与字段 NULL、绝对差 ≤ 0.01 元、绝对差 > 0.01 元。差异使用未取绝对值前的原字段精度转为 `decimal(19,4)` 后计算；最大/合计均为绝对差。

| 等式 | 行数 | 缺 | 通 | 败 | 最大绝对差（元） | 合计绝对差（元） |
|---|---:|---:|---:|---:|---:|---:|
| T_FeeAll = T_FeeIn + T_FeeOut | 592 | 0 | 587 | 5 | 9.0000 | 33.9500 |
| T_FeeAll = T_FundPay + T_SelfPayAll | 592 | 0 | 586 | 6 | 600.0000 | 1,329.0000 |

[来源: outpatient_p0_t3_20260827_073210Z Q3 全量聚合]

| T_State | T_HasRefundmented | T_PartialReturnFlag | NT_ReTradeFlag | 行数 | FeeAll=FeeIn+FeeOut 缺/通/败 | 最大/合计差 | FeeAll=FundPay+SelfPayAll 缺/通/败 | 最大/合计差 |
|---:|---:|---|---|---:|---|---:|---|---:|
| -3 | 0 | NULL | `''` | 2 | 0/2/0 | 0.0000/0.0000 | 0/2/0 | 0.0000/0.0000 |
| -3 | 0 | `''` | NULL | 5 | 0/5/0 | 0.0000/0.0000 | 0/5/0 | 0.0000/0.0000 |
| -3 | 1 | `''` | NULL | 1 | 0/1/0 | 0.0000/0.0000 | 0/1/0 | 0.0000/0.0000 |
| -1 | 0 | `''` | NULL | 1 | 0/1/0 | 0.0000/0.0000 | 0/1/0 | 0.0000/0.0000 |
| 3 | 0 | NULL | `''` | 3 | 0/3/0 | 0.0000/0.0000 | 0/1/2 | 55.0000/105.0000 |
| 3 | 0 | `''` | NULL | 14 | 0/14/0 | 0.0000/0.0000 | 0/14/0 | 0.0000/0.0000 |
| 3 | 1 | NULL | `''` | 5 | 0/5/0 | 0.0000/0.0000 | 0/2/3 | 600.0000/1,212.0000 |
| 3 | 1 | NULL | `1` | 1 | 0/1/0 | 0.0000/0.0000 | 0/0/1 | 12.0000/12.0000 |
| 4 | 0 | `''` | NULL | 393 | 0/390/3 | 8.0000/15.9500 | 0/393/0 | 0.0000/0.0000 |
| 4 | 1 | `''` | NULL | 133 | 0/132/1 | 9.0000/9.0000 | 0/133/0 | 0.0000/0.0000 |
| 4 | 1 | `1` | NULL | 34 | 0/33/1 | 9.0000/9.0000 | 0/34/0 | 0.0000/0.0000 |

[来源: outpatient_p0_t3_20260827_073210Z Q3 四状态组合聚合]

[推断: 基于上述数值聚合] 两组候选等式均出现实质差异，因此不能冻结为无条件金额口径。差异在状态组合上的分布仅是相关性；没有权威状态字典和有效记录规则时，不把任何状态码解释为成功、退费、冲正或应排除状态，也不把差异直接认定为脏数据。

#### o_FeeItem 关联与逐交易勾稽

[来源: 文档级证据批次 outpatient_p0_t3_precision_20260827_074356Z] 规格审查发现 SQL Server 的 `SUM(decimal(19,4))` 返回 `decimal(38,4)`，直接与 `decimal(19,4)` 相减可能按精度规则降低 scale。修正后先把三个明细 SUM 显式转换为 `decimal(28,4)`，再以 `decimal(28,4)` 计算 ABS 差异并与 `decimal(28,4)` 的 0.0100 阈值比较。总体及全部四状态组合一次重跑成功，聚合结果与原记录完全一致；以下 Q4 数字均以本精度复核批次为权威证据。

| 验证项 | 聚合结果 | 判断 |
|---|---:|---|
| 费用明细行数 | 2,139 | 全量 |
| 复合键分量 NULL（T_TradeNo / ItemId / ItemNo） | 0 / 0 / 0 | 通过 |
| `(T_TradeNo, ItemId, ItemNo)` 重复组 | 0 | 通过；`duplicate_rows` 的 SQL 空集 SUM 为 NULL，因重复组为 0，实际没有重复涉及行 |
| 主表交易 / 明细聚合交易 | 592 / 592 | 通过 |
| 主表无明细 / 明细无主表 | 0 / 0 | 通过 |

[来源: outpatient_p0_t3_20260827_073210Z Q2；outpatient_p0_t3_precision_20260827_074356Z Q4 全量聚合]

| 明细汇总与主表比较 | 比较交易 | 缺 | 通 | 败 | 最大绝对差（元） | 合计绝对差（元） |
|---|---:|---:|---:|---:|---:|---:|
| SUM(o_FeeItem.Fee) = o_Trade.T_FeeAll | 592 | 0 | 590 | 2 | 250.0000 | 300.0000 |
| SUM(o_FeeItem.FeeIn) = o_Trade.T_FeeIn | 592 | 0 | 592 | 0 | 0.0030 | 0.0380 |
| SUM(o_FeeItem.FeeOut) = o_Trade.T_FeeOut | 592 | 0 | 587 | 5 | 9.0000 | 33.9840 |

[来源: outpatient_p0_t3_precision_20260827_074356Z Q4 全量聚合；精度修正复核结果未变]

| T_State | T_HasRefundmented | T_PartialReturnFlag | NT_ReTradeFlag | 交易数 | 主无明/明无主 | Fee 缺/通/败；最大/合计差 | FeeIn 缺/通/败；最大/合计差 | FeeOut 缺/通/败；最大/合计差 |
|---:|---:|---|---|---:|---|---|---|---|
| -3 | 0 | NULL | `''` | 2 | 0/0 | 0/0/2；250.0000/300.0000 | 0/2/0；0.0000/0.0000 | 0/2/0；0.0000/0.0000 |
| -3 | 0 | `''` | NULL | 5 | 0/0 | 0/5/0；0.0000/0.0000 | 0/5/0；0.0000/0.0000 | 0/5/0；0.0000/0.0000 |
| -3 | 1 | `''` | NULL | 1 | 0/0 | 0/1/0；0.0000/0.0000 | 0/1/0；0.0000/0.0000 | 0/1/0；0.0000/0.0000 |
| -1 | 0 | `''` | NULL | 1 | 0/0 | 0/1/0；0.0000/0.0000 | 0/1/0；0.0000/0.0000 | 0/1/0；0.0000/0.0000 |
| 3 | 0 | NULL | `''` | 3 | 0/0 | 0/3/0；0.0000/0.0000 | 0/3/0；0.0000/0.0000 | 0/3/0；0.0000/0.0000 |
| 3 | 0 | `''` | NULL | 14 | 0/0 | 0/14/0；0.0000/0.0000 | 0/14/0；0.0000/0.0000 | 0/14/0；0.0000/0.0000 |
| 3 | 1 | NULL | `''` | 5 | 0/0 | 0/5/0；0.0000/0.0000 | 0/5/0；0.0000/0.0000 | 0/5/0；0.0000/0.0000 |
| 3 | 1 | NULL | `1` | 1 | 0/0 | 0/1/0；0.0000/0.0000 | 0/1/0；0.0000/0.0000 | 0/1/0；0.0000/0.0000 |
| 4 | 0 | `''` | NULL | 393 | 0/0 | 0/393/0；0.0000/0.0000 | 0/393/0；0.0030/0.0350 | 0/390/3；8.0000/15.9810 |
| 4 | 1 | `''` | NULL | 133 | 0/0 | 0/133/0；0.0000/0.0000 | 0/133/0；0.0030/0.0030 | 0/132/1；9.0000/9.0030 |
| 4 | 1 | `1` | NULL | 34 | 0/0 | 0/34/0；0.0000/0.0000 | 0/34/0；0.0000/0.0000 | 0/33/1；9.0000/9.0000 |

[来源: outpatient_p0_t3_precision_20260827_074356Z Q4 四状态组合聚合；精度修正复核结果未变]

[推断: 基于 outpatient_p0_t3_20260827_073210Z Q2 与 outpatient_p0_t3_precision_20260827_074356Z Q4] 复合键、T_TradeNo 主从覆盖和 FeeIn 勾稽通过，但 Fee 有 2 笔、FeeOut 有 5 笔超过 0.01 元，金额门禁未通过。差异状态分布不构成有效状态规则；在业务字典签认前不得删除或筛掉这些记录来制造全量通过。

#### 多专项基金候选字段

本节只统计 Task 1 已确认物理存在的字段。NULL、0、非零严格分列；不把 T_FundPay 与任何专项字段相加，也不把共现关系写成业务口径。

| 字段 | 行数 | NULL | 0 | 非零 |
|---|---:|---:|---:|---:|
| T_FundPay | 592 | 0 | 284 | 308 |
| T_BigPay | 592 | 0 | 288 | 304 |
| T_BCPay | 592 | 0 | 571 | 21 |
| T_JCPay | 592 | 0 | 592 | 0 |
| T_OfficalPay | 592 | 0 | 573 | 19 |
| NT_AgencySumPay | 592 | 581 | 5 | 6 |
| NT_BasicPay | 592 | 581 | 9 | 2 |
| NT_CivilPay | 592 | 0 | 590 | 2 |
| NT_OtherPay | 592 | 581 | 11 | 0 |
| T_BigillPay | 592 | 11 | 578 | 3 |
| RETIRE_OFFICER_PAY | 592 | 11 | 573 | 8 |

[来源: outpatient_p0_t3_20260827_073210Z Q5]

共现签名顺序固定为 `T_FundPay | NT_AgencySumPay | NT_BasicPay | NT_CivilPay | NT_OtherPay`；`N`=NULL、`Z`=0、`V`=非零。

| 共现签名 | 行数 |
|---|---:|
| V\|N\|N\|Z\|N | 306 |
| Z\|N\|N\|Z\|N | 273 |
| Z\|Z\|Z\|Z\|Z | 5 |
| Z\|V\|Z\|Z\|Z | 4 |
| V\|N\|N\|V\|N | 2 |
| Z\|V\|V\|Z\|Z | 2 |

[来源: outpatient_p0_t3_20260827_073210Z Q6]

`NT_AgencySumPay = NT_BasicPay + NT_CivilPay + NT_OtherPay` 仅按字段名作为候选等式验证，不视为权威业务公式。

| 范围 | 行数 | 缺 | 通 | 败 | 最大绝对差（元） | 合计绝对差（元） |
|---|---:|---:|---:|---:|---:|---:|
| 全量 | 592 | 581 | 5 | 6 | 537.7600 | 1,204.5200 |

| T_State | T_HasRefundmented | T_PartialReturnFlag | NT_ReTradeFlag | 行数 | 缺/通/败 | 最大/合计差（元） |
|---:|---:|---|---|---:|---|---:|
| -3 | 0 | NULL | `''` | 2 | 0/2/0 | 0.0000/0.0000 |
| -3 | 0 | `''` | NULL | 5 | 5/0/0 | NULL/NULL |
| -3 | 1 | `''` | NULL | 1 | 1/0/0 | NULL/NULL |
| -1 | 0 | `''` | NULL | 1 | 1/0/0 | NULL/NULL |
| 3 | 0 | NULL | `''` | 3 | 0/1/2 | 55.0000/105.0000 |
| 3 | 0 | `''` | NULL | 14 | 14/0/0 | NULL/NULL |
| 3 | 1 | NULL | `''` | 5 | 0/2/3 | 537.7600/1,087.5200 |
| 3 | 1 | NULL | `1` | 1 | 0/0/1 | 12.0000/12.0000 |
| 4 | 0 | `''` | NULL | 393 | 393/0/0 | NULL/NULL |
| 4 | 1 | `''` | NULL | 133 | 133/0/0 | NULL/NULL |
| 4 | 1 | `1` | NULL | 34 | 34/0/0 | NULL/NULL |

[来源: outpatient_p0_t3_20260827_073210Z Q7]

[推断: 基于 Q5–Q7] 候选分项字段 581/592 行不完整，在仅 11 行可比较记录中仍有 6 行超过容差；这些结果否定“当前数据已证明候选等式”的说法，但不能反向证明字段间真实业务关系。业务字典与医保办签认前，所有专项基金关系均保持候选/待确认。

#### 30 个脱敏锚点人工票据核对

状态：`MANUAL_TICKET_RECONCILIATION_BLOCKED`。

[来源: 本任务执行边界] 当前没有医保办票据、票据访问授权人员或获批的脱敏锚点传递通道，因此本批次没有选取、导出或展示任何原始锚点，也没有用数据库行代替人工票据核对。

解锁所需外部输入：至少 30 份由医保办在批准环境内选取的票据及其脱敏锚点映射；覆盖规则和有效状态范围；权威金额/退款/冲正字典；逐票据主金额与费用明细核对表。原始票据和行级映射只保存在医院批准的受控通道，本文仅接收脱敏聚合结论与签认结果。

签认角色：医保办授权经办人执行逐票核对，医保办负责人签认票据与金额口径，数据负责人签认字段和有效状态规则，信息安全/隐私负责人批准票据访问及脱敏传递边界。

#### 唯一费用明细源决定

| 冻结门槛 | 结果 | 状态 |
|---|---|---|
| 复合键与主从关联 | 复合键无重复；592/592 主交易均有明细，主表无明细 0、明细无主表 0 | 通过 |
| 金额勾稽 | Fee 2 笔失败、FeeOut 5 笔失败；两组 o_Trade 自身等式也分别有 5、6 笔失败 | 未通过 |
| 有效状态规则 | 四状态组合已聚合，但没有权威状态字典和筛选规则 | BLOCKED |
| 至少 30 个票据人工核对 | 无票据和授权人员，未选取或导出锚点 | `MANUAL_TICKET_RECONCILIATION_BLOCKED` |
| dbo.o_FeeItem 唯一费用明细源 | 仅保持候选；不冻结 | BLOCKED |

[推断: 基于 outpatient_p0_t3_20260827_073210Z 与冻结门槛] dbo.o_FeeItem 的键和关联门槛通过，但金额、有效状态和人工票据三项门槛未全部通过，因此不能冻结为唯一费用明细源。

[推断: 基于数据侧已出现超过容差的实质差异] `yb_mzfymx_mz` 仅登记为下一步**待授权验证候选**；本任务没有查询该表，也没有扩大 Task 1 的 dbo.o_Trade、dbo.o_FeeItem 两表白名单。只有取得额外表授权后才能单独验证，不能据字段名预设其优于 dbo.o_FeeItem。

## 增量游标

待验证。Task 1 仅确认候选时间字段 T_TradeDate 为 datetime NOT NULL，T_ConfirmTime、SETL_DATE、T_HadDealTime 为 datetime NULL；没有验证时间范围、重复时间点、迟到数据、回写更新或组合游标稳定性。

## 容量与性能

| 项目 | Task 1 证据 |
|---|---|
| 发现结果规模 | 2 表、236 字段；检查点快照行数合计 2,731 |
| 发现任务持久化耗时 | 约 0.379 秒 |
| 实际扫描模式 | 两表均 cached=true |

上述耗时只证明“列结构哈希核对 + 检查点复用”可完成，不证明真实全表统计的吞吐、锁影响、超时边界或生产容量。新鲜全量画像及执行计划待验证。

## 政策 Skill 依赖

### Task 4：政策解释最小字段闭包

#### 独立对照结论

文档级非数据库审计证据批次：`outpatient_p0_t4_20260827_policy_closure`。聚合执行完成戳为 `2026-08-27T08:01:38.5137703Z`（`2026-08-27 16:01:38.5137703 +08:00`）；主体指纹仍为 `38F144F8D609E1F6CFA0E3B2E4225EF783A0B313A98262F71FC0862BF97ACD70`，只引用 Task 1 已留存的脱敏主体证据，不记录账号、连接、患者或业务标识值。数据源经 `PolicyMetaStore(DATABASE_URL)`、`SemanticDataSource(meta_store=meta)` 和 datasource `bjybdb` 解析；初始化 stdout 已重定向。本批次 SQL Server 只执行 `SET`/`SELECT`。

[来源: 总设计 §9.2–§10.6；Issue 20 设计 §4–§6；`skills/settlement_explain_skill/{SKILL.md,schemas,assembler.py,fact_builder.py,scripts/normalize_fee_context.py,strategies/*/policy_queries.yaml}`；`src/runtime/policy_qa/{settlement_data_provider.py,structured_policy_retriever.py}`]

- 当前 `settlement_explain_skill` 是住院费用解释：数据提供器读取五张住院表；assembler/fact_builder 消费住院起付、统筹、大额和个人支付字段；政策检索的确定性过滤实际依赖 `insu_type`、`med_type`、`hosp_lv`、`psn_type`，现有 `NormalizedPolicyContext` 尚无地区、结算日期、异地、慢特病、专项待遇或政策适用机构字段。
- 现有住院标准化器会在缺值时补“城镇职工”“住院-普通住院”“三级医院”“退休人员”。[推断: 基于现有代码] 这些是门诊新 Skill 必须禁止继承的住院默认值；门诊上下文缺失必须保持 `missing`/`missing_external_context`。
- 设计字段按 `table.column` 去重后为 104 个（`o_Trade` 84、`o_FeeItem` 20；同名 `T_TradeNo` 是两张表各自的物理列），本次全部物理存在。A–F 共 107 个可聚合物理字段（104 个设计字段 + 3 个政策上下文物理候选）完成画像；G 组 8 个敏感字段只引用 Task 1 `INFORMATION_SCHEMA` 元数据、不做数据画像；另登记 3 个不可由两表提供的外部上下文。矩阵共 118 行。
- 物理存在不等于语义闭包完成。除 Task 2 已证明的内部交易/明细键外，当前没有院方字段字典或医保办签认足以把字段名候选升级为权威业务含义；尤其 `TB_*`/`TA_*` 不得仅凭前缀解释为交易前/后。

矩阵缩写：`n/z/v/d` 分别为 NULL、显式零（字符串为显式空串）、非零/非空、distinct；`oT`=`dbo.o_Trade`（592 行），`oF`=`dbo.o_FeeItem`（2,139 行）。`S1` 为授权场景内普通医保事实，`S2` 为可关联业务键/敏感健康事实（仅内部受限使用），`S3` 为直接标识或明确排除字段。Profile：P1 整体结算，P2 个人负担，P3 支付渠道，P4 起付与年度累计，P5 比例与封顶，P6 目录与明细，P7 身份与专项，P8 异地与机构，P9 状态与退费，`ALL` 表示九个 Profile 的内部定位依赖。

“是否核心”按用户任务而非字段数量判定：Issue20 §4 的公共上下文与 §5.2 强制锚点为“通用核心”；总设计 §9.4/§10 及 Issue20 §4/§5.4 中决定某 Profile 能否产生主要输出的字段为“对应Profile核心”；重复候选、内部去重或不能单独形成结论的字段为“辅助”；必须由可信系统注入且缺失即不能判断的上下文为“外部核心”；禁止进入公开 Skill 的字段为“排除”。[来源: 总设计 §9.3–§10.6；Issue20 §4–§6]

##### A. 交易定位与状态（13 个）

| 语义名 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 强制内部结算锚点（当前多笔歧义） / `T_SetTid` | oT | varchar(30) NULL | 是 | 11/324/257/257 | [来源: Issue20 §5.2 强制 `settlement_id→T_SetTid`；Task 2 证明不能唯一定位] | S2，内部定位 | ALL | 通用核心 | `semantics_pending` |
| 交易业务键 / `T_TradeNo` | oT | nvarchar(22) NOT NULL | 是 | 0/0/592/592 | [来源: Task 2 全量非空唯一] | S2，禁止公开 | P1,P6,P9 | 对应Profile核心 | `verified` |
| 交易日期 / `T_TradeDate` | oT | datetime NOT NULL | 是 | 0/0/592/540 | [来源: D10.1/I5.4A；时区语义未签认] | S1 | P1,P4,P5,P9 | 对应Profile核心 | `semantics_pending` |
| 交易状态 / `T_State` | oT | int NOT NULL | 是 | 0/0/592/4 | [来源: D10.1/I5.4A；无权威码表] | S1 | P1,P9 | 对应Profile核心 | `semantics_pending` |
| 已退款标志 / `T_HasRefundmented` | oT | int NOT NULL | 是 | 0/418/174/2 | [来源: D10.1/I5.4A；无权威码表] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 部分退费标志 / `T_PartialReturnFlag` | oT | nvarchar(1) NULL | 是 | 11/547/34/2 | [来源: D10.1/I5.4A；无权威码表] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 原交易号 / `T_OraginalTradeNo` | oT | nvarchar(22) NULL | 是 | 0/504/88/88 | [来源: D10.1/I5.4A；退款链含义未签认] | S2，禁止公开 | P9 | 对应Profile核心 | `semantics_pending` |
| 原交易日期 / `T_OraginalTradeDate` | oT | datetime NULL | 是 | 469/0/123/87 | [来源: D10.1/I5.4A；退款链含义未签认] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 国家平台结算状态 / `NP_Settle_State` | oT | varchar(1) NULL | 是 | 11/0/581/2 | [来源: D10.1/I5.4A；无权威码表] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 国家平台结算日期 / `SETL_DATE` | oT | datetime NULL | 是 | 17/0/575/257 | [来源: D10.1/I5.4A；与交易日期优先级未签认] | S1 | P5,P9 | 对应Profile核心 | `semantics_pending` |
| 重交易标志 / `NT_ReTradeFlag` | oT | varchar(3) NULL | 是 | 581/10/1/2 | [来源: D10.1/I5.4A；无权威码表] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 诊断交易类型 / `T_DiagType` | oT | nvarchar(1) NULL | 是 | 0/0/592/5 | [来源: I5.4A；无权威码表] | S1 | P5,P7 | 辅助 | `semantics_pending` |
| 费用号 / `T_FeeNo` | oT | nvarchar(20) NULL | 是 | 0/143/449/402 | [来源: I5.4A；内部关联用途未签认] | S2，禁止公开 | P1,P6 | 辅助 | `semantics_pending` |

##### B. 待遇身份与政策匹配（21 个）

| 语义名 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 险种 / `P_FundType` | oT | int NOT NULL | 是 | 0/0/592/9 | [来源: D10.2/I5.4B；现有检索要求 insu_type；无码表] | S1 | P1,P5,P7,P8 | 对应Profile核心 | `semantics_pending` |
| 人员类别 / `PN_PersonType` | oT | int NOT NULL | 是 | 0/0/592/28 | [来源: D10.2/I5.4B；现有检索要求 psn_type；无码表] | S1 | P2,P5,P7 | 对应Profile核心 | `semantics_pending` |
| 医疗类别 / `T_CureType` | oT | int NOT NULL | 是 | 0/0/592/4 | [来源: D10.2/I5.4B；现有检索要求 med_type；无码表] | S1 | P1,P5,P8 | 对应Profile核心 | `semantics_pending` |
| 机构待遇等级候选 / `P_JCLevel` | oT | int NOT NULL | 是 | 0/572/20/3 | [来源: D10.2/I5.4B；不能仅凭字段名等同 hosp_lv] | S1 | P5,P8 | 对应Profile核心 | `semantics_pending` |
| 医院待遇标志 / `P_HospFlag` | oT | int NOT NULL | 是 | 0/570/22/3 | [来源: D10.2/I5.4B；无权威码表] | S1 | P7,P8 | 辅助 | `semantics_pending` |
| 异地交易标志 / `PN_OutTransaction` | oT | nvarchar(3) NULL | 是 | 11/79/502/2 | [来源: D10.2/I5.4B；空串不等于否] | S1 | P8 | 对应Profile核心 | `semantics_pending` |
| 国家险种 / `PN_NationFundType` | oT | varchar(6) NULL | 是 | 581/0/11/1 | [来源: D10.2/I5.4B；无码表] | S1 | P5,P7,P8 | 对应Profile核心 | `semantics_pending` |
| 慢特病标志 / `PN_ChronicFlag` | oT | nvarchar(2) NOT NULL | 是 | 0/11/581/2 | [来源: D10.2/I5.4B；无码表] | S2，健康事实 | P5,P7 | 对应Profile核心 | `semantics_pending` |
| 慢特病代码 / `PN_ChronicCode` | oT | nvarchar(50) NOT NULL | 是 | 0/592/0/1 | [来源: D10.2/I5.4B；不输出代码样例] | S2，健康事实 | P5,P7 | 对应Profile核心 | `semantics_pending` |
| 慢特病定点机构标志 / `PN_IsChronicHosp` | oT | nvarchar(2) NOT NULL | 是 | 0/0/592/1 | [来源: D10.2/I5.4B；无码表] | S2，健康事实 | P5,P7,P8 | 对应Profile核心 | `semantics_pending` |
| 公务员待遇候选 / `P_Official` | oT | int NOT NULL | 是 | 0/503/89/3 | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 对应Profile核心 | `semantics_pending` |
| 退休待遇标志 / `P_retirementflag` | oT | varchar(50) NULL | 是 | 587/0/5/2 | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P5,P7 | 辅助 | `semantics_pending` |
| 民政待遇标志 / `P_CivilFlag` | oT | varchar(10) NULL | 是 | 11/0/581/2 | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 对应Profile核心 | `semantics_pending` |
| 民政待遇类型 / `P_CivilType` | oT | varchar(10) NULL | 是 | 11/0/581/5 | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 对应Profile核心 | `semantics_pending` |
| 退役军官待遇标志 / `RETIRE_OFFICER_FLAG` | oT | varchar(1) NULL | 是 | 11/0/581/2 | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 对应Profile核心 | `semantics_pending` |
| 公费归属标志 / `T_GFBelongFlag` | oT | varchar(50) NULL | 是 | 585/0/7/1 | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 辅助 | `semantics_pending` |
| 补充医院标志 / `T_CompHospFlag` | oT | varchar(50) NULL | 是 | 585/0/7/1 | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7,P8 | 辅助 | `semantics_pending` |
| 专项结算标志 / `T_SpSetlFlag` | oT | varchar(3) NULL | 是 | 11/7/574/2 | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 对应Profile核心 | `semantics_pending` |
| 专项待遇内部号 / `T_pneno` | oT | varchar(50) NULL | 是 | 583/9/0/1 | [来源: D10.2/I5.4B；内部号含义未签认] | S2，禁止公开 | P7 | 辅助 | `semantics_pending` |
| 全自费标志 / `NT_AllSelfPayFlag` | oT | varchar(3) NULL | 是 | 581/2/9/2 | [来源: D10.2/I5.4B；无码表] | S1 | P1,P2,P7 | 对应Profile核心 | `semantics_pending` |
| 无待遇原因 / `PN_NoRightReason` | oT | nvarchar(20) NULL | 是 | 0/435/157/6 | [来源: D10.2/I5.4B；自由文本不输出样例] | S2，受限文本 | P7,P9 | 对应Profile核心 | `semantics_pending` |

##### C. 当次费用与支付（26 个）

| 语义名 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 总费用 / `T_FeeAll` | oT | decimal(10,2) NOT NULL | 是 | 0/2/590/60 | [来源: D10.3/I5.4C；Task 3 公式有超差] | S1 | P1 | 对应Profile核心 | `semantics_pending` |
| 医保内费用 / `T_FeeIn` | oT | decimal(10,2) NOT NULL | 是 | 0/241/351/73 | [来源: D10.3/I5.4C；Task 3 公式有超差] | S1 | P1,P5,P6 | 对应Profile核心 | `semantics_pending` |
| 医保外费用 / `T_FeeOut` | oT | decimal(10,2) NOT NULL | 是 | 0/127/465/71 | [来源: D10.3/I5.4C；Task 3 公式有超差] | S1 | P1,P2,P6 | 对应Profile核心 | `semantics_pending` |
| 起付金额 / `T_FirstPay` | oT | decimal(10,2) NOT NULL | 是 | 0/541/51/24 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P4,P5 | 对应Profile核心 | `semantics_pending` |
| 自付一 / `T_SelfPay1` | oT | decimal(10,2) NOT NULL | 是 | 0/491/101/49 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P5 | 对应Profile核心 | `semantics_pending` |
| 自付二 / `T_SelfPay2` | oT | decimal(10,2) NOT NULL | 是 | 0/417/175/35 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P6 | 对应Profile核心 | `semantics_pending` |
| 个人自付合计 / `T_SelfPayAll` | oT | decimal(10,2) NOT NULL | 是 | 0/128/464/86 | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P1,P2 | 对应Profile核心 | `semantics_pending` |
| 大额基金支付 / `T_BigPay` | oT | decimal(10,2) NOT NULL | 是 | 0/288/304/72 | [来源: D10.3/I5.4C；口径待签认] | S1 | P3,P5,P7 | 对应Profile核心 | `semantics_pending` |
| 大额个人自付 / `T_BigSelfPay` | oT | decimal(10,2) NOT NULL | 是 | 0/529/63/33 | [来源: D10.3/I5.4C；口径待签认] | S1 | P2,P5 | 对应Profile核心 | `semantics_pending` |
| 超大额费用 / `T_BeyondBig` | oT | decimal(10,2) NOT NULL | 是 | 0/588/4/5 | [来源: D10.3/I5.4C；口径待签认] | S1 | P2,P5 | 对应Profile核心 | `semantics_pending` |
| 基金支付总额候选 / `T_FundPay` | oT | decimal(10,2) NOT NULL | 是 | 0/284/308/77 | [来源: D10.3/I5.4C；不得与分项盲加] | S1 | P1,P3 | 对应Profile核心 | `semantics_pending` |
| 个人账户支付 / `T_PersonCountPay` | oT | decimal(10,2) NOT NULL | 是 | 0/465/127/44 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P3 | 对应Profile核心 | `semantics_pending` |
| 现金支付 / `T_CashPay` | oT | decimal(10,2) NOT NULL | 是 | 0/239/353/72 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P3 | 对应Profile核心 | `semantics_pending` |
| 交易前账户余额候选 / `PN_PersonCount` | oT | decimal(10,2) NOT NULL | 是 | 0/468/124/85 | [来源: D10.3/I5.4C；前后语义待签认] | S1 | P3 | 对应Profile核心 | `semantics_pending` |
| 交易后账户余额候选 / `T_PersonCountAfter` | oT | decimal(10,2) NOT NULL | 是 | 0/486/106/80 | [来源: D10.3/I5.4C；前后语义待签认] | S1 | P3 | 对应Profile核心 | `semantics_pending` |
| 补充支付 / `T_BCPay` | oT | decimal(10,2) NOT NULL | 是 | 0/571/21/14 | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P3,P7 | 对应Profile核心 | `semantics_pending` |
| 字段语义冲突：救助/军残支付候选 / `T_JCPay` | oT | decimal(10,2) NOT NULL | 是 | 0/592/0/1 | [来源: D10.3/I5.4C 仅列字段；Issue20 §4 的专项待遇同时涉及救助与军残；无字典不得二选一] | S1 | P3,P7 | 对应Profile核心 | `semantics_pending` |
| 公疗支付 / `T_OfficalPay` | oT | numeric(12,2) NULL | 是 | 0/573/19/11 | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P3,P7 | 对应Profile核心 | `semantics_pending` |
| 大病支付 / `T_BigillPay` | oT | decimal(10,2) NULL | 是 | 11/578/3/4 | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P3,P7 | 对应Profile核心 | `semantics_pending` |
| 国家基础支付 / `NT_BasicPay` | oT | numeric(16,2) NULL | 是 | 581/9/2/3 | [来源: D10.3/I5.4C；总分关系待签认] | S1 | P3 | 对应Profile核心 | `semantics_pending` |
| 国家民政支付 / `NT_CivilPay` | oT | numeric(16,2) NULL | 是 | 0/590/2/3 | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P3,P7 | 对应Profile核心 | `semantics_pending` |
| 国家其他支付 / `NT_OtherPay` | oT | numeric(16,2) NULL | 是 | 581/11/0/1 | [来源: D10.3/I5.4C；零不能推出不适用] | S1 | P3 | 对应Profile核心 | `semantics_pending` |
| 经办支付合计候选 / `NT_AgencySumPay` | oT | numeric(16,2) NULL | 是 | 581/5/6/7 | [来源: D10.3/I5.4C；不得与分项盲加] | S1 | P1,P3 | 对应Profile核心 | `semantics_pending` |
| 退役军官支付 / `RETIRE_OFFICER_PAY` | oT | decimal(10,2) NULL | 是 | 11/573/8/5 | [来源: D10.3/I5.4C；资格联动待签认] | S1 | P3,P7 | 对应Profile核心 | `semantics_pending` |
| 异地二次比例候选 / `NT_OUT2_SCALE` | oT | numeric(16,2) NULL | 是 | 581/8/3/4 | [来源: D10.3/I5.4C；比例单位待签认] | S1 | P5,P8 | 对应Profile核心 | `semantics_pending` |
| 异地二次金额候选 / `NT_OUT2_PRICE` | oT | numeric(16,2) NULL | 是 | 581/8/3/3 | [来源: D10.3/I5.4C；金额口径待签认] | S1 | P5,P8 | 对应Profile核心 | `semantics_pending` |

##### D. 年度累计、起付与封顶（24 个）

下列 `TB_*`/`TA_*` 仅登记物理类型和聚合；“交易前/后”均是设计候选，不是已验证含义。`TA_MZTimes` 的物理类型为 `int`，与设计的 Count 类型不冲突，但没有字段字典证明 `TA` 或其与 `TB_MZTimes` 的增量语义，故继续阻断。

| 语义候选 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 交易前医保内累计候选 / `TB_FeeIn` | oT | decimal(10,2) NOT NULL | 是 | 0/441/151/57 | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易后医保内累计候选 / `TA_FeeIn` | oT | decimal(10,2) NOT NULL | 是 | 0/261/331/131 | 同上 | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易前大额累计候选 / `TB_BigPay` | oT | decimal(10,2) NOT NULL | 是 | 0/456/136/49 | 同上 | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易后大额累计候选 / `TA_BigPay` | oT | decimal(10,2) NOT NULL | 是 | 0/287/305/92 | 同上 | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易前封顶后费用候选 / `TB_FeeAfterBig` | oT | decimal(10,2) NOT NULL | 是 | 0/586/6/5 | 同上 | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易后封顶后费用候选 / `TA_FeeAfterBig` | oT | decimal(10,2) NOT NULL | 是 | 0/586/6/7 | 同上 | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易前门诊次数候选 / `TB_MZTimes` | oT | int NOT NULL | 是 | 0/587/5/2 | [来源: D10.4/I5.4D；无字段字典] | S1 | P4 | 对应Profile核心 | `semantics_pending` |
| 交易后门诊次数候选 / `TA_MZTimes` | oT | int NOT NULL | 是 | 0/359/233/3 | [来源: D10.4/I5.4D；类型为 int，释义仍冲突待解] | S1 | P4 | 对应Profile核心 | `semantics_pending` |
| 交易前超封顶医保内候选 / `TB_BeyondFeeIn` | oT | decimal(10,2) NULL | 是 | 11/581/0/1 | [来源: D10.4/I5.4D；零不能推出不适用] | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易后超封顶医保内候选 / `TA_BeyondFeeIn` | oT | decimal(10,2) NULL | 是 | 11/575/6/7 | 同组释义无字典 | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易前大病累计基数候选 / `TB_BigillComm` | oT | decimal(10,2) NULL | 是 | 11/489/92/40 | 同组释义无字典 | S1 | P4,P5,P7 | 对应Profile核心 | `semantics_pending` |
| 交易后大病累计基数候选 / `TA_BigillComm` | oT | decimal(10,2) NULL | 是 | 11/393/188/93 | 同组释义无字典 | S1 | P4,P5,P7 | 对应Profile核心 | `semantics_pending` |
| 交易前大病支付累计候选 / `TB_BigillPay` | oT | decimal(10,2) NULL | 是 | 11/550/31/5 | 同组释义无字典 | S1 | P4,P5,P7 | 对应Profile核心 | `semantics_pending` |
| 交易后大病支付累计候选 / `TA_BigillPay` | oT | decimal(10,2) NULL | 是 | 11/550/31/6 | 同组释义无字典 | S1 | P4,P5,P7 | 对应Profile核心 | `semantics_pending` |
| 交易前民政累计基数候选 / `TB_CivilComm` | oT | decimal(10,2) NULL | 是 | 11/574/7/6 | 同组释义无字典 | S1 | P4,P7 | 对应Profile核心 | `semantics_pending` |
| 交易后民政累计基数候选 / `TA_CivilComm` | oT | decimal(10,2) NULL | 是 | 11/574/7/7 | 同组释义无字典 | S1 | P4,P7 | 对应Profile核心 | `semantics_pending` |
| 交易前民政支付累计候选 / `TB_CivilPay` | oT | decimal(10,2) NULL | 是 | 11/574/7/5 | 同组释义无字典 | S1 | P4,P7 | 对应Profile核心 | `semantics_pending` |
| 交易后民政支付累计候选 / `TA_CivilPay` | oT | decimal(10,2) NULL | 是 | 11/574/7/4 | 同组释义无字典 | S1 | P4,P7 | 对应Profile核心 | `semantics_pending` |
| 交易前一级机构医保内候选 / `TB_FeeInL1` | oT | decimal(10,2) NULL | 是 | 0/587/5/3 | 同组释义无字典 | S1 | P4,P5,P8 | 对应Profile核心 | `semantics_pending` |
| 交易后一级机构医保内候选 / `TA_FeeInL1` | oT | decimal(10,2) NULL | 是 | 0/587/5/3 | 同组释义无字典 | S1 | P4,P5,P8 | 对应Profile核心 | `semantics_pending` |
| 交易前一级机构大额候选 / `TB_BigPayL1` | oT | decimal(10,2) NULL | 是 | 0/590/2/2 | 同组释义无字典 | S1 | P4,P5,P8 | 对应Profile核心 | `semantics_pending` |
| 交易后一级机构大额候选 / `TA_BigPayL1` | oT | decimal(10,2) NULL | 是 | 0/590/2/2 | 同组释义无字典 | S1 | P4,P5,P8 | 对应Profile核心 | `semantics_pending` |
| 交易前一级机构封顶后候选 / `TB_FeeAfterBigL1` | oT | decimal(10,2) NULL | 是 | 0/589/3/2 | 同组释义无字典 | S1 | P4,P5,P8 | 对应Profile核心 | `semantics_pending` |
| 交易后一级机构封顶后候选 / `TA_FeeAfterBigL1` | oT | decimal(10,2) NULL | 是 | 0/589/3/2 | 同组释义无字典 | S1 | P4,P5,P8 | 对应Profile核心 | `semantics_pending` |

##### E. 费用明细（20 个）

| 语义名 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 交易外键 / `T_TradeNo` | oF | nvarchar(22) NOT NULL | 是 | 0/0/2139/592 | [来源: Task 2 全量无孤儿，N:1 到 oT] | S2，禁止公开 | P6 | 对应Profile核心 | `verified` |
| 明细键组成 / `ItemId` | oF | int NOT NULL | 是 | 0/592/1547/33 | [来源: Task 2 复合键非空唯一] | S2，内部键 | P6 | 辅助 | `verified` |
| 明细键组成 / `ItemNo` | oF | int NOT NULL | 是 | 0/82/2057/51 | [来源: Task 2 复合键非空唯一] | S2，内部键 | P6 | 辅助 | `verified` |
| 院内项目代码 / `ItemCode` | oF | nvarchar(40) NOT NULL | 是 | 0/0/2139/98 | [来源: D10.5/I5.4E；代码体系未签认] | S2，健康事实 | P6 | 对应Profile核心 | `semantics_pending` |
| 标准项目代码 / `StandardCode` | oF | varchar(40) NULL | 是 | 0/0/2139/92 | [来源: D10.5/I5.4E；代码体系未签认] | S2，健康事实 | P6 | 辅助 | `semantics_pending` |
| 项目名称 / `ItemName` | oF | nvarchar(100) NOT NULL | 是 | 0/0/2139/94 | [来源: D10.5/I5.4E；授权解释内最小展示] | S2，健康事实 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目类型 / `ItemType` | oF | int NOT NULL | 是 | 0/670/1469/4 | [来源: D10.5/I5.4E；无码表] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 费用类型 / `FeeType` | oF | nvarchar(4) NOT NULL | 是 | 0/0/2139/17 | [来源: D10.5/I5.4E；无码表] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 医保项目等级 / `F_LEVEL` | oF | nvarchar(3) NULL | 是 | 0/0/2139/4 | [来源: D10.5/I5.4E；无码表] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 数量 / `Count` | oF | numeric(10,2) NOT NULL | 是 | 0/7/2132/16 | [来源: D10.5/I5.4E；单位关系待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 单价 / `UnitPrice` | oF | decimal(10,4) NOT NULL | 是 | 0/0/2139/74 | [来源: D10.5/I5.4E；舍入规则待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目费用 / `Fee` | oF | decimal(10,4) NOT NULL | 是 | 0/7/2132/119 | [来源: D10.5/I5.4E；Task 3 逐交易有超差] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目医保内候选 / `FeeIn` | oF | decimal(10,4) NOT NULL | 是 | 0/1020/1119/129 | [来源: D10.5/I5.4E；Task 3 口径未冻结] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目医保外候选 / `FeeOut` | oF | decimal(10,4) NOT NULL | 是 | 0/874/1265/95 | [来源: D10.5/I5.4E；Task 3 口径未冻结] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目自付二 / `SelfPay2` | oF | decimal(10,4) NOT NULL | 是 | 0/1917/222/44 | [来源: D10.5/I5.4E；汇总关系待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目先自付比例 / `FEE_SP_SCALE` | oF | decimal(18,4) NULL | 是 | 0/2040/99/26 | [来源: D10.5/I5.4E；比例单位待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目超限价自付 / `FEE_MEDIC_L` | oF | decimal(18,4) NULL | 是 | 0/2097/42/8 | [来源: D10.5/I5.4E；口径待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 超限价自付候选 / `MEDIC_L` | oF | decimal(5,4) NULL | 是 | 0/2036/103/3 | [来源: D10.5/I5.4E；与 FEE_MEDIC_L 关系待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 特殊药品标志 / `SPEDRUG_FLAG` | oF | varchar(3) NULL | 是 | 0/0/2139/1 | [来源: D10.5/I5.4E；零/代码不能推出不适用] | S2，健康事实 | P6,P7 | 对应Profile核心 | `semantics_pending` |
| 明细状态 / `State` | oF | int NOT NULL | 是 | 0/1757/382/2 | [来源: D10.5/I5.4E；无权威有效码表] | S1 | P6,P9 | 对应Profile核心 | `semantics_pending` |

##### F. 现有政策检索上下文与可信外部依赖（6 个）

| 语义名 / 原物理字段 | 源或可信上下文 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 参保地区候选 / `PN_InsuredAreaCode` | oT | varchar(6) NULL | 是 | 581/0/11/1 | [推断: 字段名只支持参保地区候选，不能等同政策地区] | S2 | P5,P7,P8 | 辅助 | `semantics_pending` |
| 机构代码候选 / `T_HospCode` | oT | nvarchar(10) NOT NULL | 是 | 0/0/592/1 | [推断: 需医院主数据映射，不输出代码] | S2，机构内部键 | P5,P8 | 辅助 | `semantics_pending` |
| 机构代码候选 A / `T_HospCodeA` | oT | nvarchar(10) NOT NULL | 是 | 0/0/592/2 | [推断: 与 T_HospCode 关系未签认] | S2，机构内部键 | P5,P8 | 辅助 | `semantics_pending` |
| 政策地区 / `policy_region` | 可信 HIS/医保接入上下文 + 政策元数据 | — | 否 | — | [来源: 现有政策检索缺该字段；不能用 PN_InsuredAreaCode 直接替代] | S1 | P5,P7,P8 | 外部核心 | `missing_external_context` |
| 登录医院与政策适用机构 / `hospital_id`,`policy_applicable_institution` | 登录组织 + 医院主数据 + 政策适用机构元数据 | — | 否 | — | [来源: Issue20 公共上下文 hospital_id；两表代码未获映射] | S2 | P5,P8 | 外部核心 | `missing_external_context` |
| 规范化专项待遇类型 / `special_benefit_type` | 可信资格接口 + 已发布政策证据 | — | 否 | — | [推断: 多个专项标志不能无字典合成统一资格事实] | S2，待遇事实 | P5,P7 | 外部核心 | `missing_external_context` |

上述六行与 A/B 组共同明确核对了地区、结算日期、险种、人员类别、医疗类别、机构级别、异地、慢特病、专项待遇、`hospital_id` 与政策适用机构。结算日期可从 `T_TradeDate`/`SETL_DATE` 读取但优先级和时区待签认；险种、人员类别、医疗类别、机构等级候选均存在但码表待签认。门诊新 Skill 不使用相似住院字段替代。

##### G. 明确排除的敏感字段（8 个）

这里只保留 Task 1 `INFORMATION_SCHEMA.COLUMNS` 已确认的存在性与物理类型，不执行也不展示 NULL、零、非零或 distinct 统计。它们不进入公开 Skill 语义模型；若受限内部定位确需使用，必须经最小权限、`security/desensitization` 和审计边界。

| 语义 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 身份证件号 / `P_IDNo` | oT | nvarchar(50) NULL | 是 | not_profiled（敏感排除） | [来源: Task 1 元数据；Task 4 安全边界] | S3 | — | 排除 | `excluded_sensitive` |
| 医保卡号 / `P_ICNo` | oT | nvarchar(12) NOT NULL | 是 | not_profiled（敏感排除） | 同上 | S3 | — | 排除 | `excluded_sensitive` |
| 姓名 / `P_Name` | oT | nvarchar(50) NOT NULL | 是 | not_profiled（敏感排除） | 同上 | S3 | — | 排除 | `excluded_sensitive` |
| 出生日期 / `P_Birthday` | oT | datetime NOT NULL | 是 | not_profiled（敏感排除） | 同上 | S3 | — | 排除 | `excluded_sensitive` |
| 卡号 / `P_CardNo` | oT | nvarchar(12) NULL | 是 | not_profiled（敏感排除） | 同上 | S3 | — | 排除 | `excluded_sensitive` |
| 处方号 / `RecipeNo` | oF | nvarchar(20) NOT NULL | 是 | not_profiled（敏感排除） | 同上 | S3 | — | 排除 | `excluded_sensitive` |
| HIS 名称 / `HisName` | oF | nvarchar(100) NOT NULL | 是 | not_profiled（敏感排除） | 同上 | S3 | — | 排除 | `excluded_sensitive` |
| HIS 代码 / `HisCode` | oF | nvarchar(40) NOT NULL | 是 | not_profiled（敏感排除） | 同上 | S3 | — | 排除 | `excluded_sensitive` |

#### 安全低基数枚举码聚合

下表只输出不直接标识患者的代码及计数；`PN_PersonType` distinct=28，超过低基数阈值 20，未输出值。自由文本、诊断代码、姓名、证件、卡、处方、项目名称以及全部业务键均未输出样例。

| 字段 | 安全代码:计数 |
|---|---|
| `T_State` | `4:560, 3:23, -3:8, -1:1` |
| `T_HasRefundmented` | `0:418, 1:174` |
| `T_PartialReturnFlag` | `空串:547, 1:34, NULL:11` |
| `NP_Settle_State` | `1:550, 0:31, NULL:11` |
| `NT_ReTradeFlag` | `NULL:581, 空串:10, 1:1` |
| `T_DiagType` | `2:298, 4:213, 3:56, 5:23, 1:2` |
| `P_FundType` | `32:255, 3:168, 33:35, 80:34, 91:34, 31:30, 93:19, 999:11, 92:6` |
| `T_CureType` | `19:281, 11:121, 17:96, 18:94` |
| `P_JCLevel` | `0:572, 5:15, 3:5` |
| `P_HospFlag` | `0:570, 1:19, 2:3` |
| `PN_OutTransaction` | `0:502, 空串:79, NULL:11` |
| `PN_NationFundType` | `NULL:581, 310:11` |
| `PN_ChronicFlag` | `00:581, 空串:11` |
| `PN_IsChronicHosp` | `0:592` |
| `P_Official` | `0:503, 1:80, 11:9` |
| `P_retirementflag` | `NULL:587, 1:3, 0:2` |
| `P_CivilFlag` | `0:550, 1:31, NULL:11` |
| `P_CivilType` | `0:550, 25:14, NULL:11, 336001:9, 2364:5, 336011:3` |
| `RETIRE_OFFICER_FLAG` | `0:567, 1:14, NULL:11` |
| `T_GFBelongFlag` / `T_CompHospFlag` | 各 `NULL:585, 0:7` |
| `T_SpSetlFlag` | `0:574, NULL:11, 空串:7` |
| `NT_AllSelfPayFlag` | `NULL:581, 0:9, 空串:2` |
| `ItemType` | `0:670, 1:613, 3:534, 2:322` |
| `FeeType` | `0941:429, 0102:374, 0890:348, 0811:270, 0201:230, 0601:190, 0810:110, 1010:64, 0103:57, 0819:41, 0710:8, 0750:7, 0101:6, 0202:2, 0203:1, 0605:1, 1020:1` |
| `F_LEVEL` | `2:1192, 1:857, 0:79, 3:11` |
| `SPEDRUG_FLAG` | `0:2139` |
| 明细 `State` | `0:1757, 6:382` |

[推断: 仅基于低基数聚合] 这些只是源代码分布，不是代码含义。未取得数据字典前不得把 `0/1/4/6` 等映射为成功、失败、有资格或无资格。

#### 四态证明

本批次直接数据只证明三态：非 NULL 且非零为 `non_zero`，非 NULL 且显式零为 `reported_zero`，NULL、关联缺失或可信上下文未提供为 `missing`。字符串空值独立保留为空值质量问题，不自动等同数值零。`not_applicable` 必须同时有资格事实和有效期覆盖本次结算的政策证据；任何 `NULL→0`、`0→无资格` 或“全表未见非零→不适用”的转换均禁止。[来源: 总设计 §10.6；Issue20 §6.3]

#### 九个 Profile 字段闭包状态

执行状态采用失败关闭：Issue20 §5.2 强制所有 Profile 先以 `settlement_id→T_SetTid` 定位单次交易，而 Task 2 已证明该通用核心存在 NULL 与多笔歧义。在权威版本/有效交易选择规则签认前，任何 Profile 都不能安全执行；下表即使提到其他物理字段已存在，也只描述字段成熟度，不构成可执行 `partial`。

| Profile | 状态 | 字段闭包结论与阻断原因 |
|---|---|---|
| P1 整体结算核验 | `unavailable` | 通用核心锚点不能唯一定位；汇总金额虽存在，状态有效规则和总额公式也未签认。 |
| P2 个人负担解释 | `unavailable` | 通用核心锚点不能唯一定位；自付/账户/现金成员关系、专项支付关系和零值资格含义未签认。 |
| P3 支付渠道核验 | `unavailable` | 通用核心锚点不能唯一定位；总分关系未确认，且 `T_JCPay` 存在救助/军残语义冲突，不得重复求和或确定命名。 |
| P4 起付线与年度累计 | `unavailable` | 通用核心锚点不能唯一定位；TB/TA 前后释义、年度边界和 `TA_MZTimes` 释义未签认。 |
| P5 报销比例与封顶 | `unavailable` | 通用核心锚点不能唯一定位；另缺可信政策地区、适用机构、规范资格上下文及覆盖结算日期的完整政策证据。 |
| P6 医保目录与费用明细 | `unavailable` | 通用核心锚点不能唯一定位；虽已证明明细关系，Task 3 金额仍超差，`FeeIn/FeeOut` 与明细状态码未冻结。 |
| P7 身份与特殊待遇 | `unavailable` | 通用核心锚点不能唯一定位；码表/资格定义、规范专项待遇类型和政策证据缺失，且 `T_JCPay` 救助/军残语义冲突。 |
| P8 异地与机构待遇 | `unavailable` | 通用核心锚点不能唯一定位；政策地区、登录医院、医院等级/主数据和政策适用机构映射缺失。 |
| P9 交易状态与退费 | `unavailable` | 通用核心锚点不能唯一定位；状态码、原交易关系和有效/红冲过滤规则未签认，退费/冲正仍只转人工确认。 |

九个 Profile 均不得发布门诊 Skill 输入契约：0 `complete` / 0 `partial` / 9 `unavailable`。

#### 完整可复现只读聚合 SQL

Task 1 的 `INFORMATION_SCHEMA.COLUMNS` SQL 是全部字段的物理类型证据。以下 Task 4 SQL 仅覆盖 A–F 的 107 个可聚合物理字段，不覆盖 G 组 8 个敏感排除字段，也不覆盖 3 个外部上下文；因此不能表述为“SQL 与 118 行矩阵逐字段一致”。`is_numeric=1` 才统计数值零，其他类型统计空串。执行器另对上表列出的低基数字段使用同样的 `CROSS APPLY` 后按 `field_name, code` 分组；没有查询任何样例行。

```sql
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
SET LOCK_TIMEOUT 5000;

SELECT v.field_name,
       COUNT_BIG(*) AS row_count,
       SUM(CASE WHEN v.value_text IS NULL THEN 1 ELSE 0 END) AS null_count,
       SUM(CASE WHEN v.value_text IS NOT NULL AND
                     ((v.is_numeric=1 AND TRY_CONVERT(decimal(38,10),v.value_text)=0) OR
                      (v.is_numeric=0 AND LTRIM(RTRIM(v.value_text))='')) THEN 1 ELSE 0 END) AS zero_or_blank_count,
       SUM(CASE WHEN v.value_text IS NOT NULL AND
                     ((v.is_numeric=1 AND TRY_CONVERT(decimal(38,10),v.value_text)<>0) OR
                      (v.is_numeric=0 AND LTRIM(RTRIM(v.value_text))<>'')) THEN 1 ELSE 0 END) AS nonzero_or_nonblank_count,
       COUNT_BIG(DISTINCT v.value_text) AS distinct_count
FROM dbo.o_Trade AS t
CROSS APPLY (VALUES
 ('T_SetTid',CONVERT(nvarchar(4000),t.T_SetTid),0),('T_TradeNo',CONVERT(nvarchar(4000),t.T_TradeNo),0),
 ('T_TradeDate',CONVERT(nvarchar(4000),t.T_TradeDate,121),0),('T_State',CONVERT(nvarchar(4000),t.T_State),1),
 ('T_HasRefundmented',CONVERT(nvarchar(4000),t.T_HasRefundmented),1),('T_PartialReturnFlag',CONVERT(nvarchar(4000),t.T_PartialReturnFlag),0),
 ('T_OraginalTradeNo',CONVERT(nvarchar(4000),t.T_OraginalTradeNo),0),('T_OraginalTradeDate',CONVERT(nvarchar(4000),t.T_OraginalTradeDate,121),0),
 ('NP_Settle_State',CONVERT(nvarchar(4000),t.NP_Settle_State),0),('SETL_DATE',CONVERT(nvarchar(4000),t.SETL_DATE,121),0),
 ('NT_ReTradeFlag',CONVERT(nvarchar(4000),t.NT_ReTradeFlag),0),('T_DiagType',CONVERT(nvarchar(4000),t.T_DiagType),0),('T_FeeNo',CONVERT(nvarchar(4000),t.T_FeeNo),0),
 ('P_FundType',CONVERT(nvarchar(4000),t.P_FundType),1),('PN_PersonType',CONVERT(nvarchar(4000),t.PN_PersonType),1),('T_CureType',CONVERT(nvarchar(4000),t.T_CureType),1),
 ('P_JCLevel',CONVERT(nvarchar(4000),t.P_JCLevel),1),('P_HospFlag',CONVERT(nvarchar(4000),t.P_HospFlag),1),('PN_OutTransaction',CONVERT(nvarchar(4000),t.PN_OutTransaction),0),
 ('PN_NationFundType',CONVERT(nvarchar(4000),t.PN_NationFundType),0),('PN_ChronicFlag',CONVERT(nvarchar(4000),t.PN_ChronicFlag),0),('PN_ChronicCode',CONVERT(nvarchar(4000),t.PN_ChronicCode),0),
 ('PN_IsChronicHosp',CONVERT(nvarchar(4000),t.PN_IsChronicHosp),0),('P_Official',CONVERT(nvarchar(4000),t.P_Official),1),('P_retirementflag',CONVERT(nvarchar(4000),t.P_retirementflag),0),
 ('P_CivilFlag',CONVERT(nvarchar(4000),t.P_CivilFlag),0),('P_CivilType',CONVERT(nvarchar(4000),t.P_CivilType),0),('RETIRE_OFFICER_FLAG',CONVERT(nvarchar(4000),t.RETIRE_OFFICER_FLAG),0),
 ('T_GFBelongFlag',CONVERT(nvarchar(4000),t.T_GFBelongFlag),0),('T_CompHospFlag',CONVERT(nvarchar(4000),t.T_CompHospFlag),0),('T_SpSetlFlag',CONVERT(nvarchar(4000),t.T_SpSetlFlag),0),
 ('T_pneno',CONVERT(nvarchar(4000),t.T_pneno),0),('NT_AllSelfPayFlag',CONVERT(nvarchar(4000),t.NT_AllSelfPayFlag),0),('PN_NoRightReason',CONVERT(nvarchar(4000),t.PN_NoRightReason),0),
 ('T_FeeAll',CONVERT(nvarchar(4000),t.T_FeeAll),1),('T_FeeIn',CONVERT(nvarchar(4000),t.T_FeeIn),1),('T_FeeOut',CONVERT(nvarchar(4000),t.T_FeeOut),1),
 ('T_FirstPay',CONVERT(nvarchar(4000),t.T_FirstPay),1),('T_SelfPay1',CONVERT(nvarchar(4000),t.T_SelfPay1),1),('T_SelfPay2',CONVERT(nvarchar(4000),t.T_SelfPay2),1),('T_SelfPayAll',CONVERT(nvarchar(4000),t.T_SelfPayAll),1),
 ('T_BigPay',CONVERT(nvarchar(4000),t.T_BigPay),1),('T_BigSelfPay',CONVERT(nvarchar(4000),t.T_BigSelfPay),1),('T_BeyondBig',CONVERT(nvarchar(4000),t.T_BeyondBig),1),
 ('T_FundPay',CONVERT(nvarchar(4000),t.T_FundPay),1),('T_PersonCountPay',CONVERT(nvarchar(4000),t.T_PersonCountPay),1),('T_CashPay',CONVERT(nvarchar(4000),t.T_CashPay),1),
 ('PN_PersonCount',CONVERT(nvarchar(4000),t.PN_PersonCount),1),('T_PersonCountAfter',CONVERT(nvarchar(4000),t.T_PersonCountAfter),1),
 ('T_BCPay',CONVERT(nvarchar(4000),t.T_BCPay),1),('T_JCPay',CONVERT(nvarchar(4000),t.T_JCPay),1),('T_OfficalPay',CONVERT(nvarchar(4000),t.T_OfficalPay),1),('T_BigillPay',CONVERT(nvarchar(4000),t.T_BigillPay),1),
 ('NT_BasicPay',CONVERT(nvarchar(4000),t.NT_BasicPay),1),('NT_CivilPay',CONVERT(nvarchar(4000),t.NT_CivilPay),1),('NT_OtherPay',CONVERT(nvarchar(4000),t.NT_OtherPay),1),('NT_AgencySumPay',CONVERT(nvarchar(4000),t.NT_AgencySumPay),1),
 ('RETIRE_OFFICER_PAY',CONVERT(nvarchar(4000),t.RETIRE_OFFICER_PAY),1),('NT_OUT2_SCALE',CONVERT(nvarchar(4000),t.NT_OUT2_SCALE),1),('NT_OUT2_PRICE',CONVERT(nvarchar(4000),t.NT_OUT2_PRICE),1),
 ('TB_FeeIn',CONVERT(nvarchar(4000),t.TB_FeeIn),1),('TA_FeeIn',CONVERT(nvarchar(4000),t.TA_FeeIn),1),('TB_BigPay',CONVERT(nvarchar(4000),t.TB_BigPay),1),('TA_BigPay',CONVERT(nvarchar(4000),t.TA_BigPay),1),
 ('TB_FeeAfterBig',CONVERT(nvarchar(4000),t.TB_FeeAfterBig),1),('TA_FeeAfterBig',CONVERT(nvarchar(4000),t.TA_FeeAfterBig),1),('TB_MZTimes',CONVERT(nvarchar(4000),t.TB_MZTimes),1),('TA_MZTimes',CONVERT(nvarchar(4000),t.TA_MZTimes),1),
 ('TB_BeyondFeeIn',CONVERT(nvarchar(4000),t.TB_BeyondFeeIn),1),('TA_BeyondFeeIn',CONVERT(nvarchar(4000),t.TA_BeyondFeeIn),1),
 ('TB_BigillComm',CONVERT(nvarchar(4000),t.TB_BigillComm),1),('TA_BigillComm',CONVERT(nvarchar(4000),t.TA_BigillComm),1),('TB_BigillPay',CONVERT(nvarchar(4000),t.TB_BigillPay),1),('TA_BigillPay',CONVERT(nvarchar(4000),t.TA_BigillPay),1),
 ('TB_CivilComm',CONVERT(nvarchar(4000),t.TB_CivilComm),1),('TA_CivilComm',CONVERT(nvarchar(4000),t.TA_CivilComm),1),('TB_CivilPay',CONVERT(nvarchar(4000),t.TB_CivilPay),1),('TA_CivilPay',CONVERT(nvarchar(4000),t.TA_CivilPay),1),
 ('TB_FeeInL1',CONVERT(nvarchar(4000),t.TB_FeeInL1),1),('TA_FeeInL1',CONVERT(nvarchar(4000),t.TA_FeeInL1),1),('TB_BigPayL1',CONVERT(nvarchar(4000),t.TB_BigPayL1),1),('TA_BigPayL1',CONVERT(nvarchar(4000),t.TA_BigPayL1),1),
 ('TB_FeeAfterBigL1',CONVERT(nvarchar(4000),t.TB_FeeAfterBigL1),1),('TA_FeeAfterBigL1',CONVERT(nvarchar(4000),t.TA_FeeAfterBigL1),1),
 ('PN_InsuredAreaCode',CONVERT(nvarchar(4000),t.PN_InsuredAreaCode),0),('T_HospCode',CONVERT(nvarchar(4000),t.T_HospCode),0),('T_HospCodeA',CONVERT(nvarchar(4000),t.T_HospCodeA),0)
) AS v(field_name,value_text,is_numeric)
GROUP BY v.field_name;

SELECT v.field_name,
       COUNT_BIG(*) AS row_count,
       SUM(CASE WHEN v.value_text IS NULL THEN 1 ELSE 0 END) AS null_count,
       SUM(CASE WHEN v.value_text IS NOT NULL AND
                     ((v.is_numeric=1 AND TRY_CONVERT(decimal(38,10),v.value_text)=0) OR
                      (v.is_numeric=0 AND LTRIM(RTRIM(v.value_text))='')) THEN 1 ELSE 0 END) AS zero_or_blank_count,
       SUM(CASE WHEN v.value_text IS NOT NULL AND
                     ((v.is_numeric=1 AND TRY_CONVERT(decimal(38,10),v.value_text)<>0) OR
                      (v.is_numeric=0 AND LTRIM(RTRIM(v.value_text))<>'')) THEN 1 ELSE 0 END) AS nonzero_or_nonblank_count,
       COUNT_BIG(DISTINCT v.value_text) AS distinct_count
FROM dbo.o_FeeItem AS f
CROSS APPLY (VALUES
 ('T_TradeNo',CONVERT(nvarchar(4000),f.T_TradeNo),0),('ItemId',CONVERT(nvarchar(4000),f.ItemId),1),('ItemNo',CONVERT(nvarchar(4000),f.ItemNo),1),
 ('ItemCode',CONVERT(nvarchar(4000),f.ItemCode),0),('StandardCode',CONVERT(nvarchar(4000),f.StandardCode),0),('ItemName',CONVERT(nvarchar(4000),f.ItemName),0),
 ('ItemType',CONVERT(nvarchar(4000),f.ItemType),1),('FeeType',CONVERT(nvarchar(4000),f.FeeType),0),('F_LEVEL',CONVERT(nvarchar(4000),f.F_LEVEL),0),
 ('Count',CONVERT(nvarchar(4000),f.Count),1),('UnitPrice',CONVERT(nvarchar(4000),f.UnitPrice),1),('Fee',CONVERT(nvarchar(4000),f.Fee),1),
 ('FeeIn',CONVERT(nvarchar(4000),f.FeeIn),1),('FeeOut',CONVERT(nvarchar(4000),f.FeeOut),1),('SelfPay2',CONVERT(nvarchar(4000),f.SelfPay2),1),
 ('FEE_SP_SCALE',CONVERT(nvarchar(4000),f.FEE_SP_SCALE),1),('FEE_MEDIC_L',CONVERT(nvarchar(4000),f.FEE_MEDIC_L),1),('MEDIC_L',CONVERT(nvarchar(4000),f.MEDIC_L),1),
 ('SPEDRUG_FLAG',CONVERT(nvarchar(4000),f.SPEDRUG_FLAG),0),('State',CONVERT(nvarchar(4000),f.State),1)
) AS v(field_name,value_text,is_numeric)
GROUP BY v.field_name;

SELECT CONVERT(varchar(40),SYSDATETIMEOFFSET(),127) AS executed_at,
       CONVERT(varchar(64),HASHBYTES('SHA2_256',CONVERT(nvarchar(128),SUSER_SNAME())),2)
         AS principal_fingerprint_sha256;
```

[建议] 若需逐字复跑低基数枚举，将上面相应 `VALUES` 行保留为 `field_name,value_text`，执行 `GROUP BY field_name,value_text ORDER BY field_name,COUNT_BIG(*) DESC,value_text`；只允许上文安全枚举白名单，禁止把自由文本、代码病种、标识符或业务键加入该查询。

Task 4 结果：**DONE_WITH_CONCERNS**。A–F 组 107 个可聚合物理字段完成只读画像，G 组 8 个敏感字段仅沿用 Task 1 `INFORMATION_SCHEMA` 存在性/类型元数据，另有 3 个外部核心上下文登记为 `missing_external_context`；`T_SetTid` 通用核心锚点仍存在多笔歧义，九个执行 Profile 均为 `unavailable`。业务字段字典、交易前后定义、可信外部政策上下文和资格+政策证据不足；不得伪报字段闭包 `complete`，也不提前建立运营指标、增量游标或容量结论。

## 运营指标依赖

待验证。Task 1 不确认任何运营指标、口径、维度、去重键或状态过滤规则；不得仅凭已发现字段自动发布指标。

## 阻断项

| 编号 | 阻断/关注项 | 影响 | 解锁条件 |
|---|---|---|---|
| T1-B01 | 指纹 38F144F8…ACD70 对应主体在数据库及两张候选表上具备 INSERT、UPDATE、DELETE 权限 | 不满足批准的最小只读权限基线；误操作风险高 | 提供符合批准范围的专用只读账号或等效只读隔离通道，并重新留存主体指纹及 SELECT、INSERT、UPDATE、DELETE 权限位 |
| T1-B02 | 本次两表均命中 discovery 检查点 | 行数、质量分、非空率、DDL 时间是缓存快照，不能证明 2026-08-27 新鲜画像 | 在批准流程中生成可审计的新鲜只读全量画像，并保留任务时间与统计口径 |
| T1-B03 | 核心字段没有随 Task 1 获得权威业务定义和值域 | 交易状态、退款链、金额公式和游标含义仍可能误判 | 取得院方数据字典/接口文档并由业务与数据负责人签认 |
| T1-B04 | 候选表包含直接标识符、证件/卡号及电子凭证类高敏字段 | 后续 Skill 或指标若直接读取将违反最小化与脱敏要求 | 建立允许字段白名单、用途说明和 security/desensitization 验证证据 |
| T2-B01 | [来源: outpatient_p0_t2_20260827_070052Z] T_SetTid 有 11 行 NULL，且 2 个重复组涉及 326/592 行；重复横跨多种状态组合 | [推断: 基于全量计数与 Issue20 §5.2 强制内部锚点要求] 不能冻结为内部结算锚点，`settlement_id → 单笔交易` 假设失效，所有九个执行 Profile 阻断 | 取得 T_SetTid 权威业务定义、合法一对多/版本规则及人工签认；在此之前不得自行设计替代键 |
| T2-B02 | [来源: outpatient_p0_t2_20260827_070052Z] T_TradeDate 为无时区 datetime，尚未取得其业务时区与时钟语义；固定服务器时钟参数形成的窗口只观察到交易/关联明细 0 | [推断: 基于字段类型与缺失的业务时区定义] 不能把该观察值作为可靠最近 30 天证据；不影响全量键、重复和主从关系结论 | 由数据负责人确认 T_TradeDate 的业务时区/时钟语义，并按确认后的时间口径重新执行参数化窗口查询 |
| T3-B01 | [来源: outpatient_p0_t3_20260827_073210Z、outpatient_p0_t3_precision_20260827_074356Z] o_Trade 两组等式分别有 5、6 笔超差；精度修正后的 o_FeeItem 汇总 Fee、FeeOut 分别有 2、5 笔超差；状态码无权威有效规则 | [推断: 基于全量 decimal 聚合] 金额门禁和有效状态门禁未通过，dbo.o_FeeItem 不能冻结为唯一费用明细源 | 由医保办与数据负责人签认金额公式、舍入和有效状态规则；按签认规则重新执行同口径聚合并解释全部超差 |
| T3-B02 | `MANUAL_TICKET_RECONCILIATION_BLOCKED`：当前没有至少 30 份医保办票据、票据访问授权人员或获批脱敏传递通道 | 无法完成唯一明细源的人工票据门禁 | 由医保办授权经办人完成至少 30 票据逐笔核对，医保办负责人、数据负责人和信息安全/隐私负责人签认 |
| T3-B03 | [来源: outpatient_p0_t3_20260827_073210Z] 专项基金候选等式 592 行中 581 行缺字段，11 行可比较记录中 6 行超差 | 不能把字段名相关性发布为基金总分公式 | 取得权威基金字段字典与公式并由医保办、数据负责人签认；未签认前保持候选/待确认 |
| T4-B01 | [来源: outpatient_p0_t4_20260827_policy_closure、Issue20 §4/§5.2/§5.4] `T_SetTid` 是九个执行 Profile 的通用核心锚点但仍有 NULL/多笔歧义；交易/待遇/状态码、金额成员关系及 `TB_*`/`TA_*` 前后语义缺少权威字典，`TA_MZTimes` 仅确认物理类型为 int，`T_JCPay` 又存在救助/军残候选语义冲突 | 九个执行 Profile 均为 `unavailable`；P3、P7 另受 `T_JCPay` 语义冲突阻断，年度累计、状态和资格判断也可能误释 | 先解除 T2-B01；再由医保办与数据负责人提供字段字典、码表、公式、`T_JCPay` 唯一释义及 TB/TA 前后定义并签认，按签认口径重跑聚合 |
| T4-B02 | 政策地区、登录医院/政策适用机构、规范专项待遇类型及资格证据不在两表可信闭包内 | P5、P7、P8 存在额外外部核心上下文阻断；不改变九个执行 Profile 已全部 `unavailable` 的汇总结论 | 从可信 HIS/登录组织/医院主数据和资格接口注入上下文，并与已发布、有效期覆盖结算日期的政策证据共同验证 |
| T4-B03 | 现有 `settlement_explain_skill` 是住院 Skill，标准化器会补住院险种、医疗类别、医院等级和人员默认值 | 若门诊复用会把缺失上下文伪造成住院事实，导致错误政策命中 | 门诊 Skill 保持独立字段映射；删除门诊路径所有住院默认值，缺失按 `missing` 失败关闭 |

网络、SQL Server 连接、元数据 SELECT 和发现任务持久化均成功，不构成 Task 1 的连接阻断。

## 审核结论

状态：DRAFT / PENDING_REVIEW。

Task 1 已形成两张候选表的发现证据草稿、数据库版本/脱敏权限位、236 个字段物理类型以及键/索引/FK 初步元数据观察。

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；本文留存只读 SQL 与执行时间] Task 2 已通过批准的注册表入口完成全量键、重复、孤儿和状态组合聚合；服务器时钟窗口查询仅保留为观察值，业务最近 30 天口径为 BLOCKED。仅执行只读语句，没有修改生产代码或源库。该草稿不代表正式审核完成。

[来源: 文档级证据批次 outpatient_p0_t3_20260827_073210Z、outpatient_p0_t3_precision_20260827_074356Z；本文留存完整只读 SQL、固定执行时间、聚合计数和失败分类] Task 3 已完成两组主表金额等式、三组逐交易明细勾稽、专项基金候选字段和四状态组合的全量聚合；明细 SUM 精度修正后又一次重跑总体和状态分层，结果未变。各 SELECT 一次成功，无超时或字段不存在；仅执行 SELECT/SET，没有输出行级标识、修改源库或扩大两表白名单。

[推断: 基于 outpatient_p0_t2_20260827_070052Z 与 outpatient_p0_t3_20260827_073210Z] 当前证据冻结 T_TradeNo 为交易业务键、`(T_TradeNo, ItemId, ItemNo)` 为费用明细幂等键，并确认全量 T_TradeNo 主从关系无孤儿。内部结算锚点仍为 BLOCKED：T2-B01 解锁前，九个执行 Profile 均禁止继续使用 `settlement_id → 单笔交易` 假设。dbo.o_FeeItem 仅保持费用明细候选：金额超差、有效状态规则和 `MANUAL_TICKET_RECONCILIATION_BLOCKED` 未解除前不得冻结；`yb_mzfymx_mz` 只登记为下一步待授权验证候选。增量游标、容量性能、政策 Skill 依赖和运营指标依赖未在 Task 3 提前处理。

Task 3 执行结果：**DONE_WITH_CONCERNS**。关注项为 T3-B01 至 T3-B03，未伪造人工票据或业务字典完成。

[来源: 文档级证据批次 outpatient_p0_t4_20260827_policy_closure；固定执行时间、主体指纹引用、字段矩阵与完整只读 SQL 见“政策 Skill 依赖”] Task 4 已覆盖总设计 §10.1–§10.5 与 Issue20 §5.4：A–F 组 107 个可聚合物理字段完成 NULL/零/非零/distinct 只读画像，G 组 8 个敏感字段仅以 Task 1 `INFORMATION_SCHEMA` 元数据确认存在性/类型，3 个外部核心上下文登记为可信外部依赖，总矩阵 118 行。九个执行 Profile 为 0 `complete` / 0 `partial` / 9 `unavailable`。

Task 4 执行结果：**DONE_WITH_CONCERNS**。关注项为 T4-B01 至 T4-B03；未把住院默认值、相似字段、零值或缺失上下文伪造成门诊资格与政策事实，也未提前处理运营指标、游标或容量。

| 待审核角色 | 审核状态 | 签认 |
|---|---|---|
| 医保办授权经办人 | 待审核 | 至少 30 票据逐笔核对留空 |
| 医保办负责人 | 待审核 | 留空；Task 7 完成 |
| 数据负责人 | 待审核 | 留空；Task 7 完成 |
| 信息安全/隐私负责人 | 待审核 | 票据访问与脱敏边界留空 |
