"""Issue #30 轨迹持久化与挂起/升级/恢复 Flow 测试

用户故事：收费员连续多轮政策问答 → 页面刷新（新客户端仅凭 session_id 重建完整对话）
→ 主动挂起 → 挂起期间新问答被拒 → 恢复继续 → 升级医保办 → 回复回填后继续问答。
"""

import json
import os
import uuid

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.tests.integration.api.test_policy_qa_routes import (
    safe_policy_qa_dependencies,  # noqa: F401
)

API = "/api/v1/medical-insurance-ai-agent/policy-qa"


@pytest.fixture
def client():
    return TestClient(create_app())


def _ask(client, sid, question, settlement_id="S123456789"):
    with client.stream(
        "POST",
        f"{API}/stream",
        json={
            "question": question,
            "settlement_id": settlement_id,
            "session_id": sid,
            "user_id": "demo",
            "role": "cashier",
        },
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")
    events = {}
    for block in body.split("\n\n"):
        name, data = "", []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            if line.startswith("data:"):
                data.append(line.removeprefix("data:").lstrip())
        if name and data:
            events[name] = json.loads("\n".join(data))
    return events


def test_trajectory_suspend_escalation_full_flow(client, safe_policy_qa_dependencies):
    sid = f"sess-flow-{uuid.uuid4().hex[:8]}"

    # ── 第一幕：连续两轮问答 ──
    turn1 = _ask(client, sid, "统筹自付为什么这么多？")
    assert "result" in turn1
    turn2 = _ask(client, sid, "大额自付是怎么算的？")
    assert "result" in turn2

    # ── 第二幕：刷新重建 —— 新客户端仅凭 session_id 从轨迹恢复完整对话 ──
    fresh_client = TestClient(create_app())
    traj = fresh_client.get(f"{API}/sessions/{sid}/trajectory", params={"user_id": "demo"})
    assert traj.status_code == 200
    turns = traj.json()["turns"]
    assert [t["question"] for t in turns] == ["统筹自付为什么这么多？", "大额自付是怎么算的？"]
    # 每轮携带完整可重放结果（answer + 验证摘要），刷新不丢内容
    assert turns[0]["payload"]["result"]["answer"]
    assert turns[0]["payload"]["result"]["verification_summary"]["settlement_checked"] is True
    # 轨迹轮次 ID 与流式契约一致
    assert turns[0]["qa_turn_id"] == turn1["result"]["qa_turn_id"]

    # ── 第三幕：挂起 → 拒绝新问答 → 恢复 ──
    assert fresh_client.post(f"{API}/sessions/{sid}/suspend", json={"reason": "午休"}).status_code == 200
    blocked = fresh_client.post(
        f"{API}/stream",
        json={"question": "再问", "settlement_id": "S123456789", "session_id": sid},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error_code"] == "SESSION_NOT_ACTIVE"

    resumed = fresh_client.post(f"{API}/sessions/{sid}/resume", params={"user_id": "demo"})
    assert resumed.status_code == 200
    assert len(resumed.json()["trajectory"]["turns"]) == 2  # 恢复响应自带轨迹

    # ── 第四幕：升级医保办 → 回复回填 → 会话恢复继续 ──
    esc = fresh_client.post(
        f"{API}/sessions/{sid}/escalate",
        params={"user_id": "demo"},
        json={"question": "大病保险如何申请？", "reason": "超出知识库"},
    ).json()["escalation"]
    assert esc["status"] == "waiting_human_confirmation"

    resolved = fresh_client.post(
        f"{API}/escalations/{esc['task_id']}/resolve",
        json={"reply": "请携带材料到医保办窗口。", "resolved_by": "officer-1"},
    )
    assert resolved.status_code == 200

    detail = fresh_client.get(f"{API}/sessions/{sid}", params={"user_id": "demo"}).json()
    assert detail["status"] == "active"
    assert detail["escalation"]["reply"] == "请携带材料到医保办窗口。"

    turn3 = _ask(fresh_client, sid, "继续问起付线")
    assert "result" in turn3

    # ── 收尾：会话列表可见全部轮次 ──
    items = fresh_client.get(f"{API}/sessions", params={"user_id": "demo"}).json()["items"]
    item = next(i for i in items if i["session_id"] == sid)
    assert item["turn_count"] == 3
