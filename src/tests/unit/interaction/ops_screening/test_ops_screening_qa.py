"""运营问数对筛查结果的口径、对账和下钻。"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

import pytest

from src.interaction.ops_screening.intent import parse_screening_question
from src.interaction.ops_screening.models import (
    FindingBook,
    ScreeningFinding,
    ScreeningKind,
    ScreeningResultsMissing,
    ScreeningRun,
    VerifyMark,
)
from src.interaction.ops_screening.reader import MemoryScreeningReader, SqlServerScreeningReader
from src.interaction.ops_screening.service import answer_screening, build_patient_speech
from src.interaction.ops_screening.sql import findings_sql, latest_run_sql, verify_sql
from src.runtime.policy_qa.ops_screening_public import answer_ops_screening

TODAY = datetime(2026, 11, 16, 9, 0)


def _money(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("0.01"))


def _run(run_id: str, *, finished: datetime, start: datetime, end: datetime, status: str = "succeeded") -> ScreeningRun:
    return ScreeningRun(
        run_id=run_id,
        started_at=finished,
        finished_at=finished,
        time_range_start=start,
        time_range_end=end,
        status=status,
    )


def _finding(
    finding_id: str,
    *,
    run_id: str = "run-new",
    amount: str | None = "100.00",
    finding_type: str = "mismatch",
    primary: str | None = None,
    settlement_key: str = "T001",
    rule_title: str = "甲状腺癌重复收费",
    department_name: str = "内科",
    evidence_clause: str = "原条款甲",
    fee_line_id: str = "L1",
    verify_status: str = "pending",
) -> ScreeningFinding:
    money = _money(amount)
    return ScreeningFinding(
        finding_id=finding_id,
        primary_finding_id=primary or finding_id,
        run_id=run_id,
        rule_id="rule-a" if rule_title == "甲状腺癌重复收费" else "rule-b",
        rule_title=rule_title,
        source_clause=evidence_clause,
        settlement_key=settlement_key,
        fee_line_id=fee_line_id,
        item_code="ITEM",
        item_name="甲状腺癌根治术",
        amount=money,
        finding_type=finding_type,
        evidence_clause=evidence_clause,
        evidence_facts="同单同时收取根治术与扩大根治术",
        verify_status=verify_status,
        department_name=department_name,
        fee_item_name="甲状腺癌根治术",
        fee_amount=money,
        fee_item_code="ITEM",
    )


def _reader() -> MemoryScreeningReader:
    runs = [
        _run(
            "run-old",
            finished=datetime(2026, 3, 1, 9, 0),
            start=datetime(2025, 1, 1),
            end=datetime(2025, 12, 31, 23, 59, 59),
        ),
        _run(
            "run-new",
            finished=datetime(2026, 4, 2, 9, 0),
            start=datetime(2026, 1, 1),
            end=datetime(2026, 3, 31, 23, 59, 59),
        ),
        _run(
            "run-failed",
            finished=datetime(2026, 5, 1, 9, 0),
            start=datetime(2026, 1, 1),
            end=datetime(2026, 3, 31, 23, 59, 59),
            status="failed",
        ),
    ]
    findings = [
        _finding("F1", amount="100.00", settlement_key="T001", department_name="内科"),
        _finding("F2", amount="40.00", settlement_key="T002", department_name="外科", fee_line_id="L2"),
        _finding(
            "F3",
            amount="10.00",
            settlement_key="T003",
            department_name="内科",
            rule_title="另一规则",
            fee_line_id="L3",
        ),
        _finding(
            "F4",
            amount="100.00",
            settlement_key="T001",
            primary="F1",
            evidence_clause="不应出现的从属条款",
        ),
        _finding(
            "F5",
            amount="70.00",
            settlement_key="T070",
            finding_type="insufficient_material",
            evidence_clause="材料不足条款甲",
            fee_line_id="L5",
        ),
        _finding("F-old", amount="999.00", run_id="run-old", settlement_key="T900", fee_line_id="L9"),
        _finding("F-failed", amount="888.00", run_id="run-failed", settlement_key="T800", fee_line_id="L8"),
    ]
    return MemoryScreeningReader(runs, findings)


def _ask(question: str, reader: MemoryScreeningReader | None = None):
    return answer_screening(question, reader=reader or _reader(), today=TODAY)


def test_metric_question_does_not_enter_screening() -> None:
    assert parse_screening_question("各科室药品费用排名").kind is ScreeningKind.NONE
    assert answer_screening("门诊统筹基金支付是多少") is None


def test_five_questions_share_one_batch_and_reconcile() -> None:
    reader = _reader()
    counted = _ask("2026年1月待核实疑点有多少条，涉及金额多少？", reader)
    assert counted is not None
    assert counted.answer_status == "complete"
    assert "待核实疑点 3 条，涉及金额 150.00 元" in counted.answer
    assert "明显对不上" in counted.caliber
    assert "主疑点" in counted.caliber
    assert "2026-04-02 09:00" in counted.caliber
    assert "材料不足条款甲" not in counted.answer
    assert "999.00" not in counted.answer
    assert "888.00" not in counted.answer
    assert "不应出现的从属条款" not in counted.answer

    by_rule = _ask("按规则分别是多少？", reader)
    assert by_rule is not None
    assert "甲状腺癌重复收费：2 条，140.00 元" in by_rule.answer
    assert "另一规则：1 条，10.00 元" in by_rule.answer
    assert "按规则合计 3 条，150.00 元，与总数一致。" in by_rule.answer
    assert _group_sum(by_rule.answer) == (3, Decimal("150.00"))

    by_dept = _ask("按科室分别是多少？", reader)
    assert by_dept is not None
    assert "内科：2 条，110.00 元" in by_dept.answer
    assert "外科：1 条，40.00 元" in by_dept.answer
    assert _group_sum(by_dept.answer) == (3, Decimal("150.00"))

    top = _ask("列出金额最高的几条", reader)
    assert top is not None
    assert "全量 3 条，150.00 元" in top.answer
    assert "疑点编号 F1" in top.answer
    assert "疑点编号 F2" in top.answer
    assert "疑点编号 F3" in top.answer
    assert "F4" not in top.answer
    assert "F5" not in top.answer

    opened = _ask("打开结算单 T001，看看依据是什么", reader)
    assert opened is not None
    assert "原条款甲" in opened.answer
    assert "费用行：L1" in opened.answer
    assert "不应出现的从属条款" not in opened.answer
    assert "材料不足条款甲" not in opened.answer
    speech = opened.answer.split("结算事实（给患者的话术，不含监管判断）：", 1)[1]
    speech = speech.split("口径：", 1)[0]
    for word in ("疑点", "符合", "不符合", "违规", "明显对不上", "材料不足", "待核实"):
        assert word not in speech
    assert "甲状腺癌根治术" in speech

    insufficient = _ask("材料不足的有哪些？", reader)
    assert insufficient is not None
    assert "材料不足另本 1 条，涉及金额 70.00 元" in insufficient.answer
    assert "默认待核实名单不含本本" in insufficient.answer
    assert "150.00" not in insufficient.answer
    assert "材料不足条款甲" in insufficient.answer


def test_zero_hits_is_a_real_zero_not_an_error() -> None:
    reader = MemoryScreeningReader(
        [_run(
            "run-empty",
            finished=datetime(2026, 4, 2, 9, 0),
            start=datetime(2026, 1, 1),
            end=datetime(2026, 3, 31, 23, 59, 59),
        )],
        [],
    )
    answered = _ask("待核实疑点有多少条，涉及金额多少？", reader)
    assert answered is not None
    assert answered.answer_status == "complete"
    assert "待核实疑点 0 条，涉及金额 0.00 元" in answered.answer


def test_no_succeeded_batch_does_not_invent_numbers() -> None:
    empty = MemoryScreeningReader([], [])
    answered = _ask("待核实疑点有多少条，涉及金额多少？", empty)
    assert answered is not None
    assert answered.answer_status == "unavailable"
    assert "还没有跑数结果" in answered.answer
    assert "规则管理" in answered.answer
    assert not re.search(r"\d+ 条", answered.answer)
    assert not re.search(r"\d+\.\d{2} 元", answered.answer)
    assert answered.show_table is False

    missing = MemoryScreeningReader(missing=True)
    missing_answer = _ask("待核实疑点有多少条，涉及金额多少？", missing)
    assert missing_answer is not None
    assert "还没有跑数结果" in missing_answer.answer
    assert not re.search(r"\d+ 条", missing_answer.answer)

    unread = MemoryScreeningReader(unreadable=True)
    unread_answer = _ask("按规则分别是多少？", unread)
    assert unread_answer is not None
    assert "暂时读不到筛查结果" in unread_answer.answer
    assert not re.search(r"\d+ 条", unread_answer.answer)


def test_time_range_does_not_borrow_another_batch() -> None:
    older = _ask("2025年1月待核实疑点有多少条，涉及金额多少？")
    assert older is not None
    assert "待核实疑点 1 条，涉及金额 999.00 元" in older.answer
    assert "150.00" not in older.answer

    outside = _ask("2024年1月待核实疑点有多少条，涉及金额多少？")
    assert outside is not None
    assert outside.answer_status == "unavailable"
    assert "还没有成功的跑数结果" in outside.answer
    assert "999.00" not in outside.answer
    assert "150.00" not in outside.answer
    assert not re.search(r"\d+ 条", outside.answer)


def test_default_open_hides_insufficient_material() -> None:
    opened = _ask("打开结算单 T070，看看依据是什么")
    assert opened is not None
    assert "材料不足条款甲" not in opened.answer
    assert "不能编造依据" in opened.answer


def test_verify_mark_updates_status_only() -> None:
    reader = _reader()
    answered = _ask("把疑点 F1 标为跟", reader)
    assert answered is not None
    assert "记为「跟」" in answered.answer
    assert "规则没有改动" in answered.answer
    stored = next(row for row in reader.findings("run-new", FindingBook.MISMATCH.value) if row.finding_id == "F1")
    assert stored.verify_status == "follow"
    assert stored.rule_title == "甲状腺癌重复收费"
    assert stored.amount == Decimal("100.00")
    counted = _ask("待核实疑点有多少条，涉及金额多少？", reader)
    assert counted is not None
    assert "待核实疑点 3 条，涉及金额 150.00 元" in counted.answer
    assert "已标跟 1 条" in counted.answer


def test_manage_actions_are_refused() -> None:
    answered = _ask("请批准规则并执行跑数")
    assert answered is not None
    assert answered.answer_status == "unavailable"
    assert "规则管理" in answered.answer
    assert "不能" in answered.answer
    assert not re.search(r"\d+ 条", answered.answer)


def test_patient_speech_rejects_regulatory_words() -> None:
    row = _finding("F1")
    speech = build_patient_speech(row)
    assert "疑点" not in speech
    leaked = ScreeningFinding(
        finding_id="F9",
        primary_finding_id="F9",
        run_id="run-new",
        rule_id="rule-a",
        rule_title="甲状腺癌重复收费",
        source_clause="原条款甲",
        settlement_key="T001",
        fee_line_id="L1",
        item_code="ITEM",
        item_name="甲状腺癌根治术",
        amount=Decimal("1.00"),
        finding_type="mismatch",
        evidence_clause="原条款甲",
        evidence_facts="事实",
        verify_status="pending",
        department_name="内科",
        fee_item_name="甲状腺癌根治术",
        fee_amount=Decimal("1.00"),
        fee_item_code="ITEM",
    )
    assert "符合" not in build_patient_speech(leaked)


def test_sql_keeps_user_input_out_of_the_statement() -> None:
    sql, names = latest_run_sql(bounded=True)
    assert "status = ?" in sql
    assert "TOP 1" in sql
    assert names == ["status", "asked_end", "asked_start"]
    findings = findings_sql()
    assert "primary_finding_id = f.finding_id" in findings
    assert "finding_type = ?" in findings
    assert "f.run_id = ?" in findings
    assert "T001" not in findings
    assert "OUTER APPLY" in findings
    updated = verify_sql()
    assert updated.startswith("UPDATE dbo.ai_screen_finding")
    assert "SET verify_status = ?" in updated
    assert "OUTPUT inserted.finding_id" in updated
    assert "ai_screen_rule" not in updated
    assert "amount" not in updated


def test_missing_result_table_is_not_a_zero() -> None:
    class Broken:
        def cursor(self):
            return self

        def execute(self, sql, params):
            raise Exception("Invalid object name 'dbo.ai_screen_run'.")

        def close(self):
            return None

    reader = SqlServerScreeningReader(connect=lambda: Broken())
    with pytest.raises(ScreeningResultsMissing):
        reader.latest_succeeded(None, None)


def test_sql_reader_drops_non_primary_rows() -> None:
    columns = [
        "finding_id", "primary_finding_id", "run_id", "rule_id", "settlement_key",
        "fee_line_id", "item_code", "item_name", "amount", "finding_type",
        "evidence_clause", "evidence_facts", "verify_status", "rule_title",
        "source_clause", "department_name", "fee_item_name", "fee_amount", "fee_item_code",
    ]

    class Cursor:
        description = [(name,) for name in columns]

        def cursor(self):
            return self

        def execute(self, sql, params):
            return None

        def fetchall(self):
            primary = ["F1", "F1", "run-new", "rule-a", "T001", "L1", "ITEM", "甲状腺癌根治术", Decimal("10.00"), "mismatch", "原条款甲", "事实", "pending", "甲状腺癌重复收费", "原条款甲", "内科", "甲状腺癌根治术", Decimal("10.00"), "ITEM"]
            duplicated = list(primary)
            child = ["F4", "F1", "run-new", "rule-a", "T001", "L1", "ITEM", "甲状腺癌根治术", Decimal("10.00"), "mismatch", "从属", "事实", "pending", "甲状腺癌重复收费", "从属", "内科", "甲状腺癌根治术", Decimal("10.00"), "ITEM"]
            return [tuple(primary), tuple(duplicated), tuple(child)]

        def close(self):
            return None

    reader = SqlServerScreeningReader(connect=lambda: Cursor())
    rows = reader.findings("run-new", "mismatch")
    assert [row.finding_id for row in rows] == ["F1"]


def test_verify_write_uses_output_rows_not_rowcount() -> None:
    class Cursor:
        rowcount = -1
        description = [("finding_id",)]
        params: list[object] = []

        def cursor(self):
            return self

        def execute(self, sql, params):
            assert "F9" not in sql
            self.params = list(params)

        def fetchall(self):
            if self.params == ["follow", "F9"]:
                return [("F9",)]
            return []

        def close(self):
            return None

    reader = SqlServerScreeningReader(connect=lambda: Cursor())
    assert reader.record_verify("F9", VerifyMark.FOLLOW) is True
    assert reader.record_verify("missing", VerifyMark.NOT_FOLLOW) is False


def test_public_result_carries_caliber_without_schema_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.interaction.ops_screening.service.get_reader",
        lambda: _reader(),
    )
    public = answer_ops_screening("待核实疑点有多少条，涉及金额多少？")
    assert public is not None
    payload = public.model_dump(mode="json")
    text = str(payload)
    assert "150.00" in public.answer
    assert payload["data_query_result"]["caliber"]
    assert "明显对不上" in payload["data_query_result"]["caliber"]
    for token in ("ai_screen", "o_Trade", "o_FeeItem", "o_Diagnose", "primary_finding_id", "verify_status"):
        assert token not in text


def _group_sum(answer: str) -> tuple[int, Decimal]:
    pairs = re.findall(r"- .+?：(\d+) 条，(\d+\.\d{2}) 元", answer)
    count = sum(int(item[0]) for item in pairs)
    amount = sum((Decimal(item[1]) for item in pairs), Decimal("0.00"))
    return count, amount
