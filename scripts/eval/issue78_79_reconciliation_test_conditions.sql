-- ============================================================================
-- Issue #78/#79 城镇职工 门诊 & 门特 费用分解 —— 测试条件 SQL（bjyb / SQL Server）
-- 生成日期：2026-10-12
-- 用途：按测试条件筛选满足条件的数据、复核批量对账结果、对无法对账数据取证。
-- 配套：
--   取数 SQL（单交易全量快照）见 scripts/eval/issue78_decomposition_sql_templates.sql
--   批量对账脚本 scripts/eval/fee_decomposition_batch.py          （门诊 81 笔）
--                scripts/eval/fee_decomposition_special_mz_batch.py（门特 mz 套表 14 笔）
-- 对账结果（2026-10-12 复跑）：
--   门诊    ：准确 78/81（96.30% 全量、100% 可判定）；3 笔不可用=冲正/负明细
--   门特 mz ：准确 8 / 差异 1（djh=675 公疗） / 无法核对 5（2025 年起周期表未维护）；
--             字段级可判定准确率 99.32%（147/148）
-- ============================================================================


-- ══════════════════════════════════════════════════════════════════════════
-- 链路一：城镇职工 × 普通门诊（o_Trade / o_FeeItem 套表）
-- ══════════════════════════════════════════════════════════════════════════

-- ── 1.0 批量筛选（基础测试条件：险种 + 医疗类别 + 院区）────────────────────
-- P_FundType='3'（码表=城镇职工）、T_CureType='11'（普通门诊），已经语义注册中心码表确认
SELECT T_TradeNo
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
ORDER BY T_TradeNo;

-- ── 1.1 分支覆盖筛选：按想测的分支取满足条件的交易 ─────────────────────────
-- 起付线分支（本次起付承担非零）：30 笔
SELECT T_TradeNo, T_FirstPay, TB_FeeIn, PN_PersonType
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
  AND T_FirstPay > 0
ORDER BY T_TradeNo;

-- 大额支付分支（共付段非零）：26 笔
SELECT T_TradeNo, T_BigPay, T_BigSelfPay
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
  AND T_BigPay > 0
ORDER BY T_TradeNo;

-- 退休补充补助分支：3 笔（另：退休候选码 PN_PersonType IN ('21','22') 共 11 笔）
SELECT T_TradeNo, PN_PersonType, T_BCPay, T_BigSelfPay
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
  AND T_BCPay > 0
ORDER BY T_TradeNo;

-- 公疗补充分支：2 笔（军残 T_JCPay>0 全库 0 笔——门诊链路军残分支无正向样本）
SELECT T_TradeNo, T_OfficalPay, T_FeeIn
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
  AND T_OfficalPay > 0
ORDER BY T_TradeNo;

-- 先行自付（自付二）分支：49 笔
SELECT T_TradeNo, T_SelfPay2
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
  AND T_SelfPay2 > 0
ORDER BY T_TradeNo;

-- D15 全额自费（无待遇原因码）分支：26 笔
SELECT T_TradeNo, PN_NoRightReason, T_FeeAll, T_FeeIn, T_FundPay
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
  AND PN_NoRightReason IN ('4', '5')
ORDER BY T_TradeNo;

-- 冲正/退款分支（当前不支持重算，预期不可用）：3 笔
SELECT T_TradeNo, T_HasRefundmented, T_PartialReturnFlag,
       TR_OraginalTradeNo, T_OraginalTradeNo, T_FeeAll, T_FundPay
FROM o_Trade
WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = '01110003'
  AND (T_HasRefundmented = 1 OR T_PartialReturnFlag = 1)
ORDER BY T_TradeNo;

-- ── 1.2 行级分支覆盖统计（药品/诊疗/材料/限价/自付比例）────────────────────
-- 2026-10-12 实测：总 227 行 = 药品 115 + 诊疗 62 + 材料 50；
-- SP_SCALE>0 限价行 3；MEDIC_L>0 自付比例行 17；含集采药交易 73；含自制剂候选交易 1
SELECT
  SUM(CASE WHEN f.ItemType = '0' THEN 1 ELSE 0 END)        AS 药品行,
  SUM(CASE WHEN f.ItemType IN ('1','2') THEN 1 ELSE 0 END) AS 诊疗行,
  SUM(CASE WHEN f.ItemType = '3' THEN 1 ELSE 0 END)        AS 材料行,
  SUM(CASE WHEN f.SP_SCALE > 0 THEN 1 ELSE 0 END)          AS 限价行_SP_SCALE,
  SUM(CASE WHEN f.MEDIC_L > 0 THEN 1 ELSE 0 END)           AS 自付比例行_MEDIC_L,
  COUNT(*) AS 总行数
FROM o_FeeItem f
JOIN o_Trade t ON t.T_TradeNo = f.T_TradeNo
WHERE t.P_FundType = '3' AND t.T_CureType = '11' AND t.T_HospCode = '01110003';

-- 含集采药（A_ypbs='1'）的交易：73 笔
SELECT DISTINCT f.T_TradeNo
FROM o_FeeItem f
JOIN o_Trade t ON t.T_TradeNo = f.T_TradeNo
JOIN yb_ypzdml c ON c.ypbm = f.ItemCode
WHERE t.P_FundType = '3' AND t.T_CureType = '11' AND t.T_HospCode = '01110003'
  AND c.A_ypbs = '1'
ORDER BY f.T_TradeNo;

-- 含自制剂候选（ypfl IN ('16','6')）的交易：1 笔
SELECT DISTINCT f.T_TradeNo
FROM o_FeeItem f
JOIN o_Trade t ON t.T_TradeNo = f.T_TradeNo
JOIN yb_ypzdml c ON c.ypbm = f.ItemCode
WHERE t.P_FundType = '3' AND t.T_CureType = '11' AND t.T_HospCode = '01110003'
  AND c.ypfl IN ('16', '6')
ORDER BY f.T_TradeNo;

-- ── 1.3 无法对账数据取证（2026-10-12 复跑：3 笔，全部为冲正/负明细）────────
-- 证据结论：
--   011100030X241118000005  被冲正的原单（T_HasRefundmented=1），金额 +2.50
--   011100030X241118000006  冲正单（T_OraginalTradeNo 指向 000005），金额 -2.50，1 行负明细
--   011100030X260417004968  冲正单（指向 ...004741），金额 -2637.00，33 行全负明细
-- 按设计 §7.1/EOP-REF-001/002 首期不支持重算 → unavailable，属预期行为而非算法错误。
SELECT t.T_TradeNo, t.T_HasRefundmented, t.T_PartialReturnFlag,
       t.TR_OraginalTradeNo, t.T_OraginalTradeNo, t.T_FeeAll, t.T_FundPay,
       (SELECT COUNT(*) FROM o_FeeItem f WHERE f.T_TradeNo = t.T_TradeNo) AS 明细行数,
       (SELECT COUNT(*) FROM o_FeeItem f WHERE f.T_TradeNo = t.T_TradeNo AND (f.Fee < 0 OR f.Count < 0)) AS 负明细行数
FROM o_Trade t
WHERE t.T_TradeNo IN (
  '011100030X241118000005',
  '011100030X241118000006',
  '011100030X260417004968'
);


-- ══════════════════════════════════════════════════════════════════════════
-- 链路二：城镇职工 × 门特·按项目付费 —— mz 套表
--              （yb_brdjxx + yb_mzjyxx + yb_mzfymx + yb_dyxxtsb/yb_dyxxnd 周期表）
-- ══════════════════════════════════════════════════════════════════════════

-- ── 3.0 批量筛选：FUND_TYPE=3 × yllb='12' × fyfs='0'（按项目付费）：14 笔 ───
SELECT b.djh
FROM dbo.yb_brdjxx b
JOIN dbo.yb_mzjyxx m ON b.djh = m.djh
WHERE b.FUND_TYPE = 3 AND b.yllb = '12' AND m.fyfs = '0'
ORDER BY b.djh;

-- ── 3.1 周期上下文证据（决定 confirmed / unknown 三态）────────────────────
-- dyxxtsb（特殊病调解表）/ dyxxnd（年度表）交易后快照存在 → 可推导交易前口径（confirmed）；
-- 2025 年起两表未维护 → 5 笔（1937486/1937487/2004179/2004529/2026452）周期上下文 unknown，
-- 统筹/大额 4 字段 not_verifiable。原因类别：数据源缺口，非规则错误。
SELECT 'tsb' AS 来源, djh FROM dbo.yb_dyxxtsb WHERE djh IN ('1937486','1937487','2004179','2004529','2026452')
UNION ALL
SELECT 'nd', djh FROM dbo.yb_dyxxnd WHERE djh IN ('1937486','1937487','2004179','2004529','2026452');

-- ── 3.2 资格字段（Issue #79 候选口径，未签核）──────────────────────────────
-- cjjrdj 军残等级（1-4/5-6 档）、gwydybz 公疗标志（0=享受/1=不享受，与红名单相反）、
-- cblb=61 社会化退休候选。gwydybz=0 共 5 笔，其中账面实付公疗仅 1 笔（djh=609，585.00）。
SELECT b.djh, b.cblb, b.cjjrdj, b.gwydybz, m.gfylbchbx, m.zje, m.tczhf, m.bczhf
FROM dbo.yb_brdjxx b
JOIN dbo.yb_mzjyxx m ON b.djh = m.djh
WHERE b.FUND_TYPE = 3 AND b.yllb = '12' AND m.fyfs = '0' AND b.gwydybz = 0
ORDER BY b.djh;

-- ── 3.3 无法对账数据取证：djh=675 公疗差异（唯一实质差异）──────────────────
-- 现象：内核按候选资格（gwydybz=0=享受）算出公疗补助 683.99，账面 GFYLBCHBX=0。
-- 分支轨迹：pmed.eligibility=True（gwydybz=0）→ pmed.amount=683.99
--   （公式：公疗=F×(c-a)+max(0, B×d-各基金支付-补助+F×a)，目标比例 c=0.95/d=0.97）。
-- 对照：同资格组其余 4 笔中 609 账面实付 585.00 内核核对一致（公疗公式正向验证通过）；
--   658/676/716 内核算得 0（已有基金支付已达目标，即使享受公疗也不补）与账面一致。
-- 待核查方向：
--   ① 该患者公疗「本人定点医疗机构」关系（门特内核当前缺此前提检查，见设计 §7.5.4）；
--   ② gwydybz 码义签核（候选口径，驳回则该笔回落 PMED_ELIGIBILITY_UNKNOWN）；
--   ③ 是否结算漏付。
SELECT b.djh, b.sfz, b.cblb, b.cjjrdj, b.gwydybz,
       m.zje, m.ybnqfje, m.tczhf, m.degwyzhf, m.bczhf, m.jczhf, m.gfylbchbx
FROM dbo.yb_brdjxx b
JOIN dbo.yb_mzjyxx m ON b.djh = m.djh
WHERE b.djh = '675';

-- djh=675 同人（同 sfz）其它结算：核查其历史是否享受过公疗
SELECT b.djh, b.gwydybz, m.gfylbchbx, m.zje
FROM dbo.yb_brdjxx b
JOIN dbo.yb_mzjyxx m ON b.djh = m.djh
WHERE b.sfz = (SELECT sfz FROM dbo.yb_brdjxx WHERE djh = '675')
ORDER BY b.djh;
