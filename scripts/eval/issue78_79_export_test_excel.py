"""Issue #78/#79/#80/#81 四链路测试数据导出（Excel，每 sheet 一链路，字段按执行序）。

用途：把费用分解算法所需的全部输入字段（按算法执行顺序排列）+ 账面观测值 +
批量对账结论导出为 Excel，供人工逐笔对账核查。

口径：与 scripts/eval/issue78_79_reconciliation_test_conditions.sql 一致（只读）。
脱敏：不导出姓名/身份证/医保卡号原文；同人关联用匿名组号 person_group
（SQL 侧 DENSE_RANK 生成，原始标识不出库）。

跑法：uv run python scripts/eval/issue78_79_export_test_excel.py
产出：scripts/eval/issue78_79_test_data.xlsx
  sheet「门诊」     81 笔（o_Trade 套表，城镇职工）
  sheet「门特mz」   14 笔（yb_brdjxx+yb_mzjyxx+yb_mzfymx，门诊特殊病·按项目付费）
  sheet「居民门诊」 59 笔（o_Trade 套表，城乡居民；Issue #80，含退费/医事服务费/
                  大病保险/医疗救助通道）
  sheet「居民门特mz」 3 笔（yb_brdjxx+yb_mzjyxx+yb_mzfymx，城乡居民门特·按项目付费；
                  Issue #81，目录独立重算 + dyxxtsb/dyxxnd 周期推导）
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal, ROUND_HALF_UP
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402

DATASOURCE_ID = "bjybdb"
EVAL_DIR = Path(__file__).parent
OUT_PATH = EVAL_DIR / "issue78_82_test_data.xlsx"

GROUP_FILL = PatternFill("solid", fgColor="D9E1F2")
HEADER_FONT = Font(bold=True)


def _deidentify_birthdates(rows: list[dict]) -> None:
    from datetime import date, datetime
    def date_value(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10]) if value is not None else None
    for row in rows:
        key = "P_Birthday" if "P_Birthday" in row else "csrq" if "csrq" in row else None
        if key:
            birth = date_value(row.pop(key))
            settled = date_value(row.get("T_TradeDate", row.get("jyrq")))
            row["年龄(结算日)"] = settled.year-birth.year-((settled.month, settled.day)<(birth.month, birth.day)) if birth and settled else None


def _write_sheet(wb: Workbook, title: str, groups: list[tuple[str, list[str]]],
                 rows: list[dict], note: str) -> None:
    """写一个 sheet：第 1 行执行顺序分组（合并单元格），第 2 行字段名，第 3 行注释，第 4 行起数据。"""
    ws = wb.create_sheet(title)
    _deidentify_birthdates(rows)
    groups = [(group, ["年龄(结算日)" if field in ("P_Birthday", "csrq") else field for field in fields]) for group, fields in groups]
    flat = [f for _, fields in groups for f in fields]
    col = 1
    for group_name, fields in groups:
        ws.cell(row=1, column=col, value=f"{group_name}（{len(fields)}列）")
        ws.cell(row=1, column=col).font = HEADER_FONT
        ws.cell(row=1, column=col).fill = GROUP_FILL
        if len(fields) > 1:
            ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + len(fields) - 1)
        col += len(fields)
    for i, f in enumerate(flat, start=1):
        c = ws.cell(row=2, column=i, value=f)
        c.font = HEADER_FONT
    ws.cell(row=3, column=1, value=note)
    ws.cell(row=3, column=1).font = Font(italic=True, color="808080")
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(flat))
    for r, row in enumerate(rows, start=4):
        for i, f in enumerate(flat, start=1):
            ws.cell(row=r, column=i, value=row.get(f))
    ws.freeze_panes = "C4"
    ws.auto_filter.ref = f"A2:{get_column_letter(len(flat))}{ws.max_row}"
    ws.row_dimensions[3].height = 42
    ws.cell(row=3, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=4):
        for cell in row:
            if isinstance(cell.value, (int, float)):
                cell.number_format = "0.00"
            if cell.value in ("mismatched", "差异（实质）"):
                cell.fill = PatternFill("solid", fgColor="FCE4D6")
            elif cell.value in ("not_verifiable", "无法核对"):
                cell.fill = PatternFill("solid", fgColor="FFF2CC")
    for i, f in enumerate(flat, start=1):
        width = max(10, min(28, max([len(str(f)), *(len(str(r.get(f, ""))) for r in rows[:50])]) + 2))
        ws.column_dimensions[get_column_letter(i)].width = width


def _load_csv(name: str) -> list[dict]:
    return list(csv.DictReader(open(EVAL_DIR / name, encoding="utf-8-sig")))


def _num(v):
    """Decimal/数值原样转 float 供 Excel 数值列；None 保持空；日期类型原样返回。"""
    import datetime as _dt
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v
    return float(v) if v is not None and str(v) != "" else None



SECONDARY_FIELDS = ("BIG_ILL_PAY", "FEEIN_DB_PAY", "FEEOUT_DB_PAY", "CIVIL_IN", "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY", "PERSON_PAYABLE")
SOURCE_FIELDS = ("CIVIL_TYPE", "jylsh", "annual_year", "annual_last_trade", "BIG_ILL_SUM_IN", "BIG_ILL_SUM_PAY", "CIVIL_SUM_IN", "CIVIL_SUM_PAY", "RETIRE_OFFICER_PAY",
    "BIG_ILL_PAY", "FEEIN_DB_PAY", "FEEOUT_DB_PAY", "CIVIL_IN", "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY")
SPLIT_FIELDS = ("tsbybn1", "tsbybn2", "tsbybw1", "tczhf1", "tczif1", "dezhf1", "dezif1", "bczhf1", "bczhf2", "jczhf1", "jczhf2", "gfylbchbxde")


def _read_special_coverage(cur) -> dict[str, dict]:
    # 只读原始投影，不用支付目标反推算法输入；源分拆字段只作为独立诊断证据。
    columns = ["b.djh", "b.CIVIL_TYPE", "m.jylsh", "nd.fynd AS annual_year", "nd.bnmcjylsh AS annual_last_trade",
        "nd.BIG_ILL_SUM_IN", "nd.BIG_ILL_SUM_PAY", "nd.CIVIL_SUM_IN", "nd.CIVIL_SUM_PAY", "m.RETIRE_OFFICER_PAY"]
    columns += [f"m.{code}" for code in SECONDARY_FIELDS if code != "PERSON_PAYABLE"]
    columns += [f"m.{code}" for code in SPLIT_FIELDS]
    cur.execute("SELECT " + ", ".join(columns) + " FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx m ON m.djh=b.djh "
        "LEFT JOIN dbo.yb_dyxxnd nd ON nd.djh=b.djh WHERE b.yllb='12' AND b.FUND_TYPE IN (3,91,92,93) AND m.fyfs='0' ORDER BY b.djh")
    names = ["djh", *SOURCE_FIELDS, *SPLIT_FIELDS]
    facts = {}
    for raw in cur.fetchall():
        row = dict(zip(names, raw))
        facts[str(row["djh"])] = row
    return facts


def _load_special_traces() -> dict[str, dict]:
    return {insurance: json.loads((EVAL_DIR / name).read_text(encoding="utf-8")) for insurance, name in (
        ("employee", "issue79_special_mz_batch_traces.json"),
        ("employee_fixed", "issue82_fixed_kidney_batch_traces.json"),
        ("resident", "issue81_resident_special_batch_traces.json"))}


def _coverage_groups() -> list[tuple[str, list[str]]]:
    return [("⑧二次大病及医疗救助源事实", list(SOURCE_FIELDS)),
        ("⑨源分拆诊断(非算法替代输入)", list(SPLIT_FIELDS)),
        ("⑩独立分解验证", [name for code in SECONDARY_FIELDS for name in (code+"_计算", code+"_差额", code+"_状态")]),
        ("⑪当前证据与限制", ["execution_status", "secondary_uncertainties"])]


def _extend_special_rows(rows, facts, traces) -> None:
    identifiers = {"djh", "CIVIL_TYPE", "jylsh", "annual_year", "annual_last_trade"}
    for row in rows:
        raw = facts[row["djh"]]
        row.update({key: (str(value) if value is not None else None) if key in identifiers else _num(value)
            for key, value in raw.items()})
        trace = traces[row["djh"]]
        fields = {field["field_code"]: field for field in trace["fields"]}
        for code in SECONDARY_FIELDS:
            field = fields.get(code, {})
            row[code+"_计算"] = _num(field.get("calculated_amount"))
            row[code+"_差额"] = _num(field.get("difference"))
            row[code+"_状态"] = field.get("check_status", "not_verifiable")
        row["execution_status"] = trace["execution_status"]
        row["secondary_uncertainties"] = "; ".join(u["code"] for u in trace["uncertainties"])


def _write_special_validation(wb, traces, facts) -> None:
    fields, calculations = [], []
    for insurance, settlements in traces.items():
        for djh, trace in settlements.items():
            anchor = {"险种": {"employee": "职工项目", "employee_fixed": "职工定额", "resident": "居民"}[insurance], "djh": djh}
            for field in trace["fields"]:
                fields.append({**anchor, **field, "observed_amount": _num(field.get("observed_amount")),
                    "calculated_amount": _num(field.get("calculated_amount")), "difference": _num(field.get("difference"))})
            for calc in trace["calculations"]:
                calculations.append({**anchor, **calc, "operands": "; ".join(f"{o['ref']}={o['value']}" for o in calc["operands"])})
    _write_sheet(wb, "门特逐字段验证", [("定位", ["险种", "djh"]),
        ("金额核对", ["field_code", "label", "check_type", "observed_amount", "calculated_amount", "difference", "check_status", "explanation_level", "reason_code"])], fields,
        "包含职工项目、职工定额和居民门特全部核对字段。差额=计算−账面；not_verifiable是缺证据，不是通过；identity_check是条件/账面核对，不证明日定额已独立核定。")
    _write_sheet(wb, "门特支付计算过程", [("定位", ["险种", "djh"]),
        ("确定性追踪", ["calculation_id", "formula_id", "formula_version", "operands", "unrounded_result", "rounding_rule", "result"])], calculations,
        "实际运行轨迹：基本医保→退休/军残/公疗补助→二次大病年度分段→医疗救助→个人应付。explicit:round_half_up属于本次显式假定，仍待取整口径签核。")
    diagnostics = []
    for djh, rate, aid_rate, formula in (
        ("814", Decimal("0.6"), Decimal("0"), "(dezif1−bczhf1−jczhf1)×60%"),
        ("690", Decimal("0.65"), Decimal("1"), "dezif1×65%；剩余×100%"),
        ("718", Decimal("0"), Decimal("0.85"), "(dezif1+grziftw)×85%"),
        ("658", Decimal("0"), Decimal("0"), "tczif1−bczhf1−jczhf1"),
        ("676", Decimal("0"), Decimal("0"), "tczif1−bczhf1−jczhf1"),
        ("716", Decimal("0"), Decimal("0"), "tczif1−bczhf1−jczhf1"),
        ("675", Decimal("0"), Decimal("0"), "ybnqfje+tczif−bczhf−gfylbchbxde"),
        ("708", Decimal("0"), Decimal("0"), "tczif1−bczhf1−RETIRE_OFFICER_PAY"),
        ("609", Decimal("0"), Decimal("0"), "1300+tczif1−bczhf1−jczhf1−gfylbchbxde")):
        raw = facts[djh]
        insurance = "resident" if djh in ("690", "718") else "employee_fixed" if djh in traces["employee_fixed"] else "employee"
        trace = traces[insurance][djh]
        observed = {f["field_code"]: f.get("observed_amount") for f in trace["fields"]}
        if djh == "609":
            base = Decimal("1300") + raw["tczif1"] - raw["bczhf1"] - raw["jczhf1"] - raw["gfylbchbxde"]
        elif djh in ("658", "676", "716"):
            base = raw["tczif1"] - raw["bczhf1"] - raw["jczhf1"]
        elif djh == "675":
            base = Decimal(observed["YBNQFJE"]) + Decimal(observed["TCZIF"]) - Decimal(observed["BCZHF"]) - raw["gfylbchbxde"]
        elif djh == "708":
            base = raw["tczif1"] - raw["bczhf1"] - raw["RETIRE_OFFICER_PAY"]
        else:
            base = raw["dezif1"] - raw["bczhf1"] - raw["jczhf1"]
        if djh == "718":
            base += Decimal(observed["GRZIFTW"])
        db = (base * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        aid = ((base-db)*aid_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        personal = base-db-aid
        diagnostics.append({"djh": djh, "条件等式": formula, "分拆基数": _num(base), "条件大病": _num(db),
            "账面大病": _num(observed["BIG_ILL_PAY"]), "条件救助": _num(aid), "账面救助": _num(observed["CIVIL_IN"]),
            "条件个人": _num(personal), "账面个人": _num(observed["PERSON_PAYABLE"]),
            "结论边界": "等式复现账面金额；分拆时点/范围未确认，不能替代本笔独立算法基数"})
    _write_sheet(wb, "门特源分拆诊断", [("条件性来源诊断", ["djh", "条件等式", "分拆基数", "条件大病", "账面大病", "条件救助", "账面救助", "条件个人", "账面个人", "结论边界"])], diagnostics,
        "全部来自真实源字段的条件性等式；只验证可核对线索，不能据此断定原程序实现。688分拆字段全零，说明不能通用替换。")


def _write_fixed_kidney(wb, cur, traces, facts) -> None:
    from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import KIDNEY_SCOPE_SQL
    names = ["djh", "tsb1", "tsb2", "tsb3", "SPEC_HOSP_FLAG", "FUND_TYPE", "yllb", "fyfs",
        "deqsrq", "dejzrq", "zje", "tsbybn1", "grzif1", "tczhf1", "dezhf1", "bczhf1", "jczhf1",
        "gfylbchbxde", "AGENCY_PAY_AMOUNT", "xjzf", "zhzf"]
    columns = [f"b.{key}" if key in names[:7] else f"m.{key}" for key in names]
    cur.execute("SELECT "+", ".join(columns)+" FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx m ON b.djh=m.djh "
        "WHERE b.FUND_TYPE=3 AND b.yllb='12' AND m.fyfs='0' AND "+KIDNEY_SCOPE_SQL+" ORDER BY b.djh")
    rows = []
    for source_row in cur.fetchall():
        row = dict(zip(names, source_row))
        for key in names:
            row[key] = str(row[key]) if key in names[:10] and row[key] is not None else _num(row[key])
        row["djh"] = str(source_row[0])
        trace = traces[row["djh"]]
        fields = {field["field_code"]: field for field in trace["fields"]}
        for code in ("TCZHF", "DEGWYZHF", "GRZIF1", "AGENCY_PAY", "PERSON_PAYABLE"):
            field = fields.get(code, {})
            row[code+"_计算"] = _num(field.get("calculated_amount"))
            row[code+"_差额"] = _num(field.get("difference"))
            row[code+"_状态"] = field.get("check_status", "not_verifiable")
        row["验证限制"] = "; ".join(u["message"] for u in trace["uncertainties"])
        rows.append(row)
    _extend_special_rows(rows, facts, traces)
    groups = [("①独立定额范围", names[:8]), ("②给药时段与定额条件输入", names[8:12]),
        ("③定额分拆账面支付", names[12:]),
        ("④计算与差额", [name for code in ("TCZHF", "DEGWYZHF", "GRZIF1", "AGENCY_PAY", "PERSON_PAYABLE")
            for name in (code+"_计算", code+"_差额", code+"_状态")]), ("⑤验证边界", ["验证限制"])]
    groups.extend(_coverage_groups())
    seen_fields = set()
    unique_groups = []
    for label, columns in groups:
        unique_columns = [column for column in columns if column not in seen_fields]
        seen_fields.update(unique_columns)
        if unique_columns:
            unique_groups.append((label, unique_columns))
    _write_sheet(wb, "职工门特定额-肾移植", unique_groups, rows,
        "职工FUND_TYPE=3、门特yllb=12、fyfs=0、tsb1/2/3含503/504：7笔。个人自付按实际费用减2/5个百分点，医院基金按定额减原始自付。"
        "609个人68.85；814大病23.62/个人15.75。708定点标识为空且合并透析，未套公式。定额日标准和完整目录待核定，不作为完全通过。")


def main() -> None:
    ds = get_semantic_data_source()
    conn = ds.open_connection(DATASOURCE_ID)
    cur = conn.cursor()
    coverage_facts = _read_special_coverage(cur)
    traces = _load_special_traces()
    wb = Workbook()
    wb.remove(wb.active)

    # ── sheet 1：门诊（81 笔）──────────────────────────────────────────────
    verdict = {r["trade_no"]: r for r in _load_csv("issue78_fee_decomposition_batch_result.csv")}
    cur.execute(
        """
        SELECT t.T_TradeNo, t.T_TradeDate, t.T_HospCode,
               t.P_FundType, t.T_CureType,
               t.PN_PersonType, t.P_Birthday, t.PN_NoRightReason,
               t.P_Official, t.P_OfficialCode, t.P_JCLevel,
               DENSE_RANK() OVER (ORDER BY t.P_ICNo) AS person_group,
               i.H_TYPE, i.H_LEVEL,
               t.TB_Year, t.TB_FeeIn, t.TB_BigPay,
               t.T_HasRefundmented, t.T_PartialReturnFlag, t.T_OraginalTradeNo,
               t.T_FeeAll, t.T_FeeIn, t.T_FeeOut, t.T_SelfPay2, t.T_FirstPay,
               t.T_BigPay, t.T_BigSelfPay, t.T_BCPay, t.T_JCPay, t.T_OfficalPay,
               t.T_SelfPay1, t.T_FundPay, t.T_SelfPayAll, t.T_PersonCountPay, t.T_CashPay
        FROM o_Trade t
        LEFT JOIN m_institution i ON i.H_CODE = t.T_HospCode
        WHERE t.P_FundType = '3' AND t.T_CureType = '11' AND t.T_HospCode = '01110003'
        ORDER BY t.T_TradeNo
        """
    )
    trades = {r[0]: r for r in cur.fetchall()}
    cur.execute(
        """
        SELECT f.T_TradeNo, COUNT(*) AS 行数,
               SUM(f.Fee) AS s_fee, SUM(f.FeeIn) AS s_in, SUM(f.FeeOut) AS s_out, SUM(f.SelfPay2) AS s_sp2,
               SUM(CASE WHEN f.ItemType='0' THEN 1 ELSE 0 END) AS 药品行,
               SUM(CASE WHEN f.ItemType IN ('1','2') THEN 1 ELSE 0 END) AS 诊疗行,
               SUM(CASE WHEN f.ItemType='3' THEN 1 ELSE 0 END) AS 材料行,
               SUM(CASE WHEN f.MEDIC_L>0 THEN 1 ELSE 0 END) AS medic_l行,
               SUM(CASE WHEN f.SP_SCALE>0 THEN 1 ELSE 0 END) AS sp_scale行,
               SUM(CASE WHEN f.Fee<0 OR f.Count<0 THEN 1 ELSE 0 END) AS 负明细行
        FROM o_FeeItem f
        WHERE f.T_TradeNo IN (SELECT T_TradeNo FROM o_Trade
                              WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode='01110003')
        GROUP BY f.T_TradeNo
        """
    )
    items = {r[0]: r for r in cur.fetchall()}
    cur.execute(
        """
        SELECT f.T_TradeNo, SUM(CASE WHEN c.A_ypbs='1' THEN 1 ELSE 0 END) AS 集采行
        FROM o_FeeItem f JOIN yb_ypzdml c ON c.ypbm = f.ItemCode
        WHERE f.T_TradeNo IN (SELECT T_TradeNo FROM o_Trade
                              WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode='01110003')
        GROUP BY f.T_TradeNo
        """
    )
    ncp = {r[0]: r[1] for r in cur.fetchall()}

    mz_groups = [
        ("①交易锚点", ["T_TradeNo", "T_TradeDate", "T_HospCode"]),
        ("②险种×医疗类别分流", ["P_FundType", "T_CureType"]),
        ("③人员身份", ["PN_PersonType", "P_Birthday", "PN_NoRightReason"]),
        ("④待遇资格候选列(D6/D7/D8)", ["P_Official", "P_OfficialCode", "P_JCLevel", "person_group"]),
        ("⑤机构(D9)", ["H_TYPE", "H_LEVEL"]),
        ("⑥年度累计·交易前口径(D3/D4)", ["TB_Year", "TB_FeeIn", "TB_BigPay"]),
        ("⑦冲正识别", ["T_HasRefundmented", "T_PartialReturnFlag", "T_OraginalTradeNo"]),
        ("⑧明细汇总(全量禁分页)", ["明细行数", "ΣFee", "ΣFeeIn", "ΣFeeOut", "ΣSelfPay2",
                                 "药品行", "诊疗行", "材料行", "集采行", "MEDIC_L行", "SP_SCALE行", "负明细行"]),
        ("⑨账面观测值(核对目标)", ["T_FeeAll", "T_FeeIn", "T_FeeOut", "T_SelfPay2", "T_FirstPay",
                                "T_BigPay", "T_BigSelfPay", "T_BCPay", "T_JCPay", "T_OfficalPay",
                                "T_SelfPay1", "T_FundPay", "T_SelfPayAll", "T_PersonCountPay", "T_CashPay"]),
        ("⑩对账结论(2026-10-12复跑)", ["verdict", "reconciliation_status", "mismatched_fields", "uncertainty_codes"]),
    ]
    rows = []
    for tno, t in trades.items():
        it = items.get(tno, (None,) * 12)
        v = verdict.get(tno, {})
        keys = list(t.keys()) if hasattr(t, "keys") else None
        d = {}
        cols = ["T_TradeNo", "T_TradeDate", "T_HospCode", "P_FundType", "T_CureType",
                "PN_PersonType", "P_Birthday", "PN_NoRightReason",
                "P_Official", "P_OfficialCode", "P_JCLevel", "person_group",
                "H_TYPE", "H_LEVEL", "TB_Year", "TB_FeeIn", "TB_BigPay",
                "T_HasRefundmented", "T_PartialReturnFlag", "T_OraginalTradeNo",
                "T_FeeAll", "T_FeeIn", "T_FeeOut", "T_SelfPay2", "T_FirstPay",
                "T_BigPay", "T_BigSelfPay", "T_BCPay", "T_JCPay", "T_OfficalPay",
                "T_SelfPay1", "T_FundPay", "T_SelfPayAll", "T_PersonCountPay", "T_CashPay"]
        for k, val in zip(cols, t):
            d[k] = _num(val) if k not in ("T_TradeNo", "T_HospCode", "P_FundType", "T_CureType",
                                          "PN_PersonType", "PN_NoRightReason", "P_OfficialCode",
                                          "T_OraginalTradeNo", "TB_Year") else (str(val) if val is not None else None)
        if d["T_TradeDate"] is not None:
            d["T_TradeDate"] = str(t[1])
        if d["P_Birthday"] is not None:
            d["P_Birthday"] = str(t[6])
        agg = ["明细行数", "ΣFee", "ΣFeeIn", "ΣFeeOut", "ΣSelfPay2", "药品行", "诊疗行", "材料行",
               "MEDIC_L行", "SP_SCALE行", "负明细行"]
        for k, val in zip(agg, it[1:] if it[0] else [None] * 11):
            d[k] = _num(val)
        d["集采行"] = _num(ncp.get(tno))
        d["verdict"] = v.get("verdict")
        d["reconciliation_status"] = v.get("reconciliation_status")
        d["mismatched_fields"] = v.get("mismatched_fields") or None
        d["uncertainty_codes"] = v.get("uncertainty_codes") or None
        rows.append(d)
    _write_sheet(wb, "门诊", mz_groups, rows,
                 "城镇职工(P_FundType='3')×普通门诊(T_CureType='11')×院区01110003，共81笔；"
                 "列按算法执行序：定位→分流→身份→资格→机构→累计→冲正→明细→账面→结论。"
                 "person_group 为同人匿名组号（P_ICNo 的 DENSE_RANK，原始卡号不出库）。")

    # ── sheet 2：门特 mz 套表（14 笔，门诊特殊病·按项目付费）────────────────
    mz_verdict = {r["djh"]: r for r in _load_csv("issue79_special_mz_batch_result.csv")
                  if r.get("row_type") == "verdict"}
    cur.execute(
        """
        SELECT b.djh, b.ryrq, b.FUND_TYPE, b.yllb, b.cblb, b.cjjrdj, b.gwydybz,
               DENSE_RANK() OVER (ORDER BY b.sfz) AS person_group,
               m.jyrq, m.fyfs, m.zje, m.ptybn, m.ptybw, m.tsbybn, m.tsbybw,
               m.ybnqfje, m.grziftw, m.tczhf, m.tczif, m.degwyzhf, m.degwyzif,
               m.bczhf, m.jczhf, m.gfylbchbx, m.xjzf, m.zhzf,
               CASE WHEN c.djh IS NOT NULL THEN 'row_exists_only' ELSE 'unknown' END AS 周期证据_tsb,
               nd.bnzqslj
        FROM dbo.yb_brdjxx b
        JOIN dbo.yb_mzjyxx m ON m.djh = b.djh
        LEFT JOIN dbo.yb_dyxxtsb c ON c.djh = b.djh
        LEFT JOIN dbo.yb_dyxxnd nd ON nd.djh = b.djh
        WHERE b.FUND_TYPE = 3 AND b.yllb = '12' AND m.fyfs = '0' AND COALESCE(b.tsb1,'') NOT IN ('503','504') AND COALESCE(b.tsb2,'') NOT IN ('503','504') AND COALESCE(b.tsb3,'') NOT IN ('503','504')
        ORDER BY b.djh
        """
    )
    mz_rows_raw = cur.fetchall()
    cur.execute(
        """
        SELECT f.djh, COUNT(*), SUM(f.zje), SUM(f.ybnje), SUM(f.ybwje), SUM(f.grziftw)
        FROM dbo.yb_mzfymx f
        WHERE f.djh IN (SELECT b.djh FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx m ON m.djh=b.djh
                        WHERE b.FUND_TYPE=3 AND b.yllb='12' AND m.fyfs='0')
        GROUP BY f.djh
        """
    )
    mz_items = {r[0]: r for r in cur.fetchall()}
    mz3_groups = [
        ("①登记锚点", ["djh", "ryrq"]),
        ("②险种×医疗类别×费用方式", ["FUND_TYPE", "yllb", "fyfs"]),
        ("③人员身份与资格候选(Issue#79)", ["cblb", "cjjrdj", "gwydybz", "person_group"]),
        ("④周期上下文证据", ["周期证据_tsb", "bnzqslj"]),
        ("⑤明细汇总(全量禁分页)", ["明细行数", "Σzje", "Σybnje", "Σybwje", "Σgrziftw"]),
        ("⑥账面观测值(核对目标)", ["jyrq", "zje", "ptybn", "ptybw", "tsbybn", "tsbybw", "ybnqfje", "grziftw",
                                "tczhf", "tczif", "degwyzhf", "degwyzif",
                                "bczhf", "jczhf", "gfylbchbx", "xjzf", "zhzf"]),
        ("⑦对账结论(2026-10-13复跑)", ["verdict", "reconciliation_status", "accurate_fields", "mismatched_fields", "not_verifiable_fields"]),
    ]
    rows = []
    for r in mz_rows_raw:
        cols = ["djh", "ryrq", "FUND_TYPE", "yllb", "cblb", "cjjrdj", "gwydybz", "person_group",
                "jyrq", "fyfs", "zje", "ptybn", "ptybw", "tsbybn", "tsbybw",
                "ybnqfje", "grziftw", "tczhf", "tczif", "degwyzhf", "degwyzif",
                "bczhf", "jczhf", "gfylbchbx", "xjzf", "zhzf", "周期证据_tsb", "bnzqslj"]
        d = dict(zip(cols, r))
        for k in ("djh", "FUND_TYPE", "yllb", "cblb", "fyfs"):
            d[k] = str(d[k]) if d[k] is not None else None
        for k in ("ryrq", "jyrq"):
            d[k] = str(d[k]) if d[k] is not None else None
        for k in ("cjjrdj", "gwydybz", "bnzqslj"):
            d[k] = str(d[k]) if d[k] is not None else None
        for k in ("zje", "ptybn", "ptybw", "tsbybn", "tsbybw", "ybnqfje", "grziftw",
                  "tczhf", "tczif", "degwyzhf", "degwyzif", "bczhf", "jczhf",
                  "gfylbchbx", "xjzf", "zhzf"):
            d[k] = _num(d[k])
        it = mz_items.get(d["djh"], (None,) * 6)
        for k, val in zip(["明细行数", "Σzje", "Σybnje", "Σybwje", "Σgrziftw"], it[1:]):
            d[k] = _num(val)
        v = mz_verdict.get(d["djh"], {})
        d["verdict"] = v.get("verdict")
        d["reconciliation_status"] = v.get("reconciliation_status")
        d["accurate_fields"] = v.get("accurate_fields")
        d["mismatched_fields"] = v.get("mismatched_fields") or None
        d["not_verifiable_fields"] = v.get("not_verifiable_fields") or None
        rows.append(d)
    _extend_special_rows(rows, coverage_facts, traces["employee"])
    mz3_groups.extend(_coverage_groups())
    _write_sheet(wb, "门特mz", mz3_groups, rows,
                 "城镇职工(FUND_TYPE=3)×门特(yllb='12')×按项目付费(fyfs='0')，共7笔，排除tsb1/2/3中503/504。肾/肝肾抗排异移至独立定额页。"
                 "周期表存在只表示row_exists；年度与流水须吻合且金额推导非负，才分字段确认。2025年缺累计保持未知。"
                 "djh=675 公疗差异：候选资格(gwydybz=0)算出 683.99、账面 0，待查本人定点/码义签核。")

    # ── sheet 3：居民门诊（59 笔，城乡居民·o_Trade 套表，Issue #80）────────────
    jm_verdict = {r["trade_no"]: r for r in _load_csv("issue80_resident_batch_result.csv")}
    cur.execute(
        """
        SELECT t.T_TradeNo, t.T_TradeDate, t.T_HospCode,
               t.P_FundType, t.T_CureType,
               t.PN_PersonType, t.P_Birthday, t.PN_NoRightReason,
               DENSE_RANK() OVER (ORDER BY t.P_ICNo) AS person_group,
               i.H_TYPE, i.H_LEVEL,
               t.TB_Year, t.TB_FeeIn, t.TB_BigPay, t.TB_CivilPay,
               t.T_HasRefundmented, t.T_PartialReturnFlag, t.T_OraginalTradeNo,
               t.T_BigillPay, t.NT_CivilPay,
               t.T_FeeAll, t.T_FeeIn, t.T_FeeOut, t.T_SelfPay2, t.T_FirstPay,
               t.T_BigPay, t.T_BigSelfPay, t.T_BCPay, t.T_JCPay, t.T_OfficalPay,
               t.T_SelfPay1, t.T_FundPay, t.T_SelfPayAll, t.T_PersonCountPay, t.T_CashPay
        FROM o_Trade t
        LEFT JOIN m_institution i ON i.H_CODE = t.T_HospCode
        WHERE t.P_FundType IN ('91','92','93') AND t.T_HospCode = '01110003'
        ORDER BY t.T_TradeNo
        """
    )
    jm_trades = {r[0]: r for r in cur.fetchall()}
    cur.execute(
        """
        SELECT f.T_TradeNo, COUNT(*) AS 行数,
               SUM(f.Fee) AS s_fee, SUM(f.FeeIn) AS s_in, SUM(f.FeeOut) AS s_out, SUM(f.SelfPay2) AS s_sp2,
               SUM(CASE WHEN f.ItemType='0' THEN 1 ELSE 0 END) AS 药品行,
               SUM(CASE WHEN f.ItemType IN ('1','2') THEN 1 ELSE 0 END) AS 诊疗行,
               SUM(CASE WHEN f.ItemType='3' THEN 1 ELSE 0 END) AS 材料行,
               SUM(CASE WHEN f.MEDIC_L>0 THEN 1 ELSE 0 END) AS medic_l行,
               SUM(CASE WHEN f.SP_SCALE>0 THEN 1 ELSE 0 END) AS sp_scale行,
               SUM(CASE WHEN f.Fee<0 OR f.Count<0 THEN 1 ELSE 0 END) AS 负明细行
        FROM o_FeeItem f
        WHERE f.T_TradeNo IN (SELECT T_TradeNo FROM o_Trade
                              WHERE P_FundType IN ('91','92','93') AND T_HospCode='01110003')
        GROUP BY f.T_TradeNo
        """
    )
    jm_items = {r[0]: r for r in cur.fetchall()}
    cur.execute(
        """
        SELECT f.T_TradeNo, SUM(CASE WHEN c.A_ypbs='1' THEN 1 ELSE 0 END) AS 集采行
        FROM o_FeeItem f JOIN yb_ypzdml c ON c.ypbm = f.ItemCode
        WHERE f.T_TradeNo IN (SELECT T_TradeNo FROM o_Trade
                              WHERE P_FundType IN ('91','92','93') AND T_HospCode='01110003')
        GROUP BY f.T_TradeNo
        """
    )
    jm_ncp = {r[0]: r[1] for r in cur.fetchall()}

    jm_groups = [
        ("①交易锚点", ["T_TradeNo", "T_TradeDate", "T_HospCode"]),
        ("②险种×医疗类别通道", ["P_FundType", "T_CureType"]),
        ("③人员身份", ["PN_PersonType", "P_Birthday", "PN_NoRightReason", "person_group"]),
        ("④机构(等级档分档依据)", ["H_TYPE", "H_LEVEL"]),
        ("⑤年度累计·交易前口径", ["TB_Year", "TB_FeeIn", "TB_BigPay", "TB_CivilPay"]),
        ("⑥退费识别(居民支持退费分解)", ["T_HasRefundmented", "T_PartialReturnFlag", "T_OraginalTradeNo"]),
        ("⑦渠道观测(大病/救助)", ["T_BigillPay", "NT_CivilPay"]),
        ("⑧明细汇总(全量禁分页)", ["明细行数", "ΣFee", "ΣFeeIn", "ΣFeeOut", "ΣSelfPay2",
                                 "药品行", "诊疗行", "材料行", "集采行", "MEDIC_L行", "SP_SCALE行", "负明细行"]),
        ("⑨账面观测值(核对目标)", ["T_FeeAll", "T_FeeIn", "T_FeeOut", "T_SelfPay2", "T_FirstPay",
                                "T_BigPay", "T_BigSelfPay", "T_BCPay", "T_JCPay", "T_OfficalPay",
                                "T_SelfPay1", "T_FundPay", "T_SelfPayAll", "T_PersonCountPay", "T_CashPay"]),
        ("⑩对账结论(Issue#80复跑)", ["verdict", "reconciliation_status", "mismatched_fields", "uncertainty_codes"]),
    ]
    rows = []
    for tno, t in jm_trades.items():
        it = jm_items.get(tno, (None,) * 12)
        v = jm_verdict.get(tno, {})
        d = {}
        cols = ["T_TradeNo", "T_TradeDate", "T_HospCode", "P_FundType", "T_CureType",
                "PN_PersonType", "P_Birthday", "PN_NoRightReason", "person_group",
                "H_TYPE", "H_LEVEL", "TB_Year", "TB_FeeIn", "TB_BigPay", "TB_CivilPay",
                "T_HasRefundmented", "T_PartialReturnFlag", "T_OraginalTradeNo",
                "T_BigillPay", "NT_CivilPay",
                "T_FeeAll", "T_FeeIn", "T_FeeOut", "T_SelfPay2", "T_FirstPay",
                "T_BigPay", "T_BigSelfPay", "T_BCPay", "T_JCPay", "T_OfficalPay",
                "T_SelfPay1", "T_FundPay", "T_SelfPayAll", "T_PersonCountPay", "T_CashPay"]
        for k, val in zip(cols, t):
            d[k] = _num(val) if k not in ("T_TradeNo", "T_HospCode", "P_FundType", "T_CureType",
                                          "PN_PersonType", "PN_NoRightReason",
                                          "T_OraginalTradeNo", "TB_Year",
                                          "T_HasRefundmented", "T_PartialReturnFlag",
                                          "H_TYPE", "H_LEVEL") else (str(val) if val is not None else None)
        if d["T_TradeDate"] is not None:
            d["T_TradeDate"] = str(t[1])
        if d["P_Birthday"] is not None:
            d["P_Birthday"] = str(t[6])
        agg = ["明细行数", "ΣFee", "ΣFeeIn", "ΣFeeOut", "ΣSelfPay2", "药品行", "诊疗行", "材料行",
               "MEDIC_L行", "SP_SCALE行", "负明细行"]
        for k, val in zip(agg, it[1:] if it[0] else [None] * 11):
            d[k] = _num(val)
        d["集采行"] = _num(jm_ncp.get(tno))
        d["verdict"] = v.get("verdict")
        d["reconciliation_status"] = v.get("reconciliation_status")
        d["mismatched_fields"] = v.get("mismatched_fields") or None
        d["uncertainty_codes"] = v.get("uncertainty_codes") or None
        rows.append(d)
    _write_sheet(wb, "居民门诊", jm_groups, rows,
                 "城乡居民(P_FundType∈91/92/93)×本院门诊全量（01110003），共59笔；"
                 "通道分流：T_CureType 11/19=门诊大额（起付100/550+比例55%/50%+封顶4500）、"
                 "17/18=医事服务费（限额内100%基金）、退费交易区间公式分解、"
                 "大病通道（大额封顶后仅医保内及比例先行负担按75%，排除全自费与超限）、救助渠道（NT_CivilPay≠0 字段不判定）。"
                 "核对结论取本次CSV；救助渠道口径待确认仍保持不可核对，历史退费缺原政策上下文不硬算。")

    # ── sheet 4：居民门特 mz 套表（3 笔，城乡居民·门诊特殊病·按项目付费，Issue #81）──
    rsp_verdict = {r["djh"]: r for r in _load_csv("issue81_resident_special_batch_result.csv")}
    cur.execute(
        """
        SELECT b.djh, b.ryrq, b.FUND_TYPE, b.yllb, b.cblb, b.csrq, b.tsbqsrq, b.tsbjzrq,
               DENSE_RANK() OVER (ORDER BY b.sfz) AS person_group,
               m.jyrq, m.fyfs, m.zje, m.ptybn, m.ptybw, m.tsbybn, m.tsbybw,
               m.ybnqfje, m.grziftw, m.tczhf, m.tczif, m.degwyzhf, m.degwyzif,
               m.bczhf, m.jczhf, m.gfylbchbx, m.xjzf, m.zhzf,
               c.zqxh, c.bqljybnje, c.bqqfje, nd.bnzqslj, nd.bnybnje, nd.bndezfje
        FROM dbo.yb_brdjxx b
        JOIN dbo.yb_mzjyxx m ON m.djh = b.djh
        LEFT JOIN dbo.yb_dyxxtsb c ON c.djh = b.djh
        LEFT JOIN dbo.yb_dyxxnd nd ON nd.djh = b.djh
        WHERE b.FUND_TYPE IN (91,92,93) AND b.yllb = '12' AND m.fyfs = '0'
        ORDER BY b.djh
        """
    )
    rsp_rows_raw = cur.fetchall()
    cur.execute(
        """
        SELECT f.djh, COUNT(*), SUM(f.zje), SUM(f.ybnje), SUM(f.ybwje), SUM(f.grziftw)
        FROM dbo.yb_mzfymx f
        WHERE f.djh IN (SELECT b.djh FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx m ON m.djh=b.djh
                        WHERE b.FUND_TYPE IN (91,92,93) AND b.yllb='12' AND m.fyfs='0')
        GROUP BY f.djh
        """
    )
    rsp_items = {r[0]: r for r in cur.fetchall()}
    rsp_groups = [
        ("①登记锚点", ["djh", "ryrq", "tsbqsrq", "tsbjzrq"]),
        ("②险种×医疗类别×费用方式", ["FUND_TYPE", "yllb", "fyfs"]),
        ("③人员身份", ["cblb", "csrq", "person_group"]),
        ("④周期上下文(dyxxtsb/dyxxnd)", ["zqxh", "bqljybnje", "bqqfje", "bnzqslj", "bnybnje", "bndezfje"]),
        ("⑤明细汇总(全量禁分页)", ["明细行数", "Σzje", "Σybnje", "Σybwje", "Σgrziftw"]),
        ("⑥账面观测值(核对目标)", ["jyrq", "zje", "ptybn", "ptybw", "tsbybn", "tsbybw", "ybnqfje", "grziftw",
                                "tczhf", "tczif", "degwyzhf", "degwyzif",
                                "bczhf", "jczhf", "gfylbchbx", "xjzf", "zhzf"]),
        ("⑦对账结论(Issue#81复跑)", ["verdict", "reconciliation_status", "mismatched_fields", "uncertainty_codes"]),
    ]
    rows = []
    for r in rsp_rows_raw:
        cols = ["djh", "ryrq", "FUND_TYPE", "yllb", "cblb", "csrq", "tsbqsrq", "tsbjzrq", "person_group",
                "jyrq", "fyfs", "zje", "ptybn", "ptybw", "tsbybn", "tsbybw",
                "ybnqfje", "grziftw", "tczhf", "tczif", "degwyzhf", "degwyzif",
                "bczhf", "jczhf", "gfylbchbx", "xjzf", "zhzf",
                "zqxh", "bqljybnje", "bqqfje", "bnzqslj", "bnybnje", "bndezfje"]
        d = dict(zip(cols, r))
        for k in ("djh", "FUND_TYPE", "yllb", "cblb", "fyfs", "zqxh", "bnzqslj"):
            d[k] = str(d[k]) if d[k] is not None else None
        for k in ("ryrq", "csrq", "tsbqsrq", "tsbjzrq", "jyrq"):
            d[k] = str(d[k]) if d[k] is not None else None
        for k in ("zje", "ptybn", "ptybw", "tsbybn", "tsbybw", "ybnqfje", "grziftw",
                  "tczhf", "tczif", "degwyzhf", "degwyzif", "bczhf", "jczhf",
                  "gfylbchbx", "xjzf", "zhzf", "bqljybnje", "bqqfje", "bnybnje", "bndezfje"):
            d[k] = _num(d[k])
        it = rsp_items.get(d["djh"], (None,) * 6)
        for k, val in zip(["明细行数", "Σzje", "Σybnje", "Σybwje", "Σgrziftw"], it[1:]):
            d[k] = _num(val)
        v = rsp_verdict.get(d["djh"], {})
        d["verdict"] = v.get("verdict")
        d["reconciliation_status"] = v.get("reconciliation_status")
        d["mismatched_fields"] = v.get("mismatched_fields") or None
        d["uncertainty_codes"] = v.get("uncertainty_codes") or None
        rows.append(d)
    _extend_special_rows(rows, coverage_facts, traces["resident"])
    rsp_groups.extend(_coverage_groups())
    _write_sheet(wb, "居民门特mz", rsp_groups, rows,
                 "城乡居民(FUND_TYPE∈91/92/93)×门特(yllb='12')×按项目付费(fyfs='0')，共3笔（Issue #81）。"
                 "目录独立重算 tsbybn/tsbybw/grziftw；起付 1300（周期序号=1，bqqfje 已交满→本次 0）；"
                 "基本医保degwyzhf按三级75%并受25万封顶；二次大病BIG_ILL_PAY另按30404/15202起付与60/70或65/75计算。"
                 "门特医疗救助采用住院档85%/100%、16万或无封顶；718年度表滞后，不把原值认定为交易前累计。详见逐字段与计算过程sheet。")

    _write_fixed_kidney(wb, cur, traces["employee_fixed"], coverage_facts)
    _write_special_validation(wb, traces, coverage_facts)
    conn.close()
    wb.save(OUT_PATH)
    print(f"已写出 {OUT_PATH}")
    for ws in wb.worksheets:
        print(f"  sheet[{ws.title}] 数据行数={ws.max_row - 3} 列数={ws.max_column}")


if __name__ == "__main__":
    main()
