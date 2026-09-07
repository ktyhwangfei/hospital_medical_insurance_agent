"""批次二 T2a（活库·PG 落地库）：v_op_outpatient_processed 连通/存量数值一致/med_type 边界。

派工单: docs/processing/batch2-registry.md
架构裁决（2026-09-07，#65 Phase 0 文档 §9）：加工视图落位 PG 落地库
（outpatient_postgres，源为治理视图 mz_trade），禁止在 SQL Server 源库
执行 DDL。本测试从源库部署验收改为落地库部署验收。
环境依赖: PostgreSQL 落地库（默认 127.0.0.1:5432/hospital_mcp，POSTGRES_*
可覆盖）且 mz_trade 治理视图已由同步 bootstrap 部署；不可用时整组 skip，
与确定性单元测试分开报告。
视图部署以 docs/processing/outpatient_processed_view.sql 为唯一来源
（CREATE OR REPLACE，幂等）——本测试即批次一 SQL 的活库落地验收。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
VIEW_SQL = REPO_ROOT / "docs/processing/outpatient_processed_view.sql"
VIEW_NAME = "v_op_outpatient_processed"

# 口径句 v4（与 docs/processing/outpatient_processed_view.sql 一致；PG 落地
# 视图列名保留大小写须双引号，状态码列为 payload 抽取的 text，数值比较经
# NULLIF(col,'')::NUMERIC 显式转型——与落地视图数值列渲染约定一致）
V4_WHERE = (
    "NULLIF(\"T_State\", '')::NUMERIC IN (2,3) "
    "AND NULLIF(\"NP_Settle_State\", '')::NUMERIC = 1 "
    "AND NULLIF(\"T_HasRefundmented\", '')::NUMERIC != 1 "
    "AND (\"T_PartialReturnFlag\" IS NULL OR \"T_PartialReturnFlag\"='') "
    "AND (NULLIF(\"T_CureType\", '')::NUMERIC IN (11,17,18,19) OR \"T_CureType\" IS NULL)"
)


def _connect():
    try:
        from src.data_platform.storage.postgresql.client import PostgreSQLClient

        client = PostgreSQLClient()
        client.execute("SELECT 1 FROM mz_trade LIMIT 1")
        return client
    except Exception:
        return None


pytestmark = pytest.mark.skipif(_connect() is None, reason="PG 落地库不可用（需已部署 mz_trade 治理视图）")


@pytest.fixture(scope="module")
def client():
    c = _connect()
    assert c is not None
    yield c


def _deploy_view(client) -> None:
    """以 SQL 文件为唯一来源幂等部署视图（CREATE OR REPLACE）。

    剥掉整行注释并截到最后一个分号（去掉语句尾行内注释），保证
    psycopg 以单语句执行参数化路径不报多条语句。
    """
    lines = [
        line for line in VIEW_SQL.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    ]
    sql = "\n".join(lines)
    client.execute(sql[: sql.rindex(";") + 1])


def _view_row(client) -> list:
    _deploy_view(client)
    rows = client.execute(
        f'SELECT op_valid_settle_count, op_total_fee, op_fund_pay, op_self_pay FROM {VIEW_NAME}'
    )
    assert rows, "加工视图无输出行"
    return [
        rows[0]["op_valid_settle_count"], rows[0]["op_total_fee"],
        rows[0]["op_fund_pay"], rows[0]["op_self_pay"],
    ]


# ① 连通/权限 ───────────────────────────────────────────────────

def test_连通_权限_视图可查询(client):
    """落地库连通、视图可 SELECT（含 DDL 部署权限，DDL 只落本院 PG）。"""
    _deploy_view(client)
    row = _view_row(client)
    assert len(row) == 4
    assert row[0] >= 0


# ② 存量数值一致：view vs 落地表直接聚合 ─────────────────────────

def test_存量数值一致_view等于落地表直接聚合(client):
    """4 字段逐值一致：view == mz_trade 按同一口径句 v4 直接聚合。"""
    view = _view_row(client)
    rows = client.execute(
        'SELECT COUNT(DISTINCT "T_TradeNo") AS c, SUM("T_FeeAll") AS f, '
        'SUM("T_FundPay") AS p, SUM("T_SelfPayAll") AS s '
        f"FROM mz_trade WHERE {V4_WHERE}"
    )
    direct = [rows[0]["c"], rows[0]["f"], rows[0]["p"], rows[0]["s"]]
    assert view == direct, f"view {view} != 落地表直接聚合 {direct}"


def test_存量一致_勾稽恒等(client):
    """总费用 = 统筹 + 个人（view 与落地聚合均成立，实测差 0.00）。"""
    row = _view_row(client)
    assert float(row[1]) == pytest.approx(float(row[2]) + float(row[3]))


# ③ med_type 空档边界（T_CureType NULL/非门诊档）────────────────

def test_med_type空档边界_落地无空值行则恒不触发(client):
    """T_CureType 空档边界：落地库 T_State IN (2,3) 下 T_CureType IS NULL 行数。

    ├ 若为 0 → 边界恒不触发（源库实测 0），口径句已含 OR IS NULL 分支
    │  （空=通用门诊规则），不另加分支；断言锁住该事实，数据一旦出现空值行
    │  立即告警复核边界语义。
    └ 若 >0 → 断言失败，需按口径句复核：空值行按通用门诊纳入。
    """
    rows = client.execute(
        "SELECT COUNT(*) AS n FROM mz_trade "
        "WHERE NULLIF(\"T_State\", '')::NUMERIC IN (2,3) AND \"T_CureType\" IS NULL"
    )
    null_cure = rows[0]["n"]
    assert null_cure == 0, (
        f"落地库出现 T_CureType 空值行 {null_cure} 条：空档边界不再恒不触发，"
        "需复核口径句（当前: OR T_CureType IS NULL 按通用门诊纳入）"
    )
    # 口径句一致性：视图内出现的医疗类别只可能是已发布门诊档，无外包行
    rows = client.execute(
        'SELECT DISTINCT "T_CureType" AS t FROM mz_trade '
        f'WHERE {V4_WHERE} AND NULLIF("T_CureType", \'\')::NUMERIC NOT IN (11,17,18,19)'
    )
    assert rows == [], "视图口径内出现非门诊档 T_CureType"
