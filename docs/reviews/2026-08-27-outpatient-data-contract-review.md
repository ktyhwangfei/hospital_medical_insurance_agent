# 门诊数据契约核验记录（P0 Task 1–2）

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
| 数据库时间锚点 | 2026-08-27 07:00:52.315；同次 `SYSDATETIMEOFFSET()` 返回 +00:00 |
| 完整区间 | dbo.o_Trade / dbo.o_FeeItem 全表；o_Trade.T_TradeDate 范围 2024-03-11 09:28:38.000 至 2026-04-17 10:41:45.000（源时区不另作推断） |
| 最近 30 天区间 | `[2026-07-28 07:00:52.315, 2026-08-27 07:00:52.315)`，左闭右开；按 o_Trade.T_TradeDate 过滤 |
| 时间字段确认 | INFORMATION_SCHEMA 实测为 datetime NOT NULL；MIN/MAX 与所有参数化日期过滤成功，不需要猜测或解析字符串格式 |
| 主体指纹 | SHA-256 38F144F8D609E1F6CFA0E3B2E4225EF783A0B313A98262F71FC0862BF97ACD70，与 Task 1 一致 |
| 安全入口 | 使用启用的数据源注册表 id/name 安全别名 bjybdb；配置只在进程内传递，不打印配置行、connection_config 或初始化输出 |
| 执行时段 | 2026-08-27 15:00:52.284–15:00:53.584、15:02:29.783–15:02:30.564、15:03:29.836–15:03:30.546（均 +08:00） |
| 超时边界 | 连接/语句超时 30 秒，LOCK_TIMEOUT 5 秒；所有聚合查询均在 34 毫秒内完成，无超时 |
| 实际 SQL Server 操作 | 仅 SELECT、INFORMATION_SCHEMA 元数据查询与会话级 SET；未执行写语句，未修改索引 |
| 查询失败分类 | 首次合并画像中的 TRY_CONVERT SELECT 返回 ProgrammingError / SQLSTATE 42000；按“一次失败即记录”未重试同一查询。后续独立元数据、日期边界和过滤查询成功，因此不构成 30 天口径阻断 |

诊断勘误：上一提交的 `DATASOURCE_ALIAS_NOT_FOUND` 是控制器未加载获准进程配置所致，不是源数据或注册表阻断，已撤销。

| 查询组 | 耗时 |
|---|---:|
| 主体指纹与时间锚点 | 4.06 ms |
| T_TradeDate 元数据 / 日期边界 / 最近 30 天显式零计数 | 15.93 / 5.30 / 4.93 ms |
| o_Trade 键摘要 / 重复摘要 | 25.67 / 12.67 ms |
| o_FeeItem 孤儿 / 复合键摘要 | 9.35 / 14.83 ms |
| 全量状态组合 / 重复键状态组合 | 7.03 / 33.13 ms |

#### 冻结的只读 SQL

以下批次归并了 Task 2 实际成功的完整只读口径。它只返回时间、主体哈希、状态枚举和聚合计数，不返回任何交易标识或明细键值。

```sql
SET NOCOUNT ON;
SET LOCK_TIMEOUT 5000;

DECLARE @as_of datetime2(3) = CAST(SYSDATETIME() AS datetime2(3));
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

最近 30 天费用明细没有独立日期字段，因此查询明确标为 `recent_30d_parent_joined`。只有在全量 T_TradeNo 无重复且全量孤儿数为 0 后，该关联结果才可视为完整的最近 30 天明细集合；否则必须与关系歧义分开报告。

#### Task 2 结果与冻结决定

| 验证项 | 完整区间 | 最近 30 天 | 决定 |
|---|---|---|---|
| o_Trade 行数 | 592 | 0 | 最近窗口无交易样本 |
| T_SetTid NULL / 去重数 | 11 / 257 | 0 / 0 | 不满足内部结算锚点的一对一要求 |
| T_SetTid 重复组数 / 涉及行数 | 2 / 326 | 0 / 0 | **BLOCKED**：停止 `settlement_id → 单笔交易` 假设，P1 阻断 |
| T_TradeNo NULL / 去重数 | 0 / 592 | 0 / 0 | 与 592 总行数及物理主键一致，冻结为交易业务键 |
| T_TradeNo 重复组数 / 涉及行数 | 0 / 0 | 0 / 0 | 冻结 |
| o_FeeItem 行数 | 2,139 | 0（按父交易日期关联） | 最近窗口无明细样本 |
| 复合键三个分量 NULL / 任一 NULL 行 | 0 / 0 / 0；任一 NULL 0 | 均为 0 | 通过 |
| 复合键重复组数 / 涉及行数 | 0 / 0 | 0 / 0 | 冻结 `(T_TradeNo, ItemId, ItemNo)` 为费用明细幂等键 |
| o_FeeItem → o_Trade 孤儿明细数 | 0 | 0（由全量零孤儿及最近窗口零交易共同确定） | T_TradeNo 主从关系无歧义；本范围支持一笔交易对应多条费用明细 |

三项决定：内部结算锚点 **BLOCKED**；交易业务键冻结为 T_TradeNo；费用明细幂等键冻结为 `(T_TradeNo, ItemId, ItemNo)`。T_SetTid 的 2 个重复组横跨多种状态组合，且 11 行为空，当前数据不支持把它解释为单笔交易锚点；是否属于合法批次、历史版本或其他业务对象仍需权威字典确认，不自行设计替代键，也不把重复直接认定为脏数据。

## 交易状态

最近 30 天无交易，状态组合计数为 0。全量状态组合如下；`''` 表示空字符串，`NULL` 表示数据库 NULL。

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

T_TradeNo 和费用复合键没有重复，因此没有对应的重复键状态组合。T_SetTid 重复行的二次聚合如下；“涉及重复组数”表示该状态组合涉及全量 2 个重复组中的几个，同一组跨状态时会在多行出现，不能跨行相加。

| T_State | T_HasRefundmented | T_PartialReturnFlag | NT_ReTradeFlag | 涉及重复组数 | 重复行数 |
|---:|---:|---|---|---:|---:|
| -3 | 0 | `''` | NULL | 1 | 5 |
| -3 | 1 | `''` | NULL | 1 | 1 |
| 3 | 0 | `''` | NULL | 1 | 3 |
| 4 | 0 | `''` | NULL | 1 | 250 |
| 4 | 1 | `''` | NULL | 2 | 54 |
| 4 | 1 | `1` | NULL | 1 | 13 |

重复行在数值上集中于 T_State=4（317/326），但 T_HasRefundmented=0 仍有 258/326 行，T_PartialReturnFlag=`1` 仅 13/326 行，NT_ReTradeFlag=`1` 为 0 行。因此不能认定重复仅集中在退费、部分退费或冲正，也不能从 T_State=4 推断历史版本或任何业务终态；以上是相关性计数，不是因果结论。状态码业务含义仍需权威字典签认。

## 金额勾稽

待验证。Task 1 仅确认金额字段的精度：o_Trade 核心金额多为 decimal(10,2)，o_FeeItem 的 UnitPrice、Fee、FeeIn、FeeOut、SelfPay2 为 decimal(10,4)，Count 为 numeric(10,2)。勾稽公式、舍入阈值、负数/退款口径及状态过滤条件需由后续任务验证。

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

待验证。Task 1 不建立 o_Trade/o_FeeItem 到 settlement_explain_skill 的字段映射，不修改 Skill、语义层或生产代码。后续必须逐字段对照 Skill 输入契约、引用来源与脱敏边界。

## 运营指标依赖

待验证。Task 1 不确认任何运营指标、口径、维度、去重键或状态过滤规则；不得仅凭已发现字段自动发布指标。

## 阻断项

| 编号 | 阻断/关注项 | 影响 | 解锁条件 |
|---|---|---|---|
| T1-B01 | 指纹 38F144F8…ACD70 对应主体在数据库及两张候选表上具备 INSERT、UPDATE、DELETE 权限 | 不满足批准的最小只读权限基线；误操作风险高 | 提供符合批准范围的专用只读账号或等效只读隔离通道，并重新留存主体指纹及 SELECT、INSERT、UPDATE、DELETE 权限位 |
| T1-B02 | 本次两表均命中 discovery 检查点 | 行数、质量分、非空率、DDL 时间是缓存快照，不能证明 2026-08-27 新鲜画像 | 在批准流程中生成可审计的新鲜只读全量画像，并保留任务时间与统计口径 |
| T1-B03 | 核心字段没有随 Task 1 获得权威业务定义和值域 | 交易状态、退款链、金额公式和游标含义仍可能误判 | 取得院方数据字典/接口文档并由业务与数据负责人签认 |
| T1-B04 | 候选表包含直接标识符、证件/卡号及电子凭证类高敏字段 | 后续 Skill 或指标若直接读取将违反最小化与脱敏要求 | 建立允许字段白名单、用途说明和 security/desensitization 验证证据 |
| T2-B01 | T_SetTid 有 11 行 NULL，且 2 个重复组涉及 326/592 行；重复横跨多种状态组合 | 不能冻结为内部结算锚点，`settlement_id → 单笔交易` 假设失效，P1 阻断 | 取得 T_SetTid 权威业务定义、合法一对多/版本规则及人工签认；在此之前不得自行设计替代键 |
| T2-B02 | 最近 30 天窗口交易和关联明细均为 0，源表最大 T_TradeDate 早于窗口起点 | 全量键证据可用，但没有近期数据证明当前上游仍按同一契约写入 | 取得当前数据供给周期说明，或在出现新交易后按同一固定 SQL 复核最近窗口 |

网络、SQL Server 连接、元数据 SELECT 和发现任务持久化均成功，不构成 Task 1 的连接阻断。

## 审核结论

状态：DRAFT / PENDING_REVIEW。

Task 1 已形成两张候选表的发现证据草稿、数据库版本/脱敏权限位、236 个字段物理类型以及键/索引/FK 初步元数据观察。Task 2 已通过批准的注册表入口完成全量与最近 30 天的键、重复、孤儿和状态组合聚合；仅执行只读语句，没有修改生产代码或源库。该草稿不代表正式审核完成。

当前证据冻结 T_TradeNo 为交易业务键、`(T_TradeNo, ItemId, ItemNo)` 为费用明细幂等键，并确认全量 T_TradeNo 主从关系无孤儿。内部结算锚点仍为 BLOCKED：T2-B01 解锁前，P1 禁止继续使用 `settlement_id → 单笔交易` 假设。T1-B01 至 T1-B04 与 T2-B02 仍保持；金额勾稽、增量游标、容量性能、政策 Skill 依赖和运营指标依赖未在 Task 2 提前处理。

| 待审核角色 | 审核状态 | 签认 |
|---|---|---|
| 医保办负责人 | 待审核 | 留空；Task 7 完成 |
| 数据负责人 | 待审核 | 留空；Task 7 完成 |
