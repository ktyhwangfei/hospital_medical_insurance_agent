"""费用分解字段映射 Excel 导出（567 实测口径）。

从真实分解投影 JSON（scripts/eval 或 .scratch 下的 to_public_contract_dict 产物）
生成「后端字段 ↔ 页面展示」映射工作簿，供业务核对字段口径。

用法：
    uv run python scripts/eval/fee_field_mapping_export.py [projection.json] [输出.xlsx]
默认读取 .scratch/567-dataflow/02-public-projection.json（567 真实投影）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]

# ── 与前端 fee-explanation.ts FIELD_TO_DISPLAY 同口径的映射表 ──

ROW_GROUP = {
    "费用总金额": "费用构成", "医保范围内金额": "费用构成", "医保范围外金额": "费用构成", "自付二": "费用构成",
    "起付金额": "起付与基金支付", "基金合计": "起付与基金支付", "统筹基金支付": "起付与基金支付", "大额支付": "起付与基金支付",
    "自付一": "自付构成", "统筹自付": "自付构成", "大额个人自付": "自付构成",
    "退休补助": "补助", "军残补助": "补助", "公疗补助": "补助", "退役医疗费支付": "补助",
    "大病保险支付": "大病与医疗救助", "民政救助支付": "大病与医疗救助",
    "个人支付总金额": "个人支付合计",
    "账户支付": "支付方式", "现金支付": "支付方式",
}

FIELD_TO_DISPLAY = {
    # FIELD_CANDIDATES（展示口径 → 后端 label 候选）反向
    "本次起付承担": "起付金额", "本次起付金额": "起付金额", "起付金额": "起付金额",
    "大额支付": "大额支付", "大额互助支付": "大额支付",
    "大额个人自付": "大额个人自付", "大额自付": "大额个人自付",
    "退休补充保险补助": "退休补助", "退休补助": "退休补助",
    "军残支付": "军残补助", "军残补助": "军残补助",
    "公疗补充支付": "公疗补助", "公疗补助": "公疗补助",
    "医疗救助支付": "民政救助支付", "民政救助支付": "民政救助支付",
    "大病保险支付（二次保障）": "大病保险支付", "大病保险支付": "大病保险支付",
    "最终个人承担": "个人支付总金额", "个人应付（对照现金与账户合计）": "个人支付总金额", "个人支付总金额": "个人支付总金额",
    # 门特 mz 字段 label（employee_outpatient_special._FIELD_LABELS）
    "总费用": "费用总金额", "费用总金额": "费用总金额",
    "医保内费用": "医保范围内金额", "医疗保险范围内金额": "医保范围内金额",
    "医保外费用": "医保范围外金额", "医疗保险范围外金额": "医保范围外金额",
    "个人支付自付（二）金额": "自付二", "先行自付": "自付二",
    "统筹基金支付金额": "统筹基金支付", "统筹自付金额": "统筹自付",
    "门诊大额基金支付金额": "大额支付", "大额自付金额": "大额个人自付",
    "补充保险支付金额": "退休补助", "残疾军人补助支付金额": "军残补助",
    "单位补充医疗保险（原公疗）支付金额": "公疗补助",
    "大病支付": "大病保险支付", "救助支付": "民政救助支付",
    "个人支付自付（一）金额": "自付一", "原始个人自付一": "自付一",
    "定额范围内原始自付一（含起付）": "自付一",
    # 分桶/汇总子项：计入对应合计行
    "先行自付（明细汇总）": "自付二",
    "医保内个人自付一的大病支付": "大病保险支付", "按比例先行自付的大病支付": "大病保险支付",
    "医保内剩余个人负担的救助": "民政救助支付", "按比例先行自付剩余负担的救助": "民政救助支付",
    # 特殊病/普通门诊双套事实条目
    "特殊病医保内": "医保范围内金额", "普通门诊医保内": "医保范围内金额",
    "特殊病医保外": "医保范围外金额", "普通门诊医保外": "医保范围外金额",
}
# 与展示行同名的直接回环
for _label in ROW_GROUP:
    FIELD_TO_DISPLAY.setdefault(_label, _label)

CHECK_STATUS_CN = {"matched": "一致", "mismatched": "不一致", "not_verifiable": "暂不能核对", "not_applicable": "不适用"}

FEE_ITEM_FIELDS = [
    ("line_id", "行号", "行键"), ("item_code", "项目编码", "展开区"), ("item_name", "项目名称", "首列"),
    ("item_type", "项目类型", "首列附注"), ("fee_date", "费用发生日期", "展开区"),
    ("unit_price", "单价（元）", "展开区"), ("quantity", "数量", "展开区"), ("total_fee", "总金额（元）", "明细列"),
    ("observed_in_scope", "医保内账面（元）", "明细列"), ("observed_out_scope", "医保外账面（元）", "明细列"),
    ("observed_self_pay_2", "自付二账面（元）", "明细列"),
    ("calculated_in_scope", "医保内计算（元）", "展开区"), ("calculated_out_scope", "医保外计算（元）", "展开区"),
    ("calculated_self_pay_2", "自付二计算（元）", "展开区"),
    ("division_method", "划分方式", "关键原因"), ("self_pay_ratio", "采用自付比例", "关键原因"),
    ("included_ratio", "纳入比例", "展开区"), ("unit_price_limit", "采用限价（元）", "展开区"),
    ("limit_source", "限价来源", "展开区"), ("ratio_source", "比例来源", "展开区"),
    ("classification_label", "目录类别", "明细列"), ("classification_code", "目录类别码", "展开区"),
    ("centralized_procurement", "集采标识", "展开区"), ("catalog_entry_id", "目录条目", "展开区"),
    ("effective_from", "目录生效日期", "展开区"), ("effective_to", "目录截止日期", "展开区"),
    ("settlement_price_limit", "明细结算时限价（SP_SCALE）", "展开区"),
    ("a_ypbs", "集采（A_ypbs）", "展开区"), ("a_mzxj", "门诊限价（A_mzxj）", "展开区"),
    ("a_zyxj", "住院限价（A_zyxj）", "展开区"), ("a_xbbl", "超限价自付比例（A_xbbl）", "展开区"),
    ("ypfl", "药品分类（ypfl）", "展开区"), ("bzjg", "自制剂标准价格（bzjg）", "展开区"),
    ("status", "行状态", "内部"), ("verification_status", "验证状态", "内部"),
    ("explainable", "可解释", "内部"), ("explanation_reason", "不可解释原因", "展开区"),
    ("conditions", "条件记录", "展开区"), ("formulas", "算式记录", "展开区"),
    ("notes", "备注", "展开区"), ("decision_path", "判定路径", "展开区"),
    ("calculation_refs", "计算引用", "内部"), ("reconciliations", "逐项核对", "展开区"),
    ("explanation", "逐行解释", "展开区"),
]


def _header(ws, columns: list[str], widths: list[int]) -> None:
    header_fill = PatternFill("solid", fgColor="DDEBF7")
    for index, (name, width) in enumerate(zip(columns, widths), start=1):
        cell = ws.cell(row=1, column=index, value=name)
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A2"


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".scratch/567-dataflow/02-public-projection.json"
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else source.parent / "567-字段映射.xlsx"
    payload = json.loads(source.read_text(encoding="utf-8"))

    fields = [f for f in payload["fields"] if "." not in f["field_code"]]
    facts = payload.get("settlement_facts") or {}
    fact_items = facts.get("items") or []
    payments = facts.get("payment_items") or []
    fee_items = payload.get("fee_items") or []
    rule_groups = payload.get("rule_choices") or []
    calculations = {c["calculation_id"]: c for c in payload.get("calculations") or []}

    wb = Workbook()

    # ── Sheet1 字段映射 ─────────────────────────────────────────
    ws = wb.active
    ws.title = "字段映射"
    _header(ws, ["字段代码", "后端含义", "页面显示行", "所在分组", "本单账面金额",
                 "本单计算金额", "核对状态", "是否单独成行", "金额计入说明"], [16, 34, 18, 14, 14, 14, 12, 12, 46])
    fact_values = {item.get("label"): item.get("value") for item in fact_items}
    shown_labels = {FIELD_TO_DISPLAY.get(item.get("label") or "", item.get("label")) for item in fact_items}
    for f in fields:
        display = FIELD_TO_DISPLAY.get(f["label"])
        shown = display is not None and (display in shown_labels or display in {p.get("label") for p in payments})
        included = display or "未映射（请反馈）"
        note = f"金额显示在「{display}」行" if shown else (
            f"为「{display}」行的分项/汇总，数值已含在其中" if display else "页面未单独展示")
        ws.append([f["field_code"], f["label"], display or "—", ROW_GROUP.get(display or "", "其他"),
                   f.get("observed_amount"), f.get("calculated_amount"),
                   CHECK_STATUS_CN.get(f.get("check_status"), f.get("check_status")),
                   "是" if shown else "否（见明细区）", note])

    # ── Sheet1b 模板行核对：模板显示值 vs 内核计算值 ────────────
    ws1b = wb.create_sheet("模板行核对")
    _header(ws1b, ["模板键", "模板含义", "结果字段", "页面显示值", "内核计算值", "核对状态", "说明"],
            [18, 28, 16, 16, 16, 12, 40])
    template = (payload.get("settlement_facts") or {}).get("display_template") or {}
    zero_texts = {None, "", "0", "0.0", "0.00", "0.0000", "0.000000"}
    for item in template.get("fields") or []:
        if item.get("section") == "basic":
            continue
        code = item.get("field_code")
        result = next((f for f in payload["fields"] if f["field_code"] == code), None) if code else None
        value, calculated = item.get("value"), (result or {}).get("calculated_amount")
        if result is None:
            note = "模板行无对应结果字段：仅展示原单账面值，无独立解释"
        elif value in zero_texts and calculated not in zero_texts:
            note = "模板绑定列为空/零但内核计算出金额：数值丢失，需修正模板或回填"
        else:
            note = "页面显示与内核一致"
        ws1b.append([item.get("key"), item.get("label"), code or "—", value, calculated,
                     (result or {}).get("check_status") or "—", note])

    # ── Sheet2 结算事实条目 ────────────────────────────────────
    ws2 = wb.create_sheet("结算事实条目")
    _header(ws2, ["事实条目", "页面显示行", "所在分组", "本单值"], [26, 18, 14, 16])
    for item in fact_items:
        label = item.get("label")
        display = FIELD_TO_DISPLAY.get(label, label)
        ws2.append([label, display, ROW_GROUP.get(display, "其他"), item.get("value")])
    for item in payments:
        ws2.append([item.get("label"), item.get("label"), "支付方式", item.get("value")])

    # ── Sheet3 费用明细字段映射 ────────────────────────────────
    ws3 = wb.create_sheet("费用明细字段映射")
    _header(ws3, ["字段名", "含义", "页面位置", "他克莫司胶囊行示例"], [26, 30, 12, 40])
    sample = fee_items[0] if fee_items else {}
    for key, meaning, where in FEE_ITEM_FIELDS:
        value = sample.get(key)
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
        ws3.append([key, meaning, where, str(text) if text is not None else ""])

    # ── Sheet4 档位与来源映射 ──────────────────────────────────
    ws4 = wb.create_sheet("档位与来源映射")
    _header(ws4, ["规则组", "规则ID", "档位名称", "数值", "单位", "状态", "版本", "来源", "确认状态"],
            [26, 16, 34, 10, 14, 10, 14, 50, 20])
    for group in rule_groups:
        for c in group.get("candidates") or []:
            ws4.append([group.get("title"), c.get("rule_id"), c.get("name"), c.get("value"), c.get("unit"),
                        c.get("status"), c.get("version"), c.get("source"), c.get("confirmation_status")])

    # ── Sheet5 计算记录 ────────────────────────────────────────
    ws5 = wb.create_sheet("计算记录")
    _header(ws5, ["计算ID", "公式（模型与页面同源）", "结果", "取整"], [34, 80, 14, 34])
    for calc in payload.get("calculations") or []:
        ws5.append([calc["calculation_id"], calc.get("formula"), calc.get("result"), calc.get("rounding_rule")])

    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)
    print(f"已生成: {output}")
    print(f"字段映射 {len(fields)} 行 | 事实条目 {len(fact_items)} + 支付 {len(payments)} | "
          f"明细字段 {len(FEE_ITEM_FIELDS)} | 档位 {sum(len(g.get('candidates') or []) for g in rule_groups)} | "
          f"计算记录 {len(calculations)}")


if __name__ == "__main__":
    main()
