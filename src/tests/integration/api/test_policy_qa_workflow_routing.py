"""Workflow 路由分支的 API 测试（Tool 可视化管理与工作流编排 - 第一批增量）。"""

import json
import os

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event_name = ""
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if event_name and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def _client() -> TestClient:
    return TestClient(create_app())


def test_refund_question_without_settlement_id_asks_for_clarification():
    # 注意：question 不能包含"退费"/"冲正"字面词——它们命中全局高风险动作黑名单，
    # 会被 detect_blocked_actions 拦截为人工确认（见 test_high_risk_keyword_...）。
    response = _client().post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "这笔费用多扣未退款，能帮我核实一下吗？"},
    )
    events = _sse_events(response.text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")

    assert result["answer_status"] == "unavailable"
    assert "结算单号" in result["answer"]
    assert done["success"] is True


def test_refund_question_with_settlement_id_reports_unavailable_step_as_uncertainty(monkeypatch):
    from types import SimpleNamespace

    from src.runtime.policy_qa.settlement_data_provider import SettlementContext

    class FakeSettlementDataProvider:
        async def get_settlement_context(self, settlement_id: str) -> SettlementContext:
            return SettlementContext(
                settlement_id=settlement_id,
                basic_pooling_self_pay=4962.67,
                personal_total_pay=43694.67,
                coverage_status="complete",
            )

    monkeypatch.setattr(
        "src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider",
        lambda: FakeSettlementDataProvider(),
    )

    response = _client().post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={
            "question": "这笔费用多扣未退款，能帮我核实一下吗？",
            "settlement_id": "S001",
        },
    )
    events = _sse_events(response.text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")

    assert result["answer_status"] == "unavailable"
    assert any("tool_get_refund_record" in item for item in result["uncertainties"])
    assert done["success"] is True


def test_high_risk_keyword_still_routes_to_human_confirmation_not_workflow():
    response = _client().post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={
            "question": "请帮我冲正这笔多扣的退费",
            "settlement_id": "S001",
        },
    )
    events = _sse_events(response.text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")

    assert result["action_status"] == "waiting_human_confirmation"
    assert done["halt_reason"] == "waiting_human_confirmation"


def test_unrelated_question_does_not_trigger_workflow_branch(monkeypatch):
    """未命中 Workflow 关键词时不应调用风控/工作流路由，走既有 Skill 流程。"""
    from src.runtime.api import policy_qa_routes

    called = {"blocked": False}

    def _tracking_detect(question: str):
        called["blocked"] = True
        return []

    monkeypatch.setattr(policy_qa_routes, "detect_blocked_actions", _tracking_detect)

    response = _client().post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "大额自付比例是多少？"},
    )

    assert response.status_code == 200
    assert called["blocked"] is False


# ── 门诊结算解释 Workflow（标准核验链）──────────────────────────


def test_settlement_check_without_settlement_id_asks_for_clarification():
    # 问题命中 wf_outpatient_settlement_explain 的核验关键词（"结算单对不对"），
    # 且不包含高风险动作词与退费关键词。
    response = _client().post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "帮我核对一下这张结算单对不对"},
    )
    events = _sse_events(response.text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")

    assert result["answer_status"] == "unavailable"
    assert "结算单号" in result["answer"]
    assert done["success"] is True


def test_settlement_check_completes_full_chain_with_citations(monkeypatch):
    """结算事实 → 向量政策证据 → 确定性对比，全链路完成后结论可溯源到规则。"""
    from src.runtime.policy_qa.settlement_data_provider import SettlementContext
    from src.runtime.policy_qa.structured_policy_retriever import (
        StructuredPolicyEvidence,
        StructuredRetrievalResult,
    )

    class FakeSettlementDataProvider:
        async def get_settlement_context(self, settlement_id: str) -> SettlementContext:
            return SettlementContext(
                settlement_id=settlement_id,
                person_type="退休人员",
                insurance_type="城镇职工基本医疗保险",
                service_type="普通住院",
                hospital_level="三级医院",
                medical_insurance_inner_amount=10000.0,
                basic_pooling_payment=8500.0,
                personal_total_pay=1500.0,
                total_amount=10000.0,
                coverage_status="complete",
                amounts_reliable=True,
            )

    def _fake_retrieve_policy_evidence(settlement_context, host, port, **kwargs):
        return StructuredRetrievalResult(
            selected_evidence=[
                StructuredPolicyEvidence(
                    rule_id="R-CITY-HOSP-85",
                    source_text="三级医院城镇职工住院统筹支付比例为85%。",
                    payment_ratio="0.85",
                    doc_id="DOC-001",
                ),
                StructuredPolicyEvidence(
                    rule_id="R-CITY-HOSP-85-SUP",
                    source_text="三级医院城镇职工住院统筹支付比例85%（补充规定）。",
                    payment_ratio="85%",
                    doc_id="DOC-002",
                ),
            ],
        )

    monkeypatch.setattr(
        "src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider",
        lambda: FakeSettlementDataProvider(),
    )
    monkeypatch.setattr(
        "src.runtime.policy_qa.structured_policy_retriever.retrieve_policy_evidence",
        _fake_retrieve_policy_evidence,
    )

    response = _client().post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={
            "question": "帮我核对一下这张结算单对不对",
            "settlement_id": "S001",
        },
    )
    events = _sse_events(response.text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")

    assert result["answer_status"] == "complete"
    assert "一致" in result["answer"]
    assert result["verification_summary"]["calculation_checked"] is True
    assert result["verification_summary"]["policy_count"] == 2
    assert [c["title"] for c in result["citations"]] == [
        "R-CITY-HOSP-85",
        "R-CITY-HOSP-85-SUP",
    ]
    assert done["success"] is True


def test_settlement_check_reports_partial_when_policy_evidence_missing(monkeypatch):
    """向量检索零证据时对比无法给出确定结论，answer_status 应如实降级为 partial。"""
    from src.runtime.policy_qa.settlement_data_provider import SettlementContext
    from src.runtime.policy_qa.structured_policy_retriever import StructuredRetrievalResult

    class FakeSettlementDataProvider:
        async def get_settlement_context(self, settlement_id: str) -> SettlementContext:
            return SettlementContext(
                settlement_id=settlement_id,
                medical_insurance_inner_amount=10000.0,
                basic_pooling_payment=8500.0,
                coverage_status="complete",
                amounts_reliable=True,
            )

    monkeypatch.setattr(
        "src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider",
        lambda: FakeSettlementDataProvider(),
    )
    monkeypatch.setattr(
        "src.runtime.policy_qa.structured_policy_retriever.retrieve_policy_evidence",
        lambda settlement_context, host, port, **kwargs: StructuredRetrievalResult(),
    )

    response = _client().post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={
            "question": "帮我核对一下这张结算单对不对",
            "settlement_id": "S001",
        },
    )
    events = _sse_events(response.text)
    result = next(data["result"] for name, data in events if name == "result")

    assert result["answer_status"] == "partial"
    assert "证据不足" in result["answer"]
    assert result["verification_summary"]["policy_count"] == 0
    assert result["citations"] or result["uncertainties"]
    assert any("政策证据" in item for item in result["uncertainties"])
