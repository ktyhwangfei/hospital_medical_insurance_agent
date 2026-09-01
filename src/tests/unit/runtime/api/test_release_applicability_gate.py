"""发布门禁中适用性字段校验的单元测试（Issue #25）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease
from src.runtime.api import policy_workbench_routes as routes


@dataclass
class _FakeBackfillProposal:
    rule_id: str
    field_name: str


class _FakeApplicabilityBackfillService:
    """可注入 validate_gate 结果的假服务。"""

    def __init__(self, store: Any) -> None:
        self.store = store

    def validate_gate(self) -> tuple[bool, list[_FakeBackfillProposal]]:
        return _FakeApplicabilityBackfillService._result

    _result: tuple[bool, list[_FakeBackfillProposal]] = (True, [])


class _FakeMilvusClient:
    """模拟 MilvusClient.has_collection，默认返回 True（collection 已构建）。"""

    def __init__(self, collection_name: str) -> None:
        self.collection_name = collection_name

    def has_collection(self, collection_name: str) -> bool:
        return True


class _FakeMilvusRuleStore:
    """记录构造时使用的 collection_name。"""

    def __init__(self, collection_name: str = "policy_rules_v2") -> None:
        self.collection_name = collection_name
        self.client = _FakeMilvusClient(collection_name)


def test_validate_applicability_gate_passes_when_gate_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "ApplicabilityBackfillService", _FakeApplicabilityBackfillService)
    monkeypatch.setattr(routes, "MilvusRuleStore", _FakeMilvusRuleStore)
    _FakeApplicabilityBackfillService._result = (True, [])

    release = KnowledgeRelease(
        release_id="rel_001",
        contract_version="1",
        case_set_version=0,
        config_hash="abc",
        rules_collection="policy_rules_rel_001",
        facts_collection="policy_facts_rel_001",
        source_change_set_id="cs_001",
    )

    # 不应抛异常
    routes._validate_applicability_gate_for_release(release)


def test_validate_applicability_gate_raises_when_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "ApplicabilityBackfillService", _FakeApplicabilityBackfillService)
    monkeypatch.setattr(routes, "MilvusRuleStore", _FakeMilvusRuleStore)
    _FakeApplicabilityBackfillService._result = (
        False,
        [_FakeBackfillProposal("rule_1", "region")],
    )

    release = KnowledgeRelease(
        release_id="rel_002",
        contract_version="1",
        case_set_version=0,
        config_hash="abc",
        rules_collection="policy_rules_rel_002",
        facts_collection="policy_facts_rel_002",
        source_change_set_id="cs_002",
    )

    with pytest.raises(ValueError, match="适用性字段质量门禁未通过"):
        routes._validate_applicability_gate_for_release(release)
