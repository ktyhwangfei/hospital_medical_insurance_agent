-- ============================================================================
-- Issue #78 城镇职工门诊费用分解 —— 实际执行 SQL 模板（bjyb / SQL Server）
-- 生成日期：2026-09-28；与代码渲染结果逐字一致（RecordQueryMapping 默认映射）
--
-- 用法：
--   1. 先跑 SQL 0 拿到全部符合条件的交易号；
--   2. 对每笔交易，把 @trade_no 替换为实际交易号（如 '011100030X240913000066'），
--      @hosp_code 固定 '01110003'（o_Trade 全库唯一院区值），按 SQL 1→6 顺序取数；
--   3. SQL 3/4 的 @codes 用 SQL 2 结果里的 ItemCode 列表填充
--      （ItemType='0' 的进 SQL 3 药品目录，其余进 SQL 4 诊疗/材料目录）。
--
-- 代码位置（修改映射即改 SQL，无需动代码逻辑）：
--   列名/表名映射  src/adapters/data_supply/record_query_mappings.py（DEFAULT_COLUMNS / RecordQueryMapping）
--   SQL 模板       src/adapters/data_supply/outpatient_decomposition_queries.py
--                    locate_outpatient_trade        -> SQL 1
--                    load_outpatient_fee_items      -> SQL 2
--                    load_drug_catalog              -> SQL 3
--                    load_service_catalog           -> SQL 4（材料同表，load_material_catalog 同一语句）
--                    load_institution_level         -> SQL 5
--   批量筛选       scripts/eval/fee_decomposition_batch.py（TRADE_SQL）-> SQL 0
--   编排入口       src/runtime/policy_qa/fee_decomposition/snapshot_service.py
--                    decompose_outpatient_trade（按 1→6 顺序调用）
-- ============================================================================

-- ────────────────────────────────────────────────────────────────────────────
-- SQL 0：批量筛选交易号（城镇职工 × 普通门诊）
--   位置：scripts/eval/fee_decomposition_batch.py  TRADE_SQL
--   值域待确认：P_FundType='3'（码表已解析为"城镇职工"）、T_CureType='11'（"普通门诊"）；
--              T_CureType 另有 17/18/19 无码表解析（疑门特/急诊等），如需纳入请确认含义
-- ────────────────────────────────────────────────────────────────────────────
SELECT T_TradeNo
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
ORDER BY T_TradeNo;

-- ────────────────────────────────────────────────────────────────────────────
-- SQL 1：交易定位 + 账面观测值（每笔 1 次）
--   位置：outpatient_decomposition_queries.py  locate_outpatient_trade
--   用途：锚定交易日期/院区；读取全部账面金额字段作为核对目标；识别冲正退款
--   值域待确认：PN_PersonType（人员类别代码 → 在职/退休）；TB_FeeIn 是否交易前累计口径；
--              T_HasRefundmented / T_PartialReturnFlag 取值（1=是）
-- ────────────────────────────────────────────────────────────────────────────
SELECT [T_TradeNo], [T_TradeDate], [T_HospCode], [P_FundType], [T_CureType],
       [PN_PersonType], [P_Birthday], [TB_FeeIn],
       [T_FeeAll], [T_FeeIn], [T_FeeOut], [T_FundPay], [T_SelfPay2], [T_FirstPay],
       [T_BigPay], [T_BigSelfPay], [T_BCPay], [T_JCPay], [T_OfficalPay],
       [T_SelfPay1], [T_SelfPayAll], [T_PersonCountPay], [T_CashPay],
       [T_HasRefundmented], [T_PartialReturnFlag], [TR_OraginalTradeNo], [T_OraginalTradeNo]
FROM [dbo].[o_Trade]
WHERE [T_TradeNo] = @trade_no AND [T_HospCode] = @hosp_code;

-- ────────────────────────────────────────────────────────────────────────────
-- SQL 2：费用明细全量读取（每笔 1 次，禁止分页）
--   位置：outpatient_decomposition_queries.py  load_outpatient_fee_items
--   注意：o_FeeItem 实测无费用发生日期列（2026-09-28 核实），发生日期降级用交易日期
--   值域待确认【最关键卡点】：ItemType 取值语义——0=药品已确认；
--              其余取值（1/2/...）对应诊疗/材料/其他的码表。此值域一确认，
--              54 笔"无法核对"交易的目录分解即可解锁
--   值域待确认：FeeType 取值（无自付/有自付/全自付 与目录 sflb 的一致性校验用）
-- ────────────────────────────────────────────────────────────────────────────
SELECT [ItemId], [ItemType], [ItemCode], [FeeType], [UnitPrice], [Count],
       [Fee], [FeeIn], [FeeOut], [SelfPay2]
FROM [dbo].[o_FeeItem]
WHERE [T_TradeNo] = @trade_no
ORDER BY [ItemId];

-- ────────────────────────────────────────────────────────────────────────────
-- SQL 3：药品目录全版本（ItemType='0' 的 ItemCode 批量，每笔 1 次）
--   位置：outpatient_decomposition_queries.py  load_drug_catalog
--   用途：sflb 收费类别 + zfbl 自付比例 → 逐行分解医保内/外/自付二；
--        sxrq/jzrq 有效期按费用发生日期匹配；A_ypbs=1 集采 → A_mzxj 限价比价
--   值域待确认：sflb 取值（无自付/有自付/全自付 或 甲/乙/丙）；zfbl 数值口径（%还是小数）；
--              A_ypbs 取值（1=集采？）；A_xbbl 语义（超限价自付比例：增量还是最终比例、作用基数）；
--              ypfl 取值（16/6=自制剂候选）；空 jzrq 是否=长期有效
-- ────────────────────────────────────────────────────────────────────────────
SELECT [ypbm], [sxrq], [jzrq], [sflb], [zfbl], [A_ypbs], [A_mzxj], [A_xbbl], [ypfl], [bzjg]
FROM [dbo].[yb_ypzdml]
WHERE [ypbm] IN (@codes...);

-- ────────────────────────────────────────────────────────────────────────────
-- SQL 4：诊疗/服务设施目录全版本（ItemType<>'0' 的 ItemCode 批量，每笔 1 次）
--   位置：outpatient_decomposition_queries.py  load_service_catalog / load_material_catalog
--   注意：材料目录候选与诊疗同表；材料是否完整包含在 yb_xzzlfwxm 待确认
--   值域待确认：sfxmdj（1 无自付/2 有自付/3 全自付）；zfbl 数值口径；空 jzrq 语义
-- ────────────────────────────────────────────────────────────────────────────
SELECT [xmbm], [sxrq], [jzrq], [sfxmdj], [zfbl]
FROM [dbo].[yb_xzzlfwxm]
WHERE [xmbm] IN (@codes...);

-- ────────────────────────────────────────────────────────────────────────────
-- SQL 5：机构等级（每院区 1 次）
--   位置：outpatient_decomposition_queries.py  load_institution_level
--   值域待确认：H_LEVEL 取值（候选：14=社区；0–13=其他等级）——决定社区 90% 比例档
-- ────────────────────────────────────────────────────────────────────────────
SELECT [H_CODE], [H_LEVEL]
FROM [dbo].[m_institution]
WHERE [H_CODE] = @hosp_code;
