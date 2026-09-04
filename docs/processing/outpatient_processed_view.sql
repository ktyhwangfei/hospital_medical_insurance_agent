-- ============================================================
-- v_op_outpatient_processed  门诊有效结算加工视图（口径句 v4，已签核）
-- 派工单: docs/processing/batch1-view.md（批次一交付物 1）
-- 来源列口径: docs/processing/view-dispatch.md（数据/知识定稿）
-- ============================================================
-- 四字段:
--   1. 门诊有效结算笔数 = COUNT(DISTINCT T_TradeNo)     去重键 trade_no（跨险种同 trade_no 只计 1 笔）
--   2. 门诊总费用        = SUM(T_FeeAll)
--   3. 门诊统筹基金支付   = SUM(T_FundPay)
--   4. 门诊个人支付       = SUM(T_SelfPayAll)
-- 公共外过滤（口径句 v4）:
--   T_State IN (2,3)                        有效结算档（中心端完成/同步）
--   NP_Settle_State = 1                     国家平台已受理（二级确认）
--   T_HasRefundmented != 1                  非已退费
--   T_PartialReturnFlag IS NULL OR = ''     非部分退费红冲
--   T_CureType IN (11,17,18,19) OR IS NULL  门诊档 = MZ_CURE_TYPE 已发布值域
--       [来源: src/semantic_layer/seed.py MZ_CURE_TYPE = {11:普通门诊, 17:门诊挂号,
--        18:急诊挂号, 19:普通急诊}; docs/reviews/2026-08-27-outpatient-data-contract-review.md
--        L1405/L1921 当前 4 个观测代码全覆盖]；NULL=通用门诊规则
--   负金额冲正行由 T_State 正档排除，不在此视图内
CREATE OR ALTER VIEW v_op_outpatient_processed AS
SELECT
  COUNT(DISTINCT tr.T_TradeNo)          AS op_valid_settle_count,
  SUM(tr.T_FeeAll)                      AS op_total_fee,
  SUM(tr.T_FundPay)                     AS op_fund_pay,
  SUM(tr.T_SelfPayAll)                  AS op_self_pay
FROM o_Trade AS tr
WHERE tr.T_State IN (2, 3)
  AND tr.NP_Settle_State = 1
  AND tr.T_HasRefundmented != 1
  AND (tr.T_PartialReturnFlag IS NULL OR tr.T_PartialReturnFlag = '')
  AND (tr.T_CureType IN (11, 17, 18, 19) OR tr.T_CureType IS NULL);  -- 空=通用门诊规则