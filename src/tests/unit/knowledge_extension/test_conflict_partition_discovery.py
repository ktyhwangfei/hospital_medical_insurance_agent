from decimal import Decimal


def _rule(
    rule_id: str,
    value: object,
    entity_names: list[str],
    *,
    hosp_lv: str | None = None,
    effective_start: str | None = None,
    entity_scope: str = "rule",
    entity_type: str | None = None,
):
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        ExtractionEntity,
        ExtractionRule,
    )

    return ExtractionRule(
        rule_id=rule_id,
        document_id="doc_7a1fbf7480d4",
        snapshot_id="snapshot_1",
        extraction_contract_version="contract-3",
        rule_type="支付比例",
        rule_value=value,
        rule_unit="%",
        insu_type="职工医保",
        hosp_lv=hosp_lv,
        effective_start=effective_start,
        entities=[
            ExtractionEntity(
                entity_id=f"{rule_id}_e{index}",
                name=name,
                entity_type=entity_type or ("DATE" if name.endswith("年") else "AMOUNT"),
                binding_scope=entity_scope,
            )
            for index, name in enumerate(entity_names)
        ],
        source_clause_id=f"clause_{rule_id}",
        evidence_text="；".join(entity_names),
    )


def test_rule_value_normalization_prevents_false_conflicts() -> None:
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        normalize_rule_value,
    )

    percent = normalize_rule_value("90%", rule_type="支付比例")
    decimal = normalize_rule_value("0.9", rule_type="支付比例")
    assert (percent.semantic_type, percent.canonical_value, percent.canonical_unit) == (
        decimal.semantic_type,
        decimal.canonical_value,
        decimal.canonical_unit,
    )
    assert normalize_rule_value("百分之九十", rule_type="支付比例").canonical_value == "0.9"
    amount = normalize_rule_value("50万元", rule_type="最高支付限额")
    base_amount = normalize_rule_value("500000元", rule_type="最高支付限额")
    assert (amount.semantic_type, amount.canonical_value, amount.canonical_unit) == (
        base_amount.semantic_type,
        base_amount.canonical_value,
        base_amount.canonical_unit,
    )
    assert normalize_rule_value("80%", rule_type="支付比例").canonical_value == "0.8"


def test_identity_grouping_preserves_unknown_pattern_and_effective_period() -> None:
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        group_conflict_candidates,
    )

    same_missing_pattern = [
        _rule("r1", "90%", ["基本医疗保险统筹基金支付比例"]),
        _rule("r2", "80%", ["大额医疗互助资金支付比例"]),
    ]
    different_missing_pattern = [
        same_missing_pattern[0],
        _rule("r2", "80%", ["大额医疗互助资金支付比例"], hosp_lv="三级"),
    ]
    different_period = [
        _rule("r1", "90%", ["基本医疗保险统筹基金支付比例"], effective_start="2025-01-01"),
        _rule("r2", "80%", ["大额医疗互助资金支付比例"], effective_start="2026-01-01"),
    ]

    groups = group_conflict_candidates(same_missing_pattern)
    assert len(groups) == 1
    assert "hosp_lv" in groups[0].identity_signature.unknown_fields
    assert group_conflict_candidates(different_missing_pattern) == []
    assert group_conflict_candidates(different_period) == []


def test_unique_complete_fund_partition_produces_dimension_candidate() -> None:
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        ConflictDiagnosis,
        discover_conflict_partitions,
    )

    report = discover_conflict_partitions([
        _rule("r1", "90%", ["基本医疗保险统筹基金支付比例"]),
        _rule("r2", "80%", ["大额医疗互助资金支付比例"]),
    ])

    assert report.uncertainties == []
    assert len(report.proposals) == 1
    proposal = report.proposals[0]
    assert proposal.suggested_code == "fund_type"
    assert proposal.suggested_name == "基金归属"
    assert proposal.semantic_type == "Enum"
    assert proposal.metric_role == "dimension"
    assert proposal.evidence_grade == "single_observation"
    assert proposal.evidence.coverage == Decimal("1")
    assert proposal.evidence.exclusivity == Decimal("1")
    assert {value.label for value in proposal.candidate_values} == {
        "统筹基金",
        "大额医疗互助资金",
    }
    pooled = next(value for value in proposal.candidate_values if value.code == "pooled_fund")
    assert pooled.aliases == ["基本医疗保险统筹基金"]
    assert {value.canonical_value for value in proposal.evidence.conflict_values} == {
        "0.9",
        "0.8",
    }
    assert proposal.evidence.rule_ids == ["r1", "r2"]
    assert proposal.evidence.source_clause_ids == ["clause_r1", "clause_r2"]
    assert proposal.evidence.extraction_snapshot_id == "snapshot_1"
    assert proposal.evidence.diagnosis == ConflictDiagnosis.MISSING_DIMENSION


def test_ambiguous_rule_binding_records_uncertainty_without_proposal() -> None:
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        ConflictDiagnosis,
        discover_conflict_partitions,
    )

    report = discover_conflict_partitions([
        _rule(
            "r1",
            "90%",
            ["基本医疗保险统筹基金支付比例", "大额医疗互助资金支付比例"],
        ),
        _rule("r2", "80%", ["大额医疗互助资金支付比例"]),
    ])

    assert report.proposals == []
    assert report.uncertainties[0].diagnosis == ConflictDiagnosis.RULE_BINDING_AMBIGUOUS


def test_competing_fund_and_year_partitions_are_not_auto_selected() -> None:
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        ConflictDiagnosis,
        discover_conflict_partitions,
    )

    report = discover_conflict_partitions([
        _rule("r1", "90%", ["基本医疗保险统筹基金支付比例", "2025年"]),
        _rule("r2", "80%", ["大额医疗互助资金支付比例", "2026年"]),
    ])

    assert report.proposals == []
    uncertainty = report.uncertainties[0]
    assert uncertainty.diagnosis == ConflictDiagnosis.MULTIPLE_PARTITIONS
    assert uncertainty.competing_axis_candidates == ["fund_type", "policy_year"]


def test_paragraph_level_entities_cannot_create_a_dimension_candidate() -> None:
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        ConflictDiagnosis,
        discover_conflict_partitions,
    )

    report = discover_conflict_partitions([
        _rule(
            "r1", "90%", ["基本医疗保险统筹基金支付比例"], entity_scope="paragraph"
        ),
        _rule(
            "r2", "80%", ["大额医疗互助资金支付比例"], entity_scope="paragraph"
        ),
    ])

    assert report.proposals == []
    assert report.uncertainties[0].diagnosis == ConflictDiagnosis.RULE_BINDING_AMBIGUOUS


def test_rule_type_synonyms_group_across_extracted_labels() -> None:
    """跨 rule_type 塌缩（报销比例/支付比例混标）也必须成组产出维度候选。

    实测大额互助文档：85% 标「报销比例」、80% 标「支付比例」，身份签名
    不归一 → 两组各一值 → S5 永远产不出 fund_type 候选。
    """
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        discover_conflict_partitions,
    )

    rules = [
        _rule("r1", "85%", ["基本医疗保险统筹基金支付比例"]),
        _rule("r2", "80%", ["大额医疗互助资金支付比例"]),
    ]
    rules[1] = rules[1].model_copy(update={"rule_type": "报销比例"})

    report = discover_conflict_partitions(rules)

    assert report.uncertainties == []
    assert len(report.proposals) == 1
    assert report.proposals[0].suggested_code == "fund_type"


def test_ratio_typed_measure_entities_produce_dimension_candidate() -> None:
    """提取契约 prompt 把比例度量实体标为 RATIO（如「大额医疗互助资金支付比例」），
    S5 候选过滤必须接受 RATIO，否则方案 A 输出的 entities 仍被丢弃、只进 uncertainties。
    """
    from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
        discover_conflict_partitions,
    )

    report = discover_conflict_partitions([
        _rule("r1", "85%", ["基本医疗保险统筹基金支付比例"], entity_type="RATIO"),
        _rule("r2", "80%", ["大额医疗互助资金支付比例"], entity_type="RATIO"),
    ])

    assert report.uncertainties == []
    assert len(report.proposals) == 1
    proposal = report.proposals[0]
    assert proposal.suggested_code == "fund_type"
    assert {value.label for value in proposal.candidate_values} == {
        "统筹基金",
        "大额医疗互助资金",
    }
