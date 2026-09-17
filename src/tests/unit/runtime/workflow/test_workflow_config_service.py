"""Workflow 治理配置解析单元测试：平台默认 ← 全局覆盖 ← 院区覆盖 ← 运维 kill-switch。"""

from __future__ import annotations

import pytest

from src.data_platform.storage.workflow_config.in_memory import InMemoryWorkflowConfigStorage
from src.runtime.workflow.config_service import UnknownWorkflowError, WorkflowConfigService
from src.runtime.workflow.definitions import WF_REFUND_VERIFICATION

WF = WF_REFUND_VERIFICATION.workflow_id


def _service() -> WorkflowConfigService:
    return WorkflowConfigService(InMemoryWorkflowConfigStorage())


def test_default_when_no_override() -> None:
    effective = _service().effective("")[WF]
    assert effective.source == "default"
    assert effective.enabled is True
    assert effective.intent_keywords == list(WF_REFUND_VERIFICATION.intent_keywords)


def test_global_override_replaces_keywords() -> None:
    service = _service()
    service.set_override(WF, enabled=True, intent_keywords=["多收钱"])
    effective = service.effective("")[WF]
    assert effective.source == "global"
    assert effective.intent_keywords == ["多收钱"]


def test_hospital_override_beats_global() -> None:
    service = _service()
    service.set_override(WF, enabled=True, intent_keywords=["全局词"])
    service.set_override(WF, enabled=True, intent_keywords=["甲院词"], hospital_code="HOSP-A")
    assert service.effective("")[WF].intent_keywords == ["全局词"]
    assert service.effective("HOSP-A")[WF].intent_keywords == ["甲院词"]
    assert service.effective("HOSP-A")[WF].source == "hospital"


def test_null_keywords_inherit_previous_layer() -> None:
    """关键词为 None = 继承；仅改启停时不丢已有词表。"""
    service = _service()
    service.set_override(WF, enabled=True, intent_keywords=["全局词"])
    service.set_override(WF, enabled=False, intent_keywords=None, hospital_code="HOSP-A")
    effective = service.effective("HOSP-A")[WF]
    assert effective.enabled is False
    assert effective.intent_keywords == ["全局词"]


def test_env_kill_switch_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """运维故障下线不依赖配置库：环境变量优先级最高。"""
    service = _service()
    service.set_override(WF, enabled=True, intent_keywords=["词"])
    monkeypatch.setenv("WORKFLOW_DISABLED", f"{WF},wf_policy_chat")
    effective = service.effective("")[WF]
    assert effective.enabled is False
    assert effective.source.endswith("+env_disabled")
    assert service.effective("")["wf_policy_chat"].enabled is False


def test_unknown_workflow_rejected() -> None:
    with pytest.raises(UnknownWorkflowError):
        _service().set_override("wf_不存在", enabled=True, intent_keywords=None)
