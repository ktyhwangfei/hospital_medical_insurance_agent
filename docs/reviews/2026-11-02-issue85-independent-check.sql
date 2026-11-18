-- Issue #85 独立复查。仅 SELECT，不输出患者身份或原始登记号。
-- 通过现有只读 bjybdb 连接执行；结果仅用于重建事实，不能证明医保决定原因。

SELECT xmdm, txbz, SP_SCALE, COUNT_BIG(*) AS fee_rows,
       SUM(zje) AS total_amount, SUM(ybnje) AS inner_amount,
       SUM(ybwje) AS outer_amount,
       SUM(CASE WHEN ybwje = zje * SP_SCALE THEN 1 ELSE 0 END) AS arithmetic_matches
FROM dbo.yb_zyfymx
WHERE xmdm IN ('XB05AAR021B001010179250', 'XB05AAR021B001010181789')
GROUP BY xmdm, txbz, SP_SCALE;

SELECT ypbm, sxrq, jzrq, bz, zfbl, ypdj, bzgg, jldw
FROM dbo.yb_ypzdml
WHERE ypbm IN ('XB05AAR021B001010179250', 'XB05AAR021B001010181789')
ORDER BY ypbm, sxrq;

SELECT COUNT_BIG(*) AS rows_with_input_output
FROM dbo.yb_Log_InterfaceRecord;

SELECT d.DiagnoseCode, d.DiagnoseName,
       COUNT_BIG(*) AS linked_rows,
       SUM(CASE WHEN f.RecipeNo = d.RecipeNo THEN 1 ELSE 0 END) AS same_recipe_rows
FROM dbo.o_FeeItem f
JOIN dbo.o_Diagnose d ON f.T_TradeNo = d.T_TradeNo
WHERE f.ItemCode = 'XA02BCA084B001010100453'
GROUP BY d.DiagnoseCode, d.DiagnoseName;
