from __future__ import annotations

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
