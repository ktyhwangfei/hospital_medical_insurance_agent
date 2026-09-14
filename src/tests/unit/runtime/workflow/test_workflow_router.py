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
