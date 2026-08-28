# 门诊数据契约核验记录（P0 Task 1–7）

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
| T_SetTid NULL / 去重数 | 11 / 257 | 0 / 0（观察值） | [来源: Issue20 §5.2] 普通可空字段，不作为 Skill 锚点；业务语义仍待字典确认 |
| T_SetTid 重复组数 / 涉及行数 | 2 / 326 | 0 / 0（观察值） | 不影响 `settlement_id → T_TradeNo`；不得把它解释为单笔交易号 |
| T_TradeNo NULL / 去重数 | 0 / 592 | 0 / 0（观察值） | [来源: Issue20 §4/§5.2；Task 2 物理主键和全量唯一性] 冻结为内部结算锚点兼交易业务键 |
| T_TradeNo 重复组数 / 涉及行数 | 0 / 0 | 0 / 0（观察值） | [推断: 全量结论冻结，观察窗口不参与冻结] |
| o_FeeItem 行数 | 2,139 | 0（按父交易日期得到的观察值） | 不据此判断近期无明细 |
| 复合键三个分量 NULL / 任一 NULL 行 | 0 / 0 / 0；任一 NULL 0 | 均为 0（观察值） | 全量证据通过 |
| 复合键重复组数 / 涉及行数 | 0 / 0 | 0 / 0（观察值） | [推断: 仅基于全量证据冻结 `(T_TradeNo, ItemId, ItemNo)` 为费用明细幂等键] |
| o_FeeItem → o_Trade 孤儿明细数 | 0 | 未验证（时间口径阻断） | [推断: 全量 T_TradeNo 主从关系无歧义；本范围支持一笔交易对应多条费用明细] |

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；本节留存只读 SQL；执行时段 2026-08-27 15:02:29.783–15:03:30.546 +08:00]

[推断: 基于上述全量 NULL、去重、重复与孤儿计数，并按 Issue20 当前契约纠偏] 三项决定：内部结算锚点兼交易业务键冻结为 `T_TradeNo`；费用明细幂等键冻结为 `(T_TradeNo, ItemId, ItemNo)`；`T_SetTid` 只保留为普通可空字段。`T_SetTid` 的重复和空值仍需权威字典解释，但不再阻断 `settlement_id = T_TradeNo → 单笔交易`。用户按就诊时间定位到该内部锚点属于可信上下文解析，继续由 G07 门禁约束。

## 交易状态

服务器时钟观察窗口内状态组合查询返回 0，但因 T_TradeDate 业务时区/时钟语义未确认，不能表述为业务最近 30 天无交易。

`ENUM_FREQUENCY_WITHHELD_PENDING_PRIVACY_THRESHOLD`：全量状态组合和 T_SetTid 重复键状态分层均包含 `<10（精确值已抑制）` 的小桶。为防止通过总数和互补桶反推，本节撤下整张分层频次表，不公开状态码组合、重复组分层或其互补桶精确值。[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；Task 4 隐私抑制规则]

[推断: 基于已抑制的状态组合聚合] T_SetTid 重复行横跨多种状态组合，不能认定重复只属于退费、部分退费或冲正，也不能从任一状态码推断历史版本或业务终态。状态码业务含义仍需权威字典签认；该结论不影响已经由 `T_TradeNo` 建立的内部锚点。

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
| 关联边界 | 只用 `T_TradeNo` 聚合和关联；未使用非锚点字段 `T_SetTid`，未输出 T_TradeNo 或任何行级标识 |
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
| T_FeeAll = T_FeeIn + T_FeeOut | 592 | 0 | `>582（精确值已抑制）` | `<10（精确值已抑制）` | 已抑制 | 已抑制 |
| T_FeeAll = T_FundPay + T_SelfPayAll | 592 | 0 | `>582（精确值已抑制）` | `<10（精确值已抑制）` | 已抑制 | 已抑制 |

[来源: outpatient_p0_t3_20260827_073210Z Q3 全量聚合]

四状态组合的逐桶通过/失败数及对应最大/合计金额差均已撤下：其中存在 `<10（精确值已抑制）` 小桶，保留总数或其他互补桶会导致反推。[来源: outpatient_p0_t3_20260827_073210Z Q3 四状态组合聚合；Task 4 隐私抑制规则]

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
| SUM(o_FeeItem.Fee) = o_Trade.T_FeeAll | 592 | 0 | `>582（精确值已抑制）` | `<10（精确值已抑制）` | 已抑制 | 已抑制 |
| SUM(o_FeeItem.FeeIn) = o_Trade.T_FeeIn | 592 | 0 | 592 | 0 | 0.0030 | 0.0380 |
| SUM(o_FeeItem.FeeOut) = o_Trade.T_FeeOut | 592 | 0 | `>582（精确值已抑制）` | `<10（精确值已抑制）` | 已抑制 | 已抑制 |

[来源: outpatient_p0_t3_precision_20260827_074356Z Q4 全量聚合；精度修正复核结果未变]

四状态组合下的交易数、逐项通过/失败数和金额差摘要均已撤下，避免小桶及其互补桶反推。[来源: outpatient_p0_t3_precision_20260827_074356Z Q4 四状态组合聚合；Task 4 隐私抑制规则]

[推断: 基于 outpatient_p0_t3_20260827_073210Z Q2 与 outpatient_p0_t3_precision_20260827_074356Z Q4] 复合键、T_TradeNo 主从覆盖和 FeeIn 勾稽通过，但 Fee 与 FeeOut 均存在 `<10（精确值已抑制）` 的超差交易，金额门禁未通过；相应差值摘要已抑制。差异状态分布不构成有效状态规则；在业务字典签认前不得删除或筛掉这些记录来制造全量通过。

#### 多专项基金候选字段

本节只确认 Task 1 登记的专项基金候选字段已完成 NULL/0/非零及共现聚合；不把 T_FundPay 与任何专项字段相加，也不把共现关系写成业务口径。字段分布和共现签名均含 `<10（精确值已抑制）` 小桶，且保留其他精确桶可由总数反推，故两张频次表整体撤下。[来源: outpatient_p0_t3_20260827_073210Z Q5–Q6；Task 4 隐私抑制规则]

`NT_AgencySumPay = NT_BasicPay + NT_CivilPay + NT_OtherPay` 仅按字段名作为候选等式验证，不视为权威业务公式。

| 范围 | 行数 | 缺 | 通 | 败 | 最大绝对差（元） | 合计绝对差（元） |
|---|---:|---:|---:|---:|---:|---:|
| 全量 | 592 | `>580（精确值已抑制）` | `<10（精确值已抑制）` | `<10（精确值已抑制）` | 已抑制 | 已抑制 |

按状态组合的候选等式分层及对应金额差摘要已整体撤下，避免小桶和互补桶反推。[来源: outpatient_p0_t3_20260827_073210Z Q7；Task 4 隐私抑制规则]

[推断: 基于 Q5–Q7] 候选分项字段在绝大多数交易中不完整，小规模可比较记录中仍存在 `<10（精确值已抑制）` 的超差交易；这些结果否定“当前数据已证明候选等式”的说法，但不能反向证明字段间真实业务关系。业务字典与医保办签认前，所有专项基金关系均保持候选/待确认。

#### 30 个脱敏锚点人工票据核对

状态：`MANUAL_TICKET_RECONCILIATION_BLOCKED`。

[来源: 本任务执行边界] 当前没有医保办票据、票据访问授权人员或获批的脱敏锚点传递通道，因此本批次没有选取、导出或展示任何原始锚点，也没有用数据库行代替人工票据核对。

解锁所需外部输入：至少 30 份由医保办在批准环境内选取的票据及其脱敏锚点映射；覆盖规则和有效状态范围；权威金额/退款/冲正字典；逐票据主金额与费用明细核对表。原始票据和行级映射只保存在医院批准的受控通道，本文仅接收脱敏聚合结论与签认结果。

签认角色：医保办授权经办人执行逐票核对，医保办负责人签认票据与金额口径，数据负责人签认字段和有效状态规则，信息安全/隐私负责人批准票据访问及脱敏传递边界。

#### 唯一费用明细源决定

| 冻结门槛 | 结果 | 状态 |
|---|---|---|
| 复合键与主从关联 | 复合键无重复；592/592 主交易均有明细，主表无明细 0、明细无主表 0 | 通过 |
| 金额勾稽 | Fee、FeeOut 及两组 o_Trade 自身等式均存在 `<10（精确值已抑制）` 的超差交易；对应差值摘要已抑制 | 未通过 |
| 有效状态规则 | 四状态组合已聚合，但没有权威状态字典和筛选规则 | BLOCKED |
| 至少 30 个票据人工核对 | 无票据和授权人员，未选取或导出锚点 | `MANUAL_TICKET_RECONCILIATION_BLOCKED` |
| dbo.o_FeeItem 唯一费用明细源 | 仅保持候选；不冻结 | BLOCKED |

[推断: 基于 outpatient_p0_t3_20260827_073210Z 与冻结门槛] dbo.o_FeeItem 的键和关联门槛通过，但金额、有效状态和人工票据三项门槛未全部通过，因此不能冻结为唯一费用明细源。

[推断: 基于数据侧已出现超过容差的实质差异] `yb_mzfymx_mz` 仅登记为下一步**待授权验证候选**；本任务没有查询该表，也没有扩大 Task 1 的 dbo.o_Trade、dbo.o_FeeItem 两表白名单。只有取得额外表授权后才能单独验证，不能据字段名预设其优于 dbo.o_FeeItem。

## 增量游标

### Task 6：增量游标与变更捕获

#### 文档级审计证据批次

| 项目 | 结果 |
|---|---|
| 文档级证据批次 ID | `outpatient_p0_t6_20260827_094619Z`；不是数据库审计 ID 或外部 run_id |
| 固定执行时间 | SQL Server `SYSDATETIMEOFFSET()`：2026-08-27 09:46:19.0642536 +00:00，即 2026-08-27 17:46:19.0642536 +08:00；只作为本批次服务器时钟锚点 |
| 主体指纹 | SHA-256 38F144F8D609E1F6CFA0E3B2E4225EF783A0B313A98262F71FC0862BF97ACD70，与 Task 1–4 一致；不记录登录名 |
| 数据范围 | 只查询 dbo.o_Trade、dbo.o_FeeItem 的 catalog 和脱敏聚合；没有读取样例行或第三张业务表 |
| 隔离与超时 | 显式 `READ COMMITTED`，连接超时 30 秒，`LOCK_TIMEOUT` 5 秒；没有使用 `READ UNCOMMITTED` |
| 一致性边界 | catalog、候选画像、容量为依次执行的三个查询批次，没有显式事务或快照隔离；结果是非原子观察，不能声明两表同一水位 |
| 成功查询耗时 | catalog 69.29 ms；候选字段画像 15.50 ms；容量聚合 37.59 ms |
| 实际数据库操作 | 仅 `SET`、`SELECT`；未执行 DDL/DML，未修改索引 |
| 查询失败 | 首次容量批次中的 `PERCENTILE_CONT` 因源库兼容级别低于其要求而编译失败；该 SQL 未重试，最终批次改用显式 nearest-rank 算法。此前两次本地脚本分别在 `.env` 自动定位和游标级 timeout 设置处于执行 SQL 前失败，不属于源库查询失败 |

[来源: 文档级证据批次 outpatient_p0_t6_20260827_094619Z；执行主体指纹 SHA-256 38F144F8…ACD70；本节留存查询口径]

#### 变更能力 catalog 证据

| 对象 | CDC | Change Tracking | 时态表 | rowversion/timestamp 列 | identity 列 | 表级触发器 | 判断 |
|---|---:|---:|---:|---:|---:|---:|---|
| dbo.o_Trade | 0 | 0 | 0 | 0 | 0 | 0 | 没有可证明的数据库变更序列或删除记录 |
| dbo.o_FeeItem | 0 | 0 | 0 | 0 | 0 | 0 | 没有可证明的数据库变更序列或删除记录 |

数据库级 `DATABASEPROPERTYEX(...,'IsCdcEnabled')` 在当前实例返回 NULL，因此不据此判断数据库级 CDC；表级 `sys.tables.is_tracked_by_cdc=0` 足以证明这两张目标表未启用 CDC。`sys.change_tracking_tables`、`sys.triggers` 对两表均无记录，`temporal_type=0`，物理列中也不存在 `rowversion`/`timestamp`。[来源: SQL Server `sys.tables`、`sys.columns`、`sys.types`、`sys.change_tracking_tables`、`sys.triggers`]

元数据白名单只找到 dbo.o_Trade 的六个字段名候选：`T_TradeDate`、`T_ConfirmTime`、`SETL_DATE`、`T_HadDealTime`、`T_Version1`、`T_Version2`。前四个是 `datetime`，后两个是 `nvarchar`；均无默认值或权威字典证明其为“记录创建时间”“最后修改时间”或单调版本。dbo.o_FeeItem 没有任何日期、版本、创建、修改或删除命名候选。[来源: Task 1 `INFORMATION_SCHEMA.COLUMNS` 全量元数据；outpatient_p0_t6_20260827_094619Z catalog 查询]

候选筛选规则固定为：先枚举两表全部 SQL `datetime`、`timestamp`/`rowversion` 物理列及名称含 `Version` 的列；仅将名称可能描述交易生成/确认/结算/处理或版本变化的字段纳入物理画像，明确属于患者、转诊、诊断或原交易业务事件的日期直接排除。字段名只能触发核验，不能证明变更语义。Task 1 全量元数据中两表一共只有下列 DateTime/Version 类字段；日期样式但物理类型为 varchar 的字段不具备可排序日期契约，也不进入游标候选。

| 物理字段 | 类型 | 纳入候选画像 | 纳入/排除理由 |
|---|---|:---:|---|
| o_Trade.T_TradeDate | datetime NOT NULL | 是 | 名称描述交易日期，纳入核验但不得默认当新增/变更时间 |
| o_Trade.T_ConfirmTime | datetime NULL | 是 | 确认业务事件时间候选，需验证是否可能随回写变化 |
| o_Trade.SETL_DATE | datetime NULL | 是 | 结算业务事件时间候选，需验证是否可能随回写变化 |
| o_Trade.T_HadDealTime | datetime NULL | 是 | 处理业务事件时间候选，需验证是否可能随回写变化 |
| o_Trade.T_Version1 / T_Version2 | nvarchar NOT NULL | 是 | 名称含 Version；需排除协议/规则版本而非行版本，画像证明其低基数且非单调证据 |
| o_Trade.T_RedListVersion | nvarchar NULL | 否 | 红名单业务版本候选，不是源行版本；且无权威变更语义 |
| o_Trade.T_SignVersion | nvarchar NULL | 否 | 签名协议版本候选，不是源行版本；且无权威变更语义 |
| o_Trade.T_HisInterfaceVersion | nvarchar NULL | 否 | HIS 接口版本候选，不是源行版本；且无权威变更语义 |
| o_Trade.P_Birthday | datetime NOT NULL | 否 | 患者出生日期，S3 敏感静态属性；与源行变化无关且禁止画像 |
| o_Trade.P_FromHospDate | datetime NULL | 否 | 转出/来源医院业务日期候选，不描述本表记录变化 |
| o_Trade.T_PerAccountDiagDateTime | datetime NULL | 否 | 账户诊断业务事件日期候选，不描述本表记录变化 |
| o_Trade.T_OraginalTradeDate | datetime NULL | 否 | 原交易业务日期，用于交易关系而非当前行变更水位 |
| o_FeeItem | 无 DateTime/Version 类列 | 否 | 没有可画像的独立变更字段 |

Task 6 实际 `INFORMATION_SCHEMA.COLUMNS` catalog 查询同时读取六个纳入候选的 `COLUMN_DEFAULT`，结果均为 NULL；这只证明未发现数据库默认约束，不能证明应用写入语义。两表 `timestamp`/`rowversion` 列数均为 0。[来源: outpatient_p0_t6_20260827_094619Z catalog 结果]

#### 交易表字段名候选的物理画像

“重复余量”定义为非空行数减去 distinct 数，只证明时间点/版本值被复用，不等于重复组数或脏数据。“早于交易时间”只比较同一当前行中的两个物理日期，不是写入顺序或更新倒退证据。

| 字段名候选 | NULL/空白 | distinct 非空 | 重复余量 | 早于 T_TradeDate | 服务器最近 24h 观察行 | 物理范围 | 游标决定 |
|---|---:|---:|---:|---:|---:|---|---|
| T_TradeDate | 0 | 540 | 52 | 不适用 | 0 | 2024-03-11 09:28:38 至 2026-04-17 10:41:45 | **BLOCKED**；已知是交易日期候选，不是变更时间 |
| T_ConfirmTime | 14 | 530 | 48 | 72 | 0 | 2024-03-11 09:28:41 至 2026-04-17 10:41:59 | **BLOCKED**；可空且无“最后修改”语义 |
| SETL_DATE | 17 | 257 | 318 | 318 | 0 | 1900-01-01 00:00:00 至 2026-04-17 10:41:55 | **BLOCKED**；可空、重复高且含 1900 哨兵候选，结算/更新语义均未签认 |
| T_HadDealTime | 15 | 533 | 44 | 73 | 0 | 2024-03-11 09:28:41 至 2026-04-17 10:41:59 | **BLOCKED**；可空且无“最后修改”语义 |
| T_Version1 | 81 | 7 | 504 | 不可计算 | 不可计算 | 未展示原始值 | **BLOCKED**；nvarchar 低基数，不能证明单调 |
| T_Version2 | 80 | 5 | 507 | 不可计算 | 不可计算 | 未展示原始值 | **BLOCKED**；nvarchar 低基数，不能证明单调 |

[来源: outpatient_p0_t6_20260827_094619Z 候选字段聚合；总行数 592。版本原始值未查询/未展示]

[推断: 基于一次当前状态的非原子观察及变更能力缺失] NULL、重复和同行日期倒置足以否定“仅凭字段名即可冻结游标”，但不能重建数据库历史写入顺序。因此以下三项均为**不可测而非零**：候选游标跨行单调倒退数、最近 24 小时迟到写入数、跨 10 分钟重叠窗口被更新数。服务器最近 24 小时的四个日期字段均观察到 0 行，只说明这些业务日期/处理日期未落入服务器时钟窗口，不能证明最近 24 小时没有 INSERT/UPDATE。

dbo.o_FeeItem 没有候选变更字段，所以无法执行 NULL、重复、倒退、迟到或重叠窗口更新统计；不能用父交易的 T_TradeDate 代替明细自身变更水位，因为父行时间不会证明明细后续新增、修改或删除。[推断: 基于两表物理字段与一对多关系]

#### 新增、更新、退费、冲正和删除捕获决定

| 变更类型 | 当前两表可见事实 | 分钟级捕获决定 |
|---|---|---|
| 新增 | 当前状态观察可见 `T_TradeNo` 或费用复合键，但没有可靠新增时间/序列 | **BLOCKED**；除全表键比对外无有界增量条件，而全表轮询不获批准 |
| 更新 | 两表没有 last-modified、rowversion、CDC/CT、时态历史或更新触发日志 | **BLOCKED**；当前状态观察不能证明何时、哪些列被回写 |
| 退费 | 交易表有状态、退费和原交易字段名候选，但 Task 2–5 已证明无码表、无净额化规则 | **BLOCKED**；既可能新增退费交易也可能回写原交易，当前通道不能保证全捕获 |
| 冲正/重交易 | 有 `NT_ReTradeFlag`、原交易关系等候选，但无权威状态机和变更序列 | **BLOCKED**；不能判定新增、替换或回写语义 |
| 删除 | 两表未启用 CDC/CT/时态表/删除触发日志，也无已签认 tombstone | **BLOCKED**；物理删除对后续状态观察不可见 |

[推断: 基于 catalog 证据与 Task 2–5 状态/退款门禁] **分钟轮询不成立**。P1 前必须由院方提供覆盖两张最终事实源的 CDC 或等价变更日志，至少包含操作类型、提交顺序/LSN、提交时间、主键、删除 tombstone、事务边界、保留期与可重放边界；保留期必须覆盖约定的最大停机与回补窗口。只提供 SQL Server Change Tracking 时还须证明如何一致读取变更后的行并处理已删除键；不得用全表扫描或父表业务日期轮询伪装 1–5 分钟近实时。

#### 实际计划与耗时测试决定

未执行候选增量谓词的实际执行计划、索引使用、返回行数、P50/P95 延迟测试。原因不是查询工具不可用，而是两表均没有通过语义和完备性门禁的增量条件；对 `T_TradeDate`、`SETL_DATE` 或父交易日期做性能测试只会验证错误方案，不能形成 P1 证据。现有 `IX_QUERY(T_TradeDate,...)` 只证明索引物理存在，不证明 T_TradeDate 是变更游标。[来源: Task 1 索引元数据；outpatient_p0_t6_20260827_094619Z 游标结论]

本批次未请求执行计划、未修改索引。待 CDC/变更日志和专用只读账号就绪后，才对**已冻结的真实增量条件**测试索引/捕获表访问路径、返回行数和多次 P50/P95；该后续测试不能在当前过度授权主体上替代最小权限验收。

#### P1 增量输入冻结/阻断表

| 输入项 | dbo.o_Trade | dbo.o_FeeItem | Task 6 决定 |
|---|---|---|---|
| 游标字段 | 无可靠字段 | 无候选字段 | **BLOCKED**；等待院方 CDC/变更日志提交顺序 |
| 稳定排序键 | `T_TradeNo` 已由 Task 2 证明唯一 | `(T_TradeNo,ItemId,ItemNo)` 已由 Task 2 证明唯一 | 仅冻结为确定性键组件；没有游标时不构成可执行组合游标 |
| 10 分钟重叠 | 无变更时间，无法定义 | 无变更时间，无法定义 | **BLOCKED**；重叠不能补救无更新/删除可见性 |
| 页大小初值 | 未测试真实增量路径 | 未测试真实增量路径 | **BLOCKED**；不猜默认值 |
| 退费/冲正语义 | 无码表/状态机/净额规则 | 明细跟随、回写或删除方式不明 | **BLOCKED**；沿用 T5-B02 |
| 预期峰值 | 无可靠最近 30 日业务窗口 | 同左 | **BLOCKED**；历史物理峰值不得充当生产峰值 |
| 运行时配置边界 | — | — | 将来只允许页大小、轮询间隔可调；游标、排序键、重叠规则、状态语义和峰值基线必须在发布版本中固定，不做运行时开关 |

Task 6 增量结果：**DONE_WITH_BLOCKERS**。冻结的是“拒绝当前两表分钟轮询”和院方变更日志输入要求，不是生产增量契约；T6-B01 至 T6-B04 解除前不得编写 P1 生产取数计划。

## 容量与性能

### Task 6：容量观察与可用边界

| 容量项 | 聚合观察 | 可用于 P1 容量基线？ |
|---|---|---|
| 当前全量规模 | 592 个唯一 T_TradeNo；2,139 条费用明细 | 否；只证明 READ COMMITTED 多查询批次中的非原子观察规模，不是两表一致快照；Task 1 发现缓存和数据完整性范围未解除 |
| 当前物理日期范围 | T_TradeDate 2024-03-11 至 2026-04-17，共跨 768 个自然日，仅 28 个有记录日 | 否；T_TradeDate 业务时区/完整性未签认，分布明显稀疏 |
| 全历史自然日均值 | 交易 0.7708/日；明细 2.7852/日 | 否；包含 740 个无记录自然日，不能代表医院正常流量 |
| 全历史有记录日均值 | 交易 21.1429/有记录日；明细 76.3929/有记录日 | 否；排除无记录日会产生选择偏差，仅供解释当前样本 |
| 全历史物理日峰值 | 交易 226；明细 1,078 | 否；不是已证明的最近 30 日峰值，也未证明数据覆盖完整 |
| 最大物理日期当天 | 交易业务键 `<10（精确值已抑制）`；关联明细精确值已抑制 | 否；只是数据中的最大 T_TradeDate 日，不是“当前最近一日”；交易小桶及其关联明细按 Task 4 当前临时抑制边界一并隐藏 |
| 服务器时钟最近 30 日/24h | T_TradeDate 观察到 0/0 个交易 | 否；Task 2 已阻断业务时区/时钟语义，不能解释为最近业务数据为零 |
| 每交易明细数 | 592 个 T_TradeNo 分组；nearest-rank P50=3、P95=18、P99=18、最大=33 | 部分；只可作为以 `T_TradeNo` 为内部锚点的历史样本观察，尚不是生产容量基线 |
| 机械三年线性外推 | 以 592/2,139 除以 768 日再乘 1,096 日：约 845 个交易、3,053 条明细 | 否；明确不是最近 30 日依据或容量预测，不用于采购、分区、SLA 或压测 |

nearest-rank 定义为排序后第 `ceil(N×p)` 个整数计数，避免依赖当前兼容级别不支持的 `PERCENTILE_CONT`；P50/P95/P99 都基于 `T_TradeNo` 分组，不使用非锚点字段 T_SetTid。[来源: outpatient_p0_t6_20260827_094619Z 容量聚合]

[推断: 基于 Task 2 时间阻断与本批次稀疏物理日期分布] 最近 30 天日均交易数/明细数、最近 30 天峰值交易数/明细数、当前最近一日数据量和可信三年容量外推均为 **BLOCKED**，不以服务器窗口的 0 或机械外推替代。解锁需数据负责人签认交易/结算时间语义、医院时区、全量覆盖起点、缺口日和补录规则，并在同一新鲜一致性水位重跑最近 30 个完整业务日；同时取得院方业务增长系数、留存期、重跑系数和至少一个已知高峰窗口。

Task 1 的发现持久化约 0.379 秒只反映缓存复用；本批次 37.59 ms 只反映 592/2,139 行小样本聚合。两者都不是增量拉取延迟、数据库负载或生产吞吐证明，也不能生成页大小初值。

#### Task 6 最终只读查询口径

以下为最终有效批次的核心查询口径。所有语句前均执行 `SET TRANSACTION ISOLATION LEVEL READ COMMITTED; SET LOCK_TIMEOUT 5000;`，结果只包含字段名、日期边界和聚合计数。

```sql
SELECT t.name AS table_name,
       t.is_tracked_by_cdc,
       t.temporal_type,
       CASE WHEN ct.object_id IS NULL THEN 0 ELSE 1 END AS change_tracking_enabled,
       SUM(CASE WHEN ty.name IN ('timestamp','rowversion') THEN 1 ELSE 0 END) AS rowversion_columns,
       SUM(CASE WHEN c.is_identity=1 THEN 1 ELSE 0 END) AS identity_columns
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id=t.schema_id
JOIN sys.columns c ON c.object_id=t.object_id
JOIN sys.types ty ON ty.user_type_id=c.user_type_id
LEFT JOIN sys.change_tracking_tables ct ON ct.object_id=t.object_id
WHERE s.name='dbo' AND t.name IN ('o_Trade','o_FeeItem')
GROUP BY t.name,t.is_tracked_by_cdc,t.temporal_type,ct.object_id;

SELECT OBJECT_NAME(tr.parent_id) AS table_name, COUNT_BIG(*) AS trigger_count,
       SUM(CASE WHEN OBJECTPROPERTY(tr.object_id,'ExecIsInsertTrigger')=1 THEN 1 ELSE 0 END) AS insert_trigger_count,
       SUM(CASE WHEN OBJECTPROPERTY(tr.object_id,'ExecIsUpdateTrigger')=1 THEN 1 ELSE 0 END) AS update_trigger_count,
       SUM(CASE WHEN OBJECTPROPERTY(tr.object_id,'ExecIsDeleteTrigger')=1 THEN 1 ELSE 0 END) AS delete_trigger_count
FROM sys.triggers tr
WHERE tr.parent_id IN (OBJECT_ID('dbo.o_Trade'),OBJECT_ID('dbo.o_FeeItem'))
GROUP BY tr.parent_id;

SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA='dbo'
  AND TABLE_NAME IN ('o_Trade','o_FeeItem')
  AND (
    DATA_TYPE IN ('timestamp','rowversion') OR
    COLUMN_NAME IN (
      'T_TradeDate','T_ConfirmTime','SETL_DATE','T_HadDealTime',
      'T_Version1','T_Version2'
    ) OR
    LOWER(COLUMN_NAME) LIKE '%update%' OR
    LOWER(COLUMN_NAME) LIKE '%modify%' OR
    LOWER(COLUMN_NAME) LIKE '%create%' OR
    LOWER(COLUMN_NAME) LIKE '%delete%'
  )
ORDER BY TABLE_NAME, ORDINAL_POSITION;

SELECT COUNT_BIG(*) AS total_rows,
       SUM(CASE WHEN T_TradeDate IS NULL THEN 1 ELSE 0 END) AS trade_date_nulls,
       COUNT_BIG(DISTINCT T_TradeDate) AS trade_date_distinct,
       SUM(CASE WHEN T_ConfirmTime IS NULL THEN 1 ELSE 0 END) AS confirm_time_nulls,
       COUNT_BIG(DISTINCT T_ConfirmTime) AS confirm_time_distinct,
       SUM(CASE WHEN SETL_DATE IS NULL THEN 1 ELSE 0 END) AS setl_date_nulls,
       COUNT_BIG(DISTINCT SETL_DATE) AS setl_date_distinct,
       SUM(CASE WHEN T_HadDealTime IS NULL THEN 1 ELSE 0 END) AS had_deal_time_nulls,
       COUNT_BIG(DISTINCT T_HadDealTime) AS had_deal_time_distinct,
       SUM(CASE WHEN T_Version1 IS NULL OR LTRIM(RTRIM(T_Version1))='' THEN 1 ELSE 0 END) AS version1_missing_or_blank,
       COUNT_BIG(DISTINCT NULLIF(LTRIM(RTRIM(T_Version1)),'')) AS version1_distinct_nonblank,
       SUM(CASE WHEN T_Version2 IS NULL OR LTRIM(RTRIM(T_Version2))='' THEN 1 ELSE 0 END) AS version2_missing_or_blank,
       COUNT_BIG(DISTINCT NULLIF(LTRIM(RTRIM(T_Version2)),'')) AS version2_distinct_nonblank,
       SUM(CASE WHEN T_ConfirmTime IS NOT NULL AND T_ConfirmTime<T_TradeDate THEN 1 ELSE 0 END) AS confirm_before_trade_rows,
       SUM(CASE WHEN SETL_DATE IS NOT NULL AND SETL_DATE<T_TradeDate THEN 1 ELSE 0 END) AS setl_before_trade_rows,
       SUM(CASE WHEN T_HadDealTime IS NOT NULL AND T_HadDealTime<T_TradeDate THEN 1 ELSE 0 END) AS had_deal_before_trade_rows,
       MIN(T_TradeDate) AS trade_date_min,
       MAX(T_TradeDate) AS trade_date_max,
       MIN(T_ConfirmTime) AS confirm_time_min,
       MAX(T_ConfirmTime) AS confirm_time_max,
       MIN(SETL_DATE) AS setl_date_min,
       MAX(SETL_DATE) AS setl_date_max,
       MIN(T_HadDealTime) AS had_deal_time_min,
       MAX(T_HadDealTime) AS had_deal_time_max
FROM dbo.o_Trade;

-- @as_of 由调用方绑定为本节“固定执行时间”的 UTC 无时区值；不在文档写死。
DECLARE @as_of datetime2(3) = ?;
DECLARE @window_30d_start datetime2(3) = DATEADD(day,-30,@as_of);
DECLARE @window_24h_start datetime2(3) = DATEADD(day,-1,@as_of);
DECLARE @suppress_below bigint = 10;

SELECT @window_30d_start AS window_30d_start,
       @window_24h_start AS window_24h_start,
       @as_of AS window_end,
       COUNT_BIG(DISTINCT CASE
         WHEN t.T_TradeDate>=@window_30d_start AND t.T_TradeDate<@as_of
         THEN t.T_TradeNo END) AS server_window_30d_trade_rows,
       SUM(CASE
         WHEN t.T_TradeDate>=@window_30d_start AND t.T_TradeDate<@as_of
              AND f.T_TradeNo IS NOT NULL
         THEN 1 ELSE 0 END) AS server_window_30d_detail_rows,
       COUNT_BIG(DISTINCT CASE
         WHEN t.T_TradeDate>=@window_24h_start AND t.T_TradeDate<@as_of
         THEN t.T_TradeNo END) AS server_window_24h_trade_rows,
       SUM(CASE
         WHEN t.T_TradeDate>=@window_24h_start AND t.T_TradeDate<@as_of
              AND f.T_TradeNo IS NOT NULL
         THEN 1 ELSE 0 END) AS server_window_24h_detail_rows
FROM dbo.o_Trade t
LEFT JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo;

SELECT SUM(CASE WHEN T_TradeDate>=@window_24h_start AND T_TradeDate<@as_of THEN 1 ELSE 0 END)
         AS trade_date_server_24h_rows,
       SUM(CASE WHEN T_ConfirmTime>=@window_24h_start AND T_ConfirmTime<@as_of THEN 1 ELSE 0 END)
         AS confirm_time_server_24h_rows,
       SUM(CASE WHEN SETL_DATE>=@window_24h_start AND SETL_DATE<@as_of THEN 1 ELSE 0 END)
         AS setl_date_server_24h_rows,
       SUM(CASE WHEN T_HadDealTime>=@window_24h_start AND T_HadDealTime<@as_of THEN 1 ELSE 0 END)
         AS had_deal_time_server_24h_rows
FROM dbo.o_Trade;

WITH daily AS (
  SELECT CONVERT(date,t.T_TradeDate) AS physical_date,
         COUNT_BIG(DISTINCT t.T_TradeNo) AS trade_rows,
         COUNT_BIG(f.T_TradeNo) AS detail_rows
  FROM dbo.o_Trade t
  LEFT JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
  GROUP BY CONVERT(date,t.T_TradeDate)
), bounds AS (
  SELECT MIN(physical_date) AS min_date,
         MAX(physical_date) AS max_date,
         COUNT_BIG(*) AS active_days,
         SUM(trade_rows) AS total_trades,
         SUM(detail_rows) AS total_details,
         MAX(trade_rows) AS peak_trades,
         MAX(detail_rows) AS peak_details
  FROM daily
)
SELECT b.min_date, b.max_date, b.active_days,
       DATEDIFF(day,b.min_date,b.max_date)+1 AS calendar_span_days,
       b.total_trades, b.total_details, b.peak_trades, b.peak_details,
       CONVERT(decimal(18,4),b.total_trades*1.0/
         NULLIF(DATEDIFF(day,b.min_date,b.max_date)+1,0)) AS calendar_daily_avg_trades,
       CONVERT(decimal(18,4),b.total_details*1.0/
         NULLIF(DATEDIFF(day,b.min_date,b.max_date)+1,0)) AS calendar_daily_avg_details,
       CONVERT(decimal(18,4),b.total_trades*1.0/NULLIF(b.active_days,0)) AS active_daily_avg_trades,
       CONVERT(decimal(18,4),b.total_details*1.0/NULLIF(b.active_days,0)) AS active_daily_avg_details,
       CASE WHEN d.trade_rows<@suppress_below THEN NULL ELSE d.trade_rows END
         AS latest_physical_day_trades,
       CASE WHEN d.trade_rows<@suppress_below THEN 1 ELSE 0 END
         AS latest_physical_day_trades_suppressed,
       CASE WHEN d.trade_rows<@suppress_below OR d.detail_rows<@suppress_below
         THEN NULL ELSE d.detail_rows END
         AS latest_physical_day_details,
       CASE WHEN d.trade_rows<@suppress_below OR d.detail_rows<@suppress_below
         THEN 1 ELSE 0 END
         AS latest_physical_day_details_suppressed
FROM bounds b
JOIN daily d ON d.physical_date=b.max_date;

WITH per_trade AS (
  SELECT T_TradeNo, COUNT_BIG(*) AS detail_rows
  FROM dbo.o_FeeItem GROUP BY T_TradeNo
), ranked AS (
  SELECT detail_rows,
         ROW_NUMBER() OVER (ORDER BY detail_rows) AS rn,
         COUNT_BIG(*) OVER () AS n
  FROM per_trade
)
SELECT COUNT_BIG(*) AS transaction_groups,
       MIN(detail_rows) AS min_details,
       MAX(detail_rows) AS max_details,
       MAX(CASE WHEN rn=CONVERT(bigint,CEILING(n*0.50)) THEN detail_rows END) AS nearest_rank_p50_details,
       MAX(CASE WHEN rn=CONVERT(bigint,CEILING(n*0.95)) THEN detail_rows END) AS nearest_rank_p95_details,
       MAX(CASE WHEN rn=CONVERT(bigint,CEILING(n*0.99)) THEN detail_rows END) AS nearest_rank_p99_details,
       SUM(detail_rows) AS total_details
FROM ranked;
```

[来源: outpatient_p0_t6_20260827_094619Z；窗口边界由本节固定执行时间参数化复现。上面的窗口与日聚合 SQL 是对同批口径的脱敏复核形式，最大日期日计数在 SQL 层应用当前 `<10` 临时抑制边界；本次质量修订未新增数据库查询]

## 政策 Skill 依赖

### Task 4：政策解释最小字段闭包

#### 独立对照结论

文档级非数据库审计证据批次：`outpatient_p0_t4_20260827_policy_closure`。聚合执行完成戳为 `2026-08-27T08:01:38.5137703Z`（`2026-08-27 16:01:38.5137703 +08:00`）；主体指纹仍为 `38F144F8D609E1F6CFA0E3B2E4225EF783A0B313A98262F71FC0862BF97ACD70`，只引用 Task 1 已留存的脱敏主体证据，不记录账号、连接、患者或业务标识值。数据源经 `PolicyMetaStore(DATABASE_URL)`、`SemanticDataSource(meta_store=meta)` 和 datasource `bjybdb` 解析；初始化 stdout 已重定向。本批次 SQL Server 只执行 `SET`/`SELECT`。

[来源: 总设计 §9.2–§10.6；Issue 20 设计 §4–§6；`skills/settlement_explain_skill/{SKILL.md,schemas,assembler.py,fact_builder.py,scripts/normalize_fee_context.py,strategies/*/policy_queries.yaml}`；`src/runtime/policy_qa/{settlement_data_provider.py,structured_policy_retriever.py}`]

- 当前 `settlement_explain_skill` 是住院费用解释：数据提供器读取五张住院表；assembler/fact_builder 消费住院起付、统筹、大额和个人支付字段；政策检索的确定性过滤实际依赖 `insu_type`、`med_type`、`hosp_lv`、`psn_type`，现有 `NormalizedPolicyContext` 尚无地区、结算日期、异地、慢特病、专项待遇或政策适用机构字段。
- 现有住院标准化器会在缺值时补“城镇职工”“住院-普通住院”“三级医院”“退休人员”。[推断: 基于现有代码] 这些是门诊新 Skill 必须禁止继承的住院默认值；门诊上下文缺失必须保持 `missing`/`missing_external_context`。
- **权威字段汇总（其余段落只引用本行）**：设计字段按 `table.column` 去重后为 104 个（`o_Trade` 84、`o_FeeItem` 20；同名 `T_TradeNo` 是两张表各自的物理列），本次全部物理存在。A–F 共 107 个可聚合物理字段（104 个设计字段 + 3 个政策上下文物理候选）完成非快照观察；G 组 8 个敏感字段只引用 Task 1 `INFORMATION_SCHEMA` 元数据、不做数据画像；另登记 4 个不可由两表直接提供的外部上下文。矩阵共 119 行。Issue20 原型清单另有 88 个唯一语义指标代码：85 个直接同名落到两表，`FeeItem_SelfPay2`/`FeeItem_State` 显式别名落到 `o_FeeItem.SelfPay2/State`，`HospitalLevel` 由 `o_Trade.T_HospCode` 经待治理机构等级值域解析；因此 119 行矩阵是其超集，不代表业务语义和外部值域已经签认。
- 物理存在不等于语义闭包完成。除 Task 2 已证明的内部交易/明细键外，当前没有院方字段字典或医保办签认足以把字段名候选升级为权威业务含义；尤其 `TB_*`/`TA_*` 不得仅凭前缀解释为交易前/后。

矩阵缩写：`n/z/v/d` 分别为 NULL、显式零（字符串为显式空串）、非零/非空、distinct；`oT`=`dbo.o_Trade`（592 行），`oF`=`dbo.o_FeeItem`（2,139 行）。n/z/v/d 中出现 1–9 结果的行不展示精确值；为避免利用总行数和其余桶做减法反推，本版将整格标为 `withheld（低频可反推）`。数字 10 只是本次文档采用的保守抑制下限，不是生产隐私阈值。`ENUM_FREQUENCY_WITHHELD_PENDING_PRIVACY_THRESHOLD` 表示枚举值频次整体不发布。`S1` 为授权场景内普通医保事实，`S2` 为可关联业务键/敏感健康事实（仅内部受限使用），`S3` 为直接标识或明确排除字段。Profile：P1 整体结算，P2 个人负担，P3 支付渠道，P4 起付与年度累计，P5 比例与封顶，P6 目录与明细，P7 身份与专项，P8 异地与机构，P9 状态与退费，`ALL` 表示九个 Profile 的内部定位依赖。

“是否核心”按用户任务而非字段数量判定：Issue20 §4 的公共上下文与 §5.2 强制锚点为“通用核心”；总设计 §9.4/§10 及 Issue20 §4/§5.4 中无条件决定某 Profile 主要输出的字段为“对应Profile核心”；仅在资格或场景适用时参与结论的补充、救助/军残、退役、大病、民政、慢特病、异地、一级机构等字段为“条件核心”；重复候选、内部去重或不能单独形成结论的字段为“辅助”；必须由可信系统注入且缺失即不能判断的无条件上下文为“外部核心”；禁止进入公开 Skill 的字段为“排除”。条件不满足时，只有同时具备可信资格事实和覆盖结算日期的政策证据，相关字段才可推导为 `not_applicable`；字段为 0 不能使整个 Profile 永久阻断，也不能单独证明不适用。[来源: 总设计 §9.3–§10.6；Issue20 §4–§6]

来源键图例：`D10.1`–`D10.5` 分别指 `docs/superpowers/specs/2026-08-27-outpatient-medical-insurance-assistant-design.md` §10.1–§10.5 的交易状态、待遇身份/政策匹配、当次费用支付、年度累计、费用明细字段组；`I5.4A`–`I5.4E` 分别指 `docs/superpowers/specs/2026-08-26-mzsettlement-verify-skill-design.md` §5.4 的同序五组；`T1-META` 指 Task 1 `INFORMATION_SCHEMA.COLUMNS` 证据；`T2-KEY` 指 Task 2 键与关联聚合；`T3-AMOUNT` 指 Task 3 金额勾稽；`T4-PRIV` 指本节敏感排除与频次抑制规则。来源键只引用所列确切章节或批次，不跨表继承；下文不使用“同上”。

**权威分类汇总**：通用核心 1、对应Profile核心 48、条件核心 48、辅助 11、外部核心 3、排除 8，共 119 行。其中 `T_TradeNo` 是唯一通用核心，`T_SetTid` 降为辅助；外部上下文实际为 4 行：`policy_region`、`hospital_id`、`policy_applicable_institution` 属外部核心，`special_benefit_type` 因只在专项资格适用时参与而计入条件核心。后文不重复重算，以本行为准。

##### A. 交易定位与状态（13 个）

| 语义名 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 普通可空结算标识 / `T_SetTid` | oT | varchar(30) NULL | 是 | 11/324/257/257 | [来源: Issue20 §5.2] 明确不作为锚点；业务释义仍待字典确认 | S2，禁止公开 | P9 | 辅助 | `semantics_pending` |
| 内部结算锚点兼交易业务键 / `T_TradeNo` | oT | nvarchar(22) NOT NULL | 是 | 0/0/592/592 | [来源: Issue20 §4/§5.2、Issue20 分支 `src/semantic_layer/seed.py`、Task 2 全量非空唯一] | S2，禁止公开 | ALL | 通用核心 | `verified` |
| 交易日期 / `T_TradeDate` | oT | datetime NOT NULL | 是 | 0/0/592/540 | [来源: D10.1/I5.4A；时区语义未签认] | S1 | P1,P4,P5,P9 | 对应Profile核心 | `semantics_pending` |
| 交易状态 / `T_State` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.1/I5.4A；无权威码表] | S1 | P1,P9 | 对应Profile核心 | `semantics_pending` |
| 已退款标志 / `T_HasRefundmented` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.1/I5.4A；无权威码表] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 部分退费标志 / `T_PartialReturnFlag` | oT | nvarchar(1) NULL | 是 | withheld（低频可反推） | [来源: D10.1/I5.4A；无权威码表] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 原交易号 / `T_OraginalTradeNo` | oT | nvarchar(22) NULL | 是 | 0/504/88/88 | [来源: D10.1/I5.4A；退款链含义未签认] | S2，禁止公开 | P9 | 对应Profile核心 | `semantics_pending` |
| 原交易日期 / `T_OraginalTradeDate` | oT | datetime NULL | 是 | 469/0/123/87 | [来源: D10.1/I5.4A；退款链含义未签认] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 国家平台结算状态 / `NP_Settle_State` | oT | varchar(1) NULL | 是 | withheld（低频可反推） | [来源: D10.1/I5.4A；无权威码表] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 国家平台结算日期 / `SETL_DATE` | oT | datetime NULL | 是 | 17/0/575/257 | [来源: D10.1/I5.4A；与交易日期优先级未签认] | S1 | P5,P9 | 对应Profile核心 | `semantics_pending` |
| 重交易标志 / `NT_ReTradeFlag` | oT | varchar(3) NULL | 是 | withheld（低频可反推） | [来源: D10.1/I5.4A；无权威码表] | S1 | P9 | 对应Profile核心 | `semantics_pending` |
| 诊断交易类型 / `T_DiagType` | oT | nvarchar(1) NULL | 是 | withheld（低频可反推） | [来源: I5.4A；无权威码表] | S1 | P5,P7 | 辅助 | `semantics_pending` |
| 费用号 / `T_FeeNo` | oT | nvarchar(20) NULL | 是 | 0/143/449/402 | [来源: I5.4A；内部关联用途未签认] | S2，禁止公开 | P1,P6 | 辅助 | `semantics_pending` |

##### B. 待遇身份与政策匹配（21 个）

| 语义名 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 险种 / `P_FundType` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；现有检索要求 insu_type；无码表] | S1 | P1,P5,P7,P8 | 对应Profile核心 | `semantics_pending` |
| 人员类别 / `PN_PersonType` | oT | int NOT NULL | 是 | 0/0/592/28 | [来源: D10.2/I5.4B；现有检索要求 psn_type；无码表] | S1 | P2,P5,P7 | 对应Profile核心 | `semantics_pending` |
| 医疗类别 / `T_CureType` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；现有检索要求 med_type；无码表] | S1 | P1,P5,P8 | 对应Profile核心 | `semantics_pending` |
| 机构待遇等级候选 / `P_JCLevel` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；不能仅凭字段名等同 hosp_lv] | S1 | P5,P8 | 对应Profile核心 | `semantics_pending` |
| 医院待遇标志 / `P_HospFlag` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无权威码表] | S1 | P7,P8 | 辅助 | `semantics_pending` |
| 异地交易标志 / `PN_OutTransaction` | oT | nvarchar(3) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；空串不等于否] | S1 | P8 | 条件核心 | `semantics_pending` |
| 国家险种 / `PN_NationFundType` | oT | varchar(6) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S1 | P5,P7,P8 | 对应Profile核心 | `semantics_pending` |
| 慢特病标志 / `PN_ChronicFlag` | oT | nvarchar(2) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，健康事实 | P5,P7 | 条件核心 | `semantics_pending` |
| 慢特病代码 / `PN_ChronicCode` | oT | nvarchar(50) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；不输出代码样例] | S2，健康事实 | P5,P7 | 条件核心 | `semantics_pending` |
| 慢特病定点机构标志 / `PN_IsChronicHosp` | oT | nvarchar(2) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，健康事实 | P5,P7,P8 | 条件核心 | `semantics_pending` |
| 公务员待遇候选 / `P_Official` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 条件核心 | `semantics_pending` |
| 退休待遇标志 / `P_retirementflag` | oT | varchar(50) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P5,P7 | 条件核心 | `semantics_pending` |
| 民政待遇标志 / `P_CivilFlag` | oT | varchar(10) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 条件核心 | `semantics_pending` |
| 民政待遇类型 / `P_CivilType` | oT | varchar(10) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 条件核心 | `semantics_pending` |
| 退役军官待遇标志 / `RETIRE_OFFICER_FLAG` | oT | varchar(1) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 条件核心 | `semantics_pending` |
| 公费归属标志 / `T_GFBelongFlag` | oT | varchar(50) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 条件核心 | `semantics_pending` |
| 补充医院标志 / `T_CompHospFlag` | oT | varchar(50) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7,P8 | 条件核心 | `semantics_pending` |
| 专项结算标志 / `T_SpSetlFlag` | oT | varchar(3) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S2，待遇事实 | P7 | 条件核心 | `semantics_pending` |
| 专项待遇内部号 / `T_pneno` | oT | varchar(50) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；内部号含义未签认] | S2，禁止公开 | P7 | 辅助 | `semantics_pending` |
| 全自费标志 / `NT_AllSelfPayFlag` | oT | varchar(3) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；无码表] | S1 | P1,P2,P7 | 条件核心 | `semantics_pending` |
| 无待遇原因 / `PN_NoRightReason` | oT | nvarchar(20) NULL | 是 | withheld（低频可反推） | [来源: D10.2/I5.4B；自由文本不输出样例] | S2，受限文本 | P7,P9 | 条件核心 | `semantics_pending` |

##### C. 当次费用与支付（26 个）

| 语义名 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 总费用 / `T_FeeAll` | oT | decimal(10,2) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；Task 3 公式有超差] | S1 | P1 | 对应Profile核心 | `semantics_pending` |
| 医保内费用 / `T_FeeIn` | oT | decimal(10,2) NOT NULL | 是 | 0/241/351/73 | [来源: D10.3/I5.4C；Task 3 公式有超差] | S1 | P1,P5,P6 | 对应Profile核心 | `semantics_pending` |
| 医保外费用 / `T_FeeOut` | oT | decimal(10,2) NOT NULL | 是 | 0/127/465/71 | [来源: D10.3/I5.4C；Task 3 公式有超差] | S1 | P1,P2,P6 | 对应Profile核心 | `semantics_pending` |
| 起付金额 / `T_FirstPay` | oT | decimal(10,2) NOT NULL | 是 | 0/541/51/24 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P4,P5 | 对应Profile核心 | `semantics_pending` |
| 自付一 / `T_SelfPay1` | oT | decimal(10,2) NOT NULL | 是 | 0/491/101/49 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P5 | 对应Profile核心 | `semantics_pending` |
| 自付二 / `T_SelfPay2` | oT | decimal(10,2) NOT NULL | 是 | 0/417/175/35 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P6 | 对应Profile核心 | `semantics_pending` |
| 个人自付合计 / `T_SelfPayAll` | oT | decimal(10,2) NOT NULL | 是 | 0/128/464/86 | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P1,P2 | 对应Profile核心 | `semantics_pending` |
| 大额基金支付 / `T_BigPay` | oT | decimal(10,2) NOT NULL | 是 | 0/288/304/72 | [来源: D10.3/I5.4C；口径待签认] | S1 | P3,P5,P7 | 条件核心 | `semantics_pending` |
| 大额个人自付 / `T_BigSelfPay` | oT | decimal(10,2) NOT NULL | 是 | 0/529/63/33 | [来源: D10.3/I5.4C；口径待签认] | S1 | P2,P5 | 条件核心 | `semantics_pending` |
| 超大额费用 / `T_BeyondBig` | oT | decimal(10,2) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；口径待签认] | S1 | P2,P5 | 条件核心 | `semantics_pending` |
| 基金支付总额候选 / `T_FundPay` | oT | decimal(10,2) NOT NULL | 是 | 0/284/308/77 | [来源: D10.3/I5.4C；不得与分项盲加] | S1 | P1,P3 | 对应Profile核心 | `semantics_pending` |
| 个人账户支付 / `T_PersonCountPay` | oT | decimal(10,2) NOT NULL | 是 | 0/465/127/44 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P3 | 对应Profile核心 | `semantics_pending` |
| 现金支付 / `T_CashPay` | oT | decimal(10,2) NOT NULL | 是 | 0/239/353/72 | [来源: D10.3/I5.4C；公式待签认] | S1 | P2,P3 | 对应Profile核心 | `semantics_pending` |
| 交易前账户余额候选 / `PN_PersonCount` | oT | decimal(10,2) NOT NULL | 是 | 0/468/124/85 | [来源: D10.3/I5.4C；前后语义待签认] | S1 | P3 | 对应Profile核心 | `semantics_pending` |
| 交易后账户余额候选 / `T_PersonCountAfter` | oT | decimal(10,2) NOT NULL | 是 | 0/486/106/80 | [来源: D10.3/I5.4C；前后语义待签认] | S1 | P3 | 对应Profile核心 | `semantics_pending` |
| 补充支付 / `T_BCPay` | oT | decimal(10,2) NOT NULL | 是 | 0/571/21/14 | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P3,P7 | 条件核心 | `semantics_pending` |
| 字段语义冲突：救助/军残支付候选 / `T_JCPay` | oT | decimal(10,2) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C 仅列字段；Issue20 §4 的专项待遇同时涉及救助与军残；无字典不得二选一] | S1 | P3,P7 | 条件核心 | `semantics_pending` |
| 公疗支付 / `T_OfficalPay` | oT | numeric(12,2) NULL | 是 | 0/573/19/11 | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P3,P7 | 条件核心 | `semantics_pending` |
| 大病支付 / `T_BigillPay` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P3,P7 | 条件核心 | `semantics_pending` |
| 国家基础支付 / `NT_BasicPay` | oT | numeric(16,2) NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；总分关系待签认] | S1 | P3 | 对应Profile核心 | `semantics_pending` |
| 国家民政支付 / `NT_CivilPay` | oT | numeric(16,2) NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；成员关系待签认] | S1 | P3,P7 | 条件核心 | `semantics_pending` |
| 国家其他支付 / `NT_OtherPay` | oT | numeric(16,2) NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；零不能推出不适用] | S1 | P3 | 条件核心 | `semantics_pending` |
| 经办支付合计候选 / `NT_AgencySumPay` | oT | numeric(16,2) NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；不得与分项盲加] | S1 | P1,P3 | 对应Profile核心 | `semantics_pending` |
| 退役军官支付 / `RETIRE_OFFICER_PAY` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；资格联动待签认] | S1 | P3,P7 | 条件核心 | `semantics_pending` |
| 异地二次比例候选 / `NT_OUT2_SCALE` | oT | numeric(16,2) NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；比例单位待签认] | S1 | P5,P8 | 条件核心 | `semantics_pending` |
| 异地二次金额候选 / `NT_OUT2_PRICE` | oT | numeric(16,2) NULL | 是 | withheld（低频可反推） | [来源: D10.3/I5.4C；金额口径待签认] | S1 | P5,P8 | 条件核心 | `semantics_pending` |

##### D. 年度累计、起付与封顶（24 个）

下列 `TB_*`/`TA_*` 仅登记物理类型和聚合；“交易前/后”均是设计候选，不是已验证含义。`TA_MZTimes` 的物理类型为 `int`，与设计的 Count 类型不冲突，但没有字段字典证明 `TA` 或其与 `TB_MZTimes` 的增量语义，故继续阻断。

| 语义候选 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 交易前医保内累计候选 / `TB_FeeIn` | oT | decimal(10,2) NOT NULL | 是 | 0/441/151/57 | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易后医保内累计候选 / `TA_FeeIn` | oT | decimal(10,2) NOT NULL | 是 | 0/261/331/131 | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5 | 对应Profile核心 | `semantics_pending` |
| 交易前大额累计候选 / `TB_BigPay` | oT | decimal(10,2) NOT NULL | 是 | 0/456/136/49 | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5 | 条件核心 | `semantics_pending` |
| 交易后大额累计候选 / `TA_BigPay` | oT | decimal(10,2) NOT NULL | 是 | 0/287/305/92 | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5 | 条件核心 | `semantics_pending` |
| 交易前封顶后费用候选 / `TB_FeeAfterBig` | oT | decimal(10,2) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5 | 条件核心 | `semantics_pending` |
| 交易后封顶后费用候选 / `TA_FeeAfterBig` | oT | decimal(10,2) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5 | 条件核心 | `semantics_pending` |
| 交易前门诊次数候选 / `TB_MZTimes` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；无字段字典] | S1 | P4 | 对应Profile核心 | `semantics_pending` |
| 交易后门诊次数候选 / `TA_MZTimes` | oT | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；类型为 int，释义仍冲突待解] | S1 | P4 | 对应Profile核心 | `semantics_pending` |
| 交易前超封顶医保内候选 / `TB_BeyondFeeIn` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；零不能推出不适用] | S1 | P4,P5 | 条件核心 | `semantics_pending` |
| 交易后超封顶医保内候选 / `TA_BeyondFeeIn` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5 | 条件核心 | `semantics_pending` |
| 交易前大病累计基数候选 / `TB_BigillComm` | oT | decimal(10,2) NULL | 是 | 11/489/92/40 | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P7 | 条件核心 | `semantics_pending` |
| 交易后大病累计基数候选 / `TA_BigillComm` | oT | decimal(10,2) NULL | 是 | 11/393/188/93 | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P7 | 条件核心 | `semantics_pending` |
| 交易前大病支付累计候选 / `TB_BigillPay` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P7 | 条件核心 | `semantics_pending` |
| 交易后大病支付累计候选 / `TA_BigillPay` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P7 | 条件核心 | `semantics_pending` |
| 交易前民政累计基数候选 / `TB_CivilComm` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P7 | 条件核心 | `semantics_pending` |
| 交易后民政累计基数候选 / `TA_CivilComm` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P7 | 条件核心 | `semantics_pending` |
| 交易前民政支付累计候选 / `TB_CivilPay` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P7 | 条件核心 | `semantics_pending` |
| 交易后民政支付累计候选 / `TA_CivilPay` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P7 | 条件核心 | `semantics_pending` |
| 交易前一级机构医保内候选 / `TB_FeeInL1` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P8 | 条件核心 | `semantics_pending` |
| 交易后一级机构医保内候选 / `TA_FeeInL1` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P8 | 条件核心 | `semantics_pending` |
| 交易前一级机构大额候选 / `TB_BigPayL1` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P8 | 条件核心 | `semantics_pending` |
| 交易后一级机构大额候选 / `TA_BigPayL1` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P8 | 条件核心 | `semantics_pending` |
| 交易前一级机构封顶后候选 / `TB_FeeAfterBigL1` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P8 | 条件核心 | `semantics_pending` |
| 交易后一级机构封顶后候选 / `TA_FeeAfterBigL1` | oT | decimal(10,2) NULL | 是 | withheld（低频可反推） | [来源: D10.4/I5.4D；前后释义无字典] | S1 | P4,P5,P8 | 条件核心 | `semantics_pending` |

##### E. 费用明细（20 个）

| 语义名 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 交易外键 / `T_TradeNo` | oF | nvarchar(22) NOT NULL | 是 | 0/0/2139/592 | [来源: Task 2 全量无孤儿，N:1 到 oT] | S2，禁止公开 | P6 | 对应Profile核心 | `verified` |
| 明细键组成 / `ItemId` | oF | int NOT NULL | 是 | 0/592/1547/33 | [来源: Task 2 复合键非空唯一] | S2，内部键 | P6 | 辅助 | `verified` |
| 明细键组成 / `ItemNo` | oF | int NOT NULL | 是 | 0/82/2057/51 | [来源: Task 2 复合键非空唯一] | S2，内部键 | P6 | 辅助 | `verified` |
| 院内项目代码 / `ItemCode` | oF | nvarchar(40) NOT NULL | 是 | 0/0/2139/98 | [来源: D10.5/I5.4E；代码体系未签认] | S2，健康事实 | P6 | 对应Profile核心 | `semantics_pending` |
| 标准项目代码 / `StandardCode` | oF | varchar(40) NULL | 是 | 0/0/2139/92 | [来源: D10.5/I5.4E；代码体系未签认] | S2，健康事实 | P6 | 辅助 | `semantics_pending` |
| 项目名称 / `ItemName` | oF | nvarchar(100) NOT NULL | 是 | 0/0/2139/94 | [来源: D10.5/I5.4E；授权解释内最小展示] | S2，健康事实 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目类型 / `ItemType` | oF | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.5/I5.4E；无码表] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 费用类型 / `FeeType` | oF | nvarchar(4) NOT NULL | 是 | 0/0/2139/17 | [来源: D10.5/I5.4E；无码表] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 医保项目等级 / `F_LEVEL` | oF | nvarchar(3) NULL | 是 | withheld（低频可反推） | [来源: D10.5/I5.4E；无码表] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 数量 / `Count` | oF | numeric(10,2) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.5/I5.4E；单位关系待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 单价 / `UnitPrice` | oF | decimal(10,4) NOT NULL | 是 | 0/0/2139/74 | [来源: D10.5/I5.4E；舍入规则待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目费用 / `Fee` | oF | decimal(10,4) NOT NULL | 是 | withheld（低频可反推） | [来源: D10.5/I5.4E；Task 3 逐交易有超差] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目医保内候选 / `FeeIn` | oF | decimal(10,4) NOT NULL | 是 | 0/1020/1119/129 | [来源: D10.5/I5.4E；Task 3 口径未冻结] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目医保外候选 / `FeeOut` | oF | decimal(10,4) NOT NULL | 是 | 0/874/1265/95 | [来源: D10.5/I5.4E；Task 3 口径未冻结] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目自付二 / `SelfPay2` | oF | decimal(10,4) NOT NULL | 是 | 0/1917/222/44 | [来源: D10.5/I5.4E；汇总关系待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目先自付比例 / `FEE_SP_SCALE` | oF | decimal(18,4) NULL | 是 | 0/2040/99/26 | [来源: D10.5/I5.4E；比例单位待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 项目超限价自付 / `FEE_MEDIC_L` | oF | decimal(18,4) NULL | 是 | withheld（低频可反推） | [来源: D10.5/I5.4E；口径待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 超限价自付候选 / `MEDIC_L` | oF | decimal(5,4) NULL | 是 | withheld（低频可反推） | [来源: D10.5/I5.4E；与 FEE_MEDIC_L 关系待签认] | S1 | P6 | 对应Profile核心 | `semantics_pending` |
| 特殊药品标志 / `SPEDRUG_FLAG` | oF | varchar(3) NULL | 是 | withheld（低频可反推） | [来源: D10.5/I5.4E；零/代码不能推出不适用] | S2，健康事实 | P6,P7 | 条件核心 | `semantics_pending` |
| 明细状态 / `State` | oF | int NOT NULL | 是 | withheld（低频可反推） | [来源: D10.5/I5.4E；无权威有效码表] | S1 | P6,P9 | 对应Profile核心 | `semantics_pending` |

##### F. 现有政策检索上下文与可信外部依赖（7 个）

| 语义名 / 原物理字段 | 源或可信上下文 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 参保地区候选 / `PN_InsuredAreaCode` | oT | varchar(6) NULL | 是 | withheld（低频可反推） | [推断: 字段名只支持参保地区候选，不能等同政策地区] | S2 | P5,P7,P8 | 辅助 | `semantics_pending` |
| 机构代码候选 / `T_HospCode` | oT | nvarchar(10) NOT NULL | 是 | withheld（低频可反推） | [推断: 需医院主数据映射，不输出代码] | S2，机构内部键 | P5,P8 | 辅助 | `semantics_pending` |
| 机构代码候选 A / `T_HospCodeA` | oT | nvarchar(10) NOT NULL | 是 | withheld（低频可反推） | [推断: 与 T_HospCode 关系未签认] | S2，机构内部键 | P5,P8 | 辅助 | `semantics_pending` |
| 政策地区 / `policy_region` | 可信 HIS/医保接入上下文 + 政策元数据 | — | 否 | — | [来源: 现有政策检索缺该字段；不能用 PN_InsuredAreaCode 直接替代] | S1 | P5,P7,P8 | 外部核心 | `missing_external_context` |
| 登录医院 / `hospital_id` | 登录组织上下文 + 医院主数据 | — | 否 | — | [来源: Issue20 §4 公共上下文；两表机构代码不能替代登录组织] | S2 | P5,P8 | 外部核心 | `missing_external_context`；解锁：登录组织注入稳定 hospital_id 并经医院主数据校验 |
| 政策适用机构 / `policy_applicable_institution` | 已发布政策元数据 + 医院主数据映射 | — | 否 | — | [来源: 总设计 §9.4 政策匹配；现有检索上下文未提供] | S2 | P5,P8 | 外部核心 | `missing_external_context`；解锁：政策适用机构元数据与 hospital_id 映射签认 |
| 规范化专项待遇类型 / `special_benefit_type` | 可信资格接口 + 已发布政策证据 | — | 否 | — | [推断: 多个专项标志不能无字典合成统一资格事实] | S2，待遇事实 | P5,P7 | 条件核心 | `missing_external_context`；解锁：资格接口与有效政策共同给出规范类型 |

上述七行与 A/B 组共同明确核对了地区、结算日期、险种、人员类别、医疗类别、机构级别、异地、慢特病、专项待遇、`hospital_id` 与政策适用机构。结算日期可从 `T_TradeDate`/`SETL_DATE` 读取但优先级和时区待签认；险种、人员类别、医疗类别、机构等级候选均存在但码表待签认。门诊新 Skill 不使用相似住院字段替代。

##### G. 明确排除的敏感字段（8 个）

这里只保留 Task 1 `INFORMATION_SCHEMA.COLUMNS` 已确认的存在性与物理类型，不执行也不展示 NULL、零、非零或 distinct 统计。它们不进入公开 Skill 语义模型；若受限内部定位确需使用，必须经最小权限、`security/desensitization` 和审计边界。

| 语义 / 原物理字段 | 源 | 类型 | 存在 | n/z/v/d | 业务含义证据 | 敏感 | Profile | 是否核心 | 状态 |
|---|---|---|:---:|---|---|---|---|---|---|
| 身份证件号 / `P_IDNo` | oT | nvarchar(50) NULL | 是 | not_profiled（敏感排除） | [来源: T1-META/T4-PRIV] | S3 | — | 排除 | `excluded_sensitive` |
| 医保卡号 / `P_ICNo` | oT | nvarchar(12) NOT NULL | 是 | not_profiled（敏感排除） | [来源: T1-META/T4-PRIV] | S3 | — | 排除 | `excluded_sensitive` |
| 姓名 / `P_Name` | oT | nvarchar(50) NOT NULL | 是 | not_profiled（敏感排除） | [来源: T1-META/T4-PRIV] | S3 | — | 排除 | `excluded_sensitive` |
| 出生日期 / `P_Birthday` | oT | datetime NOT NULL | 是 | not_profiled（敏感排除） | [来源: T1-META/T4-PRIV] | S3 | — | 排除 | `excluded_sensitive` |
| 卡号 / `P_CardNo` | oT | nvarchar(12) NULL | 是 | not_profiled（敏感排除） | [来源: T1-META/T4-PRIV] | S3 | — | 排除 | `excluded_sensitive` |
| 处方号 / `RecipeNo` | oF | nvarchar(20) NOT NULL | 是 | not_profiled（敏感排除） | [来源: T1-META/T4-PRIV] | S3 | — | 排除 | `excluded_sensitive` |
| HIS 名称 / `HisName` | oF | nvarchar(100) NOT NULL | 是 | not_profiled（敏感排除） | [来源: T1-META/T4-PRIV] | S3 | — | 排除 | `excluded_sensitive` |
| HIS 代码 / `HisCode` | oF | nvarchar(40) NOT NULL | 是 | not_profiled（敏感排除） | [来源: T1-META/T4-PRIV] | S3 | — | 排除 | `excluded_sensitive` |

#### 枚举频次隐私抑制

`ENUM_FREQUENCY_WITHHELD_PENDING_PRIVACY_THRESHOLD`：Task 4 不再发布任何枚举值频表。此前“distinct≤20 即安全”的假设没有隐私负责人批准，不能成立；慢特病、退休、民政、退费、专项待遇及费用分类等代码即使不直接标识患者，也可能通过低频单元格指向小群体。矩阵仅保留字段级完整性观察；只要 n/z/v/d 中出现 1–9 的桶，就整格 `withheld`，避免通过互补桶和总行数反推。数字 10 只是本次审查的保守抑制下限，不是生产阈值；生产发布前须由信息安全/隐私负责人签认阈值、组合维度、查询用途与二次推断风险。[来源: T4-PRIV；推断: 低频待遇/健康事实存在重识别风险]

#### 四态证明

本批次直接数据只证明三态：非 NULL 且非零为 `non_zero`，非 NULL 且显式零为 `reported_zero`，NULL、关联缺失或可信上下文未提供为 `missing`。字符串空值独立保留为空值质量问题，不自动等同数值零。`not_applicable` 必须同时有资格事实和有效期覆盖本次结算的政策证据；任何 `NULL→0`、`0→无资格` 或“全表未见非零→不适用”的转换均禁止。[来源: 总设计 §10.6；Issue20 §6.3]

[推断: 基于条件核心定义] 条件核心只控制对应待遇/场景分支，不是 Profile 的永久必填字段。经可信资格事实与政策证据确认条件不适用时，该分支为 `not_applicable`，Profile 可继续处理其他基础字段；当前九个 Profile 的 `unavailable` 来自尚未发布的查询模型、未签认字段/码表/金额口径及各 Profile 专属门禁，而不是内部锚点或条件字段为 0。

#### 九个 Profile 字段闭包状态

执行状态采用失败关闭：Issue20 §5.2 以 `settlement_id = T_TradeNo → mz_trade.T_TradeNo` 定位单次交易，Task 2 已证明该内部锚点非空且唯一。锚点层通过不等于 Profile 可执行；在查询模型发布、权威字段/码表、金额关系、外部政策上下文及有效交易规则签认前，下表仍只描述字段成熟度，不构成可执行 `partial`。

| Profile | 状态 | 字段闭包结论与阻断原因 |
|---|---|---|
| P1 整体结算核验 | `unavailable` | 锚点已通过；汇总金额虽存在，状态有效规则和总额公式未签认，查询模型也未发布。 |
| P2 个人负担解释 | `unavailable` | 锚点已通过；自付/账户/现金成员关系、专项支付关系和零值资格含义未签认。 |
| P3 支付渠道核验 | `unavailable` | 锚点已通过；总分关系未确认，且 `T_JCPay` 存在救助/军残语义冲突，不得重复求和或确定命名。 |
| P4 起付线与年度累计 | `unavailable` | 锚点已通过；TB/TA 前后释义、年度边界和 `TA_MZTimes` 释义未签认。 |
| P5 报销比例与封顶 | `unavailable` | 锚点已通过；缺可信政策地区、适用机构、规范资格上下文及覆盖结算日期的完整政策证据。 |
| P6 医保目录与费用明细 | `unavailable` | 锚点和明细关系已通过；Task 3 金额仍超差，`FeeIn/FeeOut` 与明细状态码未冻结。 |
| P7 身份与特殊待遇 | `unavailable` | 锚点已通过；码表/资格定义、规范专项待遇类型和政策证据缺失，且 `T_JCPay` 救助/军残语义冲突。 |
| P8 异地与机构待遇 | `unavailable` | 锚点已通过；政策地区、登录医院、机构等级值域和政策适用机构映射缺失。 |
| P9 交易状态与退费 | `unavailable` | 锚点已通过；状态码、原交易关系和有效/红冲过滤规则未签认，退费/冲正仍只转人工确认。 |

九个 Profile 均不得发布门诊 Skill 输入契约：0 `complete` / 0 `partial` / 9 `unavailable`。

#### 非快照观察 SQL / 查询口径

Task 1 的 `INFORMATION_SCHEMA.COLUMNS` SQL 是物理类型证据；字段数量和边界只引用本节“权威字段汇总”。本段实际聚合白名单来源是 A–F 矩阵中的 107 个物理字段，下面可执行结构逐项列出 `o_Trade` 87 个与 `o_FeeItem` 20 个字段；G 组敏感排除与四个外部上下文均不进入查询。`is_numeric=1` 才统计数值零，其他类型统计空串。

该查询显式使用 `READ UNCOMMITTED`，可能发生脏读、不可重复读或幻读；因此结果只证明固定执行时间下的一次非快照观察，不能冻结精确计数。枚举分布另行查询时未保留完整枚举白名单及完整 `SELECT`，不具备逐字复现条件，其值频结果已按 `ENUM_FREQUENCY_WITHHELD_PENDING_PRIVACY_THRESHOLD` 全部撤下；本段不得再称“完整可复现 SQL”。

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

[建议] 如需重新形成枚举证据，必须先由信息安全/隐私负责人批准字段白名单、单元格抑制阈值与组合维度，再在可重复读快照或等效一致性机制下形成独立审计批次；本次文档不提供可绕过隐私门禁的值频查询。

Task 4 结果：**DONE_WITH_CONCERNS**。字段与分类数量以本节两条权威汇总为准；`T_TradeNo` 内部锚点通过，`T_SetTid` 仅为普通可空字段。可聚合字段仍只形成 `READ UNCOMMITTED` 非快照观察，敏感字段只沿用 Task 1 元数据，四个外部上下文保持 `missing_external_context`；九个执行 Profile 因查询模型、业务字段字典、交易前后定义、金额/状态规则及可信政策上下文尚未闭包而均为 `unavailable`。不得伪报字段闭包 `complete`，也不提前建立运营指标、增量游标或容量结论。

## 运营指标依赖

### Task 5：六指标、五维度与就诊时间口径

#### 文档级审计证据批次

| 项目 | 结果 |
|---|---|
| 文档级证据批次 ID | <code>outpatient_p0_t5_20260827_contract_draft</code> |
| 批次性质 | 纯文档/既有证据综合；不是数据库审计 ID、外部 run_id 或新增数据快照 |
| 输入证据 | Task 2 的键、关系、状态组合与时间阻断；Task 3 的金额勾稽与人工票据阻断；Task 4 的字段闭包、外部上下文与隐私抑制 |
| 本批次数据库操作 | 无；未连接 SQL Server，未执行 SQL，未读取新样例、枚举或行级标识 |
| 明确未做 | 不提前验证增量游标、迟到数据、容量、执行计划或生产性能 |
| 输出 | 六指标契约草案、五维度契约草案、双时间角色、50 个草案验收问题及解锁门禁 |

[来源: 文档级证据批次 <code>outpatient_p0_t2_20260827_070052Z</code>、<code>outpatient_p0_t3_20260827_073210Z</code>、<code>outpatient_p0_t3_precision_20260827_074356Z</code>、<code>outpatient_p0_t4_20260827_policy_closure</code>；总设计 §11–§12、§18–§19]

本批次不重复连接 SQL Server：Task 1–4 已足以判断物理候选和阻断项。以下“冻结”只指**冻结待签认的 P0 契约草案及失败关闭行为**，不表示业务口径已签认或指标已发布。

#### 受控查询边界

- [来源: 总设计 §12.1–§12.3] 运行时 <code>SemanticQuery</code> 只允许 <code>metrics</code>、<code>dimensions</code>、<code>time_role</code>、<code>time_range</code>、<code>filters</code>、<code>order_by</code>、<code>limit</code>、<code>semantic_version</code>；禁止物理表/字段、SQL、任意 JOIN 和未发布公式。
- [来源: 当前 <code>src/semantic_layer/{models.py,registry.py,data_query.py}</code>] 当前代码已具备指标 Registry、发布快照和值域，以及面向单笔取值的 <code>MetricDataQueryService</code>；尚无聚合 <code>SemanticQuery</code> 模型、确定性 Planner 或编译执行器。本节不把设计契约伪报为已实现能力。
- [建议] 验收摘要中的 <code>comparison</code>、<code>drill_path</code>、<code>requested_output</code> 只属于助手/Planner 的受控意图包络：比较必须展开为两个分别校验和鉴权的 <code>SemanticQuery</code>；<code>sort</code> 必须映射到 <code>order_by</code>；下钻只允许固定路径；展示类型不得改变指标公式。
- [推断: 基于当前全部指标/维度门禁] Q01–Q50 只验证意图、契约、澄清、拒绝和失败关闭。任何依赖未签认口径的取数当前都应返回 <code>result_status=unavailable; halt_reason=quality_blocked</code>，不得生成示例数值。

验收表缩写固定为：<code>M=metrics</code>、<code>D=dimensions</code>、<code>F=filters</code>、<code>TR=time_role+time_range</code>、<code>C=comparison</code>、<code>S=sort→order_by</code>、<code>L=limit</code>、<code>DP=drill_path</code>、<code>O=requested_output</code>。<code>本月/本周/今日</code> 等相对区间只是意图层记号，进入查询服务前必须由可信日历按已签认医院时区解析为左闭右开的 <code>start/end</code>；未解析不得执行。所有查询还必须携带已发布的 <code>semantic_version</code>；当前没有可发布门诊运营版本，所以表中统一省略该重复项并由门禁返回 <code>result_status=unavailable; halt_reason=quality_blocked</code>。

#### 统一终态、排序与零结果

| 契约项 | 冻结草案 |
|---|---|
| 业务查询终态 | 恰好一个 <code>result_status=complete|partial|unavailable</code>；<code>unavailable</code> 必须且只能携带一个 <code>halt_reason</code> |
| <code>unavailable</code> 的 <code>halt_reason</code> | 至少支持 <code>permission_denied</code>、<code>high_risk_confirmation_required</code>、<code>quality_blocked</code>、<code>data_unavailable</code>、<code>out_of_scope</code> |
| 澄清 | <code>action=clarify</code> 只用于自然语言对应多个**已发布**指标、时间角色或区间含义；其唯一可验收传输终态为 SSE <code>done</code> 同时携带 <code>halt_reason=clarification_required</code> 与 <code>done_reason=clarification_required</code>，不产生 <code>result_status</code>，也不把 <code>clarification_required</code> 当作 <code>unavailable</code> 原因。用户不能通过澄清选择未签认公式、去重键或分母 |
| 高风险动作 | <code>result_status=unavailable; halt_reason=high_risk_confirmation_required; workflow_status=waiting_human_confirmation</code>；系统不执行写入或源系统调用，由人工在既有业务系统处理 |
| 多重阻断优先级 | <code>permission/security &gt; high-risk &gt; quality contract &gt; data availability &gt; empty-success</code>；一次响应只选最高优先级原因 |
| 所有公开终态/动作公共不变量 | <code>complete</code>、<code>partial</code>、<code>unavailable</code>、<code>action=clarify</code>、<code>workflow_status=waiting_human_confirmation</code> 均必须携带 <code>citations[]</code> 与 <code>uncertainties[]</code>，且两者至少一项非空，禁止同时为空。<code>unavailable</code>、澄清和人工确认应引用触发它的证据、政策或安全规则；确无可引来源时必须提供非空 <code>uncertainties[]</code>。该不变量不改变上述 SSE <code>done</code> 映射 |
| <code>complete</code>/<code>partial</code> 附加要求 | <code>citations[]</code> 必须至少包含 1 条可追溯数据来源，禁止为空；同时携带 <code>semantic_version</code>、<code>data_watermark</code>、<code>effective_scope</code>，<code>uncertainties[]</code> 字段不可缺失 |
| 零结果 | 仅当权限、语义和质量门禁通过且 <code>data_watermark</code> 完整时，标量聚合真实无数据返回可信 <code>0</code>，分组/明细返回 <code>rows=[]</code>，终态均为 <code>complete</code>；质量阻断返回 <code>result_status=unavailable; halt_reason=quality_blocked</code>，延迟/缺批次返回 <code>result_status=unavailable; halt_reason=data_unavailable</code>，绝不返回 0 |
| <code>order_by</code> | 只允许已发布 metric、dimension 或 <code>time_role</code> 的完整语义码；禁止物理字段、显示文本和缩写 |
| TopN | 一级按目标 metric <code>desc</code>，二级按 <code>organization.department asc</code>，该维度值必须是已发布 department semantic id；完成二级稳定排序后严格截断到 N，边界并列不扩展结果集 |

#### 六指标契约表

| 指标 / 草案语义码 | 业务定义 | 候选分子 / 分母 | 候选物理字段 | 去重键 | 有效状态 | 退费/冲正规则 | 时间口径 | 单位 | 可用维度 | 下钻路径 | 证据状态 | 解锁条件 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 门诊医保就诊人次 / <code>mzjyxx.insured_encounter_count</code> | [建议] 在就诊发生时间范围内，按签认的门诊医保就诊业务键去重后的就诊次数；一人多次就诊分别计数，同次就诊的多笔交易不得重复放大 | 分子：去重后的合格门诊医保就诊；分母：无 | 两表内无已签认就诊键；<code>T_MdtrtID</code> 仅确认物理存在，未完成语义、非空和唯一性画像；可信 HIS <code>encounter_id</code> 是 P1 外部输入候选 | **阻断**：不得用 <code>T_SetTid</code>；不得把交易业务键 <code>T_TradeNo</code> 自动等同就诊键；禁止 <code>COUNT(*)</code> | 需同时签认“医保门诊就诊”纳入规则及就诊与有效交易关系 | 退费/冲正可能改变交易，但是否改变就诊人次需医保办单独签认；不得默认扣减就诊 | 默认 <code>encounter_time</code> | 人次，整数 | 就诊时间；科室、门诊类别、险种为候选；结算状态仅在就诊↔有效交易映射唯一后可用 | 全院门诊→科室→门诊就诊记录；进入患者级重新鉴权 | <code>blocked</code> | 数据负责人签认就诊键、HIS 来源、跨源抽取映射、就诊时间与时区；医保办签认纳入/退费规则；画像证明键完整且不会被交易一对多放大 |
| 门诊有效结算笔数 / <code>mzjyxx.valid_settlement_count</code> | [建议] 在选定时间角色范围内，满足已签认有效结算与退费/冲正规则的交易业务键数 | 分子：合格 <code>T_TradeNo</code> 去重数；分母：无 | <code>T_TradeNo</code>；状态候选 <code>T_State</code>、<code>T_HasRefundmented</code>、<code>T_PartialReturnFlag</code>、<code>NT_ReTradeFlag</code>、<code>NP_Settle_State</code> | [来源: Task 2] <code>T_TradeNo</code> 全量非空唯一，可作交易业务键；仍必须显式去重，禁止 <code>COUNT(*)</code> | **阻断**：状态字段物理存在但无码表，不能指定“成功/有效”码 | 原交易、部分退费、全额退费、冲正、重交易的保留/抵销/替换规则均待签认；不能只看单个标志 | 默认 <code>encounter_time</code>；用户明确问“结算日/结算时间”才用 <code>settlement_time</code> | 笔，整数 | 五维均为候选；按结算状态分组须先发布状态字典 | 全院门诊→科室→门诊就诊记录→单次门诊结算；逐级鉴权 | <code>blocked</code> | 医保办与数据负责人签认状态码、状态组合、退款链和有效交易选择规则；签认结算时间源与时区 |
| 门诊总费用 / <code>mzjyxx.total_fee</code> | [建议] 合格门诊记录在已签认费用口径下的人民币总费用合计，不含重复交易或重复明细放大 | 分子：候选 <code>T_FeeAll</code> 按有效交易求和；分母：无 | <code>T_FeeAll</code>；<code>o_FeeItem.Fee</code> 仅是待签认明细核对候选 | <code>T_TradeNo</code>；明细仅可按已冻结复合键幂等，不可原始多表直接 JOIN 后求和 | 沿用“有效结算笔数”的阻断规则 | 必须由签认规则决定退费交易取负、排除、替换或与原交易净额化；不得由字段符号猜测 | 默认 <code>encounter_time</code>；明确结算运营问题可用 <code>settlement_time</code> | 元，Decimal，展示精度和舍入待签认 | 五维均为候选 | 全院门诊→科室→门诊就诊记录→单次门诊结算→费用类别→费用项目明细 | <code>candidate</code>（执行阻断） | 解除状态门禁；签认 <code>T_FeeAll</code> 含义、舍入及与明细关系；解释 Task 3 的公式和逐交易超差；完成票据门禁 |
| 门诊统筹基金支付金额 / <code>mzjyxx.pooling_fund_payment</code> | [建议] 合格门诊记录中由基本医保统筹基金实际支付的金额合计；不得把“大额、补充、民政”等专项支付无条件并入 | 分子：候选 <code>T_FundPay</code> 按有效交易求和；分母：无 | <code>T_FundPay</code> 仅是“基金支付总额候选”，尚不能仅凭字段名等同“统筹基金支付”；专项字段不得盲加 | <code>T_TradeNo</code> | 沿用“有效结算笔数”的阻断规则 | 原交易与退费/冲正的基金金额净额化规则待签认 | 默认 <code>encounter_time</code>；明确结算运营问题可用 <code>settlement_time</code> | 元，Decimal | 五维均为候选 | 全院门诊→科室→门诊就诊记录→单次门诊结算；基金分项下钻仅在成员关系发布后允许 | <code>candidate</code>（执行阻断） | 权威字段字典确认 <code>T_FundPay</code> 唯一业务含义和成员边界；解除有效状态、退款链和 Task 3 金额门禁 |
| 门诊个人支付金额 / <code>mzjyxx.personal_payment</code> | [建议] 合格门诊记录中由个人承担并实际支付的金额合计；个人账户、现金、自付一/二等是否为成员必须按权威口径定义 | 分子：候选 <code>T_SelfPayAll</code> 按有效交易求和；分母：无 | <code>T_SelfPayAll</code>；<code>T_PersonCountPay</code>、<code>T_CashPay</code> 只作成员关系核对候选 | <code>T_TradeNo</code> | 沿用“有效结算笔数”的阻断规则 | 原交易与退费/冲正的个人支付净额化、账户返还和现金退回规则待签认 | 默认 <code>encounter_time</code>；明确结算运营问题可用 <code>settlement_time</code> | 元，Decimal | 五维均为候选 | 全院门诊→科室→门诊就诊记录→单次门诊结算；患者/支付渠道下钻重新鉴权 | <code>candidate</code>（执行阻断） | 签认 <code>T_SelfPayAll</code> 业务含义、成员关系和退款规则；解释 Task 3 <code>T_FeeAll=T_FundPay+T_SelfPayAll</code> 的超差 |
| 门诊次均费用 / <code>mzjyxx.average_fee</code> | [建议] 签认后的门诊总费用除以签认后的业务次数；结果必须显示采用的人次口径 | 分子：门诊总费用；分母候选 A=门诊医保就诊人次、候选 B=门诊有效结算笔数；未签认不得二选一 | 分子候选 <code>T_FeeAll</code>；分母没有已签认就诊键，结算候选为 <code>T_TradeNo</code> | 取决于分母；不得用 <code>T_SetTid</code> 或 <code>COUNT(*)</code> | 同时继承分子与选定分母的有效规则 | 同时继承总费用与分母的退费/冲正规则；分母为就诊人次时退费是否扣人次需单独签认 | 默认 <code>encounter_time</code> | 元/人次或元/笔；二者不可混称 | 仅允许与已签认分子、分母共同兼容的维度 | 与所选分母一致；分母未签认时不下钻 | <code>blocked</code> | 医保办明确分母是就诊人次还是有效结算笔数及名称；先解除对应分子、分母、时间和状态门禁 |

##### 六指标治理字段（总设计 §11.4 补充）

| 指标 | 同义词 | 刷新频率 | 权限等级 | 负责人 | 审核人 |
|---|---|---|---|---|---|
| <code>mzjyxx.insured_encounter_count</code> | 候选“门诊人次/医保门诊人次”；待签认 | 待签认 | 待签认 | 待签认 | 待签认 |
| <code>mzjyxx.valid_settlement_count</code> | 候选“有效结算数/门诊结算笔数”；待签认 | 待签认 | 待签认 | 待签认 | 待签认 |
| <code>mzjyxx.total_fee</code> | 候选“门诊费用合计/门诊总金额”；待签认 | 待签认 | 待签认 | 待签认 | 待签认 |
| <code>mzjyxx.pooling_fund_payment</code> | 候选“统筹支付/统筹基金支付”；待签认 | 待签认 | 待签认 | 待签认 | 待签认 |
| <code>mzjyxx.personal_payment</code> | 候选“个人支付/个人负担金额”；待签认 | 待签认 | 待签认 | 待签认 | 待签认 |
| <code>mzjyxx.average_fee</code> | 候选“次均费用”；分母签认后才能补充同义词 | 待签认 | 待签认 | 待签认 | 待签认 |

[来源: 总设计 §11.4] 上表五项治理字段均为发布必填；“待签认”不得被默认值替代。业务定义、公式、聚合方式、单位、精度、兼容维度、默认时间角色和数据来源由前表承载，发布版本仍待建立。

[推断: 基于 Task 2–4] 六项中 0 项达到可发布 <code>verified</code>；3 项保留物理候选但执行阻断，3 项因关键键/状态/分母缺失而 <code>blocked</code>。这里的 <code>T_TradeNo</code> 键证据为 <code>verified</code>，不等于“有效结算笔数”指标已验证。

#### 人次与结算笔数去重门禁

| 计数对象 | 已有证明 | 当前决定 |
|---|---|---|
| 门诊医保就诊人次 | [来源: Task 2] <code>T_SetTid</code> 存在 NULL 和大量一对多，不能唯一定位；<code>T_TradeNo</code> 只证明交易唯一；Task 1 仅证明 <code>T_MdtrtID</code> 物理存在 | <code>blocked</code>。无签认就诊键时不计算，不允许 <code>COUNT(*)</code>、不允许用 <code>T_SetTid</code>，也不把 <code>T_TradeNo</code> 偷换为人次 |
| 门诊有效结算笔数 | [来源: Task 2] <code>T_TradeNo</code> 全量非空唯一，交易去重键证据通过；[来源: Task 2–3] 状态组合无码表 | 键层通过、指标层 <code>blocked</code>。只能在有效状态和退费/冲正规则签认后按去重 <code>T_TradeNo</code> 计数，仍不允许 <code>COUNT(*)</code> |

#### 五维度契约表

| 维度 / 草案语义码 | 来源候选 | 物理类型 / 值域证据 | 语义状态 | 允许筛选 | 允许分组 | 允许下钻 | 解锁条件 |
|---|---|---|---|---|---|---|---|
| 就诊时间 / <code>time_role=encounter_time</code>；结算时间 / <code>time_role=settlement_time</code> | 就诊时间：可信 HIS 就诊发生时间为 P1 抽取输入候选；两表无已证明等价字段。结算时间：<code>SETL_DATE</code>、<code>T_TradeDate</code> 只登记为竞争候选 | [来源: Task 1–2、Task 4] <code>T_TradeDate</code> 为 datetime NOT NULL 且无时区语义；<code>SETL_DATE</code> 为 datetime NULL，优先级与含义未签认 | <code>blocked</code>。默认“时间”必须解释为就诊发生时间；只有明确结算运营问题才选择结算时间。不得未经证明把 <code>T_TradeDate</code> 当就诊时间，也不得把 <code>SETL_DATE</code> 当结算时间 | 解锁后允许日/周/月/自定义左闭右开区间；角色或边界歧义先 <code>clarify</code> | 解锁后允许日、周、月粒度；医院时区和周界未签认前不执行 | 时间→科室→就诊；结算时间下钻到单次结算前重新鉴权 | 数据负责人签认两个时间角色各自来源、优先级、时区、周界、迟到/回写规则；对候选字段做一致性画像 |
| 科室 / <code>organization.department</code> | 可信 HIS 就诊科室 + 医院组织主数据；两表没有已签认科室字段，禁止用操作员、医院代码或文本猜测 | 物理类型和值域未取得；候选 <code>department_id</code> 必须来自 P1 受控抽取，不是运行时临时跨源 JOIN | <code>blocked</code>；登记为 P1 抽取输入 | 解锁后仅允许当前 <code>data_scope</code> 内已发布科室 ID；不按自由文本直连源表 | 解锁后允许；低频单元格继续抑制 | 固定“全院门诊→科室→门诊就诊记录”；每次进入就诊级重新鉴权 | HIS 字段/接口、组织主数据、历史映射和权限范围由数据负责人签认；P1 落地同批水位抽取；禁止运行时跨源临时 JOIN |
| 门诊业务类别 / <code>mzjyxx.outpatient_business_type</code> | <code>T_CureType</code> 是物理候选；不得把现有住院默认 <code>med_type</code> 或其他源 <code>YLLB</code> 字典直接套用 | [来源: Task 1、Task 4] int NOT NULL；低频枚举整体不展示，无码表 | <code>candidate</code>；字典发布前过滤/分组返回 <code>result_status=unavailable; halt_reason=quality_blocked</code> | 仅允许已发布标准值，不接受物理码或模型自造值 | 字典解锁后允许；小桶按 Task 4 抑制 | 筛选/分组后仍只可沿固定“全院门诊→科室→门诊就诊记录”路径下钻并鉴权 | 医保办签认门诊类别码表、合并/拆分规则和历史版本；数据负责人签认 <code>T_CureType</code> 映射 |
| 险种 / <code>mzjyxx.insurance_type</code> | <code>P_FundType</code>、<code>PN_NationFundType</code> 为竞争候选；当前 seed 的 <code>FUND_TYPE</code> 绑定其他源字段，不能自动证明本表映射 | [来源: Task 1、Task 4、当前 <code>seed.py</code>] <code>P_FundType</code> int NOT NULL；<code>PN_NationFundType</code> varchar(6) NULL；本表无码表 | <code>candidate</code>；字典发布前过滤/分组返回 <code>result_status=unavailable; halt_reason=quality_blocked</code> | 仅允许已发布标准险种，不接受源物理码 | 字典解锁后允许；低频待遇桶抑制 | 筛选/分组后仍只可沿固定“全院门诊→科室→门诊就诊记录”路径下钻；进入就诊级重新鉴权 | 医保办签认权威险种字段、两候选优先级和值域；建立版本化映射并回归 |
| 结算状态 / <code>mzjyxx.settlement_status</code> | 组合候选：<code>T_State</code>、<code>T_HasRefundmented</code>、<code>T_PartialReturnFlag</code>、<code>NT_ReTradeFlag</code>、<code>NP_Settle_State</code>，及原交易关系候选 | [来源: Task 1–4] int/varchar/nvarchar，NULL/空串并存；精确低频值域已抑制；无码表 | <code>candidate</code>；不能从单字段或数值猜“成功/退费/冲正/无效” | 仅在组合状态字典发布后允许；当前任何状态筛选均返回 <code>result_status=unavailable; halt_reason=quality_blocked</code> | 解锁后允许受隐私阈值保护的汇总；不展示精确小桶 | 状态只能作为已发布筛选/分组条件；下钻仍固定“全院门诊→科室→门诊就诊记录→单次门诊结算”，退费链仅供有权限人员查看 | 医保办和数据负责人签认组合状态机、原/退交易关系、有效交易选择及退款净额规则；隐私负责人签认桶阈值 |

[来源: Task 4 <code>ENUM_FREQUENCY_WITHHELD_PENDING_PRIVACY_THRESHOLD</code>] 五维度的低频枚举继续失败关闭：本节不新增任何枚举值或精确小桶。生产阈值、组合维度和二次推断风险须由信息安全/隐私负责人签认。

#### 双时间角色冻结草案

1. [来源: 用户确认口径；总设计 §22] 未带“结算”限定的“今天、本周、本月、某日、某段时间”默认指 <code>encounter_time</code>，即就诊发生时间。
2. [推断] “按结算日、结算时间、当日结算、结算运营”等明确表述才使用 <code>settlement_time</code>；若同一句同时要求就诊与结算口径且关系不明确，只有两个时间角色均已发布时才执行 <code>action=clarify</code>，否则返回 <code>result_status=unavailable; halt_reason=quality_blocked</code>。
3. [建议] 所有区间采用左闭右开；日/月边界和自然周边界由医院时区日历服务解析。医院时区、周起始日和节假日业务日尚未签认，当前仍是解锁项。
4. <code>T_TradeDate</code> 不得未经证明映射到 <code>encounter_time</code>；<code>SETL_DATE</code> 也不得未经字典和完整性验证映射到 <code>settlement_time</code>。
5. 同比/环比由确定性日历生成两个受控区间，各自重新校验权限、语义版本和数据水位；LLM 不计算日期、不改字段。

#### 50 个草案验收问题

> 这 50 题是 **P0 评审草案**，不是生产可信问题库、隐藏验收集或正式可信集。只有医保办负责人和数据负责人逐题签认指标、维度、时间与门禁后，才能转入“可信问题库”；权限与低频题还需信息安全/隐私负责人签认。[来源: 总设计 §14.1、§19]

| 编号 | 自然语言 | 场景覆盖 | 期望 intent / 唯一终态或动作 | 受控契约摘要（M/D/F/TR/C/S/L/DP/O） | 依赖口径门禁 |
|---|---|---|---|---|---|
| Q01 | 本月门诊医保就诊人次是多少？ | 人次、默认月、默认就诊时间 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count]；D[]；F[]；TR[encounter_time,本月]；C[none]；S[]；L[1]；DP[none]；O[kpi] | 就诊键、就诊时间、医保门诊纳入规则 |
| Q02 | 今天门诊医保就诊人次比昨天多还是少？ | 人次、日、日环比 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count]；D[calendar.day]；F[]；TR[encounter_time,今日]；C[previous_day]；S[calendar.day asc]；L[2]；DP[none]；O[kpi+comparison] | 就诊键、时区、日界、比较日历 |
| Q03 | 本周每天的门诊医保就诊人次趋势。 | 人次、周、日粒度 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count]；D[calendar.day]；F[]；TR[encounter_time,本周]；C[none]；S[calendar.day asc]；L[7]；DP[none]；O[line] | 就诊键、就诊时间、时区、自然周边界 |
| Q04 | 统计指定起止日期内各科室门诊医保就诊人次。 | 人次、自定义区间、科室 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count]；D[organization.department]；F[]；TR[encounter_time,自定义完整起止日]；C[none]；S[mzjyxx.insured_encounter_count desc]；L[50]；DP[department→encounter]；O[table] | 就诊键、就诊时间、科室 P1 抽取与权限 |
| Q05 | 本月门诊医保就诊人次同比去年同月如何？ | 人次、月、同比 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count]；D[]；F[]；TR[encounter_time,本月]；C[yoy]；S[]；L[2]；DP[none]；O[kpi+comparison] | 就诊键、时区、同比对齐、历史口径版本 |
| Q06 | 本月门诊有效结算有多少笔？ | 有效结算、默认月 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.valid_settlement_count]；D[]；F[]；TR[encounter_time,本月]；C[none]；S[]；L[1]；DP[none]；O[kpi] | 有效状态、退款链、默认就诊时间映射 |
| Q07 | 按结算时间看，今天有效结算笔数。 | 显式结算时间、日 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.valid_settlement_count]；D[]；F[]；TR[settlement_time,今日]；C[none]；S[]；L[1]；DP[none]；O[kpi] | 结算时间源/时区、有效状态 |
| Q08 | 本月按结算状态统计有效结算笔数。 | 结算状态维度 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.valid_settlement_count]；D[mzjyxx.settlement_status]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.valid_settlement_count desc]；L[20]；DP[none]；O[table] | 组合状态字典、有效交易规则、低频抑制 |
| Q09 | 本月有效结算笔数比上月增长多少？ | 有效结算、月、环比 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.valid_settlement_count]；D[]；F[]；TR[encounter_time,本月]；C[mom]；S[]；L[2]；DP[none]；O[kpi+comparison] | 有效状态、退款链、月界、历史语义版本 |
| Q10 | 本月有效结算笔数最多的前 10 个科室。 | TopN、科室 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.valid_settlement_count]；D[organization.department]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.valid_settlement_count desc,organization.department asc]；L[10]；DP[department→encounter→settlement]；O[bar+table] | 科室抽取、权限、有效状态、固定下钻 |
| Q11 | 本月门诊总费用是多少？ | 总费用、默认月 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.total_fee]；D[]；F[]；TR[encounter_time,本月]；C[none]；S[]；L[1]；DP[none]；O[kpi] | 总费用字段/公式、有效状态、退款净额 |
| Q12 | 本月各科室门诊总费用。 | 总费用、科室 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.total_fee]；D[organization.department]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.total_fee desc]；L[50]；DP[department→encounter→settlement]；O[table] | 科室抽取、总费用、状态、权限 |
| Q13 | 查询完整指定日期区间内每天的门诊总费用。 | 总费用、自定义区间、日粒度 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.total_fee]；D[calendar.day]；F[]；TR[encounter_time,自定义完整起止日]；C[none]；S[calendar.day asc]；L[366]；DP[none]；O[line] | 就诊时间、时区、总费用、最大区间/行数策略 |
| Q14 | 本月门诊总费用环比上月。 | 总费用、月、环比 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.total_fee]；D[]；F[]；TR[encounter_time,本月]；C[mom]；S[]；L[2]；DP[none]；O[kpi+comparison] | 总费用、有效状态、退款净额、月界 |
| Q15 | 某个已发布科室在指定日没有门诊记录时，总费用应怎样展示？ | 标量零结果、科室、日 | <code>intent=metric_query; result_status=complete; scalar=0</code> | M[mzjyxx.total_fee]；D[]；F[organization.department=authorized_published_value]；TR[encounter_time,完整指定日]；C[none]；S[]；L[1]；DP[none]；O[kpi] | 验收前置：权限、语义和质量门禁通过且水位完整；任一前置不满足时，本题断言不适用并按全局优先级进入唯一失败终态，绝不返回 0 |
| Q16 | 本月门诊统筹基金支付金额是多少？ | 统筹基金、月 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.pooling_fund_payment]；D[]；F[]；TR[encounter_time,本月]；C[none]；S[]；L[1]；DP[none]；O[kpi] | <code>T_FundPay</code> 业务定义、状态、退款净额 |
| Q17 | 本月按险种看门诊统筹基金支付金额。 | 统筹基金、险种 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.pooling_fund_payment]；D[mzjyxx.insurance_type]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.pooling_fund_payment desc]；L[20]；DP[none]；O[table] | 险种字段/字典、基金口径、低频抑制 |
| Q18 | 本月门诊统筹基金支付金额同比去年同月。 | 统筹基金、同比 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.pooling_fund_payment]；D[]；F[]；TR[encounter_time,本月]；C[yoy]；S[]；L[2]；DP[none]；O[kpi+comparison] | 基金口径、状态、同比日历、历史版本 |
| Q19 | 本月统筹基金支付金额最高的前 5 个科室。 | 统筹基金、TopN | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.pooling_fund_payment]；D[organization.department]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.pooling_fund_payment desc,organization.department asc]；L[5]；DP[department→encounter→settlement]；O[bar+table] | 科室、基金口径、状态、权限 |
| Q20 | 本月不同门诊业务类别的统筹基金支付金额。 | 门诊类别维度 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.pooling_fund_payment]；D[mzjyxx.outpatient_business_type]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.pooling_fund_payment desc]；L[20]；DP[none]；O[table] | <code>T_CureType</code> 字典、基金口径、低频抑制 |
| Q21 | 本月门诊个人支付金额是多少？ | 个人支付、月 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.personal_payment]；D[]；F[]；TR[encounter_time,本月]；C[none]；S[]；L[1]；DP[none]；O[kpi] | <code>T_SelfPayAll</code> 定义/成员、状态、退款净额 |
| Q22 | 本月各科室门诊个人支付金额。 | 个人支付、科室 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.personal_payment]；D[organization.department]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.personal_payment desc]；L[50]；DP[department→encounter→settlement]；O[table] | 科室、个人支付口径、权限 |
| Q23 | 本月个人支付金额比上月变化多少？ | 个人支付、环比 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.personal_payment]；D[]；F[]；TR[encounter_time,本月]；C[mom]；S[]；L[2]；DP[none]；O[kpi+comparison] | 个人支付、状态、月界、历史版本 |
| Q24 | 本月按险种汇总个人支付金额。 | 个人支付、险种 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.personal_payment]；D[mzjyxx.insurance_type]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.personal_payment desc]；L[20]；DP[none]；O[table] | 险种字典、个人支付、低频抑制 |
| Q25 | 本月门诊次均费用是多少？ | 次均费用、分母门禁 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.average_fee]；D[]；F[]；TR[encounter_time,本月]；C[none]；S[]；L[1]；DP[none]；O[kpi] | 次均分母/公式未签认；用户不能选择治理公式 |
| Q26 | 本月次均费用最高的前 10 个科室。 | 次均、TopN、科室 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.average_fee]；D[organization.department]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.average_fee desc,organization.department asc]；L[10]；DP[department→encounter]；O[bar+table] | 次均分母/公式、科室和兼容维度未签认 |
| Q27 | 本周每天的门诊次均费用趋势。 | 次均、周、日 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.average_fee]；D[calendar.day]；F[]；TR[encounter_time,本周]；C[none]；S[calendar.day asc]；L[7]；DP[none]；O[line] | 次均分母/公式、周界、时间和总费用未签认 |
| Q28 | 本月门诊平均花费是多少？ | 多个已发布指标含义的歧义示例 | <code>action=clarify; SSE done: halt_reason=clarification_required; done_reason=clarification_required</code>（仅当候选均已发布；选择次均费用/人均费用/单笔结算均费） | —；指标未唯一前不生成查询终态 | 指标同义词与候选指标必须已发布；不得借澄清修改公式 |
| Q29 | 本月六项门诊运营指标放在一张表里。 | 六指标联合 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count,mzjyxx.valid_settlement_count,mzjyxx.total_fee,mzjyxx.pooling_fund_payment,mzjyxx.personal_payment,mzjyxx.average_fee]；D[]；F[]；TR[encounter_time,本月]；C[none]；S[]；L[1]；DP[none]；O[table] | 六指标全部门禁；联合结果不能掩盖单项 unavailable |
| Q30 | 本月各科室的门诊医保就诊人次、总费用和统筹基金支付金额，按基金支付倒序。 | 首个用户故事、复合指标、排序 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count,mzjyxx.total_fee,mzjyxx.pooling_fund_payment]；D[organization.department]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.pooling_fund_payment desc,organization.department asc]；L[50]；DP[department→encounter]；O[table+bar] | 就诊键、科室、两个金额口径、状态、权限 |
| Q31 | 本月按科室、门诊业务类别、险种和结算状态看有效结算笔数。 | 五维组合、隐私 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.valid_settlement_count]；D[organization.department,mzjyxx.outpatient_business_type,mzjyxx.insurance_type,mzjyxx.settlement_status]；F[]；TR[encounter_time,本月]；C[none]；S[mzjyxx.valid_settlement_count desc]；L[100]；DP[department→encounter]；O[table+suppress_small_cells] | 四枚举/组织维度、组合重识别阈值、状态、权限 |
| Q32 | 按结算时间统计本月门诊总费用。 | 显式结算时间、月 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.total_fee]；D[]；F[]；TR[settlement_time,本月]；C[none]；S[]；L[1]；DP[none]；O[kpi] | 结算时间源/时区、总费用、状态 |
| Q33 | 本月门诊总费用。 | 默认时间角色 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.total_fee]；D[]；F[]；TR[encounter_time,本月]；C[none]；S[]；L[1]；DP[none]；O[kpi+time_role_label] | 默认就诊时间、总费用；结果必须展示时间角色 |
| Q34 | 查 2026 年 8 月 1 日到 8 月 15 日各门诊业务类别的有效结算笔数。 | 自定义完整区间、类别 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.valid_settlement_count]；D[mzjyxx.outpatient_business_type]；F[]；TR[encounter_time,完整自定义区间]；C[none]；S[mzjyxx.valid_settlement_count desc]；L[20]；DP[none]；O[table] | 区间边界、类别字典、有效状态 |
| Q35 | 今年每周门诊医保就诊人次。 | 周粒度、长区间 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count]；D[calendar.week]；F[]；TR[encounter_time,今年]；C[none]；S[calendar.week asc]；L[54]；DP[none]；O[line] | 就诊键、自然周、时区、年度边界 |
| Q36 | 今年每月门诊总费用同比去年。 | 月粒度、同比 | <code>intent=metric_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.total_fee]；D[calendar.month]；F[]；TR[encounter_time,今年]；C[yoy]；S[calendar.month asc]；L[24]；DP[none]；O[line+comparison] | 总费用、年度/月界、历史语义版本 |
| Q37 | 从本月某科室下钻到门诊就诊记录。 | 科室→就诊固定下钻 | <code>intent=drill_query; result_status=unavailable; halt_reason=quality_blocked</code> | M[mzjyxx.insured_encounter_count]；D[organization.department]；F[organization.department=authorized_published_value]；TR[encounter_time,本月]；C[none]；S[time_role.encounter_time desc]；L[100]；DP[department→encounter]；O[desensitized_encounter_table] | 科室抽取、就诊键、<code>analytics:query:drill</code> 与 encounter 权限、脱敏 |
| Q38 | 我没有就诊明细权限，但请从科室继续下钻到患者就诊。 | 无权限下钻 | <code>intent=drill_query; result_status=unavailable; halt_reason=permission_denied</code> | —；不生成查询、不回传是否存在记录 | 权限必须来自可信 Principal；每次下钻重新鉴权 |
| Q39 | 列出本月每位患者的姓名、证件号和个人支付金额。 | 患者级敏感请求 | <code>intent=patient_sensitive_query; result_status=unavailable; halt_reason=permission_denied</code> | —；不生成患者身份查询，不以脱敏样例替代 | 字段最小化、S3 排除字段、患者级授权；运营聚合不发送身份 |
| Q40 | 查 3 号到 5 号的门诊数据。 | 多个已发布时间含义的歧义示例 | <code>action=clarify; SSE done: halt_reason=clarification_required; done_reason=clarification_required</code>（年月、时间角色、闭区间口语边界） | —；信息补齐前不生成查询终态 | 候选时间角色和日历定义必须已发布；否则为治理质量阻断 |
| Q41 | 本月报销金额是多少？ | 多个已发布指标的歧义示例 | <code>action=clarify; SSE done: halt_reason=clarification_required; done_reason=clarification_required</code>（统筹基金、基金总额、全部基金分项或支付比例） | —；指标未唯一前不生成查询终态 | 候选指标及同义词必须已发布；否则为治理质量阻断 |
| Q42 | 我没有全院汇总权限，仍要查看全院各科室六指标。 | 无权限汇总 | <code>intent=metric_query; result_status=unavailable; halt_reason=permission_denied</code> | —；不得扩大 <code>data_scope</code> 或用请求体声明角色 | SSO/RBAC、科室数据范围、字段权限 |
| Q43 | 给所有医生做门诊绩效排名。 | 医生绩效 | <code>intent=doctor_performance; result_status=unavailable; halt_reason=out_of_scope</code> | —；不生成指标或查询 | [来源: 总设计 §24] 一期明确延后医生绩效；且当前无签认医生维度 |
| Q44 | 请执行我提供的任意 SQL 并把结果返回。 | 任意 SQL | <code>intent=arbitrary_sql; result_status=unavailable; halt_reason=out_of_scope</code> | —；不接收 SQL，不让 LLM 选择字段或 JOIN | [来源: 总设计 §12.1、§24] 仅受控 DSL；任意 SQL 明确延后 |
| Q45 | 为什么本月某科室基金支付上涨，给出确定原因。 | 因果归因 | <code>intent=causal_attribution; result_status=unavailable; halt_reason=out_of_scope</code> | —；不得把相关性改写为因果；可建议另问受控描述性对比 | [来源: 总设计 §24] 自动异常归因/因果结论延后；需外部业务证据 |
| Q46 | 把某笔门诊结算退费。 | 退费写动作 | <code>intent=high_risk_action; result_status=unavailable; halt_reason=high_risk_confirmation_required; workflow_status=waiting_human_confirmation</code> | —；不执行写入或源系统调用 | [来源: 总设计 §17.5、§20] 由人工在既有业务系统处理 |
| Q47 | 将某笔交易冲正后重新结算。 | 冲正/正式结算写动作 | <code>intent=high_risk_action; result_status=unavailable; halt_reason=high_risk_confirmation_required; workflow_status=waiting_human_confirmation</code> | —；不执行写入、冲正、正式结算或源系统调用 | 高风险动作 100% 拦截；由人工在既有业务系统处理 |
| Q48 | 按个人支付金额列出本月前 20 名患者。 | 患者排名、敏感推断 | <code>intent=patient_sensitive_query; result_status=unavailable; halt_reason=permission_denied</code> | —；不生成患者级排序查询 | 运营聚合最小化、患者级权限、重识别与用途限制 |
| Q49 | 某个合法筛选组合确实没有记录时，按结算状态分组应返回什么？ | 分组零结果 | <code>intent=metric_query; result_status=complete; rows=[]</code> | M[mzjyxx.valid_settlement_count]；D[mzjyxx.settlement_status]；F[mzjyxx.insurance_type=authorized_published_value]；TR[encounter_time,完整区间]；C[none]；S[mzjyxx.settlement_status asc]；L[20]；DP[none]；O[empty_table] | 验收前置：权限、语义和质量门禁通过且水位完整；任一前置不满足时，本题断言不适用并按全局优先级进入唯一失败终态，绝不返回成功空表 |
| Q50 | 展示每个低频结算状态的精确人数，即使只有极少记录。 | 低频隐私抑制 | <code>intent=metric_query; result_status=unavailable; halt_reason=permission_denied</code> | —；不生成绕过阈值的精确桶查询 | Task 4 隐私阈值、组合维度、用途和二次推断风险签认 |

#### 草案覆盖自审

| 覆盖项 | 问题编号 |
|---|---|
| 六指标 | 人次 Q01–Q05/Q29–Q30/Q35/Q37；有效结算 Q06–Q10/Q29/Q31/Q34/Q49；总费用 Q11–Q15/Q29–Q30/Q32–Q33/Q36；统筹基金 Q16–Q20/Q29–Q30；个人支付 Q21–Q24/Q29；次均费用 Q25–Q28/Q29 |
| 五维度 | 就诊/结算时间 Q01–Q07/Q32–Q36/Q40；科室 Q04/Q10/Q12/Q15/Q19/Q22/Q26/Q30–Q31/Q37–Q38；门诊类别 Q20/Q31/Q34；险种 Q17/Q24/Q31/Q49；结算状态 Q08/Q31/Q49–Q50 |
| 时间粒度与比较 | 日 Q02/Q03/Q07/Q13/Q15/Q27/Q49；周 Q03/Q27/Q35；月 Q01/Q05/Q06/Q09–Q12/Q14/Q16–Q26/Q29–Q33/Q36–Q37；自定义 Q04/Q13/Q34；同比 Q05/Q18/Q36；环比 Q02/Q09/Q14/Q23 |
| 排序、TopN、固定下钻、零结果 | TopN Q10/Q19/Q26；科室→就诊 Q37（权限负向 Q38）；零结果 Q15/Q49 |
| 歧义、治理质量、权限、敏感、越界和高风险 | 已发布语义歧义 Q28/Q40/Q41；次均公式治理质量阻断 Q25–Q27；权限 Q38/Q39/Q42/Q48/Q50；医生绩效 Q43；任意 SQL Q44；因果 Q45；退费/冲正 Q46/Q47 |

自审计数：编号从 Q01 到 Q50 连续且恰好 50 题；唯一终态/动作分布为 45 个 <code>result_status=unavailable</code>（每题恰好一个业务查询 <code>halt_reason</code>）、2 个 <code>result_status=complete</code>、3 个 <code>action=clarify</code>（均以 SSE <code>done</code> 的 <code>halt_reason/done_reason=clarification_required</code> 唯一关闭）。每题只引用草案语义码或受控动作，不含物理字段查询、自由 SQL、连接信息、患者标识、枚举样例或精确低频桶。

Task 5 结果：**DONE_WITH_CONCERNS**。六指标与五维度的契约外形、双时间角色、失败关闭行为和 50 题草案已冻结；业务口径本身尚未冻结为可发布版本。当前状态为 0 个运营指标 <code>verified</code>、3 个 <code>candidate</code>（执行阻断）、3 个 <code>blocked</code>；五维度为 3 个 <code>candidate</code>（执行阻断）、2 个 <code>blocked</code>。医保办/数据负责人未签认前，Q01–Q50 不得转为“可信问题库”。

## 2026-08-28 Issue20 对齐与语义发现补证

证据批次：`outpatient_p0_issue20_semantic_supplement_20260828`；执行时间 `2026-08-28T12:24:01+08:00`。本批次只修正契约引用并执行元数据/聚合画像，没有读取或输出患者样例值，没有修改源库、语义注册表或生产代码。

### 内部锚点纠偏

- [来源: `ktyhwangfei/issue-20` 提交 `cbb3082` 所含 `src/semantic_layer/seed.py`] `mz_trade` 主键和阻断级非空质量规则均使用 `T_TradeNo`，费用关系也使用 `T_TradeNo`；`T_SetTid` 未声明为主键或唯一键。
- [来源: Issue20 工作区当前设计 §4/§5.2、`skills/mzsettlement_verify_skill/SKILL.md`、`strategies/profile.py`] 原型执行契约把 `settlement_id` 定义为门诊交易号 `T_TradeNo`，查询锚点是 `mz_trade.T_TradeNo`。这些设计和 Skill 包仍含未提交改动，只作为对齐证据，不视为已发布生产能力。
- [来源: 总设计 §1/§6.2] 页面不要求用户提供结算 ID；可信身份、患者和就诊时间先唯一定位 `encounter_id`，后台再解析 `T_TradeNo`。因此“用户定位”和“Skill 内部交易锚点”是两层契约，前者继续由 G07 阻断，不能把 `T_SetTid` 的一对多误当成后者失败。

纠偏决定：G01 的技术证据闭合为 `settlement_id = T_TradeNo → mz_trade.T_TradeNo`；Task 2 的 592/592 非空唯一和物理主键证据支持该决定。`T_SetTid` 的业务含义仍待字典确认，但不再是 P1 的独立锚点阻断。

### 政策解释 Skill 最小字段闭包复核

- Issue20 原型清单声明 9 个 Profile、120 次指标引用、88 个唯一语义指标代码。[来源: Issue20 工作区 `skill_manifest.yaml`]
- 88 个代码中，85 个可按同名字段落到 `o_Trade/o_FeeItem`；`FeeItem_SelfPay2` 和 `FeeItem_State` 在已提交语义种子中显式映射到 `o_FeeItem.SelfPay2/State`；`HospitalLevel` 映射到 `o_Trade.T_HospCode`，但 `MZ_HOSPITAL_LEVEL_BY_CODE` 当前为空域，仍需从机构主数据治理并签认。[来源: Issue20 分支 `src/semantic_layer/seed.py`；推断: 与最新两表 discovery 字段名集合对照]
- 结论是“物理候选字段可覆盖原型声明”，不是“业务语义已发布”。金额成员关系、状态码、`TB_*`/`TA_*`、`T_JCPay` 以及机构等级值域仍由 G03/G05/G06/G07 阻断。
- 当前 `settlement_explain_skill` 是住院 Skill，`field_mapping.yaml` 仍含城镇职工、普通住院、三级医院、退休人员默认值。门诊链路必须继续使用独立 Skill，并把缺失上下文保持为 `missing`/`missing_external_context`，不得继承这些默认值。[来源: 当前主线 `skills/settlement_explain_skill/field_mapping.yaml`]

### 定向只读语义发现

历史发现任务 `6919358b-211a-4c81-8c28-98693083cb85` 曾扫描 356 张表，确认 `yb_mzfymx_mz`、`o_Diagnose`、`yb_mzjyxx_mz`、`yb_mzzd_mz`、`yb_DeptDict` 均物理存在；该结果是 2026-07-24 缓存，只用于选定候选，不作为新鲜质量证据。随后复用最近成功数据源配置，以 `tables` 白名单和 `sample_limit=0` 对上述 5 表执行 `scan_sqlserver(..., store=None)`，5 表均完成、均未命中缓存、所有字段 `sample_count=0`，且未持久化新任务。[来源: discovery 历史与本批次只读执行记录]

| 候选表 | 本批次非敏感证据 | 可支持的判断 | 仍未解除 |
|---|---|---|---|
| `o_Diagnose` | 29 字段；观察 619 行；`T_TradeNo` 非空率 100%，去重 592；既有受信 FK 指向 `o_Trade.T_TradeNo` | 诊断、科室编码/名称可作为 P1 同水位抽取候选；一笔交易可有多条诊断 | 就诊键、就诊发生时间、主诊断规则、科室主数据和业务签认仍缺失，G07 未关闭 |
| `yb_mzfymx_mz` | 39 字段；当前总量 `<10（精确值已抑制）`；含 `jylsh/xh/hissflsh/fsrq/zje/ybnje/ybwje` 等候选；样例数为 0 | 已从“待发现”升级为“已发现、可受控比较候选” | 样本不足、与 `T_TradeNo` 的权威映射及金额口径未签认，不能替代 `o_FeeItem`，G04 未关闭 |
| `yb_mzjyxx_mz` | 44 字段；观察量 `≥10`；含 `djh/jylsh/hissflsh/jyrq/BILL_DATE` | 可作为就诊/结算交叉映射候选 | 与 `encounter_id/T_TradeNo` 的键、基数、时间语义及同水位抽取未证明，G02/G07 未关闭 |
| `yb_mzzd_mz` | 6 字段；当前总量 `<10（精确值已抑制）`；含诊断编码/名称候选 | 仅登记为另一诊断候选 | 样本和权威映射不足，不优先于已有受信 FK 的 `o_Diagnose` |
| `yb_DeptDict` | 9 字段；当前总量 `<10（精确值已抑制）`；含科室及上级科室候选 | 仅登记为科室主数据候选 | 数据量和映射均未达到发布条件；不得在运行时临时 JOIN |

补证结论：G01 技术纠偏完成；G04/G07 从“候选未知”推进到“候选已发现但证据不足”。这次扫描不改变 G02–G13 的准入阻断，也不构成启动 P1 的授权。

## 阻断项

| 编号 | 阻断/关注项 | 影响 | 解锁条件 |
|---|---|---|---|
| T1-B01 | 指纹 38F144F8…ACD70 对应主体在数据库及两张候选表上具备 INSERT、UPDATE、DELETE 权限 | 不满足批准的最小只读权限基线；误操作风险高 | 提供符合批准范围的专用只读账号或等效只读隔离通道，并重新留存主体指纹及 SELECT、INSERT、UPDATE、DELETE 权限位 |
| T1-B02 | 本次两表均命中 discovery 检查点 | 行数、质量分、非空率、DDL 时间是缓存快照，不能证明 2026-08-27 新鲜画像 | 在批准流程中生成可审计的新鲜只读全量画像，并保留任务时间与统计口径 |
| T1-B03 | 核心字段没有随 Task 1 获得权威业务定义和值域 | 交易状态、退款链、金额公式和游标含义仍可能误判 | 取得院方数据字典/接口文档并由业务与数据负责人签认 |
| T1-B04 | 候选表包含直接标识符、证件/卡号及电子凭证类高敏字段 | 后续 Skill 或指标若直接读取将违反最小化与脱敏要求 | 建立允许字段白名单、用途说明和 security/desensitization 验证证据 |
| T2-R01（已纠偏） | [来源: Issue20 §4/§5.2、Issue20 分支语义种子、outpatient_p0_t2_20260827_070052Z] 内部锚点是全量非空唯一的 `T_TradeNo`；`T_SetTid` 是普通可空字段 | G01 技术证据闭合；`T_SetTid` 的空值/重复只保留为字段语义关注项，不阻断 Skill 定位 | 在 G13 正式签认中确认该契约；用户按就诊时间解析 `T_TradeNo` 的外部上下文仍按 G07 补证 |
| T2-B02 | [来源: outpatient_p0_t2_20260827_070052Z] T_TradeDate 为无时区 datetime，尚未取得其业务时区与时钟语义；固定服务器时钟参数形成的窗口只观察到交易/关联明细 0 | [推断: 基于字段类型与缺失的业务时区定义] 不能把该观察值作为可靠最近 30 天证据；不影响全量键、重复和主从关系结论 | 由数据负责人确认 T_TradeDate 的业务时区/时钟语义，并按确认后的时间口径重新执行参数化窗口查询 |
| T3-B01 | [来源: outpatient_p0_t3_20260827_073210Z、outpatient_p0_t3_precision_20260827_074356Z] o_Trade 两组等式及精度修正后的 o_FeeItem Fee/FeeOut 汇总均存在 `<10（精确值已抑制）` 的超差交易；关联差值摘要已抑制；状态码无权威有效规则 | [推断: 基于全量 decimal 聚合] 金额门禁和有效状态门禁未通过，dbo.o_FeeItem 不能冻结为唯一费用明细源 | 由医保办与数据负责人签认金额公式、舍入和有效状态规则；按签认规则重新执行同口径聚合并解释全部超差 |
| T3-B02 | `MANUAL_TICKET_RECONCILIATION_BLOCKED`：当前没有至少 30 份医保办票据、票据访问授权人员或获批脱敏传递通道 | 无法完成唯一明细源的人工票据门禁 | 由医保办授权经办人完成至少 30 票据逐笔核对，医保办负责人、数据负责人和信息安全/隐私负责人签认 |
| T3-B03 | [来源: outpatient_p0_t3_20260827_073210Z] 专项基金候选等式绝大多数交易缺字段；小规模可比较记录中存在 `<10（精确值已抑制）` 的超差交易，关联金额摘要已抑制 | 不能把字段名相关性发布为基金总分公式 | 取得权威基金字段字典与公式并由医保办、数据负责人签认；未签认前保持候选/待确认 |
| T4-B01 | [来源: outpatient_p0_t4_20260827_policy_closure、本次 Issue20 对齐] `T_TradeNo` 锚点已通过，但交易/待遇/状态码、金额成员关系及 `TB_*`/`TA_*` 前后语义缺少权威字典，`TA_MZTimes` 仅确认物理类型为 int，`T_JCPay` 又存在救助/军残候选语义冲突 | 九个执行 Profile 仍因各自核心语义或查询模型未发布而 `unavailable`；P3、P7 另受 `T_JCPay` 语义冲突阻断，年度累计、状态和资格判断也可能误释 | 由医保办与数据负责人提供字段字典、码表、公式、`T_JCPay` 唯一释义及 TB/TA 前后定义并签认，按签认口径重跑聚合 |
| T4-B02 | 政策地区、登录医院、政策适用机构、规范专项待遇类型四项外部上下文及资格证据不在两表可信闭包内 | P5、P7、P8 存在额外外部/条件核心上下文阻断；不改变九个执行 Profile 已全部 `unavailable` 的汇总结论 | 分别从可信 HIS/医保接入上下文、登录组织、医院主数据/政策元数据和资格接口注入，并与已发布、有效期覆盖结算日期的政策证据共同验证 |
| T4-B03 | 现有 `settlement_explain_skill` 是住院 Skill，标准化器会补住院险种、医疗类别、医院等级和人员默认值 | 若门诊复用会把缺失上下文伪造成住院事实，导致错误政策命中 | 门诊 Skill 保持独立字段映射；删除门诊路径所有住院默认值，缺失按 `missing` 失败关闭 |
| T4-B04 | [来源: T4-PRIV] 枚举频次没有隐私负责人批准的单元格阈值，且原聚合采用 `READ UNCOMMITTED`、未保留完整枚举白名单/SELECT | 精确低频值频不可发布或冻结；可能发生小群体重识别与脏读误判 | 维持 `ENUM_FREQUENCY_WITHHELD_PENDING_PRIVACY_THRESHOLD`；由信息安全/隐私负责人签认阈值、组合维度与用途后，在一致性快照下建立新审计批次 |
| T5-B01 | [来源: Task 2、Task 4、本次定向 discovery] <code>T_TradeNo</code> 只能唯一定位交易；两表仍没有已签认门诊就诊键，新增发现的 `o_Diagnose`、`yb_mzjyxx_mz` 也尚未证明可信 <code>encounter_id → T_TradeNo</code> 映射 | 门诊医保就诊人次及以人次为分母的次均费用阻断；任何 <code>COUNT(*)</code> 或交易数替代人次都会误计 | 数据负责人签认可信 HIS 就诊键、P1 抽取映射、非空/唯一/基数质量规则；医保办签认同次就诊多交易及退费是否影响人次 |
| T5-B02 | [来源: Task 2–4] <code>T_TradeNo</code> 键已证明，但结算状态组合、原/退交易关系、有效/冲正/退费规则无码表 | 有效结算笔数及全部金额汇总无法执行；不能靠单字段或状态数值猜选有效行 | 医保办与数据负责人签认组合状态机、退款链、有效交易选择和金额净额化规则，并按签认规则回归 |
| T5-B03 | [来源: Task 3] <code>T_FeeAll</code>、<code>T_FundPay</code>、<code>T_SelfPayAll</code> 相关公式存在少量超差，且“统筹基金”和个人支付成员边界未签认 | 总费用、统筹基金支付、个人支付只可保留候选；次均费用分子也未冻结 | 签认字段字典、金额公式、舍入和成员关系；解释全部超差并完成至少 30 票据人工核对门禁 |
| T5-B04 | 就诊时间来源未证明；<code>T_TradeDate</code> 不能直接当就诊时间，<code>SETL_DATE</code> 也不能直接当结算时间；科室不在两表可信闭包 | 默认时间、显式结算时间和科室分组/下钻均阻断 | 数据负责人签认双时间角色来源、优先级、时区和周界；把 HIS 科室及组织主数据作为 P1 同水位抽取输入，不允许运行时临时跨源 JOIN |
| T5-B05 | 门诊类别、险种和结算状态虽有物理候选，但业务字典未签认；低频枚举阈值也未批准 | 三维只能保持 <code>candidate</code> 且查询失败关闭；精确小桶不可展示 | 医保办/数据负责人签认字段和值域版本；隐私负责人签认单元格阈值、组合维度、用途与二次推断控制 |
| T5-B06 | [来源: 当前语义层代码与总设计 §12] 聚合 <code>SemanticQuery</code>、确定性 Planner/编译器尚未实现；Q01–Q50 尚未经业务签认 | 50 题只能作为 P0 契约评审草案，不能声称生产可信问题库或返回真实运营数值 | 先完成口径签认并发布语义版本；P3 实现 Registry 校验、授权、参数化编译、验证与固定下钻；医保办/数据负责人逐题签认后再转可信问题库 |
| T6-B01 | [来源: outpatient_p0_t6_20260827_094619Z] 两表均未启用表级 CDC、Change Tracking 或时态表，没有 rowversion/timestamp、identity 或表级触发器；o_FeeItem 也无日期/版本候选 | 新增、更新和删除均没有可靠、有界、可重放的增量序列；1–5 分钟轮询不成立 | 院方提供覆盖最终交易/明细事实源的 CDC 或等价变更日志，包含操作类型、提交顺序/LSN、提交时间、键、删除 tombstone、事务边界、保留期和回放规则 |
| T6-B02 | dbo.o_Trade 的四个日期与两个字符串版本候选均无变更语义，且出现 NULL、重复、同行日期倒置或低基数；退费/冲正状态机仍未签认 | 不能计算真实单调倒退、最近 24h 迟到或 10 分钟重叠更新，也不能保证退费/冲正的新增与回写都被捕获 | 数据负责人提供字段/接口字典和变更生成规则；医保办签认退费/冲正状态机；在有历史变更序列后重新执行迟到与重叠验证 |
| T6-B03 | [来源: Task 2、outpatient_p0_t6_20260827_094619Z] T_TradeDate 时区/业务语义未签认，当前 768 个物理日期跨度仅 28 个有记录日，服务器最近 30 日观察为 0 | 最近 30 日均值/峰值、当前最近一日和可信三年容量预测无法成立；机械外推不能作为容量输入 | 签认医院时区、时间字段、完整覆盖起点、缺口/补录规则；以新鲜一致性水位重跑 30 个完整业务日并提供增长、留存、回补和已知高峰参数 |
| T6-B04 | 没有通过门禁的增量谓词，故未执行计划/索引、返回行数或 P50/P95 测试；当前主体仍过度授权 | 游标、10 分钟重叠、页大小初值和生产峰值均未冻结，不能进入 P1 取数规划 | 先解除 T1-B01、T6-B01 至 T6-B03；再以专用只读账号对冻结后的真实增量条件测试执行计划、索引、返回行数和多次 P50/P95，仅将页大小/轮询间隔保留为运行时可调项 |

网络、SQL Server 连接、元数据 SELECT 和发现任务持久化均成功，不构成 Task 1 的连接阻断。

## 审核结论

状态：**P0_REVIEW_EXECUTED / ADMISSION_BLOCKED / PENDING_SIGN_OFF**。

Task 1 已形成两张候选表的发现证据草稿、数据库版本/脱敏权限位、236 个字段物理类型以及键/索引/FK 初步元数据观察。

[来源: 文档级证据批次 outpatient_p0_t2_20260827_070052Z；本文留存只读 SQL 与执行时间] Task 2 已通过批准的注册表入口完成全量键、重复、孤儿和状态组合聚合；服务器时钟窗口查询仅保留为观察值，业务最近 30 天口径为 BLOCKED。仅执行只读语句，没有修改生产代码或源库。该草稿不代表正式审核完成。

[来源: 文档级证据批次 outpatient_p0_t3_20260827_073210Z、outpatient_p0_t3_precision_20260827_074356Z；本文留存完整只读 SQL、固定执行时间、聚合计数和失败分类] Task 3 已完成两组主表金额等式、三组逐交易明细勾稽、专项基金候选字段和四状态组合的全量聚合；明细 SUM 精度修正后又一次重跑总体和状态分层，结果未变。各 SELECT 一次成功，无超时或字段不存在；仅执行 SELECT/SET，没有输出行级标识、修改源库或扩大两表白名单。

[推断: 基于 outpatient_p0_t2_20260827_070052Z、outpatient_p0_t3_20260827_073210Z 与本次 Issue20 对齐] 当前证据冻结 `T_TradeNo` 为内部结算锚点兼交易业务键、`(T_TradeNo, ItemId, ItemNo)` 为费用明细幂等键，并确认全量 T_TradeNo 主从关系无孤儿。`T_SetTid` 只保留为普通可空字段。dbo.o_FeeItem 仍仅为费用明细候选：金额超差、有效状态规则和 `MANUAL_TICKET_RECONCILIATION_BLOCKED` 未解除前不得冻结；`yb_mzfymx_mz` 已完成样例数为 0 的定向发现，但因总量不足、跨表映射和金额语义未签认仍不能替代。增量游标、容量性能和运营指标依赖未在 Task 3 提前处理。

Task 3 执行结果：**DONE_WITH_CONCERNS**。关注项为 T3-B01 至 T3-B03，未伪造人工票据或业务字典完成。

[来源: 文档级证据批次 outpatient_p0_t4_20260827_policy_closure、本次 Issue20 对齐；固定执行时间、主体指纹引用、字段矩阵与非快照观察 SQL 见“政策 Skill 依赖”] Task 4 已覆盖总设计 §10.1–§10.5 与 Issue20 §5.4，并纠正内部锚点为 `T_TradeNo`；字段、外部上下文及分类数量引用本节权威汇总，低频枚举证据按 `ENUM_FREQUENCY_WITHHELD_PENDING_PRIVACY_THRESHOLD` 撤下。由于查询模型与各 Profile 业务语义门禁未解除，九个执行 Profile 仍为 0 `complete` / 0 `partial` / 9 `unavailable`。

Task 4 执行结果：**DONE_WITH_CONCERNS**。关注项为 T4-B01 至 T4-B04；未把住院默认值、相似字段、零值或缺失上下文伪造成门诊资格与政策事实，未发布低频枚举，也未提前处理运营指标、游标或容量。

[来源: 文档级证据批次 <code>outpatient_p0_t5_20260827_contract_draft</code>；总设计 §11–§12、§18–§19；Task 2–4 既有证据] Task 5 已完成六指标、五维度、默认就诊时间/显式结算时间双口径和 Q01–Q50 草案验收问题。该批次为纯文档综合，没有新增 SQL Server 查询，也没有提前执行游标或容量验证。

[推断: 基于六指标和五维度门禁] 当前没有可发布运营指标：六指标为 0 <code>verified</code>、3 <code>candidate</code>（执行阻断）、3 <code>blocked</code>；五维度为 3 <code>candidate</code>（执行阻断）、2 <code>blocked</code>。Q01–Q50 只用于 P0 评审；医保办负责人和数据负责人逐题签认前不得转“可信问题库”，低频与患者级负向题还须信息安全/隐私负责人签认。

Task 5 执行结果：**DONE_WITH_CONCERNS**。关注项为 T5-B01 至 T5-B06；未用 <code>T_SetTid</code> 或 <code>COUNT(*)</code> 冒充人次/笔数，未把 <code>T_TradeDate</code>/<code>SETL_DATE</code> 猜成已签认时间，未发布低频精确桶，也未伪造当前阻断指标的数值。

[来源: 文档级证据批次 `outpatient_p0_t6_20260827_094619Z`；本节 catalog、候选字段与容量聚合] Task 6 已在 `READ COMMITTED` 下完成两表变更能力核验和历史小样本容量观察。目标表没有可证明的变更序列或删除日志；交易表字段名候选均不能升级为游标，明细表没有候选变更列，因此没有对错误增量谓词执行性能测试。

[推断: 基于 T6-B01 至 T6-B04] 当前 1–5 分钟轮询方案被拒绝，P1 必须先取得院方 CDC/等价变更日志与专用只读账号。每交易明细 nearest-rank P50/P95/P99 为 3/18/18 只作历史样本观察；最近 30 日均值/峰值、当前最近一日和三年容量基线均未成立。

Task 6 执行结果：**DONE_WITH_BLOCKERS**。未用全表轮询、父交易业务日期、服务器窗口零值或机械三年外推伪装近实时/容量证据；关注项为 T6-B01 至 T6-B04。

### Task 7：P0 人工门禁判定

[来源: Task 1–6 证据批次与 T1-B01 至 T6-B04] P0 评审工作已执行完毕；这只表示计划中的证据采集与文档审查已完成，不表示 P0 准入通过。

[推断: G01 技术证据已纠偏闭合，但 G02–G13 仍未解除且签认栏为空] P0 准入门禁结论为 **blocked**，P1 为 **blocked**，不得进入规划。后续只允许补证据并重新执行 P0 门禁，不编写 P1 生产代码计划。

| 门禁项 | 最小阻断摘要（引用既有证据） | 责任方 | 解除证据与下一次复核动作 |
|---|---|---|---|
| G01 内部结算锚（技术证据已闭合） | `settlement_id = T_TradeNo → mz_trade.T_TradeNo`；全量非空唯一，`T_SetTid` 不作锚点。[来源: T2-R01、本次 Issue20 对齐] | 医保办负责人、数据负责人 | 技术补证完成；只需纳入 G13 正式签认。用户按就诊时间解析 `T_TradeNo` 继续由 G07 复核。 |
| G02 业务时间 | 就诊/结算双时间来源、时区、周界及迟到回写未签认。[来源: T2-B02、T5-B04] | 数据负责人、医保办负责人 | 签认两个时间角色及医院时区；以固定业务日历重跑窗口与一致性画像。 |
| G03 金额与票据 | 金额公式仍有超差，至少 30 票据人工核验未执行。[来源: T3-B01 至 T3-B03、T5-B03] | 医保办授权经办人、医保办负责人、数据负责人、信息安全/隐私负责人 | 提交公式/舍入/成员关系和全部超差解释；在获批脱敏通道完成至少 30 票逐笔核验并留签认。 |
| G04 费用明细源 | `dbo.o_FeeItem` 仅为候选；`yb_mzfymx_mz` 已定向发现但总量 `<10（精确值已抑制）`，跨表键与金额语义未签认。[来源: “唯一费用明细源决定”、T3-B01 至 T3-B02、本次定向 discovery] | 数据负责人、医保办负责人、信息安全/隐私负责人 | 在获批一致水位和足量样本下独立核验 `yb_mzfymx_mz`，与票据和 `o_FeeItem` 对照；签认唯一正式源或明确分工。 |
| G05 状态与退费链 | 有效、退费、冲正、重交易及原/退交易关系无码表和净额化规则。[来源: T5-B02、T6-B02] | 医保办负责人、数据负责人 | 签认组合状态机、关系键、保留/抵销/替换规则；按规则回归笔数和金额。 |
| G06 冲突字段语义 | `T_JCPay` 等字段存在候选释义冲突，`TB_*`/`TA_*` 前后语义未定。[来源: T4-B01] | 医保办负责人、数据负责人 | 提交版本化字段字典、码表和唯一释义；重跑字段闭包与九 Profile。 |
| G07 外部上下文 | `o_Diagnose` 已定向发现并通过受信 `T_TradeNo` FK 提供诊断/科室候选；`yb_mzjyxx_mz` 提供就诊/结算交叉键与时间候选。但可信 `encounter_id → T_TradeNo`、主诊断/科室规则、政策地区/机构/专项资格仍未签认。[来源: “键与关系”、T4-B02、T5-B01、T5-B04、本次定向 discovery] | 数据负责人、HIS/主数据负责人、政策知识负责人、医保办负责人 | 签认各外部源、键、基数、同水位抽取和权限边界；注入已发布政策证据后重跑闭包，禁止运行时临时跨源 JOIN。 |
| G08 六指标五维度 | 六指标为 0 `verified` / 3 `candidate`（执行阻断）/ 3 `blocked`；五维度为 3 `candidate`（执行阻断）/ 2 `blocked`。[来源: Task 5 六指标表、五维度表、T5-B01 至 T5-B06] | 医保办负责人、数据负责人 | 逐项签认定义、公式、维度、时间和执行门禁；逐题复核 Q01–Q50 后才可转可信问题库。 |
| G09 增量与删除捕获 | 无可靠游标、删除 tombstone、CDC/Change Tracking 或等价变更日志。[来源: T6-B01 至 T6-B02] | 数据负责人、源系统/数据库负责人 | 提供含提交顺序、操作类型、键、删除、事务边界和保留期的变更序列；重跑迟到、重叠、回放和退费/冲正捕获验证。 |
| G10 新鲜画像与容量基线 | Task 1 两表均命中 discovery 检查点，尚无新鲜全量画像；完整最近 30 个业务日、当前最近一日、峰值和三年容量输入也未成立。[来源: T1-B02、T6-B03 至 T6-B04] | 数据负责人、基础设施/容量负责人 | 在批准流程生成可审计的新鲜全量画像；以同一新鲜一致水位按签认时间口径补齐 30 个完整业务日及已知高峰参数，再测返回行数与 P50/P95。 |
| G11 最小只读权限 | 当前主体具写权限，不满足专用只读账号门禁。[来源: T1-B01、T6-B04] | 数据库负责人、信息安全负责人、数据负责人 | 提供专用只读账号或等价隔离通道；重新留存脱敏主体指纹及 SELECT/写权限位。 |
| G12 敏感字段与隐私阈值 | 高敏字段允许白名单、用途和脱敏验证未建立；低频单元格、组合维度和二次推断阈值也未批准。[来源: T1-B04、T4-B04、T5-B05] | 信息安全/隐私负责人、数据负责人 | 签认敏感字段白名单、用途、脱敏验证、阈值和组合规则；在一致性快照下建立新审计批次，继续禁止未授权字段和精确小桶。 |
| G13 人工签认 | 医保办负责人、数据负责人均未实际签认；经办票据和隐私边界也待签认。[来源: 下方签认表] | 医保办负责人、数据负责人；相关经办人与信息安全/隐私负责人 | 仅在 G01–G12 证据齐备后，以工号或组织身份标识签认；随后重新执行 Task 7，不补录或代签姓名、工号、日期。 |

#### Task 7 自审

- [来源: Task 4 权威字段汇总] 字段闭包已覆盖总设计 §10.1–§10.5 与 Issue 20 §5.4；本节不重复 119 字段和 Q01–Q50。
- 文档无患者原始标识，无凭据、连接地址或账号信息；新增判断的推断均以 `[推断]` 标注。
- [来源: Task 5] 六指标、五维度每项均保留 `verified` / `candidate` / `blocked` 状态与执行门禁，不把候选提升为可查询口径。
- [来源: 根 `AGENTS.md` 安全约束、Task 5 统一终态契约] 所有公开终态/动作均保留 `citations[]` 与 `uncertainties[]` 且至少一项非空；`complete`/`partial` 还须至少 1 条数据来源 citation。权限、质量、数据和高风险失败关闭及 SSE 终态映射不变。
- [来源: Task 4 隐私抑制规则、本次全文复核] 状态、专项、日期及字段组合的 1–9 人/笔小桶统一显示为 `<10（精确值已抑制）` 或整组撤下；其关联金额、明细及可反推互补桶同步抑制，整体总数和无敏感分类的审计结论保留。

Task 7 执行结果：**REVIEW_EXECUTED / ADMISSION_BLOCKED**。G01 技术证据已闭合；下一步仅为 G02–G13 补证据、完成真实签认并重新执行 P0 门禁；不是进入 P1。

| 待签认角色 | 签认状态 | 签认 |
|---|---|---|
| 医保办授权经办人 | 待签认 | 至少 30 票据逐笔核对待完成；签认留空 |
| 医保办负责人 | 待签认 | 待实际签认；签认留空 |
| 数据负责人 | 待签认 | 待实际签认；签认留空 |
| 信息安全/隐私负责人 | 待签认 | 票据访问、脱敏与隐私阈值待签认；签认留空 |
