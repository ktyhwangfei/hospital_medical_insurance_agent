"""健康运营 P1-5 LLM 智能诊断单元测试 — issue #51。

验收映射：
- 无引用诊断不得产生可执行建议（负例）→ TestBuildReport
  .test_no_citations_insufficient_evidence_no_actions
- 引用只能从证据目录选取、模型不可编造 → .test_fabricated_citation_dropped
- 模型失败/输出不可解析不落库 → TestService
  .test_model_failure_raises_unavailable_keeps_old_state
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.data_platform.storage.ops.ops_in_memory import InMemoryOpsFindingStorage
from src.domain.ops.models import (
    DiagnosisStatus,
    DiagnosisUnavailableError,
    FindingDraft,
    OpsAssetType,
    OpsSeverity,
)
from src.model_service.models import ModelResponse, TokenUsage
from src.model_service.router import ModelRouter
from src.runtime.ops.diagnosis import (
    DIAGNOSIS_MODEL_TYPE,
    DIAGNOSIS_SCENE,
    OpsDiagnosisService,
    build_evidence_catalog,
    build_report,
)

NOW = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)


class _FakeGateway:
    """记录调用并回放固定输出/异常的假模型网关。"""

    def __init__(self, content: str = "", error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls: list[dict] = []

    def generate(self, messages, model_type, scene, **kwargs):
        self.calls.append(
            {"model_type": model_type, "scene": scene, "messages": messages}
        )
        if self.error is not None:
            raise self.error
        return ModelResponse(
            content=self.content,
            model_name="fake-diag-model",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=10),
            finish_reason="stop",
        )


def _finding(payload: dict | None = None) -> FindingDraft:
    return FindingDraft(
        asset_type=OpsAssetType.DATA,
        asset_id="bjybdb",
        check_id="data_sync_failed",
        severity=OpsSeverity.CRITICAL,
        payload=payload if payload is not None else {
            "problem": "sync_job_failed",
            "job_status": "failed",
            "last_error_code": "E_CONN",
        },
    )


def _catalog(payload: dict | None = None, supplement: list | None = None):
    return build_evidence_catalog(_draft_like(payload or {
        "problem": "sync_job_failed",
        "job_status": "failed",
    }), supplement or [])


def _draft_like(payload: dict):
    """构造带 payload 的只读 finding 形态（build_evidence_catalog 只读这些字段）。"""
    from src.domain.ops.models import OpsFinding

    return OpsFinding(
        finding_id="f1",
        asset_type=OpsAssetType.DATA,
        asset_id="bjybdb",
        check_id="data_sync_failed",
        severity=OpsSeverity.CRITICAL,
        status="open",
        fingerprint="data:bjybdb:data_sync_failed",
        payload=payload,
        first_seen_at=NOW,
        last_seen_at=NOW,
        occurrence_count=2,
        revision=1,
    )


class TestBuildReport:
    def test_complete_report_with_catalog_citations(self):
        catalog = _catalog()
        content = json.dumps({
            "root_cause": "同步任务连续失败，连接超时",
            "citations": ["E2", "E1"],
            "uncertainties": ["缺少最近一次成功同步时间"],
            "actions": [
                {"level": "L1", "description": "重试同步任务", "citation_ids": ["E1"]},
                {"level": "L2", "description": "人工核对源库凭据", "citation_ids": ["E2"]},
            ],
        })
        report = build_report(
            "f1", content, catalog, actor="ops-admin", model_name="fake-diag-model",
        )
        assert report.status is DiagnosisStatus.COMPLETE
        assert report.root_cause == "同步任务连续失败，连接超时"
        # 引用按模型选择顺序取自目录（quote 来自目录而非模型输出）
        assert [c.citation_id for c in report.citations] == ["E2", "E1"]
        assert all(c.quote for c in report.citations)
        assert [a.level.value for a in report.actions] == ["L1", "L2"]
        assert report.model_route == {
            "scene": DIAGNOSIS_SCENE,
            "model_type": DIAGNOSIS_MODEL_TYPE,
            "model_name": "fake-diag-model",
        }

    def test_no_citations_insufficient_evidence_no_actions(self):
        """验收负例：无引用诊断不得产生可执行建议。"""
        catalog = _catalog()
        content = json.dumps({
            "root_cause": "看起来是网络问题",  # 模型仍给出了根因与建议
            "citations": [],
            "uncertainties": ["证据不足"],
            "actions": [
                {"level": "L1", "description": "重试同步任务", "citation_ids": ["E1"]},
                {"level": "L3", "description": "直接重算结算", "citation_ids": ["E1"]},
            ],
        })
        report = build_report("f1", content, catalog, actor="ops-admin")
        assert report.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
        assert report.root_cause is None
        assert report.actions == []  # 硬约束：无引用 → 不留任何建议动作
        assert report.citations == []
        assert any("证据引用" in u for u in report.uncertainties)

    def test_fabricated_citation_dropped(self):
        """模型编造的证据编号（不在目录内）不进入报告。"""
        catalog = _catalog()
        content = json.dumps({
            "root_cause": "x",
            "citations": ["E99"],
            "uncertainties": [],
            "actions": [],
        })
        report = build_report("f1", content, catalog, actor="ops-admin")
        assert report.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
        assert report.citations == []

    def test_action_validation_rules(self):
        catalog = _catalog()
        content = json.dumps({
            "root_cause": "x",
            "citations": ["E1", "E2"],
            "uncertainties": [],
            "actions": [
                {"level": "L9", "description": "未知级别", "citation_ids": ["E1"]},  # 级别非法
                {"level": "L1", "description": "", "citation_ids": ["E1"]},  # 无描述
                {"level": "L1", "description": "引用全被丢弃", "citation_ids": ["E99"]},  # 引用无效
                {"level": "L2", "description": "人工核对凭据", "citation_ids": ["E2", "E99"]},  # 部分有效
            ],
        })
        report = build_report("f1", content, catalog, actor="ops-admin")
        assert len(report.actions) == 1
        assert report.actions[0].level.value == "L2"
        assert report.actions[0].citation_ids == ["E2"]

    def test_unparseable_content_raises_unavailable(self):
        catalog = _catalog()
        with pytest.raises(DiagnosisUnavailableError):
            build_report("f1", "这不是 JSON", catalog, actor="ops-admin")

    def test_fenced_json_tolerated(self):
        catalog = _catalog()
        content = "```json\n" + json.dumps({
            "root_cause": "r", "citations": ["E1"], "uncertainties": [], "actions": [],
        }) + "\n```"
        report = build_report("f1", content, catalog, actor="ops-admin")
        assert report.status is DiagnosisStatus.COMPLETE


class TestEvidenceCatalog:
    def test_payload_and_supplement_numbered_and_redacted(self):
        finding = _draft_like({
            "problem": "sync_job_failed",
            "note": "患者姓名：张三 身份证号 11010119900307123X",
        })
        supplement = [("supplement.sync_attempts[0]", "status=failed rows=0")]
        catalog = build_evidence_catalog(finding, supplement)
        assert set(catalog) == {"E1", "E2", "E3"}
        assert catalog["E1"].source == "payload.problem"
        # PHI 原值不出现在证据目录（进入模型与落库的都是脱敏文本）
        joined = " ".join(c.quote for c in catalog.values())
        assert "张三" not in joined
        assert "11010119900307123X" not in joined
        assert "[已脱敏" in joined
        assert catalog["E3"].source == "supplement.sync_attempts[0]"

    def test_empty_values_skipped(self):
        finding = _draft_like({"problem": "sync_job_failed", "empty": ""})
        catalog = build_evidence_catalog(finding, [])
        assert set(catalog) == {"E1"}


class TestService:
    def _storage_with_finding(self) -> tuple[InMemoryOpsFindingStorage, str]:
        storage = InMemoryOpsFindingStorage()
        finding = storage.upsert_finding(_finding(), seen_at=NOW)
        return storage, finding.finding_id

    def test_diagnose_saves_report_and_keeps_lifecycle_fields(self):
        storage, finding_id = self._storage_with_finding()
        before = storage.get_finding(finding_id)
        gateway = _FakeGateway(content=json.dumps({
            "root_cause": "同步连接失败",
            "citations": ["E1"],
            "uncertainties": [],
            "actions": [
                {"level": "L1", "description": "重试同步", "citation_ids": ["E1"]},
            ],
        }))
        service = OpsDiagnosisService(storage, lambda: gateway, evidence_collector=lambda f: [])
        result = service.diagnose_finding(finding_id, actor="ops-admin")

        assert result.report.status is DiagnosisStatus.COMPLETE
        # 报告覆盖落库，且不动状态与乐观锁版本（诊断只读）
        assert result.finding.diagnosis is not None
        assert result.finding.diagnosis["status"] == "complete"
        assert result.finding.status == before.status
        assert result.finding.revision == before.revision
        # 模型路由参数正确（scene=asset_diagnosis / model_type=llm）
        assert gateway.calls[0]["scene"] == DIAGNOSIS_SCENE
        assert gateway.calls[0]["model_type"] == DIAGNOSIS_MODEL_TYPE
        assert len(gateway.calls[0]["messages"]) == 2  # system + user

    def test_model_failure_raises_unavailable_keeps_old_state(self):
        storage, finding_id = self._storage_with_finding()
        gateway = _FakeGateway(error=RuntimeError("模型服务不可达"))
        service = OpsDiagnosisService(storage, lambda: gateway, evidence_collector=lambda f: [])
        with pytest.raises(DiagnosisUnavailableError):
            service.diagnose_finding(finding_id, actor="ops-admin")
        # 不落库：diagnosis 保持为空
        assert storage.get_finding(finding_id).diagnosis is None

    def test_unknown_finding_raises_not_found(self):
        storage = InMemoryOpsFindingStorage()
        service = OpsDiagnosisService(storage, _FakeGateway, evidence_collector=lambda f: [])
        from src.domain.ops.models import OpsFindingNotFoundError

        with pytest.raises(OpsFindingNotFoundError):
            service.diagnose_finding("missing", actor="ops-admin")


class TestSceneRouting:
    def test_diagnosis_scene_resolves_without_governance(self):
        """未发布治理路由时诊断 scene 也能经默认路由表解析（#40 教训回归）。"""
        model, fallbacks = ModelRouter().resolve(DIAGNOSIS_SCENE, DIAGNOSIS_MODEL_TYPE)
        assert model
        assert isinstance(fallbacks, list)

    def test_weekly_summary_scene_resolves_after_fix(self):
        model, _ = ModelRouter().resolve("ops_weekly_summary", "llm")
        assert model
