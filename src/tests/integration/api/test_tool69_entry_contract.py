"""入口契约连通性与 Workflow 停用开关测试（无库环境可跑）。"""

import os

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def _sse_result(body: str) -> dict:
    import json

    for block in body.replace("\r\n", "\n").split("\n\n"):
        event_name = ""
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if event_name == "result" and data_lines:
            payload = json.loads("\n".join(data_lines))
            return payload.get("result", payload)
    raise AssertionError("SSE 流中无 result 事件")


def test_multi_settlement_ids_reaches_workflow_not_clarify() -> None:
    """Q1 型入口连通：settlement_ids 传入后不再卡在澄清（进入执行链）。"""
    response = _client().post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={
            "question": "同一患者同药三次结算报销比例不同，帮我对比核验",
            "settlement_ids": ["687", "689", "691"],
        },
    )
    result = _sse_result(response.text)
    # 不再返回“请提供需要对比的至少两笔结算单号”的澄清，即入口契约打通；
    # 有库环境 complete，无库环境 unavailable（工具 fail-closed），两者皆合法。
    assert "至少两笔结算单号" not in result["answer"]


def test_workflow_disable_switch_routes_to_skill_pipeline(monkeypatch) -> None:
    """停用开关：WORKFLOW_DISABLED 命中的工作流不再被关键词/模式路由。"""
    from src.runtime.policy_qa.models import PolicyQAMode
    from src.runtime.workflow import service as workflow_service

    monkeypatch.setenv("WORKFLOW_DISABLED", "wf_settlement_reimbursement_diff")
    workflow_service._get_router.cache_clear()
    try:
        assert (
            workflow_service.route_workflow_question("同一患者同药三次结算报销比例不同") is None
        )
        assert workflow_service.is_workflow_enabled("wf_settlement_reimbursement_diff") is False
        assert workflow_service.is_workflow_enabled("wf_refund_verification") is True
        # 模式路由的停用同样生效
        monkeypatch.setenv("WORKFLOW_DISABLED", "wf_outpatient_settlement_explain")
        assert workflow_service.get_workflow_by_mode(PolicyQAMode.SETTLEMENT_EXPLAIN) is None
    finally:
        monkeypatch.delenv("WORKFLOW_DISABLED", raising=False)
        workflow_service._get_router.cache_clear()
