"""运营问数：用同一批筛查结果回答条数、分布、名单和下钻。

默认口径：最新成功批次 + 明显对不上 + 主疑点（同一费用只计一次）。
材料不足只有被点名才进入回答。没有成功批次时不编造数字。
对患者的话术只复述结算明细，不写监管判断。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal

from src.interaction.ops_screening.intent import parse_screening_question
from src.interaction.ops_screening.models import (
    FindingBook,
    PatientSpeechLeak,
    ScreeningAnswer,
    ScreeningFinding,
    ScreeningKind,
    ScreeningQuestion,
    ScreeningResultsMissing,
    ScreeningResultsUnreadable,
    ScreeningRun,
    VerifyMark,
)
from src.interaction.ops_screening.reader import ScreeningReader, get_reader

_ZERO = Decimal("0.00")
_VERIFY_LABELS = {
    "pending": "尚未标记",
    "follow": "已标跟",
    "not_follow": "已标不跟",
    "insufficient": "已标材料不足",
}
_MARK_LABELS = {
    VerifyMark.FOLLOW: "跟",
    VerifyMark.NOT_FOLLOW: "不跟",
    VerifyMark.INSUFFICIENT: "材料不足",
}
_PATIENT_FORBIDDEN = (
    "疑点",
    "符合",
    "不符合",
    "违规",
    "明显对不上",
    "材料不足",
    "待核实",
    "筛查",
)
_LEAKED_SCHEMA = (
    "ai_screen",
    "o_Trade",
    "o_FeeItem",
    "o_Diagnose",
    "primary_finding_id",
    "finding_type",
    "verify_status",
)


def answer_screening(
    question: str,
    *,
    reader: ScreeningReader | None = None,
    today: datetime | None = None,
) -> ScreeningAnswer | None:
    """不是筛查问法时返回 None，让原有指标问数继续处理。"""
    parsed = parse_screening_question(question, today=today)
    if parsed.kind is ScreeningKind.NONE:
        return None
    if parsed.kind is ScreeningKind.MANAGE_REFUSED:
        return _refuse_manage()
    source = reader if reader is not None else get_reader()
    try:
        return _answer(parsed, source)
    except ScreeningResultsMissing:
        return _no_batch("还没有跑数结果。请到规则管理批准规则并执行后再问。这次不能给出条数或金额。")
    except ScreeningResultsUnreadable:
        return _no_batch("暂时读不到筛查结果。请确认数据源后，到规则管理查看是否已有成功批次。这次不能给出条数或金额。")
    except PatientSpeechLeak:
        return _withhold("回答没有通过口径或话术检查，本次不展示条数和金额。")


def build_patient_speech(finding: ScreeningFinding) -> str:
    """只复述结算明细。监管名单上的判断不得出现在这段话里。"""
    item = finding.fee_item_name or finding.item_name or "未命名项目"
    if finding.fee_amount is None:
        speech = f"结算单 {finding.settlement_key} 的费用明细里没有对上这一费用行，不能摘录该项金额。"
    else:
        speech = (
            f"结算单 {finding.settlement_key} 含费用项目「{item}」，"
            f"明细金额 {_money_text(finding.fee_amount)} 元。"
        )
    sources = (finding.settlement_key, finding.item_name, finding.fee_item_name, finding.item_code)
    for word in _PATIENT_FORBIDDEN:
        if word in speech and not any(word in (source or "") for source in sources):
            raise PatientSpeechLeak(word)
    return speech


def _answer(parsed: ScreeningQuestion, reader: ScreeningReader) -> ScreeningAnswer:
    if parsed.kind is ScreeningKind.RECORD_VERIFY:
        return _record_verify(parsed, reader)
    run = reader.latest_succeeded(parsed.time_start, parsed.time_end)
    if run is None:
        return _missing_run(parsed, reader)
    book = (
        FindingBook.INSUFFICIENT_MATERIAL
        if parsed.kind is ScreeningKind.INSUFFICIENT
        else FindingBook.MISMATCH
    )
    rows = reader.findings(run.run_id, book.value)
    if parsed.kind is ScreeningKind.OPEN_SETTLEMENT:
        return _open(parsed, run, rows, reader)
    if parsed.kind is ScreeningKind.INSUFFICIENT:
        return _insufficient(parsed, run, rows)
    if parsed.kind is ScreeningKind.TOP_AMOUNT:
        return _top(parsed, run, rows, book)
    if parsed.kind in (ScreeningKind.GROUP_BY_RULE, ScreeningKind.GROUP_BY_DEPARTMENT):
        return _grouped(parsed, run, rows, book)
    return _counted(parsed, run, rows, book)


def _missing_run(parsed: ScreeningQuestion, reader: ScreeningReader) -> ScreeningAnswer:
    if parsed.time_start is None and parsed.time_end is None:
        return _no_batch("还没有跑数结果。请到规则管理批准规则并执行后再问。这次不能给出条数或金额。")
    other = reader.latest_succeeded(None, None)
    if other is None:
        return _no_batch("还没有跑数结果。请到规则管理批准规则并执行后再问。这次不能给出条数或金额。")
    window = _window_text(other)
    return _no_batch(
        f"所问时间范围（{parsed.time_label}）还没有成功的跑数结果。"
        f"请到规则管理对这个时间范围执行后再问。这次不能给出条数或金额。"
        f"最近一次成功批次的统计范围是 {window}，这里只说明批次时间。"
    )


def _counted(
    parsed: ScreeningQuestion,
    run: ScreeningRun,
    rows: list[ScreeningFinding],
    book: FindingBook,
) -> ScreeningAnswer:
    count, amount = _totals(rows)
    groups = _groups(rows, lambda row: row.rule_title or "未命名规则")
    if not _reconciled(count, amount, groups):
        return _withhold("分组合计与总数不一致，本次不展示条数和金额。")
    caliber = _caliber(parsed, run, book)
    headline = _headline(parsed, count, amount, book)
    marks = _mark_line(rows)
    answer = f"{headline}\n{marks}\n口径：{caliber}\n改规则请到规则管理，问数里不能改规则。"
    _reject_schema_leak(answer)
    return _table_answer(
        answer=answer,
        caliber=caliber,
        summary=headline,
        metric_id="screening.count",
        metric_name="待核实疑点" if book is FindingBook.MISMATCH else "材料不足",
        columns=(("item", "项目"), ("count", "条数"), ("amount", "金额（元）")),
        rows=({"item": "合计", "count": count, "amount": _as_float(amount)},),
        chart_name="金额",
        chart_labels=("合计",),
        chart_values=(_as_float(amount),),
        settlement_checked=False,
    )


def _grouped(
    parsed: ScreeningQuestion,
    run: ScreeningRun,
    rows: list[ScreeningFinding],
    book: FindingBook,
) -> ScreeningAnswer:
    by_rule = parsed.kind is ScreeningKind.GROUP_BY_RULE
    key_name = "规则" if by_rule else "科室"
    groups = _groups(
        rows,
        (lambda row: row.rule_title or "未命名规则") if by_rule
        else (lambda row: row.department_name or "未关联科室"),
    )
    count, amount = _totals(rows)
    if not _reconciled(count, amount, groups):
        return _withhold("分组合计与总数不一致，本次不展示条数和金额。")
    lines = [
        f"- {group['name']}：{group['count']} 条，{_money_text(group['amount'])} 元"
        for group in groups
    ]
    body = "\n".join(lines) if lines else "- （无）"
    caliber = _caliber(parsed, run, book)
    headline = f"按{key_name}合计 {count} 条，{_money_text(amount)} 元，与总数一致。"
    answer = f"{headline}\n{body}\n口径：{caliber}"
    _reject_schema_leak(answer)
    return _table_answer(
        answer=answer,
        caliber=caliber,
        summary=headline,
        metric_id="screening.group",
        metric_name=f"按{key_name}",
        columns=(( "name", key_name), ("count", "条数"), ("amount", "金额（元）")),
        rows=tuple(
            {"name": group["name"], "count": group["count"], "amount": _as_float(group["amount"])}
            for group in groups
        ),
        chart_name="金额",
        chart_labels=tuple(group["name"] for group in groups) or ("无",),
        chart_values=tuple(_as_float(group["amount"]) for group in groups) or (0.0,),
        settlement_checked=False,
    )


def _top(
    parsed: ScreeningQuestion,
    run: ScreeningRun,
    rows: list[ScreeningFinding],
    book: FindingBook,
) -> ScreeningAnswer:
    ordered = _by_amount(rows)
    count, amount = _totals(rows)
    shown = ordered[: parsed.top_n]
    shown_count, shown_amount = _totals(shown)
    caliber = _caliber(parsed, run, book)
    lines = [_finding_line(index, row) for index, row in enumerate(shown, start=1)]
    covered = "已列出全部。" if len(shown) == len(ordered) else (
        f"下面只是金额最高的 {len(shown)} 条，不是全量；全量仍是 {count} 条、{_money_text(amount)} 元。"
    )
    if len(shown) == len(ordered):
        if shown_count != count or shown_amount != amount:
            return _withhold("短名单与全量对不上，本次不展示条数和金额。")
    headline = f"金额最高的 {len(shown)} 条。全量 {count} 条，{_money_text(amount)} 元。{covered}"
    answer = headline + ("\n" + "\n".join(lines) if lines else "\n没有待列出的疑点。") + f"\n口径：{caliber}"
    _reject_schema_leak(answer)
    return _table_answer(
        answer=answer,
        caliber=caliber,
        summary=headline,
        metric_id="screening.top",
        metric_name="金额最高的疑点",
        columns=(
            ("finding_no", "疑点编号"),
            ("settlement_no", "结算单号"),
            ("rule_title", "规则"),
            ("department", "科室"),
            ("amount", "金额（元）"),
        ),
        rows=tuple(_finding_row(row) for row in shown),
        chart_name="金额",
        chart_labels=tuple(row.finding_id for row in shown) or ("无",),
        chart_values=tuple(_as_float(row.amount or _ZERO) for row in shown) or (0.0,),
        settlement_checked=False,
    )


def _insufficient(
    parsed: ScreeningQuestion,
    run: ScreeningRun,
    rows: list[ScreeningFinding],
) -> ScreeningAnswer:
    """材料不足另本。只有这一问才列出，默认待核实合计不进这里。"""
    ordered = _by_amount(rows)
    count, amount = _totals(rows)
    caliber = _caliber(parsed, run, FindingBook.INSUFFICIENT_MATERIAL)
    lines = [
        (
            f"- 疑点编号 {row.finding_id}，结算单 {row.settlement_key}，"
            f"金额 {_money_text(row.amount)} 元，原条款：{row.evidence_clause or row.source_clause or '原条款为空'}"
        )
        for row in ordered
    ]
    headline = _headline(parsed, count, amount, FindingBook.INSUFFICIENT_MATERIAL)
    answer = headline + ("\n" + "\n".join(lines) if lines else "\n（无）") + f"\n口径：{caliber}"
    _reject_schema_leak(answer)
    return _table_answer(
        answer=answer,
        caliber=caliber,
        summary=headline,
        metric_id="screening.insufficient",
        metric_name="材料不足",
        columns=(
            ("finding_no", "疑点编号"),
            ("settlement_no", "结算单号"),
            ("clause", "原条款"),
            ("amount", "金额（元）"),
        ),
        rows=tuple(
            {
                "finding_no": row.finding_id,
                "settlement_no": row.settlement_key,
                "clause": row.evidence_clause or row.source_clause,
                "amount": _as_float(row.amount or _ZERO),
            }
            for row in ordered
        ),
        chart_name="金额",
        chart_labels=tuple(row.finding_id for row in ordered) or ("无",),
        chart_values=tuple(_as_float(row.amount or _ZERO) for row in ordered) or (0.0,),
        settlement_checked=False,
    )


def _open(
    parsed: ScreeningQuestion,
    run: ScreeningRun,
    rows: list[ScreeningFinding],
    reader: ScreeningReader,
) -> ScreeningAnswer:
    chosen = _pick_open_targets(parsed, rows)
    caliber = _caliber(parsed, run, FindingBook.MISMATCH)
    if not chosen:
        hidden = _hidden_insufficient_clause(parsed, run, reader)
        answer = (
            "这批结果的默认待核实名单里没有这条明显对不上的疑点，不能编造依据。"
            "材料不足不在默认名单里。"
        )
        if hidden:
            answer += "若要看材料不足，请直接问「材料不足的有哪些」。"
        answer += f"\n口径：{caliber}"
        _reject_schema_leak(answer)
        if hidden and hidden in answer:
            return _withhold("材料不足混进了默认名单，本次不展示。")
        return _table_answer(
            answer=answer,
            caliber=caliber,
            summary="默认名单中没有这条明显对不上的疑点",
            metric_id="screening.open",
            metric_name="单笔依据",
            columns=(("note", "说明"),),
            rows=({"note": "默认名单中没有这条明显对不上的疑点"},),
            chart_name="金额",
            chart_labels=("无",),
            chart_values=(0.0,),
            settlement_checked=False,
            answer_status="complete",
        )
    blocks = []
    speeches = []
    for row in chosen:
        speech = build_patient_speech(row)
        speeches.append(speech)
        clause = row.evidence_clause or row.source_clause or "原条款为空"
        facts = row.evidence_facts or "对照事实为空"
        fee_fact = (
            f"结算明细对上的费用：{row.fee_item_name or row.item_name}，"
            f"明细金额 {_money_text(row.fee_amount)} 元，项目编码 {row.fee_item_code or row.item_code or '无'}。"
            if row.fee_amount is not None
            else "结算明细里没有对上这一费用行。"
        )
        blocks.append(
            "\n".join([
                f"疑点编号 {row.finding_id}",
                f"结算单 {row.settlement_key}",
                f"规则：{row.rule_title or '未命名规则'}",
                f"原条款：{clause}",
                f"对照事实：{facts}",
                f"费用行：{row.fee_line_id or '无'}，项目 {row.item_name or '无'}，筛查金额 {_money_text(row.amount)} 元",
                fee_fact,
                "结算事实（给患者的话术，不含监管判断）：",
                speech,
            ])
        )
    answer = (
        f"本批次默认名单中，该结算有 {len(chosen)} 条明显对不上的主疑点。以下只给医保办核实。\n"
        + "\n\n".join(blocks)
        + f"\n口径：{caliber}\n监管名单不写入上面的结算事实。"
    )
    _reject_schema_leak(answer)
    for speech in speeches:
        if speech not in answer:
            return _withhold("单笔回答没有带上结算事实。")
    return _table_answer(
        answer=answer,
        caliber=caliber,
        summary=f"已打开 {len(chosen)} 条明显对不上的疑点",
        metric_id="screening.open",
        metric_name="单笔依据",
        columns=(
            ("finding_no", "疑点编号"),
            ("settlement_no", "结算单号"),
            ("clause", "原条款"),
            ("fee_line", "费用行"),
            ("amount", "金额（元）"),
        ),
        rows=tuple(
            {
                "finding_no": row.finding_id,
                "settlement_no": row.settlement_key,
                "clause": row.evidence_clause or row.source_clause,
                "fee_line": row.fee_line_id,
                "amount": _as_float(row.amount or _ZERO),
                "rule_title": row.rule_title,
            }
            for row in chosen
        ),
        chart_name="筛查金额",
        chart_labels=tuple(row.finding_id for row in chosen),
        chart_values=tuple(_as_float(row.amount or _ZERO) for row in chosen),
        settlement_checked=any(row.fee_amount is not None for row in chosen),
    )


def _hidden_insufficient_clause(
    parsed: ScreeningQuestion,
    run: ScreeningRun,
    reader: ScreeningReader,
) -> str:
    """默认下钻不得把材料不足的条款写出来。返回条款文本供调用方自检。"""
    if not parsed.settlement_key:
        return ""
    hidden = [
        row for row in reader.findings(run.run_id, FindingBook.INSUFFICIENT_MATERIAL.value)
        if row.settlement_key == parsed.settlement_key
    ]
    return " ".join(row.evidence_clause for row in hidden if row.evidence_clause)


def _record_verify(parsed: ScreeningQuestion, reader: ScreeningReader) -> ScreeningAnswer:
    if parsed.verify_mark is None:
        return _no_batch("没有识别出要记的核实结论。可以说「把疑点编号标为跟、不跟或材料不足」。这次没有改任何记录。")
    finding_id = parsed.finding_id
    if not finding_id and parsed.rank is not None:
        run = reader.latest_succeeded(None, None)
        if run is None:
            return _no_batch("还没有跑数结果，不能记核实结论。请到规则管理执行后再试。")
        ordered = _by_amount(reader.findings(run.run_id, FindingBook.MISMATCH.value))
        if parsed.rank < 1 or parsed.rank > len(ordered):
            return _no_batch("按金额从高到低没有这一条，核实结论没有改。")
        finding_id = ordered[parsed.rank - 1].finding_id
    if not finding_id:
        return _no_batch("请给出疑点编号，或说「第N条标为跟」。这次没有改任何记录。")
    saved = reader.record_verify(finding_id, parsed.verify_mark)
    label = _MARK_LABELS[parsed.verify_mark]
    if not saved:
        return _no_batch(f"没有找到疑点编号 {finding_id}，核实结论没有改。规则也没有改。")
    answer = (
        f"已把疑点编号 {finding_id} 的核实结论记为「{label}」。"
        "规则没有改动。如需改规则，请到规则管理。"
        "这条仍留在原批次里，默认条数口径不变。"
    )
    _reject_schema_leak(answer)
    return ScreeningAnswer(
        answer=answer,
        answer_status="complete",
        caliber="只更新了该疑点的核实结论，没有改规则，也没有重算金额。",
        summary=f"核实结论已记为{label}",
        metric_id="screening.verify",
        metric_name="核实结论",
        columns=(("finding_no", "疑点编号"), ("mark", "核实结论")),
        rows=({"finding_no": finding_id, "mark": label},),
        chart_name="",
        chart_labels=(),
        chart_values=(),
        uncertainties=(),
        calculation_checked=False,
        settlement_checked=False,
        show_table=True,
    )


def _pick_open_targets(
    parsed: ScreeningQuestion,
    rows: list[ScreeningFinding],
) -> list[ScreeningFinding]:
    if parsed.settlement_key:
        return [row for row in _by_amount(rows) if row.settlement_key == parsed.settlement_key]
    if parsed.finding_id:
        return [row for row in rows if row.finding_id == parsed.finding_id]
    if parsed.rank is not None:
        ordered = _by_amount(rows)
        if 1 <= parsed.rank <= len(ordered):
            return [ordered[parsed.rank - 1]]
    return []


def _groups(rows: list[ScreeningFinding], key_of) -> list[dict[str, Decimal | int | str]]:
    buckets: dict[str, list[ScreeningFinding]] = {}
    for row in rows:
        buckets.setdefault(str(key_of(row)), []).append(row)
    groups = []
    for name, items in buckets.items():
        count, amount = _totals(items)
        groups.append({"name": name, "count": count, "amount": amount})
    groups.sort(key=lambda item: (-item["amount"], str(item["name"])))
    return groups


def _reconciled(
    count: int,
    amount: Decimal,
    groups: list[dict[str, Decimal | int | str]],
) -> bool:
    grouped_count = sum(int(item["count"]) for item in groups)
    grouped_amount = sum((item["amount"] for item in groups if isinstance(item["amount"], Decimal)), _ZERO)
    return grouped_count == count and grouped_amount == amount


def _totals(rows: list[ScreeningFinding]) -> tuple[int, Decimal]:
    amount = sum((row.amount for row in rows if row.amount is not None), _ZERO)
    return len(rows), amount.quantize(Decimal("0.01"))


def _by_amount(rows: list[ScreeningFinding]) -> list[ScreeningFinding]:
    return sorted(rows, key=lambda row: (-(row.amount or _ZERO), row.finding_id))


def _mark_line(rows: list[ScreeningFinding]) -> str:
    counts = Counter(row.verify_status or "pending" for row in rows)
    parts = [
        f"{_VERIFY_LABELS.get(key, '其他')} {counts.get(key, 0)} 条"
        for key in ("pending", "follow", "not_follow", "insufficient")
    ]
    other = sum(value for key, value in counts.items() if key not in _VERIFY_LABELS)
    if other:
        parts.append(f"其他 {other} 条")
    total = sum(counts.values())
    return "核实结论不改变条数：" + "、".join(parts) + f"（合计 {total} 条）。"


def _headline(
    parsed: ScreeningQuestion,
    count: int,
    amount: Decimal,
    book: FindingBook,
) -> str:
    scope = f"{parsed.time_label} " if parsed.time_label else ""
    if book is FindingBook.INSUFFICIENT_MATERIAL:
        return (
            f"{scope}材料不足另本 {count} 条，涉及金额 {_money_text(amount)} 元。"
            "默认待核实名单不含本本。"
        )
    return f"{scope}待核实疑点 {count} 条，涉及金额 {_money_text(amount)} 元。材料不足另本未计入。"


def _caliber(parsed: ScreeningQuestion, run: ScreeningRun, book: FindingBook) -> str:
    window = _window_text(run)
    finished = _clock(run.finished_at or run.started_at)
    asked = f"所问时间 {parsed.time_label}。" if parsed.time_label else ""
    if book is FindingBook.INSUFFICIENT_MATERIAL:
        kind = "本问才列出「材料不足」；默认待核实仍只含「明显对不上」。"
    else:
        kind = "只含「明显对不上」。材料不足未计入。"
    return (
        f"{asked}最新成功执行批次完成于 {finished}，统计范围 {window}。"
        f"{kind}金额与条数只计主疑点，同一费用只计一次。"
        "条数不按核实结论再过滤。"
    )


def _window_text(run: ScreeningRun) -> str:
    return f"{_clock(run.time_range_start)} 至 {_clock(run.time_range_end)}"


def _clock(value: datetime | None) -> str:
    if value is None:
        return "未记录"
    return value.strftime("%Y-%m-%d %H:%M")


def _money_text(value: Decimal | None) -> str:
    if value is None:
        return "空"
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _as_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _finding_line(index: int, row: ScreeningFinding) -> str:
    return (
        f"{index}. 疑点编号 {row.finding_id}，结算单 {row.settlement_key}，"
        f"规则 {row.rule_title or '未命名规则'}，科室 {row.department_name or '未关联科室'}，"
        f"金额 {_money_text(row.amount)} 元"
    )


def _finding_row(row: ScreeningFinding) -> dict[str, str | int | float | None]:
    return {
        "finding_no": row.finding_id,
        "settlement_no": row.settlement_key,
        "rule_title": row.rule_title,
        "department": row.department_name,
        "amount": _as_float(row.amount or _ZERO),
    }


def _table_answer(
    *,
    answer: str,
    caliber: str,
    summary: str,
    metric_id: str,
    metric_name: str,
    columns: tuple[tuple[str, str], ...],
    rows: tuple[dict[str, str | int | float | None], ...],
    chart_name: str,
    chart_labels: tuple[str, ...],
    chart_values: tuple[float, ...],
    settlement_checked: bool,
    answer_status: str = "complete",
) -> ScreeningAnswer:
    return ScreeningAnswer(
        answer=answer,
        answer_status=answer_status,  # type: ignore[arg-type]
        caliber=caliber,
        summary=summary,
        metric_id=metric_id,
        metric_name=metric_name,
        columns=columns,
        rows=rows,
        chart_name=chart_name,
        chart_labels=chart_labels,
        chart_values=chart_values,
        uncertainties=(),
        calculation_checked=True,
        settlement_checked=settlement_checked,
        show_table=True,
    )


def _no_batch(message: str) -> ScreeningAnswer:
    _reject_schema_leak(message)
    if _looks_like_a_number(message):
        message = "还没有可对账的跑数结果。请到规则管理执行后再问。这次不能给出条数或金额。"
    return ScreeningAnswer(
        answer=message,
        answer_status="unavailable",
        caliber="",
        summary=message,
        metric_id="screening.none",
        metric_name="筛查结果",
        columns=(),
        rows=(),
        chart_name="",
        chart_labels=(),
        chart_values=(),
        uncertainties=("还没有可对账的成功执行批次。",),
        calculation_checked=False,
        settlement_checked=False,
        show_table=False,
    )


def _refuse_manage() -> ScreeningAnswer:
    return _no_batch("问数里不能上传材料、批准规则、关闭规则或执行跑数。请到规则管理处理。这里不给出条数或金额。")


def _withhold(message: str) -> ScreeningAnswer:
    return ScreeningAnswer(
        answer=message,
        answer_status="unavailable",
        caliber="",
        summary=message,
        metric_id="screening.withhold",
        metric_name="筛查结果",
        columns=(),
        rows=(),
        chart_name="",
        chart_labels=(),
        chart_values=(),
        uncertainties=(message,),
        calculation_checked=False,
        settlement_checked=False,
        show_table=False,
    )


def _reject_schema_leak(text: str) -> None:
    for token in _LEAKED_SCHEMA:
        if token in text:
            raise PatientSpeechLeak(token)


def _looks_like_a_number(text: str) -> bool:
    import re
    return re.search(r"\d+\s*条|\d+\.\d{2}\s*元", text) is not None
