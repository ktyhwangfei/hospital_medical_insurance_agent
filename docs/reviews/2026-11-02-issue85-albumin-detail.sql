-- 在 SQL Server 的 bjybdb 库执行；全部为只读查询。
-- 1. 两个白蛋白编码的全部明细。不只筛全额医保外，保留10%对照及原始标志。
SELECT
    f.djh AS 登记号,
    f.xh AS 明细序号,
    f.fsrq AS 费用日期,
    f.xmdm AS 项目编码,
    f.xmmc AS 项目名称,
    f.gg AS 规格,
    f.dw AS 单位,
    f.sl AS 数量,
    f.dj AS 单价,
    f.zje AS 项目金额,
    f.ybnje AS 医保内金额,
    f.ybwje AS 医保外金额,
    f.grziftw AS 个人自付二,
    CAST(100.0 * f.ybwje / NULLIF(f.zje, 0) AS decimal(10,2)) AS 医保外占比百分数,
    f.txbz,
    f.SP_SCALE,
    f.MEDIC_L,
    f.FEE_SP_SCALE,
    f.FEE_MEDIC_L,
    p.ypmc AS 目录药品名称,
    p.bzgg AS 目录规格,
    p.ypdj AS 目录等级,
    p.zfbl AS 目录自付比例,
    p.bz AS 限制性备注,
    p.sxrq AS 目录生效日期,
    p.jzrq AS 目录截止日期
FROM dbo.yb_zyfymx f
LEFT JOIN dbo.yb_ypzdml p
    ON p.ypbm = f.xmdm
   AND f.fsrq BETWEEN p.sxrq AND p.jzrq
WHERE f.xmdm IN ('XB05AAR021B001010179250', 'XB05AAR021B001010181789')
ORDER BY f.djh, f.fsrq, f.xh;

-- 2. 对应登记号的入院/出院诊断；此前查询未命中，不代表患者无相应诊断。
SELECT N'入院诊断' AS 来源, d.DJH AS 登记号,
       d.DIAG_TYPE,d.DIAG_CODE,d.DIAG_NAME,d.DIAG_TIME
FROM dbo.yb_NN_InHosp_DiseInfo d
WHERE EXISTS (
    SELECT 1 FROM dbo.yb_zyfymx f
    WHERE f.djh=d.DJH
      AND f.xmdm IN ('XB05AAR021B001010179250','XB05AAR021B001010181789')
)
UNION ALL
SELECT N'出院诊断', d.DJH,d.DIAG_TYPE,d.DIAG_CODE,d.DIAG_NAME,d.DIAG_TIME
FROM dbo.yb_NN_OutHosp_DiseInfo d
WHERE EXISTS (
    SELECT 1 FROM dbo.yb_zyfymx f
    WHERE f.djh=d.DJH
      AND f.xmdm IN ('XB05AAR021B001010179250','XB05AAR021B001010181789')
);

-- 3. 通过登记表身份关联病案首页；不输出姓名、证件号。
-- 此查询仅确认是否存在同身份病案，不自动证明是对应次住院，命中后需再核入院时间。
SELECT m.A_INH_IN_DATETIME,m.A_INH_IN_DIAG_CODE,m.A_INH_IN_DIAG_NAME,
       m.A_INH_OUT_DIAG_MAIN_CODE,m.A_INH_OUT_DIAG_MAIN_NAME,
       m.A_INH_PERIOD_ILL_CRITICAL_CODE,m.A_INH_PERIOD_ILL_EMG_CODE
FROM dbo.yb_ba_main m
WHERE EXISTS (
    SELECT 1 FROM dbo.yb_brdjxx b
    WHERE b.sfz=m.A_ID_NUM
      AND EXISTS (
          SELECT 1 FROM dbo.yb_zyfymx f
          WHERE f.djh=b.djh
            AND f.xmdm IN ('XB05AAR021B001010179250','XB05AAR021B001010181789')
      )
);
