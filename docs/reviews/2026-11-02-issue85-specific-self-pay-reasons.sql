-- SQL Server / bjybdb，只读。仍限定四链路中的职工/居民门诊范围。
-- 1. 原库“医保未结算原因”字典；不能套用k90/k95的同码含义。
SELECT bm,mc FROM dbo.v_NoRightReason ORDER BY bm;

-- 2. 罗沙司他全额医保外：同时查看整单金额、未结算原因与其他明细的处理。
-- 整单有原因码、全单医保外，不等于已证明药品限制不满足；两类条件独立核验。
SELECT t.T_TradeNo,f.ItemId,t.T_TradeDate,t.P_FundType,t.T_CureType,
       f.ItemCode,f.ItemName,f.Fee,f.FeeIn,f.FeeOut,f.SelfPay2,
       t.PN_NoRightReason,d.mc AS single_reason_name,
       t.NT_AllSelfPayFlag,t.T_State,t.T_HasRefundmented,
       t.T_FeeAll,t.T_FeeIn,t.T_FeeOut,t.T_FundPay,
       (SELECT COUNT_BIG(*) FROM dbo.o_FeeItem x
        WHERE x.T_TradeNo=t.T_TradeNo AND x.Fee>0) AS positive_lines,
       (SELECT COUNT_BIG(*) FROM dbo.o_FeeItem x
        WHERE x.T_TradeNo=t.T_TradeNo AND x.Fee>0 AND x.FeeOut=x.Fee) AS full_outer_lines
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
LEFT JOIN dbo.v_NoRightReason d ON d.bm=t.PN_NoRightReason
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.ItemCode='XB03XAL373E001010180523'
  AND f.Fee>0 AND f.FeeOut=f.Fee
ORDER BY t.T_TradeDate,f.T_TradeNo,f.ItemId;

-- 3. 复查状态4且未退的候选数；不是最终医保业务认证。
-- 3^5为源字段原始复合值，字典3、5分别解释，不擅自规定两者优先级或排他性。
SELECT t.PN_NoRightReason,COUNT_BIG(*) candidate_rows
FROM dbo.o_Trade t JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.ItemCode='XB03XAL373E001010180523'
  AND f.Fee>0 AND f.FeeOut=f.Fee
  AND t.T_State=4 AND t.T_HasRefundmented=0
GROUP BY t.PN_NoRightReason;
