"""数据治理全流程端到端验收脚本（V3.0 闭环）。

用途：一条命令验证「接入 → 探查 → 同步 → 建模 → 加工 → 质量 → 资产 → 消费」全链路当前成立。
直连服务层与 PG（不走 HTTP/LLM），幂等只读，可随时重跑。

用法：python scripts/e2e_governance_closed_loop.py
退出码：全部断言通过 0；任一失败 1。
"""
from __future__ import annotations

import sys
from decimal import Decimal

PASS = "✅"
FAIL = "❌"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = PASS if ok else FAIL
    print(f"{mark} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    from src.config.production import DATABASE_URL
    from src.data_platform.storage.postgresql.client import PostgreSQLClient

    pg = PostgreSQLClient(DATABASE_URL)

    print("── ① 数据接入（契约管道 + 选表通道）──")
    jobs = pg.execute("SELECT source_id, status FROM outpatient_sync_jobs WHERE source_id='bjybdb'")
    check("门诊同步任务存在且非 failed", bool(jobs) and jobs[0]["status"] in {"ready", "running", "paused"}, str(jobs))
    trade = pg.execute("SELECT COUNT(*) AS n FROM mz_trade")[0]["n"]
    fee = pg.execute("SELECT COUNT(*) AS n FROM mz_fee_item")[0]["n"]
    check("契约管道落地 mz_trade/mz_fee_item 非空", trade > 0 and fee > 0, f"{trade}/{fee} 行")

    sync_tables = pg.execute(
        "SELECT table_name, last_row_count FROM data_source_sync_tables WHERE source_id='bjybdb' AND status='active' ORDER BY table_name"
    )
    check("选表通道覆盖 yb 三表", {"yb_brdjxx", "yb_mzjyxx", "yb_mzfymx"} <= {r["table_name"] for r in sync_tables},
          f"{len(sync_tables)} 张已选")
    for table in ("yb_brdjxx", "yb_mzjyxx", "yb_mzfymx"):
        n = pg.execute(f'SELECT COUNT(*) AS n FROM "{table}"')[0]["n"]
        check(f"落地表 {table} 有数据", n > 0, f"{n} 行")

    print("── ② 数据探查（按数据源隔离的全库画像）──")
    from src.data_platform.storage.postgresql.discovery_store import DiscoveryStore
    result = DiscoveryStore().get_latest_result("bjybdb")
    tables_seen = {f.get("table_name") for f in (result or {}).get("fields", [])}
    check("HIS 全库探查结果存在且为全库规模", len(tables_seen) > 100, f"{len(tables_seen)} 表")

    print("── ③ 数据建模（结构契约已发布）──")
    models = pg.execute("SELECT model_code, status FROM data_models WHERE status='published' ORDER BY model_code")
    model_codes = {r["model_code"] for r in models}
    expected = {"dwd_mz_settlement", "dwd_mz_fee_item", "dwd_mz_diagnose",
                "dwd_yb_patient_reg", "dwd_yb_mz_settlement", "dwd_yb_mz_fee_item"}
    check("六个 DWD 模型全部 published", expected <= model_codes, f"{len(model_codes & expected)}/6")
    mappings = pg.execute(
        "SELECT COUNT(*) AS n FROM data_model_mappings WHERE status='confirmed'"
    )[0]["n"]
    check("映射全部 confirmed", mappings >= 60, f"{mappings} 条")

    print("── ④ 数据加工 + 质量门禁（Flow 消费）──")
    from src.data_platform.storage.flow.flow_factory import get_flow_view_reader, get_governed_flow_storage
    from src.runtime.flow.flow_query_service import FlowQueryService

    svc = FlowQueryService(get_governed_flow_storage(), get_flow_view_reader())
    golden = svc.query_by_metrics(["op_total_fee", "op_fund_pay", "op_self_pay"], caller_role="ops_admin")
    check("Golden Flow 消费 quality=passed", golden.quality_status == "passed")
    row = golden.rows[0] if golden.rows else {}
    total, fund, self_pay = (Decimal(str(row.get(k, 0))) for k in ("op_total_fee", "op_fund_pay", "op_self_pay"))
    check("勾稽恒等成立（总费用=统筹+个人）",
          abs(total - fund - self_pay) < Decimal("0.01"),
          f"{total} = {fund} + {self_pay}")

    yb = svc.query_by_metrics(["yb_op_pooling_pay", "yb_op_total_amount"], caller_role="ops_admin")
    check("医保基金 Flow 消费 quality=passed", yb.quality_status == "passed", str(yb.rows[:1]))

    # Slice 2 物化：dwd 明细视图存在且有数据
    from src.data_platform.storage.flow.flow_factory import get_flow_view_reader
    dwd_rows = get_flow_view_reader().read("dwd_yb_mz_settlement", ["trade_serial_no", "pooling_pay"])
    check("模型物化视图 dwd_yb_mz_settlement 有数据", len(dwd_rows) > 0, f"{len(dwd_rows)} 行")
    # Slice 3 登记：运营指标已绑定模型字段
    bound = pg.execute(
        "SELECT COUNT(*) AS n FROM semantic_metrics WHERE model_field_ref IS NOT NULL"
    )[0]["n"]
    check("指标绑定数据模型字段（model_field_ref）", bound >= 30, f"{bound} 个")

    print("── ⑤ 数据资产（目录 + 血缘）──")
    dm = pg.execute("SELECT COUNT(*) AS n FROM data_catalog_assets WHERE asset_type='data_model'")[0]["n"]
    check("数据模型入册数据目录", dm >= 6, f"{dm} 个")
    edges = pg.execute("SELECT COUNT(*) AS n FROM data_catalog_lineage_edges")[0]["n"]
    check("血缘边已推导落表", edges > 200, f"{edges} 条")

    print("── ⑥ 消费（可信问题库命中回放）──")
    from src.data_platform.storage.question_library.question_factory import get_trusted_question_storage
    from src.runtime.question_library.service import QuestionLibraryService

    svc_q = QuestionLibraryService(get_trusted_question_storage())
    outcome = svc_q.match("门诊统筹基金支付是多少")
    check("可信问题命中", outcome.kind == "hit", outcome.kind)

    print()
    if failures:
        print(f"{FAIL} {len(failures)} 项未通过：")
        for f in failures:
            print(f"   - {f}")
        return 1
    print(f"{PASS} 数据治理全流程验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
