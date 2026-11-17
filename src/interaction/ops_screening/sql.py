"""bjyb 上的只读语句。用户输入只进参数，不拼进 SQL。

口径与内存读取必须一致：最新成功批次、指定类型、主疑点（primary_finding_id = finding_id）。
核实结论只更新 verify_status 一列。
"""

from __future__ import annotations

# 科室取诊断上的科室名。同一结算多条诊断时只取一条，避免金额被连接乘大。
_DEPARTMENT_APPLY = """
OUTER APPLY (
    SELECT TOP 1
        COALESCE(NULLIF(d.HISSectionName, N''), NULLIF(d.Sectionname, N''), N'未关联科室') AS dept_name
    FROM dbo.o_Diagnose AS d
    WHERE d.T_TradeNo = f.settlement_key
    ORDER BY CASE WHEN d.DiagnoseType IN (N'1', N'主诊断') THEN 0 ELSE 1 END,
             d.DiagnoseNo, d.RecipeNo
) AS dept
""".strip()

# 费用行按费用行号对上，只取一行。金额仍以疑点表 amount 为准。
_FEE_APPLY = """
OUTER APPLY (
    SELECT TOP 1 fi.ItemName AS fee_item_name, fi.Fee AS fee_amount, fi.ItemCode AS fee_item_code
    FROM dbo.o_FeeItem AS fi
    WHERE fi.T_TradeNo = f.settlement_key
      AND (
            CONVERT(nvarchar(64), fi.ItemId) = f.fee_line_id
            OR CONVERT(nvarchar(64), fi.ItemNo) = f.fee_line_id
          )
    ORDER BY CASE WHEN CONVERT(nvarchar(64), fi.ItemId) = f.fee_line_id THEN 0 ELSE 1 END,
             fi.ItemNo
) AS fee
""".strip()


def latest_run_sql(*, bounded: bool) -> tuple[str, list[str]]:
    """返回语句和占位符名顺序。调用方按这个顺序填参数。"""
    where = "WHERE status = ?"
    names = ["status"]
    if bounded:
        where += " AND time_range_start <= ? AND time_range_end >= ?"
        names.extend(["asked_end", "asked_start"])
    sql = f"""
        SELECT TOP 1 run_id, started_at, finished_at, time_range_start, time_range_end
        FROM dbo.ai_screen_run
        {where}
        ORDER BY COALESCE(finished_at, started_at) DESC, run_id DESC
    """.strip()
    return sql, names


def findings_sql() -> str:
    return f"""
        SELECT
            f.finding_id, f.primary_finding_id, f.run_id, f.rule_id,
            f.settlement_key, f.fee_line_id, f.item_code, f.item_name, f.amount,
            f.finding_type, f.evidence_clause, f.evidence_facts, f.verify_status,
            COALESCE(NULLIF(r.title, N''), N'未命名规则') AS rule_title,
            COALESCE(r.source_clause, N'') AS source_clause,
            COALESCE(dept.dept_name, N'未关联科室') AS department_name,
            COALESCE(fee.fee_item_name, N'') AS fee_item_name,
            fee.fee_amount AS fee_amount,
            COALESCE(fee.fee_item_code, N'') AS fee_item_code
        FROM dbo.ai_screen_finding AS f
        LEFT JOIN dbo.ai_screen_rule AS r ON r.rule_id = f.rule_id
        {_DEPARTMENT_APPLY}
        {_FEE_APPLY}
        WHERE f.run_id = ?
          AND f.finding_type = ?
          AND f.primary_finding_id = f.finding_id
    """.strip()


def verify_sql() -> str:
    """只改核实结论。不改规则、不改金额、不改类型。

    OUTPUT 把受影响的疑点编号作为结果集返回。SQL Server 的 ODBC
    rowcount 可能是 -1，不能靠它判断有没有写上。
    """
    return """
        UPDATE dbo.ai_screen_finding
        SET verify_status = ?
        OUTPUT inserted.finding_id
        WHERE finding_id = ?
    """.strip()
