-- SQL Server / bjybdb，只读。Issue #85 特需与目录内甲乙自费复查，2026-11-04。
-- 范围：四条费用分解链路（职工门诊/居民门诊/职工门特/居民门特），与 issue-78 回放口径一致。
-- 目标：目录内甲/乙类药全额医保外行按原单原因分解；排除欠费(4)/住院期间就诊(5)后核实剩余；
--       检查四链路内是否存在特需标记（txbz）或特需门诊交易样本。

-- 1. 门诊链（职工+居民）目录内甲/乙药全额医保外，按链路/原单原因/目录等级分布。
--    目录等级 ypdj：1=甲类（全表 zfbl 均 0）、2=乙类（zfbl 多为 0.1）、3=丙类（zfbl 多为 1）。
--    原因字典取 v_NoRightReason（yb_zdxm.flid=ckrycztbz），禁止套用 k90/k95 同码含义。
SELECT CASE WHEN t.P_FundType=3 THEN N'职工门诊' ELSE N'居民门诊' END chain,
       t.PN_NoRightReason, d.mc AS reason_name, p.ypdj, p.zfbl,
       COUNT_BIG(*) rows_n, SUM(f.Fee) total_fee
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
JOIN dbo.yb_ypzdml p ON p.ypbm=f.ItemCode AND t.T_TradeDate BETWEEN p.sxrq AND p.jzrq
LEFT JOIN dbo.v_NoRightReason d ON d.bm=t.PN_NoRightReason
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.Fee>0 AND f.FeeOut=f.Fee
  AND p.ypdj IN ('1','2')
GROUP BY CASE WHEN t.P_FundType=3 THEN N'职工门诊' ELSE N'居民门诊' END,
         t.PN_NoRightReason, d.mc, p.ypdj, p.zfbl
ORDER BY 1, 7 DESC;

-- 2. 排除欠费/住院期间就诊后的剩余逐行明细。
--    结果应只剩复合值 3^5（非本人定点+住院期间就诊）；展示原始交易号供院内定位，不输出姓名、身份证。
SELECT CONVERT(nvarchar(64),t.T_TradeNo) trade_no, f.ItemId, t.T_TradeDate,
       f.ItemCode, f.ItemName, f.Fee, f.FeeOut, t.PN_NoRightReason,
       p.ypdj, p.zfbl, p.bz
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
JOIN dbo.yb_ypzdml p ON p.ypbm=f.ItemCode AND t.T_TradeDate BETWEEN p.sxrq AND p.jzrq
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.Fee>0 AND f.FeeOut=f.Fee AND p.ypdj IN ('1','2')
  AND (t.PN_NoRightReason IS NULL OR t.PN_NoRightReason NOT IN ('4','5'))
ORDER BY t.T_TradeDate;

-- 3. 门特链（职工+居民）正金额明细的目录匹配与医保外分布。
--    核实门特链是否存在目录内甲/乙全额医保外行，以及未匹配行的项目性质。
SELECT CASE WHEN b.FUND_TYPE='3' THEN N'职工门特' ELSE N'居民门特' END chain,
       CASE WHEN p.ypbm IS NULL THEN N'未匹配药品目录'
            WHEN p.ypdj='1' THEN N'甲类' WHEN p.ypdj='2' THEN N'乙类' ELSE N'丙类' END grade,
       COUNT_BIG(*) rows_n,
       SUM(CASE WHEN f.ybwje=f.zje THEN 1 ELSE 0 END) full_outer,
       SUM(f.zje) fee, SUM(f.ybwje) outer_fee
FROM dbo.yb_brdjxx b
JOIN dbo.yb_mzjyxx s ON s.djh=b.djh
JOIN dbo.yb_mzfymx f ON f.djh=s.djh
LEFT JOIN dbo.yb_ypzdml p ON p.ypbm=f.xmdm AND f.fsrq BETWEEN p.sxrq AND p.jzrq
WHERE b.yllb='12' AND s.fyfs='0' AND b.FUND_TYPE IN ('3','91','92','93')
  AND f.zje>0
GROUP BY CASE WHEN b.FUND_TYPE='3' THEN N'职工门特' ELSE N'居民门特' END,
         CASE WHEN p.ypbm IS NULL THEN N'未匹配药品目录'
              WHEN p.ypdj='1' THEN N'甲类' WHEN p.ypdj='2' THEN N'乙类' ELSE N'丙类' END
ORDER BY 1, 2;

-- 4. 特需标记存在性检查。
-- 4a. 门特链明细 txbz 值分布（门诊 HIS 明细 o_FeeItem 无 txbz 列，无需查询）。
SELECT f.txbz, COUNT_BIG(*) rows_n
FROM dbo.yb_brdjxx b
JOIN dbo.yb_mzjyxx s ON s.djh=b.djh
JOIN dbo.yb_mzfymx f ON f.djh=s.djh
WHERE b.yllb='12' AND s.fyfs='0' AND b.FUND_TYPE IN ('3','91','92','93')
GROUP BY f.txbz;

-- 4b. 特需相关字典条目（flid=053 科室专业含 bm=63 特需门诊；flid=350 含 bm=2 特需医疗部）。
SELECT flid, bm, mc FROM dbo.yb_zdxm WHERE mc LIKE N'%特需%' ORDER BY flid, bm;

-- 4c. 本院险种 3/91/92/93 的特需门诊（T_CureType=63）交易计数。
SELECT COUNT_BIG(*) AS texu_clinic_trades
FROM dbo.o_Trade
WHERE T_HospCode='01110003' AND T_CureType='63'
  AND (P_FundType=3 OR P_FundType IN (91,92,93));

-- 5. 门诊链目录内甲/乙全额医保外逐药汇总（分原因），供分原因解释引用。
SELECT f.ItemName, p.ypdj, t.PN_NoRightReason, COUNT_BIG(*) rows_n, SUM(f.Fee) total_fee
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
JOIN dbo.yb_ypzdml p ON p.ypbm=f.ItemCode AND t.T_TradeDate BETWEEN p.sxrq AND p.jzrq
WHERE t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND f.Fee>0 AND f.FeeOut=f.Fee AND p.ypdj IN ('1','2')
GROUP BY f.ItemName, p.ypdj, t.PN_NoRightReason
ORDER BY 5 DESC;
