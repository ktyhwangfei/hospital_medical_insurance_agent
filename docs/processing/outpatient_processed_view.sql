-- ============================================================
-- v_op_outpatient_processed  门诊有效结算加工视图（口径句 v4，已签核）
-- 派工单: docs/processing/batch1-view.md（批次一交付物 1）
-- 来源列口径: docs/processing/view-dispatch.md（数据/知识定稿）
-- 架构裁决（2026-09-07，Phase 0 文档 §9）：加工落位 PG 落地库
--   （outpatient_postgres），源为治理视图 mz_trade（同步落地 dbo.o_Trade，
--   已排除删除行与质量拦截行）；禁止在 SQL Server 源库执行任何 DDL。
--   方言随裁决切换为 PostgreSQL：CREATE OR REPLACE VIEW，标识符双引号
--   （mz_trade 列名保留大小写，裸引用会被 PG 折叠小写而找不到列）。
--   口径句 v4 语义与签核原文一致，签核继续有效。
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
--   （状态码列 T_State/NP_Settle_State/T_HasRefundmented/T_CureType 在落地视图
--    仍为 text（payload 抽取）；口径句数值比较经 NULLIF(col,'')::NUMERIC 显式
--    转型执行，与落地视图数值列的渲染约定一致。列类型数值化需 DROP VIEW
--    重建（PG 的 CREATE OR REPLACE 不支持改列类型），留待 Phase 3 迁移。）
CREATE OR REPLACE VIEW v_op_outpatient_processed AS
SELECT
  COUNT(DISTINCT tr."T_TradeNo")        AS op_valid_settle_count,
  SUM(tr."T_FeeAll")                    AS op_total_fee,
  SUM(tr."T_FundPay")                   AS op_fund_pay,
  SUM(tr."T_SelfPayAll")                AS op_self_pay
FROM mz_trade AS tr
WHERE NULLIF(tr."T_State", '')::NUMERIC IN (2, 3)
  AND NULLIF(tr."NP_Settle_State", '')::NUMERIC = 1
  AND NULLIF(tr."T_HasRefundmented", '')::NUMERIC != 1
  AND (tr."T_PartialReturnFlag" IS NULL OR tr."T_PartialReturnFlag" = '')
  AND (NULLIF(tr."T_CureType", '')::NUMERIC IN (11, 17, 18, 19) OR tr."T_CureType" IS NULL);  -- 空=通用门诊规则
