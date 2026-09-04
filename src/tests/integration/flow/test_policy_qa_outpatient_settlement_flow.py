import json
from types import SimpleNamespace

import pytest

from src.runtime.api import policy_qa_routes
from src.runtime.policy_qa.models import PolicyQARequest


def _events(body: str) -> list[tuple[str, dict]]:
    parsed = []
    for block in body.split("\n\n"):
        name = next(
            (line.removeprefix("event:").strip() for line in block.splitlines() if line.startswith("event:")),
            "",
        )
        data = next(
            (line.removeprefix("data:").strip() for line in block.splitlines() if line.startswith("data:")),
            "",
        )
        if name and data:
            parsed.append((name, json.loads(data)))
    return parsed


@pytest.mark.asyncio
async def test_outpatient_question_routes_queries_verifies_and_finishes(monkeypatch):
    class Provider:
        async def run_semantic_query(self, query):
            assert query.scope.anchor.value == "MZ-FLOW-1"
            if query.scope.query_scope == "fee_item":
                return SimpleNamespace(
                    rows=[{
                        "ItemName": "乙类药品",
                        "Fee": 104.35,
                        "FeeIn": 0,
                        "FeeOut": 104.35,
                        "FeeItem_SelfPay2": 104.35,
                    }],
                    quality_status="complete",
                )
            return SimpleNamespace(
                rows=[{
                    "T_FeeAll": 1916.72,
                    "T_FeeIn": 1812.37,
                    "T_FeeOut": 104.35,
                    "T_FundPay": 1326.43,
                    "T_SelfPayAll": 590.29,
                    "T_SelfPay1": 485.94,
                    "T_SelfPay2": 104.35,
                    "T_BigSelfPay": 292.14,
                    "T_FirstPay": 838.56,
                    "T_PersonCountPay": 590.29,
                    "T_CashPay": 0,
                    "T_OfficalPay": 644.76,
                    "P_FundType": "职工",
                    "PN_PersonType": "退休",
                    "T_CureType": "普通门诊",
                    "HospitalLevel": "三级",
                    "P_JCLevel": "不享受伤残待遇",
                    "T_TradeDate": "2026-08-26",
                }],
                quality_status="complete",
            )

    monkeypatch.setattr(
        policy_qa_routes, "create_settlement_data_provider", lambda: Provider()
    )
    monkeypatch.setattr(
        policy_qa_routes,
        "retrieve_policy_evidence",
        lambda **_kwargs: SimpleNamespace(
            selected_evidence=[], missing_required_rules=["政策证据"]
        ),
    )
    monkeypatch.setattr(
        policy_qa_routes,
        "ensure_session_and_workflow",
        lambda **_kwargs: ("session-flow", "workflow-flow"),
    )
    monkeypatch.setattr(policy_qa_routes, "record_qa_task", lambda **_kwargs: None)
    monkeypatch.setattr(policy_qa_routes, "finalize_workflow", lambda *_args: None)

    chunks = [
        chunk async for chunk in policy_qa_routes._policy_qa_stream(
            PolicyQARequest(
                question="这次门诊结算对不对", settlement_id="MZ-FLOW-1"
            )
        )
    ]
    events = _events("".join(chunks))
    result = next(payload["result"] for name, payload in events if name == "result")

    assert result["scenario_id"] == "overall-settlement-verification"
    assert result["answer_status"] == "partial"
    total_amount = next(
        item for item in result["field_explanations"]
        if item["field_name"] == "费用总金额"
    )
    assert total_amount["value"] == 1916.72
    assert "1916.72" not in result["answer"]
    assert result["case_context"]["total_amount"] == 1916.72
    assert result["amount_checks"][0]["status"] == "passed"
    assert result["citations"] or result["uncertainties"]
    assert events[-1][0] == "done"
    assert events[-1][1]["halt_reason"] == "verified"

    followup_chunks = [
        chunk async for chunk in policy_qa_routes._policy_qa_stream(
            PolicyQARequest(
                question="为什么统筹自付这么多", settlement_id="MZ-FLOW-1"
            )
        )
    ]
    followup_events = _events("".join(followup_chunks))
    followup_result = next(
        payload["result"] for name, payload in followup_events if name == "result"
    )

    assert followup_result["scenario_id"] == "personal-liability-explanation"
    self_pay_one = next(
        item for item in followup_result["field_explanations"]
        if item["field_name"] == "个人自付一"
    )
    assert self_pay_one["value"] == 485.94
    assert "统筹自付 = 个人自付一 + 个人自付二" not in followup_result["answer"]
    assert "个人自付一 = 医保范围内金额 - 基金支付总金额" not in followup_result["answer"]
    assert "实际 " not in followup_result["answer"]
    assert "期望 " not in followup_result["answer"]
    assert followup_events[-1][1]["halt_reason"] == "verified"
