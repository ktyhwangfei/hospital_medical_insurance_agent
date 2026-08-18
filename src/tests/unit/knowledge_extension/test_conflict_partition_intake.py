from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
    ExtractionEntity,
    ExtractionRule,
    discover_conflict_partitions,
)
from src.semantic_layer.models import BusinessObject, Metric
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


def _report():
    rules = [
        ExtractionRule(
            rule_id=rule_id,
            document_id="doc_7a1fbf7480d4",
            snapshot_id="snapshot_1",
            extraction_contract_version="contract-3",
            rule_type="支付比例",
            rule_value=value,
            rule_unit="%",
            insu_type="职工医保",
            entities=[ExtractionEntity(
                entity_id=f"{rule_id}_entity",
                name=entity_name,
                entity_type="AMOUNT",
            )],
            source_clause_id=f"clause_{rule_id}",
            evidence_text=entity_name,
        )
        for rule_id, value, entity_name in (
            ("r1", "90%", "基本医疗保险统筹基金支付比例"),
            ("r2", "80%", "大额互助资金支付比例"),
        )
    ]
    return discover_conflict_partitions(rules)


def _service():
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )

    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz",
        domain_code="policy",
        name="政策规则",
        status="published",
    ))
    alignment_store = InMemorySemanticAlignmentStore()
    return (
        SemanticAlignmentService(SemanticRegistry(registry_store), alignment_store),
        registry_store,
    )


def test_conflict_report_intake_is_idempotent_and_keeps_candidate_separate() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import ProposalType

    service, _registry_store = _service()
    first = service.intake_conflict_report(
        _report(), document_id="doc_7a1fbf7480d4", snapshot_id="snapshot_1"
    )[0]
    repeated = service.intake_conflict_report(
        _report(), document_id="doc_7a1fbf7480d4", snapshot_id="snapshot_1"
    )[0]

    assert first.proposal_id == repeated.proposal_id
    assert repeated.proposal_type == ProposalType.DIMENSION
    assert repeated.metric_draft is None
    assert repeated.dimension_candidate.suggested_code == "fund_type"  # type: ignore[union-attr]
    assert len(service.list_proposals(ProposalType.DIMENSION)) == 1

    service.intake_conflict_report(
        type(_report())(), document_id="doc_7a1fbf7480d4", snapshot_id="snapshot_2"
    )
    assert service.get_proposal(first.proposal_id).status.value == "stale"  # type: ignore[union-attr]
    reappeared = service.intake_conflict_report(
        _report(), document_id="doc_7a1fbf7480d4", snapshot_id="snapshot_1"
    )[0]
    assert reappeared.status.value == "proposed"
    assert reappeared.proposal_id != first.proposal_id


def test_published_enum_with_same_name_suppresses_solved_dimension_proposal() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import ProposalType

    service, registry_store = _service()
    registry_store.save_metric(Metric(
        metric_code="jjgs",
        object_code="zcgz",
        name="基金归属",
        semantic_type="Enum",
        status="published",
    ))

    saved = service.intake_conflict_report(
        _report(), document_id="doc_7a1fbf7480d4", snapshot_id="snapshot_1"
    )

    assert saved == []
    assert service.list_proposals(ProposalType.DIMENSION) == []


def test_non_dimension_resolution_records_conclusion_without_publishing() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        DimensionReviewConclusion,
        ProposalStatus,
    )

    service, registry_store = _service()
    proposal = service.intake_conflict_report(
        _report(), document_id="doc_7a1fbf7480d4", snapshot_id="snapshot_1"
    )[0]

    resolved = service.resolve_dimension_proposal(
        proposal.proposal_id,
        DimensionReviewConclusion.METRIC_SPLIT_REQUIRED,
        reviewed_by="semantic-reviewer",
        review_note="支付比例与限额应拆分",
    )

    assert resolved.status == ProposalStatus.REJECTED
    assert resolved.review_conclusion == DimensionReviewConclusion.METRIC_SPLIT_REQUIRED
    assert registry_store.get_metric("zcgz.fund_type") is None
    assert registry_store.get_value_domain("fund_type") is None


def test_new_dimension_resolution_atomically_publishes_enum_domain_and_contract() -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        DimensionReviewConclusion,
        ProposalStatus,
    )

    service, registry_store = _service()
    proposal = service.intake_conflict_report(
        _report(), document_id="doc_7a1fbf7480d4", snapshot_id="snapshot_1"
    )[0]

    published = service.resolve_dimension_proposal(
        proposal.proposal_id,
        DimensionReviewConclusion.NEW_DIMENSION,
        reviewed_by="semantic-reviewer",
    )

    metric = registry_store.get_metric("zcgz.fund_type")
    domain = registry_store.get_value_domain("fund_type")
    assert published.status == ProposalStatus.PUBLISHED
    assert published.review_conclusion == DimensionReviewConclusion.NEW_DIMENSION
    assert metric is not None
    assert metric.semantic_type == "Enum"
    assert metric.value_domain == "fund_type"
    assert metric.indexed is True
    assert domain is not None
    assert set(domain.standard_values) == {"统筹基金", "大额医疗互助资金"}
    assert registry_store.get_object("zcgz").current_version == "1"  # type: ignore[union-attr]
    assert registry_store.get_value_mappings("fund_type")[0].description.startswith(
        f"维度候选 {proposal.proposal_id}"
    )


def test_postgres_payload_keeps_dimension_candidate_and_review_conclusion() -> None:
    from src.data_platform.storage.postgresql.semantic_alignment_store import (
        _proposal_payload,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        DimensionReviewConclusion,
    )

    service, _registry_store = _service()
    proposal = service.intake_conflict_report(
        _report(), document_id="doc_7a1fbf7480d4", snapshot_id="snapshot_1"
    )[0].model_copy(update={
        "review_conclusion": DimensionReviewConclusion.NEW_DIMENSION,
    })

    payload = _proposal_payload(proposal)

    assert payload["review_conclusion"] == "new_dimension"
    assert payload["dimension_candidate"]["suggested_code"] == "fund_type"
