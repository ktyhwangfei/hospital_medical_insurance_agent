-- SQL Server / bjybdb，只读。与 issue-78 四条费用分解回放的范围一致。
-- 职工门诊：险种3、普通门诊11、本院；居民门诊：91/92/93、本院，医疗类别由内核分流。
-- 门特：yllb=12、fyfs=0；职工503/504肾移植定额为职工门特内的变体，保留并标注。
-- 1. 四链路覆盖结算单计数。覆盖范围包含无效/退费候选，不代表每笔分解成功。
SELECT chain, COUNT_BIG(*) settlement_count
FROM (
    SELECT N'职工门诊' chain, CONVERT(nvarchar(64),t.T_TradeNo) identifier
    FROM dbo.o_Trade t
    WHERE t.P_FundType=3 AND t.T_CureType=11 AND t.T_HospCode='01110003'
    UNION ALL
    SELECT N'居民门诊',CONVERT(nvarchar(64),t.T_TradeNo)
    FROM dbo.o_Trade t
    WHERE t.P_FundType IN (91,92,93) AND t.T_HospCode='01110003'
    UNION ALL
    SELECT CASE WHEN b.FUND_TYPE='3' THEN N'职工门特' ELSE N'居民门特' END,
           CONVERT(nvarchar(64),b.djh)
    FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx s ON s.djh=b.djh
    WHERE b.yllb='12' AND s.fyfs='0' AND b.FUND_TYPE IN ('3','91','92','93')
) scope
GROUP BY chain;

-- 2. 从四链路结算单反查明细，再按费用当日目录匹配，找全额医保外且备注非空的候选。
-- 展示原始交易号/登记号供院内定位，不输出姓名、身份证。
WITH ordinary_scope AS (
    SELECT t.*,
           CASE WHEN t.P_FundType=3 THEN N'职工门诊' ELSE N'居民门诊' END chain
    FROM dbo.o_Trade t
    WHERE t.T_HospCode='01110003'
      AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
), special_scope AS (
    SELECT b.djh,s.jyrq,
           CASE WHEN b.FUND_TYPE='3' THEN N'职工门特' ELSE N'居民门特' END chain
    FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx s ON s.djh=b.djh
    WHERE b.yllb='12' AND s.fyfs='0' AND b.FUND_TYPE IN ('3','91','92','93')
), scoped_fees AS (
    SELECT t.chain,N'o_FeeItem' source,
           CONVERT(nvarchar(64),t.T_TradeNo) identifier,f.ItemId line_id,
           t.T_TradeDate fee_date,f.ItemCode code,f.ItemName item_name,
           f.Fee amount,f.FeeIn inner_amount,f.FeeOut outer_amount,f.SelfPay2 self_pay2,
           t.T_State bill_state,t.T_HasRefundmented refunded
    FROM ordinary_scope t JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
    UNION ALL
    SELECT s.chain,N'yb_mzfymx',CONVERT(nvarchar(64),s.djh),f.xh,
           f.fsrq,f.xmdm,f.xmmc,f.zje,f.ybnje,f.ybwje,f.grziftw,
           NULL,NULL
    FROM special_scope s JOIN dbo.yb_mzfymx f ON f.djh=s.djh
)
SELECT f.*,p.ypmc catalog_name,p.ypdj,p.zfbl,p.bz,p.sxrq,p.jzrq
FROM scoped_fees f
JOIN dbo.yb_ypzdml p
    ON p.ypbm=f.code AND f.fee_date BETWEEN p.sxrq AND p.jzrq
WHERE f.amount>0 AND f.outer_amount=f.amount
  AND NULLIF(LTRIM(RTRIM(p.bz)),'') IS NOT NULL
ORDER BY f.chain,f.code,f.fee_date,f.identifier,f.line_id;

-- 3. 只复查四链路普通门诊范围内，罗沙司他全额医保外行的同处方诊断。
-- 不将此关联结果的金额再次汇总，避免一对多诊断放大费用。
SELECT CASE WHEN t.P_FundType=3 THEN N'职工门诊' ELSE N'居民门诊' END chain,
       f.T_TradeNo,f.ItemId,f.RecipeNo,t.T_TradeDate,
       f.Fee,f.FeeIn,f.FeeOut,t.T_State,t.T_HasRefundmented,
       d.DiagnoseCode,d.DiagnoseName,d.MedicalRecord
FROM dbo.o_Trade t JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
LEFT JOIN dbo.o_Diagnose d ON d.T_TradeNo=f.T_TradeNo AND d.RecipeNo=f.RecipeNo
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.ItemCode='XB03XAL373E001010180523'
  AND f.Fee>0 AND f.FeeOut=f.Fee
ORDER BY t.T_TradeDate,f.T_TradeNo,f.ItemId;
