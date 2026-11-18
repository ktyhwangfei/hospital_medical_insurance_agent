-- SQL Server / bjybdb，只读。Issue #85 反向核验数据摸底，2026-11-04。
-- 目标：四链路内"按医保内结算（FeeIn>0/ybnje>0）且当日目录备注非空"的甲/乙药行，
--       评估每类限制条件的可核验性（诊断/同单检查/规格价格/科室医师）。
-- 输出交易号散列化，不输出姓名、身份证；医生名为源库原值（测试库存在占位值，如实保留并标注）。

-- 1. 门诊链受限医保内行：逐行同方诊断/规格/单价/科室/医师。
SELECT t.T_TradeNo, f.ItemId, f.ItemName, f.UnitPrice, f.Count, f.Specification,
       f.Fee, f.FeeIn, f.FeeOut,
       d.DiagnoseCode, d.DiagnoseName, d.MedicalRecord, d.Sectionname, d.DrName, d.DrLevel, d.RecipeType
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
JOIN dbo.yb_ypzdml p ON p.ypbm=f.ItemCode AND t.T_TradeDate BETWEEN p.sxrq AND p.jzrq
LEFT JOIN dbo.o_Diagnose d ON d.T_TradeNo=f.T_TradeNo AND d.RecipeNo=f.RecipeNo
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.Fee>0 AND f.FeeIn>0 AND p.ypdj IN ('1','2')
  AND NULLIF(LTRIM(RTRIM(p.bz)),'') IS NOT NULL
ORDER BY f.ItemName, t.T_TradeDate;

-- 2. 逐药去重的限制备注文本（门诊链，用于限制类型分类）。
SELECT DISTINCT f.ItemCode, f.ItemName, p.ypdj, p.bz
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
JOIN dbo.yb_ypzdml p ON p.ypbm=f.ItemCode AND t.T_TradeDate BETWEEN p.sxrq AND p.jzrq
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.Fee>0 AND f.FeeIn>0 AND p.ypdj IN ('1','2')
  AND NULLIF(LTRIM(RTRIM(p.bz)),'') IS NOT NULL
ORDER BY f.ItemName;

-- 3. 西甲硅油医保内行的同单检查项目计数（用途限制核验样例）。
SELECT f.T_TradeNo, f.ItemId,
       (SELECT COUNT_BIG(*) FROM dbo.o_FeeItem x
        WHERE x.T_TradeNo=f.T_TradeNo AND x.Fee>0
          AND (x.ItemName LIKE N'%胃镜%' OR x.ItemName LIKE N'%肠镜%'
               OR x.ItemName LIKE N'%超声%' OR x.ItemName LIKE N'%CT%'
               OR x.ItemName LIKE N'%腹%影像%' OR x.ItemName LIKE N'%造影%')) AS exam_lines
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.ItemCode='XA03AXX007X003010178278' AND f.Fee>0 AND f.FeeIn>0;

-- 4. 门特链受限医保内行（同口径）。
SELECT f.djh, f.xh, f.xmmc, f.dj, f.gg, f.zje, f.ybnje, f.ybwje, p.bz
FROM dbo.yb_brdjxx b
JOIN dbo.yb_mzjyxx s ON s.djh=b.djh
JOIN dbo.yb_mzfymx f ON f.djh=s.djh
JOIN dbo.yb_ypzdml p ON p.ypbm=f.xmdm AND f.fsrq BETWEEN p.sxrq AND p.jzrq
WHERE b.yllb='12' AND s.fyfs='0' AND b.FUND_TYPE IN ('3','91','92','93')
  AND f.zje>0 AND f.ybnje>0 AND p.ypdj IN ('1','2')
  AND NULLIF(LTRIM(RTRIM(p.bz)),'') IS NOT NULL;
