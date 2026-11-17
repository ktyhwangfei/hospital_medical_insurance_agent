"""运营问数筛查问答走 policy-qa 的 data_query 入口。"""

from __future__ import annotations

import json
import os

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.tests.unit.interaction.ops_screening.test_ops_screening_qa import _reader

_SCHEMA_TOKENS = ("ai_screen", "o_Trade", "o_FeeItem", "o_Diagnose", "primary_finding_id", "verify_status")


def _events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name = ""
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if name and data_lines:
            events.append((name, json.loads("\n".join(data_lines))))
    return events


def _ask(client: TestClient, question: str) -> dict:
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": question, "mode": "data_query"},
    )
    assert response.status_code == 200
    events = _events(response.text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")
    assert done["success"] is True
    blob = response.text
    for token in _SCHEMA_TOKENS:
        assert token not in blob
    return result


def test_ops_screening_answers_reconcile_through_the_ops_entry(monkeypatch) -> None:
    monkeypatch.setattr("src.interaction.ops_screening.service.get_reader", lambda: _reader())
    client = TestClient(create_app())

    counted = _ask(client, "2026年1月待核实疑点有多少条，涉及金额多少？")
    assert counted["answer_status"] == "complete"
    assert "待核实疑点 3 条，涉及金额 150.00 元" in counted["answer"]
    assert "明显对不上" in counted["data_query_result"]["caliber"]
    assert "主疑点" in counted["data_query_result"]["caliber"]
    assert counted["verification_summary"]["calculation_checked"] is True

    grouped = _ask(client, "按规则分别是多少？")
    assert "按规则合计 3 条，150.00 元，与总数一致。" in grouped["answer"]

    opened = _ask(client, "打开结算单 T001，看看依据是什么")
    assert "原条款甲" in opened["answer"]
    assert "不应出现的从属条款" not in opened["answer"]
    speech = opened["answer"].split("结算事实（给患者的话术，不含监管判断）：", 1)[1]
    assert "疑点" not in speech.split("口径：", 1)[0]

    insufficient = _ask(client, "材料不足的有哪些？")
    assert "材料不足另本 1 条，涉及金额 70.00 元" in insufficient["answer"]
    assert "150.00" not in insufficient["answer"]


def test_ops_screening_without_a_batch_does_not_invent_numbers(monkeypatch) -> None:
    from src.interaction.ops_screening.reader import MemoryScreeningReader

    monkeypatch.setattr(
        "src.interaction.ops_screening.service.get_reader",
        lambda: MemoryScreeningReader([], []),
    )
    result = _ask(TestClient(create_app()), "待核实疑点有多少条，涉及金额多少？")
    assert result["answer_status"] == "unavailable"
    assert "还没有跑数结果" in result["answer"]
    assert "规则管理" in result["answer"]
    assert "data_query_result" not in result
    assert "0 条" not in result["answer"]
    assert "0.00" not in result["answer"]
