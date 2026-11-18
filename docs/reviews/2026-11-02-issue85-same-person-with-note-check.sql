-- SQL Server / bjybdb，只读；不输出身份原文。
-- 必须每条参与比较的费用都有费用当日有效、非空的目录备注。
-- 保留全部状态作更宽的初筛；本初筛无变化组，排除退费/无效状态后也不可能新增变化组。
WITH scoped_fees AS (
    SELECT UPPER(LTRIM(RTRIM(t.P_IDNo))) person_key,
           f.ItemCode code,t.T_TradeDate fee_date,
           f.Fee amount,f.FeeOut outer_amount,f.SelfPay2 self_pay2
    FROM dbo.o_Trade t JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
    WHERE t.T_HospCode='01110003'
      AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
      AND NULLIF(LTRIM(RTRIM(t.P_IDNo)),'') IS NOT NULL AND f.Fee>0
    UNION ALL
    SELECT UPPER(LTRIM(RTRIM(b.sfz))),f.xmdm,f.fsrq,f.zje,f.ybwje,f.grziftw
    FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx s ON s.djh=b.djh
    JOIN dbo.yb_mzfymx f ON f.djh=b.djh
    WHERE b.FUND_TYPE IN ('3','91','92','93') AND b.yllb='12' AND s.fyfs='0'
      AND NULLIF(LTRIM(RTRIM(b.sfz)),'') IS NOT NULL AND f.zje>0
), noted_fees AS (
    SELECT f.*
    FROM scoped_fees f JOIN dbo.yb_ypzdml p
      ON p.ypbm=f.code AND f.fee_date BETWEEN p.sxrq AND p.jzrq
    WHERE NULLIF(LTRIM(RTRIM(p.bz)),'') IS NOT NULL
)
SELECT COUNT_BIG(*) note_fee_rows,COUNT(DISTINCT code) drug_codes FROM noted_fees;

WITH scoped_fees AS (
    SELECT UPPER(LTRIM(RTRIM(t.P_IDNo))) person_key,
           f.ItemCode code,t.T_TradeDate fee_date,
           f.Fee amount,f.FeeOut outer_amount,f.SelfPay2 self_pay2
    FROM dbo.o_Trade t JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
    WHERE t.T_HospCode='01110003'
      AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
      AND NULLIF(LTRIM(RTRIM(t.P_IDNo)),'') IS NOT NULL AND f.Fee>0
    UNION ALL
    SELECT UPPER(LTRIM(RTRIM(b.sfz))),f.xmdm,f.fsrq,f.zje,f.ybwje,f.grziftw
    FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx s ON s.djh=b.djh
    JOIN dbo.yb_mzfymx f ON f.djh=b.djh
    WHERE b.FUND_TYPE IN ('3','91','92','93') AND b.yllb='12' AND s.fyfs='0'
      AND NULLIF(LTRIM(RTRIM(b.sfz)),'') IS NOT NULL AND f.zje>0
), noted_fees AS (
    SELECT f.*
    FROM scoped_fees f JOIN dbo.yb_ypzdml p
      ON p.ypbm=f.code AND f.fee_date BETWEEN p.sxrq AND p.jzrq
    WHERE NULLIF(LTRIM(RTRIM(p.bz)),'') IS NOT NULL
)
SELECT COUNT_BIG(*) person_drug_groups,
       SUM(CASE WHEN min_outer_ratio<>max_outer_ratio THEN 1 ELSE 0 END) outer_ratio_change_groups,
       SUM(CASE WHEN min_self2_ratio<>max_self2_ratio THEN 1 ELSE 0 END) self2_ratio_change_groups
FROM (
    SELECT person_key,code,
           MIN(CAST(outer_amount/NULLIF(amount,0) AS decimal(28,12))) min_outer_ratio,
           MAX(CAST(outer_amount/NULLIF(amount,0) AS decimal(28,12))) max_outer_ratio,
           MIN(CAST(self_pay2/NULLIF(amount,0) AS decimal(28,12))) min_self2_ratio,
           MAX(CAST(self_pay2/NULLIF(amount,0) AS decimal(28,12))) max_self2_ratio
    FROM noted_fees
    GROUP BY person_key,code
) matched;
