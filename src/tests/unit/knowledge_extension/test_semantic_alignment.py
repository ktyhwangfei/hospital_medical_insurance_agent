from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager

import pytest

from src.semantic_layer.models import BusinessObject, Metric, ValueDomain
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


def _registry() -> tuple[SemanticRegistry, InMemoryRegistryStore]:
    store = InMemoryRegistryStore()
    store.save_object(BusinessObject(
        object_code="zcgz",
        domain_code="policy",
        name="政策规则",
    ))
    store.save_value_domain(ValueDomain(
        domain_code="PERSON_TYPE",
        name="人员类别",
        standard_values=["职工医保", "居民医保"],
    ))
    store.save_metric(Metric(
        metric_code="zcgz.person_type",
        object_code="zcgz",
        name="参保人员类别",
        semantic_type="Enum",
        value_domain="PERSON_TYPE",
        status="published",
    ))
    return SemanticRegistry(store), store


def test_one_metric_accepts_structured_and_policy_source_bindings() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        SemanticAlignmentService,
    )

    registry, _registry_store = _registry()
    alignment_store = InMemorySemanticAlignmentStore()
    service = SemanticAlignmentService(registry, alignment_store)
    structured = MetricSourceBindingDraft(
        metric_code="zcgz.person_type",
        source_type="structured_field",
        source_ref="his.patient",
        source_field="person_type",
        source_version="v3",
        evidence="HIS 患者主索引字段",
    )
    policy = MetricSourceBindingDraft(
        metric_code="zcgz.person_type",
        source_type="policy_knowledge",
        source_ref="doc_1/unit_1/kn_1",
        source_field="psn_type",
        source_version="contract-2",
        evidence="政策原文：在职职工参加基本医疗保险",
    )

    first = service.bind_existing_metric(structured)
    duplicate = service.bind_existing_metric(structured)
    second = service.bind_existing_metric(policy)

    assert duplicate.binding_id == first.binding_id
    assert {item.source_type for item in service.list_metric_bindings("zcgz.person_type")} == {
        "structured_field",
        "policy_knowledge",
    }
    assert second.metric_code == first.metric_code


def test_source_values_align_many_to_one_standard_value_after_review() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    registry, _registry_store = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    structured = service.bind_existing_metric(MetricSourceBindingDraft(
        metric_code="zcgz.person_type",
        source_type="structured_field",
        source_ref="his.patient",
        source_field="person_type",
        source_version="v3",
        evidence="HIS.person_type=1",
    ))
    policy = service.bind_existing_metric(MetricSourceBindingDraft(
        metric_code="zcgz.person_type",
        source_type="policy_knowledge",
        source_ref="doc_1/unit_1/kn_1",
        source_field="psn_type",
        source_version="contract-2",
        evidence="政策值：城镇职工",
    ))

    first = service.propose_value_mapping(SourceValueMappingDraft(
        metric_code="zcgz.person_type",
        domain_code="PERSON_TYPE",
        binding_id=structured.binding_id,
        source_value="1",
        standard_value="职工医保",
    ))
    second = service.propose_value_mapping(SourceValueMappingDraft(
        metric_code="zcgz.person_type",
        domain_code="PERSON_TYPE",
        binding_id=policy.binding_id,
        source_value="城镇职工",
        standard_value="职工医保",
    ))

    assert first.status == second.status == "draft"
    service.approve_value_mapping(first.mapping_id, reviewed_by="semantic_reviewer")
    service.approve_value_mapping(second.mapping_id, reviewed_by="semantic_reviewer")
    assert service.resolve_source_value(structured.binding_id, "1") == "职工医保"
    assert service.resolve_source_value(policy.binding_id, "城镇职工") == "职工医保"


def test_same_raw_value_can_map_differently_for_different_sources() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    registry, registry_store = _registry()
    domain = registry_store.get_value_domain("PERSON_TYPE")
    domain.standard_values.append("特殊人员")  # type: ignore[union-attr]
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    first_binding = service.bind_existing_metric(MetricSourceBindingDraft(
        metric_code="zcgz.person_type",
        source_type="structured_field",
        source_ref="his.patient",
        source_field="person_type",
        source_version="v3",
        evidence="HIS 字段",
    ))
    second_binding = service.bind_existing_metric(MetricSourceBindingDraft(
        metric_code="zcgz.person_type",
        source_type="structured_field",
        source_ref="insurance.person",
        source_field="person_type",
        source_version="v1",
        evidence="医保接口字段",
    ))
    first = service.propose_value_mapping(SourceValueMappingDraft(
        metric_code="zcgz.person_type", domain_code="PERSON_TYPE",
        binding_id=first_binding.binding_id, source_value="1", standard_value="职工医保",
    ))
    second = service.propose_value_mapping(SourceValueMappingDraft(
        metric_code="zcgz.person_type", domain_code="PERSON_TYPE",
        binding_id=second_binding.binding_id, source_value="1", standard_value="特殊人员",
    ))
    service.approve_value_mapping(first.mapping_id, "reviewer")
    service.approve_value_mapping(second.mapping_id, "reviewer")

    assert service.resolve_source_value(first_binding.binding_id, "1") == "职工医保"
    assert service.resolve_source_value(second_binding.binding_id, "1") == "特殊人员"


def test_new_standard_value_stays_draft_until_semantic_review() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
        StandardValueProposalDraft,
    )

    registry, registry_store = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())

    proposal = service.propose_standard_value(StandardValueProposalDraft(
        domain_code="PERSON_TYPE",
        standard_value="灵活就业医保",
        evidence="政策知识出现新人员类别：灵活就业人员",
        source_ref="doc_1/unit_2/kn_3",
    ))

    assert proposal.status == "draft"
    assert "灵活就业医保" not in registry_store.get_value_domain("PERSON_TYPE").standard_values  # type: ignore[union-attr]

    approved = service.approve_standard_value(proposal.proposal_id, reviewed_by="semantic_reviewer")

    assert approved.status == "published"
    assert "灵活就业医保" in registry_store.get_value_domain("PERSON_TYPE").standard_values  # type: ignore[union-attr]


def test_create_policy_metric_only_creates_draft_with_source_binding() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        CreateMetricDraft,
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        SemanticAlignmentService,
    )

    registry, _registry_store = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    metric = CreateMetricDraft(
        metric_code="zcgz.special_population",
        object_code="zcgz",
        name="特殊人群",
        semantic_type="Enum",
        value_domain="PERSON_TYPE",
        metric_kind="field",
        indexed=True,
        extraction_hint="提取特殊人群",
        schema_version=2,
        source_binding=MetricSourceBindingDraft(
            metric_code="zcgz.special_population",
            source_type="policy_knowledge",
            source_ref="doc_1/unit_2/kn_4",
            source_field="special_population",
            source_version="contract-2",
            evidence="政策原文：困难人群",
        ),
    )

    created = service.create_metric_draft(metric)

    assert created.status == "draft"
    assert registry.get_metric("zcgz.special_population").status == "draft"  # type: ignore[union-attr]
    assert registry.get_metric("zcgz.special_population").indexed is True  # type: ignore[union-attr]
    assert registry.get_metric("zcgz.special_population").extraction_hint == "提取特殊人群"  # type: ignore[union-attr]
    assert registry.get_metric("zcgz.special_population").schema_version == 2  # type: ignore[union-attr]
    assert len(service.list_metric_bindings("zcgz.special_population")) == 1


def test_postgres_alignment_store_upserts_and_reads_source_binding() -> None:
    from src.data_platform.storage.postgresql.semantic_alignment_store import (
        PostgresSemanticAlignmentStore,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        MetricSourceBinding,
    )

    calls: list[tuple[str, tuple[object, ...]]] = []
    row = {
        "binding_id": "mb_1",
        "metric_code": "zcgz.person_type",
        "source_type": "policy_knowledge",
        "source_ref": "doc_1/unit_1/kn_1",
        "source_field": "psn_type",
        "source_version": "contract-2",
        "evidence": "政策证据",
        "status": "draft",
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": None,
    }

    class FakeClient:
        def execute(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
            calls.append((sql, params))
            return [row] if sql.lstrip().upper().startswith("SELECT") else []

    store = PostgresSemanticAlignmentStore("postgresql://test")
    store._client = FakeClient()  # type: ignore[assignment]
    binding = MetricSourceBinding(**{k: v for k, v in row.items() if k != "created_at"})

    store.save_binding(binding)
    result = store.list_bindings("zcgz.person_type")

    assert result[0].binding_id == "mb_1"
    assert "ON CONFLICT (binding_id)" in calls[0][0]
    assert calls[1][1] == ("zcgz.person_type",)


def _signal(**overrides: object):
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        DiscoveryEvidence,
        DiscoverySignal,
        TriggerSource,
    )

    data = {
        "trigger_source": TriggerSource.EXTRACTION_UNKNOWN,
        "concept": "大额互助起付标准",
        "metric_code": "zcgz.mutual_aid_deductible",
        "metric_name": "大额互助起付标准",
        "semantic_type": "Amount",
        "unit": "元",
        "confidence": 0.45,
        "evidence": DiscoveryEvidence(
            source_ref="doc_1/unit_1/extraction_1",
            excerpt="大额医疗互助年度起付标准 650 元",
            doc_id="doc_1",
            unit_id="unit_1",
            extraction_id="extraction_1",
            occurrence_count=2,
        ),
    }
    data.update(overrides)
    return DiscoverySignal(**data)


def test_intake_rejects_shell_metric_signal() -> None:
    """空壳 new_metric（code/semantic_type/definition 缺失）不生成提议（修1）。"""
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())

    # 空 code + 空 semantic_type + 空 definition → 丢弃
    dropped = service.intake_signal(_signal(
        metric_code=None, metric_name=None, semantic_type=None,
    ))
    assert dropped is None
    assert service.list_proposals() == []


def test_intake_skips_concept_already_published() -> None:
    """建议 code 已在 registry published → 不重复提议（修2，sp_73ac7 复现）。"""
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, store = _registry()
    store.save_metric(Metric(
        metric_code="zcgz.dyylhzzj", object_code="zcgz", name="大额医疗互助资金",
        semantic_type="String", status="published",
    ))
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())

    result = service.intake_signal(_signal(
        concept="大病医疗保险", metric_code="zcgz.dyylhzzj",
    ))
    assert result is None
    assert service.list_proposals() == []


def test_publish_dimension_creates_object_prefixed_metric() -> None:
    """维度候选发布：指标 code 必须带对象前缀（zcgz.fund_type），
    不能是裸码（jjgs）——否则提取契约字段风格不一致、按对象检索失真。"""
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        CandidateDomainValue,
        ConflictPartitionEvidence,
        DimensionCandidateProposal,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        DimensionReviewConclusion,
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        ProposalType,
        SemanticAlignmentService,
        SemanticProposal,
        TriggerSource,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    proposal = SemanticProposal(
        proposal_id="sp_dim_test",
        fingerprint="fp_dim_test",
        proposal_type=ProposalType.DIMENSION,
        trigger_source=TriggerSource.CONFLICT_PARTITION,
        concept="基金归属",
        object_code="zcgz",
        dimension_candidate=DimensionCandidateProposal(
            fingerprint="fp_dim_candidate",
            suggested_code="fund_type",
            suggested_name="基金归属",
            semantic_type="Enum",
            metric_role="dimension",
            candidate_values=[
                CandidateDomainValue(code="pooled_fund", label="统筹基金"),
                CandidateDomainValue(code="large_mutual_aid_fund", label="大额医疗互助资金"),
            ],
            evidence_grade="single_observation",
            naming_status="resolved",
            evidence=ConflictPartitionEvidence(
                trigger_source=TriggerSource.CONFLICT_PARTITION,
                document_id="doc_1",
                extraction_snapshot_id="snap_1",
                extraction_contract_version="2",
                identity_signature={"known_values": {}, "unknown_fields": []},
                conflict_values=[],
                partition_mappings=[],
                coverage=1.0,
                exclusivity=1.0,
                evidence_grade="single_observation",
                rule_ids=["r1"],
                source_clause_ids=["c1"],
                evidence_texts=["原文证据"],
                unknown_identity_fields=[],
                competing_axis_candidates=[],
                diagnosis="missing_dimension",
            ),
            status="proposed",
        ),
        evidence=[],
        confidence=0.0,
        occurrence_count=1,
    )
    service._store.merge_proposal(proposal)
    resolved = service.resolve_dimension_proposal(
        "sp_dim_test",
        DimensionReviewConclusion.NEW_DIMENSION,
        reviewed_by="reviewer",
        suggested_name="基金归属",
        suggested_code="fund_type",
    )

    assert resolved.status == ProposalStatus.PUBLISHED
    metric = registry.get_metric("zcgz.fund_type")
    assert metric is not None, "应创建带对象前缀的指标 zcgz.fund_type"
    assert metric.object_code == "zcgz"
    assert metric.semantic_type == "Enum"
    domain = registry.get_value_domain("fund_type")
    assert domain is not None and len(domain.standard_values) == 2


def test_intake_drops_dimension_value_family_concepts() -> None:
    """方案 C：基金名同族概念是缺失维度的候选取值（由 S5 维度候选承接），
    禁止注册为 String 指标（实测 sp_e813/sp_6def41f0 系列）。"""
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())

    for concept in (
        "大额医疗互助资金", "住院大额医疗互助资金",
        "门诊大额医疗互助资金", "基本医疗保险统筹基金",
    ):
        dropped = service.intake_signal(_signal(
            concept=concept, metric_code="zcgz.some_code",
        ))
        assert dropped is None, concept
    assert service.list_proposals() == []

    # 含度量核心的同族概念（如「大额医疗互助资金支付比例」）是真度量，不拦截
    kept = service.intake_signal(_signal(
        concept="大额医疗互助资金支付比例", metric_code="zcgz.mutual_aid_ratio",
    ))
    assert kept is not None


def test_intake_requires_snake_case_metric_code() -> None:
    """LLM 自报 code 非小写蛇形（中英混拼/大写/连字符）→ 丢弃而非入队（修3）。"""
    import re
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())

    bad = service.intake_signal(_signal(
        concept="住院补充医疗保险",
        metric_code="zcgz.hospital_large_medical_mutual_fund",
    ))
    # 英文全拼风格合法（仅小写字母数字下划线），但与语义层拼音风格并存——
    # 本条只拦截非法字符；风格统一由命名审核把关。
    assert bad is not None
    result = service.intake_signal(_signal(
        concept="门诊大额", metric_code="zcgz.Outpatient-大额",
    ))
    assert result is None
    assert len(service.list_proposals()) == 1


def test_intake_normalizes_mismatched_metric_code_prefix() -> None:
    """LLM 自报 code 前缀与对象不一致时（实测 zcfg.dyylhzzj 挂在 zcgz 下），
    提议创建即纠正为 object_code 前缀，避免发布后语义层展示错乱。"""
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())

    proposal = service.intake_signal(_signal(metric_code="zcfg.dyylhzzj"))
    assert proposal.metric_draft is not None
    assert proposal.metric_draft.metric_code == "zcgz.dyylhzzj"

    no_dot = service.intake_signal(_signal(
        concept="门诊特殊病种", metric_code="plaincode",
    ))
    assert no_dot.metric_draft is not None
    assert no_dot.metric_draft.metric_code == "zcgz.plaincode"


def test_intake_routes_new_concept_new_enum_value_and_alias() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalType,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())

    metric = service.intake_signal(_signal())
    new_value = service.intake_signal(_signal(
        concept="灵活就业人员",
        axis_metric_code="zcgz.person_type",
        metric_code=None,
        metric_name=None,
        semantic_type=None,
        unit=None,
    ))
    alias = service.intake_signal(_signal(
        concept="城镇职工",
        axis_metric_code="zcgz.person_type",
        alias_target="职工医保",
        metric_code=None,
        metric_name=None,
        semantic_type=None,
        unit=None,
        suggested_mappings=[SourceValueMappingDraft(
            metric_code="zcgz.person_type",
            domain_code="PERSON_TYPE",
            source_value="城镇职工",
            standard_value="职工医保",
        )],
    ))

    assert metric.proposal_type == ProposalType.METRIC
    assert new_value.proposal_type == ProposalType.VALUE
    assert new_value.mapping_only is False
    assert alias.proposal_type == ProposalType.VALUE
    assert alias.mapping_only is True
    assert alias.value_draft.standard_value == "职工医保"  # type: ignore[union-attr]


def test_intake_merges_cross_source_evidence_without_source_ref_in_fingerprint() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    first = service.intake_signal(_signal())
    duplicate = service.intake_signal(_signal())
    merged = service.intake_signal(_signal(
        confidence=0.7,
        evidence={
            "source_ref": "doc_2/unit_9/extraction_2",
            "excerpt": "大额互助的起付标准为 650 元",
            "doc_id": "doc_2",
            "unit_id": "unit_9",
            "extraction_id": "extraction_2",
            "occurrence_count": 3,
        },
    ))

    assert first.proposal_id == duplicate.proposal_id == merged.proposal_id
    assert len(service.list_proposals()) == 1
    assert len(merged.evidence) == 2
    assert merged.occurrence_count == 5
    assert merged.confidence == 1.0


def test_same_source_ref_replaces_evidence_without_inflating_confidence() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    first = service.intake_signal(_signal(evidence={
        "source_ref": "doc_1/unit_1/concept_hash",
        "excerpt": "大额医疗互助年度起付标准 650 元",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "extraction_id": "extraction_old",
        "occurrence_count": 2,
    }))
    refreshed = service.intake_signal(_signal(
        confidence=0.9,
        evidence={
            "source_ref": "doc_1/unit_1/concept_hash",
            "excerpt": "大额医疗互助年度起付标准调整为 700 元",
            "doc_id": "doc_1",
            "unit_id": "unit_1",
            "extraction_id": "extraction_current",
            "occurrence_count": 4,
        },
    ))

    assert refreshed.proposal_id == first.proposal_id
    assert refreshed.occurrence_count == 4
    assert refreshed.confidence == first.confidence
    assert len(refreshed.evidence) == 1
    assert refreshed.evidence[0].extraction_id == "extraction_current"


def test_semantic_alignment_singleton_initializes_once_under_concurrency(monkeypatch) -> None:
    import time
    from src.knowledge_extension.rule_explanation import semantic_alignment as module
    from src.semantic_layer import registry as registry_module

    registry, _ = _registry()
    calls = 0
    calls_lock = threading.Lock()
    start = threading.Barrier(12)

    def get_registry():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.02)
        return registry

    previous = module._semantic_alignment_service
    module._semantic_alignment_service = None
    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    monkeypatch.setattr(registry_module, "get_semantic_registry", get_registry)
    services = []

    def load() -> None:
        start.wait()
        services.append(module.get_semantic_alignment_service())

    threads = [threading.Thread(target=load) for _ in range(12)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert calls == 1
        assert len({id(service) for service in services}) == 1
    finally:
        module._semantic_alignment_service = previous


def test_proposal_state_machine_allows_only_governed_transitions() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    proposal = service.intake_signal(_signal())

    reviewing = service.transition_proposal(
        proposal.proposal_id, ProposalStatus.REVIEWING, reviewed_by="reviewer"
    )
    accepted = service.transition_proposal(
        proposal.proposal_id, ProposalStatus.ACCEPTED, reviewed_by="reviewer"
    )
    assert reviewing.status == ProposalStatus.REVIEWING
    assert accepted.status == ProposalStatus.ACCEPTED
    assert service.get_proposal(proposal.proposal_id).status == ProposalStatus.ACCEPTED  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="非法状态转换"):
        service.transition_proposal(
            proposal.proposal_id, ProposalStatus.PROPOSED, reviewed_by="reviewer"
        )

    rejectable = service.intake_signal(_signal(concept="另一概念", metric_code="zcgz.other"))
    service.transition_proposal(rejectable.proposal_id, ProposalStatus.REVIEWING)
    rejected = service.transition_proposal(
        rejectable.proposal_id, ProposalStatus.REJECTED, reviewed_by="reviewer",
        review_note="概念不成立",
    )
    assert rejected.status == ProposalStatus.REJECTED
    assert service.list_proposals(status=ProposalStatus.REJECTED) == [rejected]


def test_publish_metric_proposals_are_visible_to_extraction_schema_and_idempotent() -> None:
    from src.domain.indicator.models import MetricFormula
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )
    from src.semantic_layer.extraction_contract import build_extraction_schema

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())

    atomic = service.intake_signal(_signal())
    enum = service.intake_signal(_signal(
        concept="互助人群",
        metric_code="zcgz.mutual_aid_population",
        metric_name="互助人群",
        semantic_type="Enum",
        value_domain="MUTUAL_AID_POPULATION",
    ))
    derived = service.intake_signal(_signal(
        concept="个人支付互补比例",
        metric_code="zcgz.personal_complement_ratio",
        metric_name="个人支付互补比例",
        metric_type="Derived",
        semantic_type="Ratio",
        unit="%",
        formula=MetricFormula(
            expression="1 - zcgz.payment_ratio",
            dependencies=["zcgz.payment_ratio"],
            type="arithmetic",
        ),
    ))

    for proposal in (atomic, enum, derived):
        service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
        service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
        published = service.publish_proposal(proposal.proposal_id, reviewed_by="reviewer")
        assert published.status == ProposalStatus.PUBLISHED
        assert service.publish_proposal(proposal.proposal_id).status == ProposalStatus.PUBLISHED

    schema = build_extraction_schema(registry, "zcgz")
    assert {field.code for field in schema.fields} >= {
        "mutual_aid_deductible", "mutual_aid_population", "personal_complement_ratio"
    }
    assert schema.dictionaries["MUTUAL_AID_POPULATION"] == []
    assert registry.get_metric("zcgz.mutual_aid_deductible").status == "published"  # type: ignore[union-attr]
    assert registry.get_metric("zcgz.personal_complement_ratio").transformation == {  # type: ignore[union-attr]
        "expression": "1 - zcgz.payment_ratio",
        "dependencies": ["zcgz.payment_ratio"],
        "type": "arithmetic",
    }


def test_publish_value_and_mapping_only_proposals_update_registry_resolution() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    registry, registry_store = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    value = service.intake_signal(_signal(
        concept="灵活就业人员",
        axis_metric_code="zcgz.person_type",
        metric_code=None,
        metric_name=None,
        semantic_type=None,
        unit=None,
        suggested_mappings=[SourceValueMappingDraft(
            metric_code="zcgz.person_type", domain_code="PERSON_TYPE",
            source_value="灵活就业", standard_value="灵活就业人员",
        )],
    ))
    alias = service.intake_signal(_signal(
        concept="城镇职工", axis_metric_code="zcgz.person_type",
        alias_target="职工医保", metric_code=None, metric_name=None,
        semantic_type=None, unit=None,
    ))
    merged_alias = service.intake_signal(_signal(
        concept="城镇在职职工", axis_metric_code="zcgz.person_type",
        alias_target="职工医保", metric_code=None, metric_name=None,
        semantic_type=None, unit=None,
    ))
    assert merged_alias.proposal_id == alias.proposal_id

    for proposal in (value, alias):
        service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
        service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
        service.publish_proposal(proposal.proposal_id, reviewed_by="reviewer")

    domain = registry_store.get_value_domain("PERSON_TYPE")
    assert domain.standard_values.count("灵活就业人员") == 1  # type: ignore[union-attr]
    assert "城镇职工" not in domain.standard_values  # type: ignore[union-attr]
    assert registry.resolve_value("PERSON_TYPE", "灵活就业") == "灵活就业人员"
    assert registry.resolve_value("PERSON_TYPE", "城镇职工") == "职工医保"
    assert registry.resolve_value("PERSON_TYPE", "城镇在职职工") == "职工医保"


def test_intake_rejects_sensitive_evidence_without_persisting() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    store = InMemorySemanticAlignmentStore()
    service = SemanticAlignmentService(registry, store)

    with pytest.raises(ValueError, match="敏感信息"):
        service.intake_signal(_signal(evidence={
            "source_ref": "doc_sensitive/unit_1",
            "excerpt": "患者手机号 13812345678",
            "doc_id": "doc_sensitive",
            "unit_id": "unit_1",
            "extraction_id": "extraction_sensitive",
        }))

    assert service.list_proposals() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"concept": "患者 11010519491231002X 的新概念"},
        {"suggested_mappings": [{
            "metric_code": "zcgz.person_type", "domain_code": "PERSON_TYPE",
            "source_value": "13812345678", "standard_value": "职工医保",
        }]},
    ],
)
def test_intake_rejects_sensitive_data_anywhere_in_signal(
    overrides: dict[str, object]
) -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    with pytest.raises(ValueError, match="敏感信息"):
        service.intake_signal(_signal(**overrides))
    assert service.list_proposals() == []


def test_postgres_proposal_store_upserts_gets_and_lists_json_payload() -> None:
    from src.data_platform.storage.postgresql.semantic_alignment_store import (
        PostgresSemanticAlignmentStore,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    proposal = SemanticAlignmentService(
        registry, InMemorySemanticAlignmentStore()
    ).intake_signal(_signal())
    row = {
        "proposal_id": proposal.proposal_id,
        "fingerprint": proposal.fingerprint,
        "proposal_type": proposal.proposal_type,
        "trigger_source": proposal.trigger_source,
        "status": proposal.status,
        "confidence": proposal.confidence,
        "occurrence_count": proposal.occurrence_count,
        "payload": proposal.model_dump(mode="json", exclude={"evidence"}),
        "evidence": [item.model_dump(mode="json") for item in proposal.evidence],
    }
    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeClient:
        def execute(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
            calls.append((sql, params))
            return [row] if sql.lstrip().upper().startswith("SELECT") else []

    store = PostgresSemanticAlignmentStore("postgresql://test")
    store._client = FakeClient()  # type: ignore[assignment]

    store.save_proposal(proposal)
    assert store.get_proposal(proposal.proposal_id).proposal_id == proposal.proposal_id  # type: ignore[union-attr]
    assert store.list_proposals()[0].fingerprint == proposal.fingerprint
    assert "ON CONFLICT (fingerprint)" in calls[0][0]


@pytest.mark.parametrize(
    ("trigger_source", "evidence"),
    [
        ("EXTRACTION_UNKNOWN", {"source_ref": "doc/u/e", "doc_id": "doc", "unit_id": "u", "extraction_id": "e", "excerpt": "原文"}),
        ("DEMAND_GAP", {"source_ref": "gap:insu", "gap_signature": "insu|hosp", "representative_questions": ["问题"]}),
        ("DATA_SCAN", {"source_ref": "his.patient.kind", "table_name": "patient", "field_name": "kind", "sample_values": ["1"], "non_null_rate": 0.9, "distinct_count": 3}),
        ("DERIVATION_PATTERN", {"source_ref": "derive:ratio", "base_metric_code": "zcgz.payment_ratio", "operator": "multiply", "observations": ["退休×0.6", "二次住院×0.5"], "rule_ids": ["r1"]}),
    ],
)
def test_discovery_signal_accepts_all_trigger_evidence_shapes(
    trigger_source: str, evidence: dict[str, object]
) -> None:
    signal = _signal(trigger_source=trigger_source, evidence=evidence)
    assert signal.trigger_source == trigger_source
    assert signal.evidence.source_ref == evidence["source_ref"]


@pytest.mark.parametrize(
    ("trigger_source", "evidence"),
    [
        ("EXTRACTION_UNKNOWN", {"source_ref": "doc/u/e", "doc_id": "doc", "unit_id": "u"}),
        ("DEMAND_GAP", {"source_ref": "gap", "gap_signature": "insu|hosp", "representative_questions": []}),
        ("DATA_SCAN", {"source_ref": "scan", "table_name": "patient", "field_name": "kind", "non_null_rate": 0.9}),
        ("DERIVATION_PATTERN", {"source_ref": "derive", "base_metric_code": "zcgz.ratio", "operator": "multiply", "observations": ["只一次"], "rule_ids": []}),
    ],
)
def test_discovery_signal_rejects_incomplete_trigger_evidence(
    trigger_source: str, evidence: dict[str, object]
) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="evidence"):
        _signal(trigger_source=trigger_source, evidence=evidence)


def test_demand_gap_fingerprint_uses_gap_signature_not_concept() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    evidence = {
        "source_ref": "gap:insu|hosp",
        "gap_signature": "insu|hosp",
        "representative_questions": ["问题一"],
    }
    first = service.intake_signal(_signal(
        trigger_source="DEMAND_GAP", concept="职工起付空回", evidence=evidence,
    ))
    merged = service.intake_signal(_signal(
        trigger_source="DEMAND_GAP", concept="住院起付线未命中",
        metric_code="zcgz.other_suggestion",
        evidence={**evidence, "source_ref": "gap:second", "representative_questions": ["问题二"]},
    ))
    assert merged.proposal_id == first.proposal_id
    assert merged.occurrence_count == first.occurrence_count + 1


def test_metric_fingerprint_merges_same_concept_despite_different_suggested_code() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    first = service.intake_signal(_signal(metric_code="zcgz.first_code"))
    merged = service.intake_signal(_signal(
        metric_code="zcgz.second_code",
        evidence={
            "source_ref": "doc_2/unit_1", "excerpt": "同一大额互助起付概念",
            "doc_id": "doc_2", "unit_id": "unit_1", "extraction_id": "extraction_2",
        },
    ))
    assert merged.proposal_id == first.proposal_id
    assert len(service.list_proposals()) == 1


def test_transition_cannot_bypass_landing_or_reject_without_reason() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    proposal = service.intake_signal(_signal())
    service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
    service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
    with pytest.raises(ValueError, match="publish_proposal"):
        service.transition_proposal(proposal.proposal_id, ProposalStatus.PUBLISHED)

    rejectable = service.intake_signal(_signal(concept="待驳回", metric_code="zcgz.reject_me"))
    service.transition_proposal(rejectable.proposal_id, ProposalStatus.REVIEWING)
    with pytest.raises(ValueError, match="驳回原因"):
        service.transition_proposal(rejectable.proposal_id, ProposalStatus.REJECTED)


@pytest.mark.parametrize(
    "signal_overrides",
    [
        {"metric_code": None},
        {"object_code": "missing"},
        {"metric_type": "Unknown"},
        {"semantic_type": None},
        {"semantic_type": "Unknown"},
        {"metric_kind": "unknown"},
        {"semantic_type": "Enum", "value_domain": None},
        {"metric_type": "Derived", "formula": None},
    ],
)
def test_accept_metric_proposal_validates_required_review_fields(
    signal_overrides: dict[str, object]
) -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    proposal = service.intake_signal(_signal(**signal_overrides))
    if "metric_code" in signal_overrides and signal_overrides["metric_code"] is None:
        # 空 code 在入队门禁即被拦截（不再产生空壳提议进入审核流）
        assert proposal is None
        return
    service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
    with pytest.raises(ValueError, match="指标提议"):
        service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)


def test_metric_publish_rejects_conflict_but_accepts_equivalent_published_metric() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, registry_store = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    conflict = service.intake_signal(_signal(
        concept="冲突人员类型", metric_code="zcgz.person_type_conflict",
        metric_name="不同名称", semantic_type="String",
    ))
    service.transition_proposal(conflict.proposal_id, ProposalStatus.REVIEWING)
    service.transition_proposal(conflict.proposal_id, ProposalStatus.ACCEPTED)
    # 发布前指标才被另一个流程注册且不等价 → 发布拒绝（竞态防线）
    registry_store.save_metric(Metric(
        metric_code="zcgz.person_type_conflict", object_code="zcgz", name="另一含义",
        metric_type="Atomic", semantic_type="String", status="published",
    ))
    with pytest.raises(ValueError, match="已存在且不等价"):
        service.publish_proposal(conflict.proposal_id)
    assert service.get_proposal(conflict.proposal_id).status == ProposalStatus.ACCEPTED  # type: ignore[union-attr]

    registry_store.save_metric(Metric(
        metric_code="zcgz.same", object_code="zcgz", name="等价指标",
        metric_type="Atomic", semantic_type="Amount", unit="元",
        metric_kind="field", indexed=True, extraction_hint="提取金额",
        schema_version=2, status="published",
    ))
    equivalent = service.intake_signal(_signal(
        concept="等价概念", metric_code="zcgz.same", metric_name="等价指标",
        metric_type="Atomic", semantic_type="Amount", unit="元",
        metric_kind="field", indexed=True, extraction_hint="提取金额", schema_version=2,
    ))
    # 新门禁：code 已发布 → 不再重复提议（发布幂等冲突防线仍在，但入队即拦）
    assert equivalent is None


def test_published_suggested_mappings_preserve_source_specific_resolution() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        ProposalStatus,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    first_binding = service.bind_existing_metric(MetricSourceBindingDraft(
        metric_code="zcgz.person_type", source_type="structured_field",
        source_ref="his.patient", source_field="kind", source_version="v1", evidence="HIS",
    ))
    second_binding = service.bind_existing_metric(MetricSourceBindingDraft(
        metric_code="zcgz.person_type", source_type="structured_field",
        source_ref="insurance.patient", source_field="kind", source_version="v1", evidence="医保",
    ))
    first = service.intake_signal(_signal(
        concept="灵活就业人员", axis_metric_code="zcgz.person_type",
        metric_code=None, metric_name=None, semantic_type=None, unit=None,
        suggested_mappings=[SourceValueMappingDraft(
            metric_code="zcgz.person_type", domain_code="PERSON_TYPE",
            binding_id=first_binding.binding_id, source_value="1", standard_value="灵活就业人员",
        )],
    ))
    second = service.intake_signal(_signal(
        concept="HIS职工别名", axis_metric_code="zcgz.person_type", alias_target="职工医保",
        metric_code=None, metric_name=None, semantic_type=None, unit=None,
        suggested_mappings=[SourceValueMappingDraft(
            metric_code="zcgz.person_type", domain_code="PERSON_TYPE",
            binding_id=second_binding.binding_id, source_value="2", standard_value="职工医保",
        )],
    ))
    for proposal in (first, second):
        service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
        service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
        service.publish_proposal(proposal.proposal_id)
    assert service.resolve_source_value(first_binding.binding_id, "1") == "灵活就业人员"
    assert service.resolve_source_value(second_binding.binding_id, "2") == "职工医保"


def test_postgres_merge_proposal_uses_transaction_lock_and_shared_merge_semantics() -> None:
    from src.data_platform.storage.postgresql.semantic_alignment_store import (
        PostgresSemanticAlignmentStore,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    proposal = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore()).intake_signal(_signal())
    calls: list[tuple[str, tuple[object, ...]]] = []
    transactions = 0

    class FakeClient:
        @contextmanager
        def transaction(self):
            nonlocal transactions
            transactions += 1
            yield

        def execute(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
            calls.append((sql, params))
            return []

    store = PostgresSemanticAlignmentStore("postgresql://test")
    store._client = FakeClient()  # type: ignore[assignment]
    store.merge_proposal(proposal)
    assert transactions == 1
    assert "pg_advisory_xact_lock" in calls[0][0]
    assert "FOR UPDATE" in calls[1][0]
    assert "ON CONFLICT (fingerprint)" in calls[2][0]


def test_global_mapping_conflict_does_not_publish_any_partial_mapping() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        ProposalStatus,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    bindings = [
        service.bind_existing_metric(MetricSourceBindingDraft(
            metric_code="zcgz.person_type", source_type="structured_field",
            source_ref=source, source_field="kind", source_version="v1", evidence=source,
        ))
        for source in ("his.patient", "insurance.patient")
    ]

    def _proposal(concept: str, standard: str, binding_id: str):
        alias_target = standard if standard == "职工医保" else None
        return service.intake_signal(_signal(
            concept=concept, axis_metric_code="zcgz.person_type", alias_target=alias_target,
            metric_code=None, metric_name=None, semantic_type=None, unit=None,
            suggested_mappings=[SourceValueMappingDraft(
                metric_code="zcgz.person_type", domain_code="PERSON_TYPE",
                binding_id=binding_id, source_value="X", standard_value=standard,
            )],
        ))

    first = _proposal("灵活就业人员", "灵活就业人员", bindings[0].binding_id)
    second = _proposal("职工别名", "职工医保", bindings[1].binding_id)
    for proposal in (first, second):
        service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
        service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
    service.publish_proposal(first.proposal_id)
    with pytest.raises(ValueError, match="落地目标已被其他提议占用|全局值域映射冲突"):
        service.publish_proposal(second.proposal_id)

    assert registry.resolve_value("PERSON_TYPE", "X") == "灵活就业人员"
    assert service.resolve_source_value(bindings[0].binding_id, "X") == "灵活就业人员"
    assert service.resolve_source_value(bindings[1].binding_id, "X") == "X"


@pytest.mark.parametrize(
    "mapping_overrides",
    [
        {"metric_code": "zcgz.wrong_axis"},
        {"domain_code": "WRONG_DOMAIN"},
        {"standard_value": "错误目标"},
    ],
)
def test_value_publish_rejects_wrong_axis_domain_or_target_without_writes(
    mapping_overrides: dict[str, str]
) -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        ProposalStatus,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    registry, registry_store = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    binding = service.bind_existing_metric(MetricSourceBindingDraft(
        metric_code="zcgz.person_type", source_type="structured_field",
        source_ref="his.patient", source_field="kind", source_version="v1", evidence="HIS",
    ))
    mapping = {
        "metric_code": "zcgz.person_type", "domain_code": "PERSON_TYPE",
        "binding_id": binding.binding_id, "source_value": "BAD",
        "standard_value": "灵活就业人员",
    }
    mapping.update(mapping_overrides)
    proposal = service.intake_signal(_signal(
        concept="灵活就业人员", axis_metric_code="zcgz.person_type",
        metric_code=None, metric_name=None, semantic_type=None, unit=None,
        suggested_mappings=[SourceValueMappingDraft(**mapping)],
    ))
    service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
    service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
    with pytest.raises(ValueError, match="建议映射"):
        service.publish_proposal(proposal.proposal_id)

    assert "灵活就业人员" not in registry_store.get_value_domain("PERSON_TYPE").standard_values  # type: ignore[union-attr]
    assert registry.resolve_value("PERSON_TYPE", "BAD") == "BAD"
    assert service.resolve_source_value(binding.binding_id, "BAD") == "BAD"


def test_in_memory_publish_and_reject_use_compare_and_set_under_concurrency() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    proposal = service.intake_signal(_signal())
    service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
    service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def publish() -> None:
        barrier.wait()
        try:
            service.publish_proposal(proposal.proposal_id)
            outcomes.append("published")
        except ValueError:
            outcomes.append("publish_failed")

    def reject() -> None:
        barrier.wait()
        try:
            service.transition_proposal(
                proposal.proposal_id, ProposalStatus.REJECTED, review_note="驳回"
            )
            outcomes.append("rejected")
        except ValueError:
            outcomes.append("reject_failed")

    threads = [threading.Thread(target=publish), threading.Thread(target=reject)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) in (["publish_failed", "rejected"], ["published", "reject_failed"])


def test_postgres_transition_uses_status_compare_and_set() -> None:
    from src.data_platform.storage.postgresql.semantic_alignment_store import (
        PostgresSemanticAlignmentStore,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    proposal = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore()).intake_signal(_signal())
    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeClient:
        def execute(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
            calls.append((sql, params))
            return []

    store = PostgresSemanticAlignmentStore("postgresql://test")
    store._client = FakeClient()  # type: ignore[assignment]
    assert store.compare_and_set_proposal(
        proposal, ProposalStatus.PROPOSED
    ) is None
    assert "WHERE proposal_id=%s AND status=%s" in calls[0][0]
    assert "RETURNING *" in calls[0][0]


def test_postgres_transaction_coordinator_shares_client_and_rolls_back() -> None:
    from src.data_platform.storage.postgresql.semantic_alignment_store import (
        PostgresSemanticAlignmentStore,
    )

    events: list[str] = []

    class FakeClient:
        @contextmanager
        def transaction(self):
            events.append("begin")
            try:
                yield
            except Exception:
                events.append("rollback")
                raise

    class RegistryStore:
        _client = object()

    store = PostgresSemanticAlignmentStore("postgresql://test")
    client = FakeClient()
    store._client = client  # type: ignore[assignment]
    registry_store = RegistryStore()
    original = registry_store._client
    with pytest.raises(RuntimeError):
        with store.registry_transaction(registry_store):
            assert registry_store._client is client
            raise RuntimeError("landing failed")
    assert events == ["begin", "rollback"]
    assert registry_store._client is original


def test_different_proposals_competing_for_same_metric_have_one_winner() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    store = InMemorySemanticAlignmentStore()
    services = [SemanticAlignmentService(registry, store) for _ in range(2)]
    proposals = [
        services[index].intake_signal(_signal(
            concept=concept, metric_code="zcgz.shared_target",
            metric_name="共享落地指标",
        ))
        for index, concept in enumerate(("概念甲", "概念乙"))
    ]
    for index, proposal in enumerate(proposals):
        services[index].transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
        services[index].transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
    barrier = threading.Barrier(2)
    results: list[bool] = []

    def publish(index: int) -> None:
        barrier.wait()
        try:
            services[index].publish_proposal(proposals[index].proposal_id)
            results.append(True)
        except ValueError:
            results.append(False)

    threads = [threading.Thread(target=publish, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True]
    assert sorted(service.get_proposal(proposal.proposal_id).status for service, proposal in zip(services, proposals)) == [
        ProposalStatus.ACCEPTED, ProposalStatus.PUBLISHED,
    ]


def test_postgres_landing_targets_use_sorted_transaction_advisory_locks_and_claims() -> None:
    from src.data_platform.storage.postgresql.semantic_alignment_store import (
        PostgresSemanticAlignmentStore,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    proposal = SemanticAlignmentService(
        registry, InMemorySemanticAlignmentStore()
    ).intake_signal(_signal())
    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeClient:
        def execute(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
            calls.append((sql, params))
            if "RETURNING proposal_id" in sql:
                return [{"proposal_id": proposal.proposal_id}]
            return []

    store = PostgresSemanticAlignmentStore("postgresql://test")
    store._client = FakeClient()  # type: ignore[assignment]
    store.lock_and_claim_landing_targets(proposal)

    lock_calls = [(sql, params) for sql, params in calls if "pg_advisory_xact_lock" in sql]
    assert lock_calls
    assert [params[0] for _, params in lock_calls] == sorted(params[0] for _, params in lock_calls)
    assert "hashtextextended(%s, 0)" in lock_calls[0][0]
    assert any("ON CONFLICT (target_key)" in sql for sql, _ in calls)


def test_in_memory_publish_failure_rolls_back_registry_and_landing_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    store = InMemorySemanticAlignmentStore()
    service = SemanticAlignmentService(registry, store)
    proposal = service.intake_signal(_signal(
        concept="内存事务回滚指标",
        metric_code="zcgz.memory_rollback",
        metric_name="内存事务回滚指标",
    ))
    service.transition_proposal(proposal.proposal_id, ProposalStatus.REVIEWING)
    service.transition_proposal(proposal.proposal_id, ProposalStatus.ACCEPTED)
    original_cas = store.compare_and_set_proposal
    monkeypatch.setattr(store, "compare_and_set_proposal", lambda *_args: None)

    with pytest.raises(ValueError, match="发布已回滚"):
        service.publish_proposal(proposal.proposal_id)

    assert registry.get_metric("zcgz.memory_rollback") is None
    assert store.landing_target_claims == {}
    assert service.get_proposal(proposal.proposal_id).status == ProposalStatus.ACCEPTED  # type: ignore[union-attr]

    monkeypatch.setattr(store, "compare_and_set_proposal", original_cas)
    assert service.publish_proposal(proposal.proposal_id).status == ProposalStatus.PUBLISHED


@pytest.mark.parametrize("terminal_status", ["published", "rejected"])
def test_terminal_metric_proposal_does_not_repeat_an_already_resolved_problem(
    terminal_status: str,
) -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    first = service.intake_signal(_signal(
        concept=f"终态后重新发现-{terminal_status}",
        metric_code=f"zcgz.terminal_{terminal_status}",
        metric_name=f"终态后重新发现-{terminal_status}",
    ))
    service.transition_proposal(first.proposal_id, ProposalStatus.REVIEWING)
    if terminal_status == "published":
        service.transition_proposal(first.proposal_id, ProposalStatus.ACCEPTED)
        service.publish_proposal(first.proposal_id)
    else:
        service.transition_proposal(
            first.proposal_id, ProposalStatus.REJECTED, review_note="证据不足",
        )

    rediscovered = service.intake_signal(_signal(
        concept=f"终态后重新发现-{terminal_status}",
        metric_code=f"zcgz.terminal_{terminal_status}",
        metric_name=f"终态后重新发现-{terminal_status}",
        evidence={
            "source_ref": "doc_2/unit_2/extraction_2",
            "excerpt": "新一轮发现证据",
            "doc_id": "doc_2",
            "unit_id": "unit_2",
            "extraction_id": "extraction_2",
        },
    ))

    if terminal_status == "published":
        # 已发布指标的重复发现被入队门禁拦截（不再重复提议）
        assert rediscovered is None
        assert service.get_proposal(first.proposal_id).status == ProposalStatus.PUBLISHED
    else:
        assert rediscovered.proposal_id == first.proposal_id
        assert rediscovered.status == ProposalStatus.REJECTED
        assert service.get_proposal(first.proposal_id).status == ProposalStatus.REJECTED
        assert len(service.list_proposals()) == 1


def test_mapping_discovered_after_published_generation_is_reviewed_and_landed() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        ProposalStatus,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    registry, _ = _registry()
    service = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    bindings = [
        service.bind_existing_metric(MetricSourceBindingDraft(
            metric_code="zcgz.person_type",
            source_type="structured_field",
            source_ref=source_ref,
            source_field="person_type",
            source_version="v1",
            evidence=source_ref,
        ))
        for source_ref in ("his.patient", "insurance.patient")
    ]

    def intake(binding_index: int, raw_value: str, source_ref: str):
        return service.intake_signal(_signal(
            concept="城镇在职职工",
            axis_metric_code="zcgz.person_type",
            alias_target="职工医保",
            metric_code=None,
            metric_name=None,
            semantic_type=None,
            unit=None,
            evidence={
                "source_ref": source_ref,
                "excerpt": "城镇在职职工映射证据",
                "doc_id": source_ref,
                "unit_id": "unit_1",
                "extraction_id": f"extraction_{binding_index}",
            },
            suggested_mappings=[SourceValueMappingDraft(
                metric_code="zcgz.person_type",
                domain_code="PERSON_TYPE",
                binding_id=bindings[binding_index].binding_id,
                source_value=raw_value,
                standard_value="职工医保",
            )],
        ))

    first = intake(0, "A", "doc_first")
    service.transition_proposal(first.proposal_id, ProposalStatus.REVIEWING)
    service.transition_proposal(first.proposal_id, ProposalStatus.ACCEPTED)
    service.publish_proposal(first.proposal_id)

    second = intake(1, "B", "doc_second")
    assert second.proposal_id != first.proposal_id
    assert second.status == ProposalStatus.PROPOSED
    assert service.resolve_source_value(bindings[1].binding_id, "B") == "B"
    service.transition_proposal(second.proposal_id, ProposalStatus.REVIEWING)
    service.transition_proposal(second.proposal_id, ProposalStatus.ACCEPTED)
    service.publish_proposal(second.proposal_id)
    assert service.resolve_source_value(bindings[1].binding_id, "B") == "职工医保"


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not configured")
def test_postgres_proposal_transaction_roundtrip_when_database_available() -> None:
    """可选真实 PostgreSQL 跨 store 回滚 + 不同提议落地竞争。"""
    from src.data_platform.storage.postgresql.semantic_alignment_store import (
        PostgresSemanticAlignmentStore,
    )
    from src.data_platform.storage.postgresql.semantic_registry_store import (
        PostgresRegistryStore,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalStatus,
        SemanticAlignmentService,
    )
    from src.semantic_layer.registry import SemanticRegistry

    database_url = os.environ["DATABASE_URL"]
    memory_registry, _ = _registry()
    suffix = uuid.uuid4().hex
    metric_code = f"zcgz.pg_compete_{suffix}"
    rollback_metric_code = f"zcgz.pg_rollback_{suffix}"

    def make_proposal(concept: str, code: str):
        return SemanticAlignmentService(
            memory_registry, InMemorySemanticAlignmentStore()
        ).intake_signal(_signal(
            concept=concept, metric_code=code, metric_name="PG 竞争指标",
        )).model_copy(update={
            "proposal_id": f"sp_test_{uuid.uuid4().hex}",
            "fingerprint": uuid.uuid4().hex,
            "status": ProposalStatus.ACCEPTED,
        })

    proposals = [make_proposal("竞争甲", metric_code), make_proposal("竞争乙", metric_code)]
    rollback_proposal = make_proposal("回滚验证", rollback_metric_code)
    setup_store = PostgresSemanticAlignmentStore(database_url)
    client = setup_store._get_client()
    try:
        for proposal in [*proposals, rollback_proposal]:
            setup_store.save_proposal(proposal)
        results: list[bool] = []
        barrier = threading.Barrier(2)

        def publish(index: int) -> None:
            alignment_store = PostgresSemanticAlignmentStore(database_url)
            service = SemanticAlignmentService(
                SemanticRegistry(PostgresRegistryStore(database_url)), alignment_store
            )
            barrier.wait()
            try:
                service.publish_proposal(proposals[index].proposal_id)
                results.append(True)
            except ValueError:
                results.append(False)
            if alignment_store._client is not None:
                alignment_store._client.close()

        threads = [
            threading.Thread(target=publish, args=(0,)),
            threading.Thread(target=publish, args=(1,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results) == [False, True]
        statuses = [setup_store.get_proposal(item.proposal_id).status for item in proposals]  # type: ignore[union-attr]
        assert sorted(statuses) == [ProposalStatus.ACCEPTED, ProposalStatus.PUBLISHED]

        rollback_store = PostgresSemanticAlignmentStore(database_url)
        rollback_registry = SemanticRegistry(PostgresRegistryStore(database_url))
        rollback_service = SemanticAlignmentService(rollback_registry, rollback_store)

        def fail_cas(*_args: object, **_kwargs: object):
            raise RuntimeError("force cross-store rollback")

        rollback_store.compare_and_set_proposal = fail_cas  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="cross-store rollback"):
            rollback_service.publish_proposal(rollback_proposal.proposal_id)
        assert rollback_registry.get_metric(rollback_metric_code) is None
        assert setup_store.get_proposal(rollback_proposal.proposal_id).status == ProposalStatus.ACCEPTED  # type: ignore[union-attr]
    finally:
        client.execute(
            "DELETE FROM semantic_proposals WHERE proposal_id = ANY(%s)",
            ([item.proposal_id for item in [*proposals, rollback_proposal]],),
        )
        client.execute(
            "DELETE FROM semantic_metrics WHERE metric_code = ANY(%s)",
            ([metric_code, rollback_metric_code],),
        )
        client.close()
