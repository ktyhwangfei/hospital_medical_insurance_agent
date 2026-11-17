"""筛查规则服务单元测试 — issue #86（批准门禁 + 执行批次 + 名单）。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.data_platform.storage.screening_rules.in_memory import (
    InMemoryScreeningRuleStorage,
)
from src.domain.screening_rules.executor import FeeLine
from src.domain.screening_rules.models import (
    FindingType,
    NoApprovedRulesError,
    RuleClass,
    RuleNotApprovedError,
    RuleStatus,
    RunStatus,
    VerifyStatus,
)
from src.runtime.screening_rules.service import ScreeningRuleService

NOW = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
DOC = "国家定点医疗机构违法违规使用医疗保障基金典型问题清单（2025版）"
THYROID_CLAUSE = "开展甲状腺癌扩大根治术，重复收取甲状腺癌根治术和（或）淋巴结清扫术费用"

HIT_LINES = [
    FeeLine("T1", "1:1", "A1", "甲状腺癌扩大根治术", 5000.0),
    FeeLine("T1", "1:2", "A2", "甲状腺癌根治术", 3000.0),
]


def _service(lines: list[FeeLine] | None = None) -> ScreeningRuleService:
    return ScreeningRuleService(
        InMemoryScreeningRuleStorage(),
        fee_line_loader=lambda _start, _end: list(lines or []),
        now=lambda: NOW,
    )


def _upload_thyroid(service: ScreeningRuleService) -> str:
    items, rules = service.upload_checklist(source_doc=DOC, content=THYROID_CLAUSE)
    assert items[0].rule_class is RuleClass.EXECUTABLE
    assert len(rules) == 1
    return rules[0].rule_id


class TestApprovalGate:
    def test_unapproved_rule_run_refused(self):
        """未批准不得跑数：显式指定候选规则时整批拒绝。"""
        service = _service(HIT_LINES)
        rule_id = _upload_thyroid(service)
        with pytest.raises(RuleNotApprovedError):
            service.start_run(
                time_range_start=START, time_range_end=END,
                created_by="tester", rule_ids=[rule_id],
            )
        assert service.list_findings() == []
        assert service.list_runs() == []

    def test_no_approved_rules_refused(self):
        service = _service(HIT_LINES)
        _upload_thyroid(service)
        with pytest.raises(NoApprovedRulesError):
            service.start_run(time_range_start=START, time_range_end=END, created_by="tester")
        assert service.list_findings() == []

    def test_needs_mapping_cannot_be_approved(self):
        service = _service()
        service.upload_checklist(source_doc=DOC, content="限三级医疗机构使用的项目超范围收费")
        rule = service.list_rules(rule_class=RuleClass.NEEDS_MAPPING)
        # needs_mapping 不生成候选规则，列表为空——上传不产生规则行
        assert rule == []

    def test_disabled_rule_excluded_from_runs(self):
        service = _service(HIT_LINES)
        rule_id = _upload_thyroid(service)
        service.approve_rule(rule_id, approved_by="admin")
        service.disable_rule(rule_id)
        with pytest.raises(NoApprovedRulesError):
            service.start_run(time_range_start=START, time_range_end=END, created_by="tester")

    def test_editing_approved_rule_requires_reapproval(self):
        service = _service(HIT_LINES)
        rule_id = _upload_thyroid(service)
        service.approve_rule(rule_id, approved_by="admin")
        updated = service.update_rule(rule_id, title="新标题")
        assert updated.status is RuleStatus.CANDIDATE
        assert updated.approved_by is None
        with pytest.raises(RuleNotApprovedError):
            service.start_run(
                time_range_start=START, time_range_end=END,
                created_by="tester", rule_ids=[rule_id],
            )


class TestRunExecution:
    def test_run_with_hits(self):
        service = _service(HIT_LINES)
        rule_id = _upload_thyroid(service)
        service.approve_rule(rule_id, approved_by="admin")
        run = service.start_run(time_range_start=START, time_range_end=END, created_by="admin")
        assert run.status is RunStatus.SUCCEEDED
        findings = service.list_findings(run_id=run.run_id)
        assert len(findings) == 1
        assert findings[0].finding_type is FindingType.MISMATCH
        assert findings[0].evidence_clause == THYROID_CLAUSE
        assert findings[0].primary_finding_id == findings[0].finding_id
        _, rule_ids, counts = service.get_run(run.run_id)
        assert rule_ids == [rule_id]
        assert counts == {"mismatch": 1}

    def test_run_without_hits_succeeds_with_zero(self):
        """无命中也算执行完成：status=succeeded 且命中为 0，不报错不编造。"""
        service = _service([FeeLine("T9", "9:1", "B1", "换药（中）", 120.0)])
        rule_id = _upload_thyroid(service)
        service.approve_rule(rule_id, approved_by="admin")
        run = service.start_run(time_range_start=START, time_range_end=END, created_by="admin")
        assert run.status is RunStatus.SUCCEEDED
        assert service.list_findings(run_id=run.run_id) == []
        _, _, counts = service.get_run(run.run_id)
        assert counts == {}

    def test_verify_finding(self):
        service = _service(HIT_LINES)
        rule_id = _upload_thyroid(service)
        service.approve_rule(rule_id, approved_by="admin")
        run = service.start_run(time_range_start=START, time_range_end=END, created_by="admin")
        finding = service.list_findings(run_id=run.run_id)[0]
        verified = service.verify_finding(finding.finding_id, VerifyStatus.FOLLOW)
        assert verified.verify_status is VerifyStatus.FOLLOW

    def test_range_longer_than_92_days_rejected(self):
        service = _service()
        with pytest.raises(ValueError, match="92"):
            service.start_run(
                time_range_start=START,
                time_range_end=START + timedelta(days=93),
                created_by="admin",
            )

    def test_invalid_time_range_rejected(self):
        service = _service()
        rule_id = _upload_thyroid(service)
        service.approve_rule(rule_id, approved_by="admin")
        with pytest.raises(ValueError):
            service.start_run(time_range_start=END, time_range_end=START, created_by="admin")
