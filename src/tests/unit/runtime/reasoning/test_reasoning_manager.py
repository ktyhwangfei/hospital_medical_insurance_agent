"""ReasoningStateManager 单元测试

对应评估报告任务 1.6 / 2.4 验证标准：
- UT: 推理链正确序列化/反序列化
- UT: WorkflowInstance 扩展 reasoning_state 后序列化/反序列化
"""

from src.runtime.reasoning.manager import ReasoningStateManager
from src.runtime.runtime_state.models import (
    ReasoningState,
    ReasoningStep,
    StepState,
    WorkflowInstance,
)


def test_get_or_create_returns_same_state():
    """同一会话重复获取返回同一推理状态。"""
    manager = ReasoningStateManager()
    first = manager.get_or_create("sess-001", workflow_id="wf-1")
    second = manager.get_or_create("sess-001")

    assert first is second
    assert first.session_id == "sess-001"
    assert first.workflow_id == "wf-1"


def test_add_step_appends_to_chain():
    """添加推理步骤：链增长且字段完整（含 source_memory_ids，§5.3）。"""
    manager = ReasoningStateManager()
    step = manager.add_step(
        "sess-001",
        claim="结算金额为 100 元",
        kind="fact",
        confidence=0.9,
        citations=["policy-001"],
        source_memory_ids=["m-001"],
    )

    assert isinstance(step, ReasoningStep)
    assert step.source_memory_ids == ["m-001"]
    assert step.citations == ["policy-001"]
    chain = manager.get_chain("sess-001")
    assert len(chain) == 1
    assert chain[0].claim == "结算金额为 100 元"


def test_add_step_with_depends_on():
    """推理步骤可声明依赖关系。"""
    manager = ReasoningStateManager()
    step1 = manager.add_step("sess-001", claim="事实一")
    step2 = manager.add_step("sess-001", claim="推论一", kind="inference", depends_on=[step1.step_id])

    assert step2.depends_on == [step1.step_id]


def test_hypothesis_lifecycle():
    """假设生命周期：open → confirmed（自动转为 verified 步骤）/ rejected。"""
    manager = ReasoningStateManager()
    hyp = manager.add_hypothesis("sess-001", "患者可能漏缴费用")

    assert hyp.status == "open"
    assert len(manager.get_open_hypotheses("sess-001")) == 1

    # 确认：状态变更 + 自动追加 verified 推理步骤
    assert manager.confirm_hypothesis("sess-001", hyp.hypothesis_id) is True
    assert manager.get_open_hypotheses("sess-001") == []
    chain = manager.get_chain("sess-001")
    assert any(s.kind == "verified" and s.claim == hyp.statement for s in chain)

    # 拒绝另一个假设
    hyp2 = manager.add_hypothesis("sess-001", "假设二")
    assert manager.reject_hypothesis("sess-001", hyp2.hypothesis_id) is True
    assert manager.get_open_hypotheses("sess-001") == []


def test_confirm_hypothesis_unknown_session_or_id():
    """对不存在的会话/假设确认返回 False。"""
    manager = ReasoningStateManager()
    assert manager.confirm_hypothesis("sess-404", "hyp-x") is False
    manager.add_hypothesis("sess-001", "假设")
    assert manager.confirm_hypothesis("sess-001", "hyp-404") is False


def test_get_chain_summary_format():
    """推理链摘要格式为 [kind] claim，供 LLM Context 消费。"""
    manager = ReasoningStateManager()
    manager.add_step("sess-001", claim="事实一", kind="fact")
    manager.add_step("sess-001", claim="推论一", kind="inference")

    summary = manager.get_chain_summary("sess-001")

    assert summary == ["[fact] 事实一", "[inference] 推论一"]


def test_build_reasoning_context():
    """注入 RuntimeContext 的推理上下文结构。"""
    manager = ReasoningStateManager()
    manager.add_step("sess-001", claim="事实一")
    manager.add_hypothesis("sess-001", "待验证假设")

    ctx = manager.build_reasoning_context("sess-001")

    assert ctx["total_steps"] == 1
    assert ctx["total_hypotheses"] == 1
    assert ctx["open_hypotheses"] == ["待验证假设"]
    assert ctx["chain_summary"] == ["[fact] 事实一"]


def test_clear_removes_state():
    """清除会话推理状态。"""
    manager = ReasoningStateManager()
    manager.add_step("sess-001", claim="事实一")
    manager.clear("sess-001")

    assert manager.get_chain("sess-001") == []
    assert manager.build_reasoning_context("sess-001") == {}


def test_reasoning_state_serialization_roundtrip():
    """评估报告任务 2.4：ReasoningState 序列化/反序列化。"""
    manager = ReasoningStateManager()
    manager.add_step(
        "sess-001", claim="事实一", kind="fact",
        citations=["c-1"], source_memory_ids=["m-1"],
    )
    manager.add_hypothesis("sess-001", "假设一")

    state = manager.get_or_create("sess-001")
    data = state.model_dump(mode="json")
    restored = ReasoningState.model_validate(data)

    assert restored.session_id == "sess-001"
    assert len(restored.chain) == 1
    assert restored.chain[0].source_memory_ids == ["m-1"]
    assert len(restored.hypotheses) == 1


def test_workflow_instance_with_reasoning_state_roundtrip():
    """评估报告任务 1.6：WorkflowInstance 扩展 reasoning_state 后序列化/反序列化。"""
    instance = WorkflowInstance(
        workflow_id="wf-1",
        scenario="settlement_exception_guidance",
        status="running",
        steps=[StepState(
            step_id="s-1",
            status="done",
            reasoning_chain=[ReasoningStep(step_id="rs-1", claim="中间结论")],
        )],
        reasoning_state=ReasoningState(
            session_id="sess-001",
            workflow_id="wf-1",
            chain=[ReasoningStep(step_id="rs-2", claim="事实", kind="fact")],
        ),
    )

    data = instance.model_dump(mode="json")
    restored = WorkflowInstance.model_validate(data)

    assert restored.reasoning_state is not None
    assert restored.reasoning_state.chain[0].step_id == "rs-2"
    assert restored.steps[0].reasoning_chain[0].claim == "中间结论"
