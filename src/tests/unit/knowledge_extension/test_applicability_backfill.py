"""ApplicabilityBackfillService 单元测试（Issue #25 存量回填）。"""
from __future__ import annotations

import pytest

from src.knowledge_extension.rule_explanation.policy_retrieval.applicability_backfill import (
    ApplicabilityBackfillService,
    BackfillProposal,
    InMemoryDocumentStore,
    InMemoryRuleStore,
)
from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    _DEFAULT_EFFECTIVE_DATE,
    _DEFAULT_EXPIRY_DATE,
    _DEFAULT_POLICY_VERSION,
    _DEFAULT_PUBLISH_STATUS,
    _DEFAULT_REGION,
    rule_to_entity,
)


def _entity(rule_id: str, missing_fields: set[str] | None = None, **overrides) -> dict:
    rule = {
        "rule_id": rule_id,
        "rule_type": "支付比例",
        "insu_type": "城镇职工基本医疗保险",
        "med_type": "住院-普通住院",
        "hosp_lv": "三级",
        "psn_type": "在职职工",
        "source_text": "测试规则",
        **overrides,
    }
    entity = rule_to_entity(rule, vector=[0.0] * 768, extracted_at="2024-09-01T00:00:00")
    # 模拟旧数据缺失指定字段
    for f in (missing_fields or set()):
        entity.pop(f, None)
    return entity


@pytest.fixture
def service() -> ApplicabilityBackfillService:
    entities = [
        _entity("r_complete", region="北京", publish_status="published"),
        _entity("r_missing_all", missing_fields={
            "region", "effective_date", "expiry_date", "publish_status", "policy_version", "is_remote",
        }),
        _entity("r_partial", missing_fields={"effective_date", "expiry_date", "publish_status", "policy_version", "is_remote"}, region="上海"),
    ]
    return ApplicabilityBackfillService(InMemoryRuleStore(entities))


def test_propose_returns_missing_fields(service: ApplicabilityBackfillService) -> None:
    proposals = service.propose()
    # r_complete 不缺失；r_missing_all 缺失 6 个；r_partial 缺失除 region 外 5 个
    assert len(proposals) == 11
    by_rule: dict[str, list[str]] = {}
    for p in proposals:
        by_rule.setdefault(p.rule_id, []).append(p.field_name)
    assert "r_complete" not in by_rule
    assert set(by_rule["r_missing_all"]) == {
        "region", "effective_date", "expiry_date", "publish_status", "policy_version", "is_remote",
    }
    assert "region" not in by_rule["r_partial"]


def test_propose_default_values(service: ApplicabilityBackfillService) -> None:
    proposals = service.propose()
    p = next((x for x in proposals if x.rule_id == "r_missing_all" and x.field_name == "region"), None)
    assert p is not None
    assert p.proposed_value == _DEFAULT_REGION
    assert p.old_value in (None, "")


def test_apply_requires_reviewer(service: ApplicabilityBackfillService) -> None:
    proposals = service.propose()
    with pytest.raises(ValueError, match="reviewed_by"):
        service.apply(proposals, "")


def test_apply_updates_store(service: ApplicabilityBackfillService) -> None:
    proposals = service.propose()
    applications, count = service.apply(proposals, "reviewer_001")
    assert count == 2  # r_missing_all 和 r_partial
    assert len(applications) == len(proposals)

    # 重新扫描应无缺失
    after = service.propose()
    assert len(after) == 0

    # 验证具体字段
    rules = {r["rule_id"]: r for r in service._store.list_rules()}
    assert rules["r_missing_all"]["region"] == _DEFAULT_REGION
    assert rules["r_missing_all"]["publish_status"] == _DEFAULT_PUBLISH_STATUS
    assert rules["r_partial"]["region"] == "上海"  # 未被覆盖
    assert rules["r_partial"]["expiry_date"] == _DEFAULT_EXPIRY_DATE


def test_apply_is_idempotent(service: ApplicabilityBackfillService) -> None:
    proposals = service.propose()
    service.apply(proposals, "reviewer_001")
    # 第二次应用无缺失，不产生更新
    second = service.propose()
    applications, count = service.apply(second, "reviewer_002")
    assert count == 0
    assert len(applications) == 0


def test_validate_gate_blocks_missing_core_fields(service: ApplicabilityBackfillService) -> None:
    passed, missing = service.validate_gate()
    assert passed is False
    # region/effective_date/expiry_date/publish_status 为阻塞项
    assert any(p.field_name == "region" for p in missing)
    assert any(p.field_name == "publish_status" for p in missing)
    # policy_version/is_remote 不阻塞 Runtime
    assert not any(p.field_name == "policy_version" for p in missing)


def test_validate_gate_passes_after_apply(service: ApplicabilityBackfillService) -> None:
    proposals = service.propose()
    service.apply(proposals, "reviewer_001")
    passed, missing = service.validate_gate()
    assert passed is True
    assert len(missing) == 0


def test_propose_uses_document_metadata_when_available() -> None:
    entities = [
        _entity(
            "r_from_doc",
            missing_fields={"region", "effective_date", "expiry_date", "publish_status"},
            doc_id="doc_beijing_2024",
        ),
    ]
    doc_store = InMemoryDocumentStore({
        "doc_beijing_2024": {
            "policy_region": "北京",
            "effective_date": "2024-01-01",
            "abolition_date": "2025-12-31",
            "validity": "valid",
        },
    })
    service = ApplicabilityBackfillService(
        InMemoryRuleStore(entities),
        document_store=doc_store,
    )
    proposals = service.propose()
    by_field = {p.field_name: p for p in proposals}

    assert by_field["region"].proposed_value == "北京"
    assert by_field["region"].confidence == "doc_metadata"
    assert by_field["effective_date"].proposed_value == "2024-01-01"
    assert by_field["expiry_date"].proposed_value == "2025-12-31"
    assert by_field["publish_status"].proposed_value == "published"


def test_propose_falls_back_to_system_defaults_when_metadata_missing() -> None:
    entities = [
        _entity(
            "r_no_meta",
            missing_fields={"region", "effective_date", "expiry_date"},
            doc_id="doc_unknown",
        ),
    ]
    service = ApplicabilityBackfillService(
        InMemoryRuleStore(entities),
        document_store=InMemoryDocumentStore(),
    )
    proposals = service.propose()
    by_field = {p.field_name: p for p in proposals}

    assert by_field["region"].proposed_value == _DEFAULT_REGION
    assert by_field["region"].confidence == "system_default"
    assert by_field["effective_date"].proposed_value == _DEFAULT_EFFECTIVE_DATE
    assert by_field["expiry_date"].proposed_value == _DEFAULT_EXPIRY_DATE
