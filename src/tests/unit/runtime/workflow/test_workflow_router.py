from src.domain.workflow.models import WorkflowDefinition, WorkflowStep
from src.runtime.workflow.router import WorkflowRouter


def _definition(workflow_id: str, keywords: list[str]) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        name=workflow_id,
        description=workflow_id,
        intent_keywords=keywords,
        steps=[WorkflowStep(step_id="s1", tool_id="tool_a")],
    )


def test_route_matches_highest_scoring_definition() -> None:
    router = WorkflowRouter(
        [
            _definition("wf_a", ["退费", "冲正"]),
            _definition("wf_b", ["起付线"]),
        ]
    )

    matched = router.route("这笔住院费用是否存在多扣未退款、需要冲正的情况？")

    assert matched is not None
    assert matched.workflow_id == "wf_a"


def test_route_returns_none_when_no_keyword_matches() -> None:
    router = WorkflowRouter([_definition("wf_a", ["退费"])])

    assert router.route("大额自付比例是多少？") is None


def test_amount_questions_route_to_data_query_not_policy_chat() -> None:
    """运营金额问法路由到问数 workflow（2026-09-16 验收缺陷：
    「门诊统筹基金支付是多少」曾落入政策问答链路答非所问）。"""
    from src.runtime.workflow.service import route_workflow_question

    for question in (
        "门诊统筹基金支付是多少",
        "门诊总费用是多少",
        "医保门诊结算总额",
        "门诊大额支付金额",
        "门诊个人账户支付一共多少",
    ):
        matched = route_workflow_question(question)
        assert matched is not None, f"未命中任何 workflow: {question}"
        assert matched.workflow_id == "wf_data_query", f"{question} → {matched.workflow_id}"


def test_ratio_questions_stay_in_policy_chat() -> None:
    """比例类政策咨询不被问数关键词误伤（「支付比例」≠「支付是多少」）。"""
    from src.runtime.workflow.service import route_workflow_question

    matched = route_workflow_question("门诊统筹基金支付比例怎么算")
    assert matched is None or matched.workflow_id != "wf_data_query"
