-- 单单样例复查，仅SELECT；不输出患者身份和原交易号。
SELECT f.ItemId, f.ItemCode, f.ItemName, f.[Count], f.UnitPrice,
       f.Fee, f.FeeIn, f.FeeOut, t.T_TradeDate,
       CASE WHEN f.FeeIn = f.[Count] *
         CASE WHEN f.UnitPrice < 1835 THEN f.UnitPrice ELSE 1835 END
       THEN 1 ELSE 0 END AS cap_matches
FROM dbo.o_FeeItem f JOIN dbo.o_Trade t ON f.T_TradeNo = t.T_TradeNo
WHERE f.ItemCode = 'C08010415101001'
  AND t.T_TradeDate = '2024-04-08T14:33:49';

SELECT f.ItemId, f.ItemCode, f.Fee, f.FeeIn, f.FeeOut, t.T_TradeDate,
       CASE WHEN f.FeeIn = CASE WHEN f.Fee * 0.5 < 10000
         THEN f.Fee * 0.5 ELSE 10000 END
       THEN 1 ELSE 0 END AS conditional_cap_matches
FROM dbo.o_FeeItem f JOIN dbo.o_Trade t ON f.T_TradeNo = t.T_TradeNo
WHERE f.ItemCode = 'w0503140015yz'
  AND t.T_TradeDate = '2024-03-11T10:25:58';

SELECT xmbm, xmmc, sxrq, jzrq, bz, zfbl, xb, dw
FROM dbo.yb_ybzlfwxm
WHERE xmbm IN ('C08010415101001', 'w0503140015yz');
