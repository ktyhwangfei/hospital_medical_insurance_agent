"""Issue #81 城乡居民门特费用分解：bjyb 库数据探查（只读）。

探查问题：
1. 居民门特登记与结算量（yb_brdjxx FUND_TYPE∈91/92/93，yllb=16 住院套表 / yllb=12 门诊套表）
2. 两套表的费用方式（fyfs）分布
3. 人员类别（cblb）分布
4. 账面勾稽闭合性（zje/ybn/ybw/tczhf/tczif/degwyzhf/degwyzif/xjzf/zhzf）
5. 周期上下文证据（yb_dyxxtsb/dyxxnd 维护情况）
6. 军残/公疗资格候选列（cjjrdj/gwydybz）分布
"""

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
        for r in cur.fetchall():
            print("  ", r)

    q("居民登记套表分布（FUND_TYPE×yllb）", """
        SELECT FUND_TYPE, yllb, COUNT(*) FROM dbo.yb_brdjxx
        WHERE FUND_TYPE IN (91, 92, 93)
        GROUP BY FUND_TYPE, yllb ORDER BY 1, 2
    """)

    q("居民门特 zy 套表（yllb=16）结算", """
        SELECT COUNT(*), MIN(s.jyrq), MAX(s.jyrq)
        FROM dbo.yb_brdjxx b JOIN dbo.yb_zyjyxx s ON s.djh = b.djh
        WHERE b.FUND_TYPE IN (91, 92, 93) AND b.yllb = '16'
    """)

    q("居民门特 mz 套表（yllb=12）结算与 fyfs 分布", """
        SELECT m.fyfs, COUNT(*)
        FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx m ON m.djh = b.djh
        WHERE b.FUND_TYPE IN (91, 92, 93) AND b.yllb = '12'
        GROUP BY m.fyfs ORDER BY 2 DESC
    """)

    q("居民门特 zy 人员类别分布", """
        SELECT b.cblb, COUNT(*) FROM dbo.yb_brdjxx b
        JOIN dbo.yb_zyjyxx s ON s.djh = b.djh
        WHERE b.FUND_TYPE IN (91, 92, 93) AND b.yllb = '16'
        GROUP BY b.cblb ORDER BY 2 DESC
    """)

    q("居民门特 mz 人员类别分布", """
        SELECT b.cblb, COUNT(*) FROM dbo.yb_brdjxx b
        JOIN dbo.yb_mzjyxx m ON m.djh = b.djh
        WHERE b.FUND_TYPE IN (91, 92, 93) AND b.yllb = '12'
        GROUP BY b.cblb ORDER BY 2 DESC
    """)

    q("居民门特 zy 账面观测值样本", """
        SELECT b.djh, b.cblb, b.FUND_TYPE, s.jyrq, s.zje, s.ybn, s.ybw, s.ybnqfje, s.grziftw,
               s.tczhf, s.tczif, s.degwyzhf, s.degwyzif, s.bczhf, s.jczhf, s.gfylbchbx, s.xjzf, s.zhzf
        FROM dbo.yb_brdjxx b JOIN dbo.yb_zyjyxx s ON s.djh = b.djh
        WHERE b.FUND_TYPE IN (91, 92, 93) AND b.yllb = '16'
        ORDER BY b.djh
    """)

    q("居民门特 mz 账面观测值样本", """
        SELECT b.djh, b.cblb, b.FUND_TYPE, m.fyfs, m.jyrq, m.zje, m.ptybn, m.ptybw, m.tsbybn, m.tsbybw,
               m.ybnqfje, m.grziftw, m.tczhf, m.tczif, m.degwyzhf, m.degwyzif,
               m.bczhf, m.jczhf, m.gfylbchbx, m.xjzf, m.zhzf
        FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx m ON m.djh = b.djh
        WHERE b.FUND_TYPE IN (91, 92, 93) AND b.yllb = '12'
        ORDER BY b.djh
    """)

    q("周期上下文证据（dyxxtsb/dyxxnd）", """
        SELECT b.djh,
               CASE WHEN c.djh IS NOT NULL THEN 'tsb' ELSE '' END AS has_tsb,
               CASE WHEN nd.djh IS NOT NULL THEN 'nd' ELSE '' END AS has_nd
        FROM dbo.yb_brdjxx b
        LEFT JOIN dbo.yb_dyxxtsb c ON c.djh = b.djh
        LEFT JOIN dbo.yb_dyxxnd nd ON nd.djh = b.djh
        WHERE b.FUND_TYPE IN (91, 92, 93) AND b.yllb IN ('12','16')
        ORDER BY b.djh
    """)

    q("资格候选列分布（cjjrdj/gwydybz）", """
        SELECT b.yllb, b.cjjrdj, b.gwydybz, COUNT(*)
        FROM dbo.yb_brdjxx b
        WHERE b.FUND_TYPE IN (91, 92, 93) AND b.yllb IN ('12','16')
        GROUP BY b.yllb, b.cjjrdj, b.gwydybz ORDER BY 1, 4 DESC
    """)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
