"""政策问答统筹自付样板链路 Flow 测试。"""

import pytest


@pytest.mark.asyncio
async def test_policy_qa_pooling_self_pay_flow_outputs_explainable_chain():
    """输入统筹自付问题后，输出必须包含上下文、分段比例、权威金额和复核结论。"""
    from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
    from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
    from src.runtime.policy_qa.models import PolicyQARequest, PolicyRule, SQLQueryResult
    from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator
    from src.runtime.policy_qa.question_rewriter import QuestionRewriter

    class FakeSQLFetcher:
        async def fetch_all_tables(self, settlement_id):
            return SQLQueryResult(
                yb_brdjxx={
                    "fund_type": "城镇职工",
                    "fund_type_raw": "城镇职工",
                    "PER_TYPE": "退休",
                    "PER_TYPE_raw": "退休人员",
                    "yllb": "普通住院",
                    "yllb_raw": "普通住院",
                },
                yb_dyxxnd={"fynd": "2025"},
                yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
                yb_zyfdxx={
                    "bdfyzje": 189085.85,
                    "bdybnzje": 164411.81,
                    "bdtczf": 4962.67,
                    "bdtczfje": 91759.51,
                    "bddegwyzf": 13407.93,
                    "bddegwyzfje": 53631.71,
                    "bdgryf": 43694.67,
                },
            )

    class FakeSearchEngine:
        def search(self, question, top_k=10, expr=None):
            return [
                PolicyRule(
                    rule_id="r1",
                    rule_type="支付比例",
                    amount_band="650-30000",
                    payment_ratio="0.15",
                    source_text="起付线以上至3万元部分，自付比例15%",
                    score=0.99,
                ).__dict__,
                PolicyRule(
                    rule_id="r2",
                    rule_type="支付比例",
                    amount_band="30000-40000",
                    payment_ratio="0.10",
                    source_text="3万元至4万元部分，自付比例10%",
                    score=0.98,
                ).__dict__,
                PolicyRule(
                    rule_id="r3",
                    rule_type="支付比例",
                    amount_band="40000-inf",
                    payment_ratio="0.05",
                    source_text="4万元以上部分，自付比例5%",
                    score=0.97,
                ).__dict__,
            ]

        def search_with_context(self, question, insu_type=None, med_type=None,
                                psn_type=None, top_k=10):
            """与 search() 同义，适配 PolicySearchAdapter 的接口请求。"""
            return self.search(question, top_k=top_k)

    orchestrator = PolicyQAOrchestrator(
        model_gateway=None,
        sql_fetcher=FakeSQLFetcher(),
        question_rewriter=QuestionRewriter(),
        search_engine=FakeSearchEngine(),
        fee_skill=FeeDecompositionSkill(),
        explanation_generator=ExplanationGenerator(model_gateway=None),
    )

    events = []
    async for event in orchestrator.process(
        PolicyQARequest(question="为什么我这次统筹自付这么多？", settlement_id="1671213")
    ):
        events.append(event)

    intent_done = next(event for event in events if event.step == "intent_detection" and event.status == "done")
    query_done = next(event for event in events if event.step == "settlement_query" and event.status == "done")
    policy_done = next(event for event in events if event.step == "policy_rule_search" and event.status == "done")
    explanation_done = next(event for event in events if event.step == "answer_generation" and event.status == "done")
    trace_done = next(event for event in events if event.step == "trace_result" and event.status == "done")

    assert intent_done.detail["target_fee_item"] == "pooling_self_pay"
    assert query_done.detail["settlement_id"] == "1671213"
    assert policy_done.detail["rules_count"] == 3
    assert policy_done.policy_cards
    assert explanation_done.answer
    assert explanation_done.answer_status == "complete"
    assert not hasattr(explanation_done, "patient_view")
    assert not hasattr(explanation_done, "office_view")
    assert trace_done.detail["status"] == "success"
    assert trace_done.answer_status == "complete"
