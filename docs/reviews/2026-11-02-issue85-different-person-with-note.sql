-- SQL Server / bjybdb，只读。
-- 四链路中的职工普通门诊；同药品编码、同数量、同单价、同单位，患者可不同。
-- 只保留状态4且未退，费用当日有有效非空项目内涵。
-- 匿名序号仅表示当前结果内的不同身份证，不输出姓名、身份证原文。
SELECT
    DENSE_RANK() OVER (ORDER BY UPPER(LTRIM(RTRIM(t.P_IDNo)))) AS anonymous_person_no,
    t.T_TradeNo,f.ItemId,t.T_TradeDate,
    t.P_FundType,t.PN_PersonType,t.T_CureType,
    f.ItemCode,f.ItemName,f.Specification,f.Unit,f.[Count],f.UnitPrice,
    f.Fee,f.FeeIn,f.FeeOut,f.SelfPay2,f.MEDIC_L,
    CAST(100.0*f.FeeOut/NULLIF(f.Fee,0) AS decimal(10,2)) AS outer_pct,
    t.PN_NoRightReason,d.mc AS recorded_reason,
    t.T_State,t.T_HasRefundmented,
    t.T_FeeAll,t.T_FeeIn,t.T_FeeOut,t.T_FundPay,
    p.ypmc AS catalog_name,p.bzgg,p.zfbl,p.bz,p.sxrq,p.jzrq
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
JOIN dbo.yb_ypzdml p
    ON p.ypbm=f.ItemCode AND t.T_TradeDate BETWEEN p.sxrq AND p.jzrq
LEFT JOIN dbo.v_NoRightReason d ON d.bm=t.PN_NoRightReason
WHERE t.T_HospCode='01110003'
  AND t.P_FundType=3 AND t.T_CureType=11
  AND t.T_State=4 AND t.T_HasRefundmented=0
  AND NULLIF(LTRIM(RTRIM(t.P_IDNo)),'') IS NOT NULL
  AND f.ItemCode='XB03XAL373E001010180523'
  AND f.Fee>0 AND f.UnitPrice=5 AND f.[Count]=5
  AND NULLIF(LTRIM(RTRIM(p.bz)),'') IS NOT NULL
ORDER BY t.T_TradeDate,t.T_TradeNo,f.ItemId;

-- 同处方诊断独立列出，不与上面金额再次汇总，避免一对多诊断放大金额。
SELECT t.T_TradeNo,f.ItemId,d.DiagnoseCode,d.DiagnoseName,d.MedicalRecord
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
LEFT JOIN dbo.o_Diagnose d ON d.T_TradeNo=f.T_TradeNo AND d.RecipeNo=f.RecipeNo
WHERE t.T_HospCode='01110003'
  AND t.P_FundType=3 AND t.T_CureType=11
  AND t.T_State=4 AND t.T_HasRefundmented=0
  AND f.ItemCode='XB03XAL373E001010180523'
  AND f.Fee>0 AND f.UnitPrice=5 AND f.[Count]=5
ORDER BY t.T_TradeNo,f.ItemId;
