"""批次二 T2a（活库）：v_op_outpatient_processed 连通/权限/存量数值一致/med_type 边界。

派工单: docs/processing/batch2-registry.md
环境依赖: SQL Server 门诊源（o_Trade），经 MSSQL_* 环境变量注入（建立连接即认为
连通+权限可用）；不可用时整组 skip，与确定性单元测试分开报告。
视图部署以 docs/processing/outpatient_processed_view.sql 为唯一来源（CREATE OR
ALTER，幂等）——本测试即批次一 SQL 的活库落地验收。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
VIEW_SQL = REPO_ROOT / "docs/processing/outpatient_processed_view.sql"
VIEW_NAME = "v_op_outpatient_processed"

# 口径句 v4（与 docs/processing/outpatient_processed_view.sql 一致）
V4_WHERE = (
    "T_State IN (2,3) AND NP_Settle_State=1 AND T_HasRefundmented != 1 "
    "AND (T_PartialReturnFlag IS NULL OR T_PartialReturnFlag='') "
    "AND (T_CureType IN (11,17,18,19) OR T_CureType IS NULL)"
)


def _conn_str() -> str | None:
    host = os.getenv("MSSQL_HOST")
    db = os.getenv("MSSQL_DATABASE")
    user = os.getenv("MSSQL_USER")
    pwd = os.getenv("MSSQL_PASSWORD")
    if not all([host, db, user]):  # 密码允许为空（sa 空口令），缺配置视为不可用
        return None
    driver = os.getenv("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server")
    port = os.getenv("MSSQL_PORT", "1433")
    return (
        f"DRIVER={{{driver}}};SERVER={host},{port};DATABASE={db};"
        f"UID={user};PWD={pwd};Connection Timeout=8"
    )


def _db_ready() -> bool:
    cs = _conn_str()
    if not cs:
        return False
    try:
        import pyodbc
        with pyodbc.connect(cs, autocommit=True) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM o_Trade")
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="SQL Server 门诊活库不可用（需 MSSQL_* 环境）")


@pytest.fixture(scope="module")
def conn():
    import pyodbc
    cs = _conn_str()
    assert cs is not None
    with pyodbc.connect(cs, autocommit=True) as c:
        yield c


def _deploy_view(conn) -> None:
    """以 SQL 文件为唯一来源幂等部署视图（CREATE OR ALTER）。"""
    sql = "\n".join(
        line for line in VIEW_SQL.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("```")
    )
    conn.cursor().execute(sql)


def _view_row(conn) -> tuple:
    _deploy_view(conn)
    cur = conn.cursor()
    cur.execute(f"SELECT op_valid_settle_count, op_total_fee, op_fund_pay, op_self_pay FROM {VIEW_NAME}")
    return tuple(cur.fetchone())


# ① 连通/权限 ───────────────────────────────────────────────────

def test_连通_权限_视图可查询(conn):
    """活库连通、视图可 SELECT（含 DDL 部署权限）。"""
    _deploy_view(conn)
    row = _view_row(conn)
    assert len(row) == 4
    assert row[0] >= 0


# ② 存量数值一致：view vs 源直接聚合 ────────────────────────────

def test_存量数值一致_view等于源直接聚合(conn):
    """4 字段逐值一致：view == 源表按同一口径句 v4 直接聚合。"""
    view = _view_row(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(DISTINCT T_TradeNo), SUM(T_FeeAll), SUM(T_FundPay), SUM(T_SelfPayAll) "
        f"FROM o_Trade WHERE {V4_WHERE}"
    )
    direct = tuple(cur.fetchone())
    assert view == direct, f"view {view} != 源直接聚合 {direct}"


def test_存量一致_勾稽恒等(conn):
    """总费用 = 统筹 + 个人（view 与源聚合均成立，实测差 0.00）。"""
    row = _view_row(conn)
    assert float(row[1]) == pytest.approx(float(row[2]) + float(row[3]))


# ③ med_type 空档边界（T_CureType NULL/非门诊档）────────────────

def test_med_type空档边界_源无空值行则恒不触发(conn):
    """T_CureType 空档边界：源库 T_State IN (2,3) 下 T_CureType IS NULL 行数。

    ├ 若为 0 → 边界恒不触发（当前实测 0），口径句已含 OR IS NULL 分支
    │  （空=通用门诊规则），不另加分支；断言锁住该事实，源一旦出现空值行
    │  立即告警复核边界语义。
    └ 若 >0 → 断言失败，需按口径句复核：空值行按通用门诊纳入。
    """
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM o_Trade WHERE T_State IN (2,3) AND T_CureType IS NULL")
    null_cure = cur.fetchone()[0]
    assert null_cure == 0, (
        f"源出现 T_CureType 空值行 {null_cure} 条：空档边界不再恒不触发，"
        "需复核口径句（当前: OR T_CureType IS NULL 按通用门诊纳入）"
    )
    # 口径句一致性：视图内出现的医疗类别只可能是已发布门诊档，无外包行
    cur.execute(
        "SELECT DISTINCT T_CureType FROM o_Trade "
        f"WHERE {V4_WHERE} AND T_CureType NOT IN (11,17,18,19)"
    )
    assert cur.fetchall() == [], "视图口径内出现非门诊档 T_CureType"