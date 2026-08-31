"""Issue #30 会话生命周期与轨迹持久化单元测试

覆盖：轨迹存储、会话状态机、升级工单闭环、所有权校验。
所有测试 monkeypatch 内存存储，不依赖 PostgreSQL 环境。
"""

from __future__ import annotations

import pytest

from src.data_platform.storage.policy_qa.trajectory_storage import (
    InMemoryTrajectoryStorage,
)
from src.data_platform.storage.session.in_memory import InMemorySessionStorage
from src.runtime.task_closure import service as task_service
from src.runtime.policy_qa import session_lifecycle


@pytest.fixture()
def memory_stores(monkeypatch):
    """注入内存实现：session 存储 / 轨迹存储 / task 工单存储"""
    sessions = InMemorySessionStorage()
    trajectories = InMemoryTrajectoryStorage()

    class _MemTaskStore:
        def __init__(self):
            self.tasks: dict[str, dict] = {}

        def save_task(self, task):
            self.tasks[task["task_id"]] = task
            return task

        def get_task(self, task_id):
            return self.tasks.get(task_id)

        def create_task(self, task_id, task_type, description, responsible_role,
                        workflow_id=None, executor_type=None, input_data=None,
                        output_data=None, step_id=None, error_message=None,
                        duration_ms=None, status="pending"):
            task = {"task_id": task_id, "task_type": task_type, "status": status,
                    "description": description, "responsible_role": responsible_role,
                    "workflow_id": workflow_id, "updated_at": "now"}
            if input_data is not None:
                task["input_data"] = input_data
            if output_data is not None:
                task["output_data"] = output_data
            return self.save_task(task)

        def list_tasks_by_workflow(self, workflow_id):
            return [t for t in self.tasks.values() if t.get("workflow_id") == workflow_id]

    tasks = _MemTaskStore()

    monkeypatch.setattr(session_lifecycle, "session_storage", sessions)
    monkeypatch.setattr(session_lifecycle, "default_trajectory_storage", trajectories)
    monkeypatch.setattr(task_service, "_task_store", tasks)
    return sessions, trajectories, tasks


def _make_session(store, session_id="sess-1", user_id="u1"):
    store.create_or_update_session(session_id, user_id, role="cashier")


# ── 轨迹存储 ────────────────────────────────────────────────────

def test_trajectory_storage_appends_and_lists_in_order():
    store = InMemoryTrajectoryStorage()
    for i in range(3):
        store.append_turn({
            "qa_turn_id": f"qat_{i}",
            "session_id": "s1",
            "user_id": "u1",
            "question": f"q{i}",
            "answer_status": "verified",
            "payload": {"attempt_count": 1},
        })
    store.append_turn({"qa_turn_id": "qat_other", "session_id": "s2", "user_id": "u1",
                       "question": "x", "answer_status": "verified", "payload": {}})

    turns = store.list_by_session("s1")
    assert [t["qa_turn_id"] for t in turns] == ["qat_0", "qat_1", "qat_2"]
    assert store.count_by_session("s1") == 3
    assert store.count_by_session("missing") == 0


def test_trajectory_storage_upsert_is_idempotent():
    store = InMemoryTrajectoryStorage()
    base = {"qa_turn_id": "qat_1", "session_id": "s1", "user_id": "u1",
            "question": "q", "answer_status": "unavailable", "payload": {}}
    store.append_turn(base)
    base["answer_status"] = "verified"
    base["payload"] = {"result": {"answer": "ok"}}
    store.append_turn(base)

    turns = store.list_by_session("s1")
    assert len(turns) == 1
    assert turns[0]["answer_status"] == "verified"


# ── 状态机 ──────────────────────────────────────────────────────

def test_suspend_then_resume_roundtrip(memory_stores):
    sessions, _, _ = memory_stores
    _make_session(sessions)

    suspended = session_lifecycle.suspend_session("sess-1", "u1", reason="等患者补材料")
    assert suspended.status == "suspended"
    assert suspended.status_reason == "等患者补材料"

    resumed = session_lifecycle.resume_session("sess-1", "u1")
    assert resumed.status == "active"


def test_close_is_terminal_state(memory_stores):
    sessions, _, _ = memory_stores
    _make_session(sessions)
    session_lifecycle.close_session("sess-1", "u1")

    for op in (
        lambda: session_lifecycle.suspend_session("sess-1", "u1"),
        lambda: session_lifecycle.resume_session("sess-1", "u1"),
        lambda: session_lifecycle.escalate_session("sess-1", "u1", question="q"),
        lambda: session_lifecycle.close_session("sess-1", "u1"),
    ):
        with pytest.raises(session_lifecycle.SessionLifecycleError) as e:
            op()
        assert e.value.code == "INVALID_SESSION_TRANSITION"
        assert e.value.status_code == 409


def test_suspended_cannot_escalate_directly(memory_stores):
    sessions, _, _ = memory_stores
    _make_session(sessions)
    session_lifecycle.suspend_session("sess-1", "u1")

    with pytest.raises(session_lifecycle.SessionLifecycleError):
        session_lifecycle.escalate_session("sess-1", "u1", question="q")


def test_missing_session_returns_404(memory_stores):
    with pytest.raises(session_lifecycle.SessionLifecycleError) as e:
        session_lifecycle.suspend_session("nope", "u1")
    assert e.value.status_code == 404


def test_owner_mismatch_returns_404_not_403(memory_stores):
    sessions, _, _ = memory_stores
    _make_session(sessions, user_id="u1")
    # 非本人一律按不存在处理，不泄露会话存在性
    with pytest.raises(session_lifecycle.SessionLifecycleError) as e:
        session_lifecycle.list_session_trajectory("sess-1", "attacker")
    assert e.value.status_code == 404


# ── 升级闭环 ────────────────────────────────────────────────────

def test_escalate_creates_ticket_and_blocks_session(memory_stores):
    sessions, _, tasks = memory_stores
    _make_session(sessions)

    escalation = session_lifecycle.escalate_session(
        "sess-1", "u1", question="大病保险如何申请？", reason="超出知识范围", qa_turn_id="qat_9",
    )
    assert sessions.get_session("sess-1").status == "escalated"
    ticket = tasks.get_task(escalation["task_id"])
    assert ticket["task_type"] == "policy_qa_escalation"
    assert ticket["status"] == "waiting_human_confirmation"
    assert ticket["input_data"]["session_id"] == "sess-1"
    assert ticket["input_data"]["qa_turn_id"] == "qat_9"
    # 工单登记 workflow_id=session_id，供会话详情反查
    assert ticket["workflow_id"] == "sess-1"


def test_resolve_escalation_restores_session_and_is_idempotent(memory_stores):
    sessions, _, _ = memory_stores
    _make_session(sessions)
    escalation = session_lifecycle.escalate_session("sess-1", "u1", question="大病保险如何申请？")

    resolved = session_lifecycle.resolve_escalation(escalation["task_id"], "请携带材料到医保办窗口", "officer-1")
    assert resolved["status"] == "completed"
    assert resolved["reply"] == "请携带材料到医保办窗口"
    assert sessions.get_session("sess-1").status == "active"

    again = session_lifecycle.resolve_escalation(escalation["task_id"], "重复提交", "officer-2")
    assert again["reply"] == "请携带材料到医保办窗口"  # 幂等：不覆盖首次回复


def test_resolve_unknown_escalation_returns_404(memory_stores):
    with pytest.raises(session_lifecycle.SessionLifecycleError) as e:
        session_lifecycle.resolve_escalation("esc_missing", "r", "o")
    assert e.value.status_code == 404


def test_session_detail_includes_escalation(memory_stores):
    sessions, _, _ = memory_stores
    _make_session(sessions)
    session_lifecycle.escalate_session("sess-1", "u1", question="q1")

    detail = session_lifecycle.get_session_detail("sess-1", "u1")
    assert detail["status"] == "escalated"
    assert detail["escalation"] is not None
    assert detail["escalation"]["status"] == "waiting_human_confirmation"


# ── 轨迹读取与会话列表 ──────────────────────────────────────────

def test_list_session_trajectory_returns_turns_in_order(memory_stores):
    sessions, trajectories, _ = memory_stores
    _make_session(sessions)
    trajectories.append_turn({
        "qa_turn_id": "qat_1", "session_id": "sess-1", "user_id": "u1",
        "question": "第一问", "answer_status": "verified",
        "payload": {"result": {"answer": "a1"}, "attempt_count": 1, "halt_reason": "verified"},
    })
    trajectories.append_turn({
        "qa_turn_id": "qat_2", "session_id": "sess-1", "user_id": "u1",
        "question": "第二问", "answer_status": "unavailable",
        "payload": {"halt_reason": "stalled"},
    })

    result = session_lifecycle.list_session_trajectory("sess-1", "u1")
    assert result["session_id"] == "sess-1"
    assert result["status"] == "active"
    assert [t["qa_turn_id"] for t in result["turns"]] == ["qat_1", "qat_2"]
    assert result["turns"][0]["payload"]["result"]["answer"] == "a1"


def test_list_user_sessions_summary(memory_stores):
    sessions, trajectories, _ = memory_stores
    _make_session(sessions)
    trajectories.append_turn({
        "qa_turn_id": "qat_1", "session_id": "sess-1", "user_id": "u1",
        "question": "统筹自付为什么这么多？后续追问", "answer_status": "verified", "payload": {},
    })

    items = session_lifecycle.list_user_sessions("u1")
    assert len(items) == 1
    item = items[0]
    assert item["turn_count"] == 1
    assert item["first_question_excerpt"].startswith("统筹自付")
    assert item["last_question_excerpt"] == item["first_question_excerpt"]
    assert item["status"] == "active"


def test_create_or_update_session_preserves_lifecycle_status():
    """活跃刷新（新一轮问答）不得重置挂起/升级状态（设计 §3.2）"""
    store = InMemorySessionStorage()
    store.create_or_update_session("s", "u1", "cashier")
    store.update_session_status("s", "suspended", "等材料")

    refreshed = store.create_or_update_session("s", "u1", "cashier")
    assert refreshed.status == "suspended"
    assert refreshed.status_reason == "等材料"


# ── PG task store 协议对齐（防回归：create_task 全参数）────────

def test_postgres_task_store_create_task_accepts_full_protocol():
    """PG create_task 必须与 service 层/内存版同签名（此前缺 input_data/status 导致
    record_qa_task 在 PG 模式静默失败）。不连库，仅校验签名。"""
    import inspect
    from src.data_platform.storage.postgresql.task_store import PostgreSQLTaskStore
    from src.data_platform.storage.session.in_memory import InMemorySessionStorage  # noqa: F401

    sig = inspect.signature(PostgreSQLTaskStore.create_task)
    for param in ("executor_type", "input_data", "output_data", "step_id",
                  "error_message", "duration_ms", "status"):
        assert param in sig.parameters, f"PG create_task 缺少参数 {param}"
