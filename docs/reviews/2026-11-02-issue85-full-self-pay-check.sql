-- Issue #85，只读复查；不输出姓名、证件号、原始结算单号。
-- “全自费候选”按全额医保外筛选，不按基金支付为零筛选。
SELECT f.ItemCode, COUNT_BIG(*) full_outer_rows,
       SUM(CASE WHEN t.T_State=4 AND t.T_HasRefundmented=0 THEN 1 ELSE 0 END) state4_no_refund_rows
FROM dbo.o_FeeItem f
JOIN dbo.o_Trade t ON t.T_TradeNo=f.T_TradeNo
WHERE f.ItemCode='XB03XAL373E001010180523' AND f.Fee>0 AND f.FeeOut=f.Fee
GROUP BY f.ItemCode;

-- 必须同交易、同处方；本库命中的是占位值，不能用其证明条件不满足。
SELECT d.DiagnoseCode,d.DiagnoseName,
       CASE WHEN LTRIM(RTRIM(CONVERT(nvarchar(max),d.MedicalRecord)))='1' THEN 'literal_1' ELSE 'other' END record_profile,
       COUNT_BIG(*) linked_rows
FROM dbo.o_FeeItem f
LEFT JOIN dbo.o_Diagnose d ON f.T_TradeNo=d.T_TradeNo AND f.RecipeNo=d.RecipeNo
WHERE f.ItemCode='XB03XAL373E001010180523'
GROUP BY d.DiagnoseCode,d.DiagnoseName,
         CASE WHEN LTRIM(RTRIM(CONVERT(nvarchar(max),d.MedicalRecord)))='1' THEN 'literal_1' ELSE 'other' END;

SELECT f.xmdm, COUNT_BIG(*) full_outer_rows, SUM(f.zje) full_outer_amount
FROM dbo.yb_zyfymx f
WHERE f.xmdm IN ('XC05BAD165F002010180481','XB05AAR021B001010179250')
  AND f.zje>0 AND f.ybwje=f.zje
GROUP BY f.xmdm;

-- 指定医院冲突与丙类/自付1同时存在，不能作为文字备注的新增归因正例。
SELECT DISTINCT f.ItemCode,t.T_HospCode,h.yymc,p.ypdj,p.zfbl,p.bz
FROM dbo.o_FeeItem f
JOIN dbo.o_Trade t ON t.T_TradeNo=f.T_TradeNo
LEFT JOIN dbo.yb_yyzd h ON h.yydm=t.T_HospCode
JOIN dbo.yb_ypzdml p ON p.ypbm=f.ItemCode AND t.T_TradeDate BETWEEN p.sxrq AND p.jzrq
WHERE f.ItemCode='J110101029290029' AND f.Fee>0 AND f.FeeOut=f.Fee;
