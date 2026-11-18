-- 限制性备注+本单事实核验；只读SELECT，不输出原身份或交易号。
-- 不把诊断关联后的重复费用行加总，不把检查收费当执行。
SELECT f.ItemId, f.ItemCode, f.Fee, f.FeeIn, f.FeeOut, f.SelfPay2,
       d.DiagnoseCode, d.DiagnoseName, d.RecipeDate
FROM dbo.o_FeeItem f JOIN dbo.o_Trade t ON t.T_TradeNo=f.T_TradeNo
JOIN dbo.o_Diagnose d ON d.T_TradeNo=f.T_TradeNo AND d.RecipeNo=f.RecipeNo
WHERE f.ItemCode='XA02BCA084B001010100453'
  AND t.T_TradeDate='2026-04-16T12:31:40';

SELECT e.ItemId, e.ItemCode, e.ItemName, e.Fee, e.FeeIn, e.FeeOut
FROM dbo.o_FeeItem e
WHERE e.ItemCode IN ('XA03AXX007X003010178278','FPB01602','FPS01601')
  AND EXISTS (
    SELECT 1 FROM dbo.o_Trade t WHERE t.T_TradeNo=e.T_TradeNo
      AND t.T_TradeDate='2026-04-17T10:41:45'
      AND EXISTS (SELECT 1 FROM dbo.o_FeeItem f WHERE f.T_TradeNo=t.T_TradeNo
        AND f.ItemCode='XA03AXX007X003010178278' AND f.Fee>0)
  );
