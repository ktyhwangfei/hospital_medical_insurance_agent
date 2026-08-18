"""TDD tests for LangGraph interrupt + human confirmation mode.

Verifies:
  - interrupt() pauses execution at high-risk step
  - POST /tasks/confirm {task_id, action: "confirm"} resumes execution
  - POST /tasks/confirm {task_id, action: "reject"} terminates execution
  - Checkpoint saves pause state
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
import pytest
from fastapi.testclient import TestClient

from src.runtime.api.schemas import AgentResponse
from src.runtime.langgraph.nodes import (
    after_human_confirmation,
    human_confirmation_node,
    response_build_node,
)
from src.runtime.langgraph.states import BaseAgentState


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _build_graph():
    """Return a compiled StateGraph with human_confirmation + response_build."""
    builder = StateGraph(BaseAgentState)
    builder.add_node("human_confirmation", human_confirmation_node)
    builder.add_node("response_build", response_build_node)
    builder.add_edge(START, "human_confirmation")
    builder.add_conditional_edges(
        "human_confirmation",
        after_human_confirmation,
        {"confirmed": "response_build", "rejected": "response_build"},
    )
    builder.add_edge("response_build", END)
    return builder.compile(checkpointer=MemorySaver())


def _make_initial_state(
    blocked_actions: list[str] | None = None,
    workflow_id: str = "wf-test",
) -> BaseAgentState:
    state: BaseAgentState = {
        "messages": [],
        "intent": "high_risk_action_confirmation",
        "role": "cashier",
        "workflow_id": workflow_id,
        "citations": [],
        "uncertainties": [],
        "requires_confirmation": False,
        "human_confirmed": False,
    }
    if blocked_actions:
        state["blocked_actions"] = blocked_actions
    return state


def _get_client():
    from src.runtime.api.app import create_app

    return TestClient(create_app())


def _chat_blocked(client: TestClient, message: str) -> dict:
    resp = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={
            "user_id": "user-001",
            "role": "cashier",
            "message": message,
            "patient_id": "P001",
            "encounter_id": "E001",
        },
    )
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Graph-level tests
# ---------------------------------------------------------------------------

class TestRiskConfirmationGraph:

    def test_graph_compiles_with_checkpointer(self):
        graph = _build_graph()
        assert graph is not None
        assert hasattr(graph, "invoke")

    def test_interrupt_pauses_execution(self):
        """interrupt() pauses execution at high-risk step."""
        graph = _build_graph()
        initial = _make_initial_state(blocked_actions=["退费"])

        result = graph.invoke(initial, {"configurable": {"thread_id": "t-pause-1"}})

        assert result.get("blocked_actions") == ["退费"]
        # human_confirmation_node hasn't completed, so its return
        # (requires_confirmation) is NOT yet applied.
        assert result.get("requires_confirmation") is False

    def test_confirm_resumes_execution(self):
        """Command(resume={"confirmed": true}) completes with human_confirmed=true."""
        graph = _build_graph()
        initial = _make_initial_state(blocked_actions=["退费"])
        thread_id = "t-confirm-1"

        graph.invoke(initial, {"configurable": {"thread_id": thread_id}})

        final = graph.invoke(
            Command(resume={"confirmed": True}),
            {"configurable": {"thread_id": thread_id}},
        )

        assert final.get("human_confirmed") is True
        assert final.get("requires_confirmation") is True
        response = final.get("response")
        assert isinstance(response, AgentResponse)
        assert response.status == "completed"
        assert "confirmed_actions" in response.result

    def test_reject_terminates_execution(self):
        """Command(resume={"confirmed": false}) completes with human_confirmed=false."""
        graph = _build_graph()
        initial = _make_initial_state(blocked_actions=["冲正"])
        thread_id = "t-reject-1"

        graph.invoke(initial, {"configurable": {"thread_id": thread_id}})

        final = graph.invoke(
            Command(resume={"confirmed": False}),
            {"configurable": {"thread_id": thread_id}},
        )

        assert final.get("human_confirmed") is False
        assert final.get("requires_confirmation") is True
        response = final.get("response")
        assert isinstance(response, AgentResponse)
        assert response.status == "rejected"
        assert "blocked_actions" in response.result

    def test_checkpoint_saves_pause_state(self):
        """Checkpoint preserves state between invoke calls."""
        graph = _build_graph()
        initial = _make_initial_state(
            blocked_actions=["退费", "撤销结算"],
            workflow_id="wf-checkpoint-test",
        )
        thread_id = "t-cp-1"

        graph.invoke(initial, {"configurable": {"thread_id": thread_id}})

        # get_state should return a snapshot with pending nodes
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        assert snap is not None
        # next is a tuple of node names that are pending (interrupted)
        assert len(snap.next) > 0

        # Verify state at checkpoint still has blocked_actions
        assert "退费" in snap.values.get("blocked_actions", [])

    def test_after_human_confirmation_routes_correctly(self):
        confirmed = _make_initial_state()
        confirmed["human_confirmed"] = True
        confirmed["requires_confirmation"] = True
        assert after_human_confirmation(confirmed) == "confirmed"

        rejected = _make_initial_state()
        rejected["human_confirmed"] = False
        rejected["requires_confirmation"] = True
        assert after_human_confirmation(rejected) == "rejected"


# ---------------------------------------------------------------------------
# API-level integration tests
# ---------------------------------------------------------------------------

class TestHumanConfirmationAPI:
    # c4838b1 重构删除了 /chat 与 /tasks/confirm 端点且无替代入口，
    # 高风险确认流程目前无法通过 API 触发/恢复（scenario_executor 内部逻辑仍存在）。
    # 待恢复 API 后移除 skip。
    @pytest.mark.skip(reason="API 端点 /chat + /tasks/confirm 已在 c4838b1 删除且无替代（功能缺口）")
    def test_chat_returns_waiting_human_confirmation(self):
        data = _chat_blocked(_get_client(), "我要办理退费")

        assert data["status"] == "waiting_human_confirmation"
        assert any("退费" in action for action in data.get("blocked_actions", []))
        assert len(data.get("tasks", [])) > 0
        assert data["scenario"] == "high_risk_action_confirmation"

    @pytest.mark.skip(reason="API 端点 /chat + /tasks/confirm 已在 c4838b1 删除且无替代（功能缺口）")
    def test_confirm_resumes_execution_via_api(self):
        client = _get_client()
        chat_data = _chat_blocked(client, "我要办理退费")
        task_id = chat_data["tasks"][0]["task_id"]

        resp = client.post(
            "/api/v1/medical-insurance-ai-agent/tasks/confirm",
            json={
                "task_id": task_id,
                "action": "confirm",
                "user_id": "user-001",
                "reason": "已核实费用，同意退费",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "confirmed"
        assert body["task_id"] == task_id
        assert body["confirmed_by"] == "user-001"

    @pytest.mark.skip(reason="API 端点 /chat + /tasks/confirm 已在 c4838b1 删除且无替代（功能缺口）")
    def test_reject_terminates_execution_via_api(self):
        client = _get_client()
        chat_data = _chat_blocked(client, "我要办理冲正")
        task_id = chat_data["tasks"][0]["task_id"]

        resp = client.post(
            "/api/v1/medical-insurance-ai-agent/tasks/confirm",
            json={
                "task_id": task_id,
                "action": "reject",
                "user_id": "user-001",
                "reason": "无法确认该操作",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        assert body["task_id"] == task_id
        assert body["result"].get("blocked") is True

    @pytest.mark.skip(reason="API 端点 /chat + /tasks/confirm 已在 c4838b1 删除且无替代（功能缺口）")
    def test_confirm_endpoint_validates_action(self):
        client = _get_client()
        resp = client.post(
            "/api/v1/medical-insurance-ai-agent/tasks/confirm",
            json={
                "task_id": "task-001",
                "action": "invalid",
                "user_id": "user-001",
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "confirm" in body["detail"]["message"] or "reject" in body["detail"]["message"]

    @pytest.mark.skip(reason="API 端点 /chat + /tasks/confirm 已在 c4838b1 删除且无替代（功能缺口）")
    def test_workflow_state_updates_after_confirm(self):
        client = _get_client()
        chat_data = _chat_blocked(client, "我要办理退费")
        task_id = chat_data["tasks"][0]["task_id"]
        workflow_id = chat_data["audit"]["workflow_id"]

        client.post(
            "/api/v1/medical-insurance-ai-agent/tasks/confirm",
            json={
                "task_id": task_id,
                "action": "confirm",
                "user_id": "user-001",
            },
        )

        wf_resp = client.get(
            f"/api/v1/medical-insurance-ai-agent/workflows/{workflow_id}",
        )
        assert wf_resp.status_code == 200
        wf_data = wf_resp.json()
        assert wf_data["status"] == "completed"
