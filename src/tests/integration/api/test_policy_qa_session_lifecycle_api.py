"""Issue #30 会话生命周期与轨迹 API 测试

全内存链路（USE_MEMORY_STORAGE=1）；会话 ID 每用例唯一，避免模块级内存单例跨用例串扰。
"""

import json
import os
import uuid

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.tests.integration.api.test_policy_qa_routes import (
    safe_policy_qa_dependencies,  # noqa: F401 — 复用同层 fixture
)

API = "/api/v1/medical-insurance-ai-agent/policy-qa"


@pytest.fixture
def client():
    return TestClient(create_app())


def _stream(client, session_id, question="统筹自付为什么这么多？"):
    with client.stream(
        "POST",
        f"{API}/stream",
        json={
            "question": question,
            "settlement_id": "S123456789",
            "session_id": session_id,
            "user_id": "demo",
            "role": "cashier",
        },
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")
    events = []
    for block in body.split("\n\n"):
        name, data = "", []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            if line.startswith("data:"):
                data.append(line.removeprefix("data:").lstrip())
        if name and data:
            events.append((name, json.loads("\n".join(data))))
    return events


def _sid() -> str:
    return f"sess-test-{uuid.uuid4().hex[:8]}"


class TestTrajectoryPersistence:
    def test_stream_persists_replayable_trajectory(
        self, client, safe_policy_qa_dependencies
    ):
        sid = _sid()
        events = _stream(client, sid)
        assert any(e[0] == "result" for e in events)

        resp = client.get(f"{API}/sessions/{sid}/trajectory", params={"user_id": "demo"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == sid
        assert body["status"] == "active"
        assert len(body["turns"]) == 1
        turn = body["turns"][0]
        assert turn["qa_turn_id"].startswith("qat_")
        assert turn["question"] == "统筹自付为什么这么多？"
        assert turn["answer_status"] in ("complete", "partial")
        assert turn["payload"]["result"]["answer"]
        assert turn["payload"]["attempt_count"] == 1
        assert turn["payload"]["halt_reason"] == "verified"
        # result 与 done 共享的 qa_turn_id 必须与轨迹一致
        done = [d for n, d in events if n == "done"][0]
        assert done["qa_turn_id"] == turn["qa_turn_id"]

    def test_failed_stream_persists_unavailable_turn(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from src.runtime.api import policy_qa_routes

        monkeypatch.setattr(policy_qa_routes, "get_assembler", lambda _s: object())

        sid = _sid()
        _stream(client, sid)

        resp = client.get(f"{API}/sessions/{sid}/trajectory", params={"user_id": "demo"})
        assert resp.status_code == 200
        turn = resp.json()["turns"][0]
        assert turn["answer_status"] == "unavailable"
        assert "result" not in turn["payload"] or not turn["payload"].get("result")
        assert turn["payload"]["halt_reason"] in ("non_retryable_error", "max_attempts", "stalled")

    def test_trajectory_owner_mismatch_is_404(self, client, safe_policy_qa_dependencies):
        sid = _sid()
        _stream(client, sid)
        resp = client.get(f"{API}/sessions/{sid}/trajectory", params={"user_id": "intruder"})
        assert resp.status_code == 404

    def test_sessions_list_shows_turn_summary(self, client, safe_policy_qa_dependencies):
        sid = _sid()
        _stream(client, sid, question="起付线是多少？")
        resp = client.get(f"{API}/sessions", params={"user_id": "demo"})
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["session_id"] == sid)
        assert item["turn_count"] == 1
        assert item["status"] == "active"
        assert item["last_question_excerpt"].startswith("起付线")


class TestSuspendResume:
    def test_suspend_blocks_stream_and_resume_restores(
        self, client, safe_policy_qa_dependencies
    ):
        sid = _sid()
        _stream(client, sid)

        # 挂起
        resp = client.post(f"{API}/sessions/{sid}/suspend", json={"reason": "等患者补材料"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"

        # 挂起后新问答被拒（端点级拦截，非 SSE 内部）
        resp = client.post(
            f"{API}/stream",
            json={"question": "再问一个", "settlement_id": "S123456789", "session_id": sid},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "SESSION_NOT_ACTIVE"

        # 恢复：响应携带完整轨迹
        resp = client.post(f"{API}/sessions/{sid}/resume", params={"user_id": "demo"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "active"
        assert len(body["trajectory"]["turns"]) == 1

        # 恢复后可继续问答
        events = _stream(client, sid, question="追问大额自付")
        assert any(e[0] == "result" for e in events)
        resp = client.get(f"{API}/sessions/{sid}/trajectory", params={"user_id": "demo"})
        assert len(resp.json()["turns"]) == 2

    def test_double_suspend_conflicts(self, client, safe_policy_qa_dependencies):
        sid = _sid()
        _stream(client, sid)
        client.post(f"{API}/sessions/{sid}/suspend", json={})
        resp = client.post(f"{API}/sessions/{sid}/suspend", json={})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "INVALID_SESSION_TRANSITION"

    def test_resume_unknown_session_404(self, client):
        resp = client.post(f"{API}/sessions/sess-nope/resume", params={"user_id": "demo"})
        assert resp.status_code == 404


class TestEscalation:
    def test_escalate_resolve_roundtrip(self, client, safe_policy_qa_dependencies):
        sid = _sid()
        _stream(client, sid)

        # 升级：创建医保办工单并锁会话
        resp = client.post(
            f"{API}/sessions/{sid}/escalate",
            params={"user_id": "demo"},
            json={"question": "大病保险如何申请？", "reason": "超出知识库范围"},
        )
        assert resp.status_code == 200
        escalation = resp.json()["escalation"]
        assert escalation["status"] == "waiting_human_confirmation"

        # 升级期间会话详情可见工单
        detail = client.get(f"{API}/sessions/{sid}", params={"user_id": "demo"}).json()
        assert detail["status"] == "escalated"
        assert detail["escalation"]["task_id"] == escalation["task_id"]

        # 医保办回复：会话恢复 active
        resp = client.post(
            f"{API}/escalations/{escalation['task_id']}/resolve",
            json={"reply": "请携带诊断证明到医保办窗口办理。", "resolved_by": "officer-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

        detail = client.get(f"{API}/sessions/{sid}", params={"user_id": "demo"}).json()
        assert detail["status"] == "active"
        assert detail["escalation"]["reply"] == "请携带诊断证明到医保办窗口办理。"

        # 恢复后可继续问答（用带单项关键词的问题，与 fake assembler 能力匹配）
        events = _stream(client, sid, question="继续追问大额自付")
        assert any(e[0] == "result" for e in events)

    def test_resolve_unknown_escalation_404(self, client):
        resp = client.post(
            f"{API}/escalations/esc-nope/resolve", json={"reply": "r", "resolved_by": "o"}
        )
        assert resp.status_code == 404
