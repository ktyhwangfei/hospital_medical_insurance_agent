-- SQL Server / bjybdb，只读。
-- 本候选已撤回：2024用药时有效目录备注为空，不符合“必须有项目内涵”的要求。
-- 四链路内，按同一非空身份证匹配普通门诊与门特，再核同药品编码。
-- 身份证和姓名仅用于关联/一致性标志，不输出原文；结算定位号供院内核对。
-- 候选：注射用培美曲塞二钠 XL01BAP030B001010178396。
-- 不要求备注非空，不预设自费原因，不用退费负数制造比例变化。
SELECT
    t.T_TradeNo AS ordinary_trade_no,
    f.ItemId AS ordinary_line_id,
    t.T_TradeDate AS ordinary_date,
    t.P_FundType AS ordinary_fund,
    t.T_CureType AS ordinary_cure_type,
    t.T_State,t.T_HasRefundmented,t.PN_NoRightReason,
    f.ItemCode,f.ItemName,
    f.Specification AS ordinary_spec,f.Unit AS ordinary_unit,
    f.[Count] AS ordinary_qty,f.UnitPrice AS ordinary_price,
    f.Fee AS ordinary_amount,f.FeeIn AS ordinary_inner,
    f.FeeOut AS ordinary_outer,f.SelfPay2 AS ordinary_self_pay2,
    CAST(100.0*f.FeeOut/NULLIF(f.Fee,0) AS decimal(10,2)) AS ordinary_outer_pct,
    b.djh AS special_registration_id,g.xh AS special_line_id,
    g.fsrq AS special_fee_date,s.jyrq AS special_settlement_date,
    b.FUND_TYPE AS special_fund,b.yllb AS special_care_type,s.fyfs,
    b.tsb1,b.tsb2,b.tsb3,
    g.gg AS special_spec,g.dw AS special_unit,g.sl AS special_qty,g.dj AS special_price,
    g.zje AS special_amount,g.ybnje AS special_inner,
    g.ybwje AS special_outer,g.grziftw AS special_self_pay2,
    CAST(100.0*g.ybwje/NULLIF(g.zje,0) AS decimal(10,2)) AS special_outer_pct,
    CASE WHEN t.P_IDNo=b.sfz THEN 1 ELSE 0 END AS exact_identity_match,
    CASE WHEN t.P_Name=b.xm THEN 1 ELSE 0 END AS name_match,
    CASE WHEN CONVERT(date,t.P_Birthday)=CONVERT(date,b.csrq) THEN 1 ELSE 0 END AS birth_date_match
FROM dbo.o_Trade t
JOIN dbo.o_FeeItem f ON f.T_TradeNo=t.T_TradeNo
JOIN dbo.yb_brdjxx b
    ON UPPER(LTRIM(RTRIM(b.sfz)))=UPPER(LTRIM(RTRIM(t.P_IDNo)))
JOIN dbo.yb_mzjyxx s ON s.djh=b.djh
JOIN dbo.yb_mzfymx g ON g.djh=b.djh AND g.xmdm=f.ItemCode
WHERE NULLIF(LTRIM(RTRIM(t.P_IDNo)),'') IS NOT NULL
  AND NULLIF(LTRIM(RTRIM(b.sfz)),'') IS NOT NULL
  AND t.T_HospCode='01110003'
  AND ((t.P_FundType=3 AND t.T_CureType=11) OR t.P_FundType IN (91,92,93))
  AND b.FUND_TYPE IN ('3','91','92','93') AND b.yllb='12' AND s.fyfs='0'
  AND t.T_State=4 AND t.T_HasRefundmented=0
  AND f.ItemCode='XL01BAP030B001010178396'
  AND f.Fee>0 AND g.zje>0
  AND f.FeeOut*g.zje<>g.ybwje*f.Fee
ORDER BY t.T_TradeDate,t.T_TradeNo,f.ItemId,g.fsrq,g.xh;

-- 目录全版本原文；不能用2023-02-28以前的备注覆盖2024年的空备注版本。
SELECT ypbm,ypmc,bzgg,jldw,sflb,ypdj,zfbl,bz,sxrq,jzrq
FROM dbo.yb_ypzdml
WHERE ypbm='XL01BAP030B001010178396'
ORDER BY sxrq;
