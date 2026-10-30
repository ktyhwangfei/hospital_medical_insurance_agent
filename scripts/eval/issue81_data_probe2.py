"""Issue #81 第二轮探查：yb_mzfymx 列结构、特殊病标识、周期表、明细样本。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402


def main() -> int:
    conn = get_semantic_data_source().open_connection("bjybdb")
    cur = conn.cursor()

    def q(label, sql, params=()):
        print(f"== {label} ==")
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        for r in cur.fetchall():
            print("  ", dict(zip(cols, (str(v) for v in r))))

    q("yb_mzfymx 全部列（首行）", "SELECT TOP 1 * FROM dbo.yb_mzfymx")

    q("yb_mzfymx 的 xmlb 分布（居民门特 3 笔）", """
        SELECT f.xmlb, COUNT(*), SUM(f.zje), SUM(f.ybnje), SUM(f.ybwje), SUM(f.grziftw)
        FROM dbo.yb_mzfymx f
        WHERE f.djh IN ('688','690','718')
        GROUP BY f.xmlb ORDER BY 1
    """)

    q("688 明细全量", """
        SELECT f.xh, f.xmdm, f.xmmc, f.xmlb, f.dj, f.sl, f.zje, f.ybnje, f.ybwje, f.grziftw, f.fsrq
        FROM dbo.yb_mzfymx f WHERE f.djh = '688' ORDER BY f.xh
    """)

    q("690 明细全量", """
        SELECT f.xh, f.xmdm, f.xmmc, f.xmlb, f.dj, f.sl, f.zje, f.ybnje, f.ybwje, f.grziftw, f.fsrq
        FROM dbo.yb_mzfymx f WHERE f.djh = '690' ORDER BY f.xh
    """)

    q("718 明细全量", """
        SELECT f.xh, f.xmdm, f.xmmc, f.xmlb, f.dj, f.sl, f.zje, f.ybnje, f.ybwje, f.grziftw, f.fsrq
        FROM dbo.yb_mzfymx f WHERE f.djh = '718' ORDER BY f.xh
    """)

    q("dyxxtsb 688/690/718", """
        SELECT * FROM dbo.yb_dyxxtsb WHERE djh IN ('688','690','718')
    """)

    q("dyxxnd 688/690/718", """
        SELECT * FROM dbo.yb_dyxxnd WHERE djh IN ('688','690','718')
    """)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
