"""从规则值冲突中确定性诊断缺失维度候选；不访问存储或模型。"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


IDENTITY_FIELDS = (
    "rule_type",
    "insu_type",
    "med_type",
    "psn_type",
    "hosp_lv",
    "setl_type",
    "region_code",
    "effective_start",
    "effective_end",
    "value_semantic_type",
    "canonical_unit",
)

# 身份签名用的规则类型同义词：LLM 对同一比例身份会混用「报销比例/支付比例」，
# 不归一会把跨 rule_type 塌缩（统筹 85% vs 大额 80%）拆成两组，S5 永远不成组。
RULE_TYPE_SYNONYMS = {
    "报销比例": "支付比例",
    "赔付比例": "支付比例",
    "reimbursement_ratio": "payment_ratio",
}


def _canonical_rule_type(rule_type: str) -> str:
    return RULE_TYPE_SYNONYMS.get(rule_type, rule_type)


class ConflictDiagnosis(StrEnum):
    MISSING_DIMENSION = "missing_dimension"
    METRIC_SPLIT_REQUIRED = "metric_split_required"
    TEMPORAL_VERSION = "temporal_version"
    VALUE_NORMALIZATION = "value_normalization"
    EXTRACTION_INCOMPLETE = "extraction_incomplete"
    RULE_BINDING_AMBIGUOUS = "rule_binding_ambiguous"
    MULTIPLE_PARTITIONS = "multiple_partitions"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNKNOWN = "unknown"


class ProposalKind(StrEnum):
    NEW_DIMENSION = "new_dimension"


class ExtractionEntity(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    entity_id: str
    name: str
    entity_type: str = Field(
        default="",
        validation_alias=AliasChoices("entity_type", "type"),
    )
    highlight: str | None = None
    binding_scope: Literal["rule", "paragraph"] = "rule"


class ExtractionRelation(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    subject: str
    predicate: str
    object_value: str = Field(validation_alias=AliasChoices("object_value", "object"))
    rule_id: str | None = None
    binding_scope: Literal["rule", "paragraph"] = "rule"


class ExtractionRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    document_id: str
    snapshot_id: str
    extraction_contract_version: str = "unknown"
    rule_type: str
    rule_value: Any
    rule_unit: str | None = None
    insu_type: str | None = None
    med_type: str | None = None
    psn_type: str | None = None
    hosp_lv: str | None = None
    setl_type: str | None = None
    effective_start: date | None = None
    effective_end: date | None = None
    region_code: str | None = None
    entities: list[ExtractionEntity] = Field(default_factory=list)
    relations: list[ExtractionRelation] = Field(default_factory=list)
    source_clause_id: str
    evidence_text: str


class CanonicalRuleValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    semantic_type: Literal["percentage", "amount", "integer", "range", "formula", "text"]
    canonical_value: str
    canonical_unit: str | None = None
    raw_value: str


class IdentitySignature(BaseModel):
    model_config = ConfigDict(frozen=True)

    known_values: dict[str, str]
    unknown_fields: tuple[str, ...]


class ConflictCandidateGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity_signature: IdentitySignature
    rules: list[ExtractionRule]
    distinct_values: list[CanonicalRuleValue]


class PartitionCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis_key: str
    axis_code: str | None
    axis_name: str | None
    canonical_phrase: str
    display_phrase: str
    source_phrase: str
    measure_core: str
    rule_id: str
    canonical_value: str
    source_entity_ids: list[str]


class PartitionMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_phrase: str
    display_phrase: str
    canonical_value: str
    rule_ids: list[str]
    source_entity_ids: list[str]


class PartitionEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_axis_code: str | None = None
    candidate_axis_name: str | None = None
    mappings: list[PartitionMapping] = Field(default_factory=list)
    coverage: Decimal = Decimal("0")
    exclusivity: Decimal = Decimal("0")
    value_count: int = 0
    phrase_count: int = 0
    support_per_phrase: dict[str, int] = Field(default_factory=dict)
    uncovered_rule_ids: list[str] = Field(default_factory=list)
    ambiguous_rule_ids: list[str] = Field(default_factory=list)
    competing_axis_candidates: list[str] = Field(default_factory=list)
    diagnosis: ConflictDiagnosis = ConflictDiagnosis.UNKNOWN
    eligible_for_proposal: bool = False


class CandidateDomainValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str | None
    label: str
    aliases: list[str] = Field(default_factory=list)


class ConflictPartitionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    trigger_source: Literal["CONFLICT_PARTITION"] = "CONFLICT_PARTITION"
    document_id: str
    extraction_snapshot_id: str
    extraction_contract_version: str
    identity_signature: IdentitySignature
    conflict_values: list[CanonicalRuleValue]
    partition_mappings: list[PartitionMapping]
    coverage: Decimal
    exclusivity: Decimal
    evidence_grade: Literal["single_observation", "repeated_within_document"]
    rule_ids: list[str]
    source_clause_ids: list[str]
    evidence_texts: list[str]
    unknown_identity_fields: list[str]
    competing_axis_candidates: list[str]
    diagnosis: ConflictDiagnosis


class DimensionCandidateProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    fingerprint: str
    proposal_kind: Literal[ProposalKind.NEW_DIMENSION] = ProposalKind.NEW_DIMENSION
    trigger_source: Literal["CONFLICT_PARTITION"] = "CONFLICT_PARTITION"
    suggested_name: str | None
    suggested_code: str | None
    semantic_type: Literal["Enum"] = "Enum"
    metric_role: Literal["dimension"] = "dimension"
    candidate_values: list[CandidateDomainValue]
    evidence: ConflictPartitionEvidence
    evidence_grade: Literal["single_observation", "repeated_within_document"]
    naming_status: Literal["resolved", "manual_required"]
    status: Literal["proposed"] = "proposed"


class ConflictUncertainty(BaseModel):
    model_config = ConfigDict(frozen=True)

    fingerprint: str
    document_id: str
    extraction_snapshot_id: str
    diagnosis: ConflictDiagnosis
    identity_signature: IdentitySignature
    conflict_values: list[CanonicalRuleValue]
    rule_ids: list[str]
    competing_axis_candidates: list[str] = Field(default_factory=list)
    message: str


class DiscoveryReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposals: list[DimensionCandidateProposal] = Field(default_factory=list)
    uncertainties: list[ConflictUncertainty] = Field(default_factory=list)


class AxisValueConcept(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    label: str
    aliases: tuple[str, ...]


class AxisConcept(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    values: tuple[AxisValueConcept, ...]


class AxisConceptRegistry:
    """候选值别名词典；命中只代表命名建议，不代表正式维度。"""

    def __init__(self, axes: tuple[AxisConcept, ...] | None = None) -> None:
        self.axes = axes or (
            AxisConcept(
                code="fund_type",
                name="基金归属",
                values=(
                    AxisValueConcept(
                        code="pooled_fund",
                        label="统筹基金",
                        aliases=("基本医疗保险统筹基金", "基本医保统筹基金", "统筹基金"),
                    ),
                    AxisValueConcept(
                        code="large_mutual_aid_fund",
                        label="大额医疗互助资金",
                        aliases=("大额医疗互助资金", "大额互助资金"),
                    ),
                ),
            ),
        )

    def resolve(self, phrase: str) -> tuple[AxisConcept, AxisValueConcept] | None:
        matches = [
            (len(alias), axis, value)
            for axis in self.axes
            for value in axis.values
            for alias in value.aliases
            if alias in phrase
        ]
        if not matches:
            return None
        _length, axis, value = max(matches, key=lambda item: item[0])
        return axis, value

    def value(self, axis_code: str, value_code: str) -> AxisValueConcept | None:
        return next(
            (
                value
                for axis in self.axes
                if axis.code == axis_code
                for value in axis.values
                if value.code == value_code
            ),
            None,
        )


class MeasureConceptRegistry:
    def __init__(self, cores: tuple[str, ...] | None = None) -> None:
        self.cores = cores or (
            "个人自付比例",
            "最高支付限额",
            "基金支付金额",
            "支付比例",
            "起付标准",
            "报销金额",
        )

    def split(self, name: str) -> tuple[str, str] | None:
        for core in sorted(self.cores, key=len, reverse=True):
            if core in name:
                qualifier = name.replace(core, "", 1).strip(" ：:，,。；;（）()")
                if qualifier:
                    return core, qualifier
        return None


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def _chinese_number(text: str) -> Decimal:
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _CHINESE_DIGITS:
            number = _CHINESE_DIGITS[char]
            continue
        unit = _CHINESE_UNITS.get(char)
        if unit is None:
            raise InvalidOperation
        if unit == 10000:
            section = (section + number) * unit
            total += section
            section = number = 0
        else:
            section += (number or 1) * unit
            number = 0
    return Decimal(total + section + number)


def _decimal(text: str) -> Decimal:
    cleaned = text.strip().replace(",", "")
    if re.fullmatch(r"[零〇一二两三四五六七八九十百千万]+", cleaned):
        return _chinese_number(cleaned)
    return Decimal(cleaned)


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def normalize_rule_value(
    raw_value: Any,
    *,
    rule_type: str = "",
    rule_unit: str | None = None,
) -> CanonicalRuleValue:
    """把可比较规则值规范成稳定字符串；无法识别时保留为 text。"""
    raw = raw_value if isinstance(raw_value, str) else json.dumps(
        raw_value, ensure_ascii=False, sort_keys=True, default=str
    )
    text = raw.strip()
    if not text:
        raise ValueError("规则值为空")

    if isinstance(raw_value, (dict, list)):
        return CanonicalRuleValue(
            semantic_type="formula",
            canonical_value=json.dumps(raw_value, ensure_ascii=False, sort_keys=True, default=str),
            raw_value=raw,
        )

    percent_match = re.fullmatch(r"百分之([零〇一二两三四五六七八九十百千万]+)", text)
    if percent_match:
        value = _chinese_number(percent_match.group(1)) / Decimal("100")
        return CanonicalRuleValue(
            semantic_type="percentage",
            canonical_value=_decimal_text(value),
            raw_value=raw,
        )

    percent_match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*%", text)
    if percent_match:
        value = Decimal(percent_match.group(1)) / Decimal("100")
        return CanonicalRuleValue(
            semantic_type="percentage",
            canonical_value=_decimal_text(value),
            raw_value=raw,
        )

    amount_match = re.fullmatch(
        r"([+-]?\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+)\s*(万)?\s*(?:元|人民币|CNY)",
        text,
        re.IGNORECASE,
    )
    if amount_match:
        value = _decimal(amount_match.group(1))
        if amount_match.group(2):
            value *= Decimal("10000")
        return CanonicalRuleValue(
            semantic_type="amount",
            canonical_value=_decimal_text(value),
            canonical_unit="CNY",
            raw_value=raw,
        )

    range_match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(?:-|~|至)\s*([+-]?\d+(?:\.\d+)?)", text)
    if range_match:
        return CanonicalRuleValue(
            semantic_type="range",
            canonical_value=f"{_decimal_text(Decimal(range_match.group(1)))}..{_decimal_text(Decimal(range_match.group(2)))}",
            canonical_unit=rule_unit,
            raw_value=raw,
        )

    numeric_match = re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text)
    if numeric_match:
        value = Decimal(text)
        if rule_unit == "%" or "比例" in rule_type:
            if value > 1:
                value /= Decimal("100")
            return CanonicalRuleValue(
                semantic_type="percentage",
                canonical_value=_decimal_text(value),
                raw_value=raw,
            )
        semantic_type: Literal["integer", "amount"] = (
            "amount" if rule_unit in {"元", "人民币", "CNY"} else "integer"
        )
        return CanonicalRuleValue(
            semantic_type=semantic_type,
            canonical_value=_decimal_text(value),
            canonical_unit="CNY" if semantic_type == "amount" else rule_unit,
            raw_value=raw,
        )

    if any(marker in text for marker in ("×", "*", "/", "依照", "乘以")):
        return CanonicalRuleValue(
            semantic_type="formula",
            canonical_value=" ".join(text.split()),
            canonical_unit=rule_unit,
            raw_value=raw,
        )
    return CanonicalRuleValue(
        semantic_type="text",
        canonical_value=" ".join(text.split()),
        canonical_unit=rule_unit,
        raw_value=raw,
    )


def _signature(rule: ExtractionRule, value: CanonicalRuleValue) -> IdentitySignature:
    source: dict[str, Any] = {
        "rule_type": _canonical_rule_type(rule.rule_type),
        "insu_type": rule.insu_type,
        "med_type": rule.med_type,
        "psn_type": rule.psn_type,
        "hosp_lv": rule.hosp_lv,
        "setl_type": rule.setl_type,
        "region_code": rule.region_code,
        "effective_start": rule.effective_start,
        "effective_end": rule.effective_end,
        "value_semantic_type": value.semantic_type,
        "canonical_unit": value.canonical_unit,
    }
    known: dict[str, str] = {}
    unknown: list[str] = []
    for name in IDENTITY_FIELDS:
        item = source[name]
        if item is None or (isinstance(item, str) and not item.strip()):
            unknown.append(name)
        else:
            known[name] = item.isoformat() if isinstance(item, date) else str(item)
    return IdentitySignature(known_values=known, unknown_fields=tuple(unknown))


def _value_key(value: CanonicalRuleValue) -> str:
    return f"{value.semantic_type}:{value.canonical_value}:{value.canonical_unit or ''}"


def group_conflict_candidates(rules: list[ExtractionRule]) -> list[ConflictCandidateGroup]:
    grouped: dict[str, list[tuple[ExtractionRule, CanonicalRuleValue, IdentitySignature]]] = defaultdict(list)
    for rule in rules:
        try:
            value = normalize_rule_value(
                rule.rule_value,
                rule_type=rule.rule_type,
                rule_unit=rule.rule_unit,
            )
        except ValueError:
            continue
        signature = _signature(rule, value)
        key = json.dumps(
            [
                rule.document_id,
                rule.snapshot_id,
                signature.known_values,
                signature.unknown_fields,
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        grouped[key].append((rule, value, signature))

    result: list[ConflictCandidateGroup] = []
    for entries in grouped.values():
        values = {_value_key(value): value for _rule, value, _signature_value in entries}
        if len(values) < 2:
            continue
        result.append(ConflictCandidateGroup(
            identity_signature=entries[0][2],
            rules=sorted((entry[0] for entry in entries), key=lambda item: item.rule_id),
            distinct_values=sorted(values.values(), key=_value_key),
        ))
    return sorted(result, key=lambda item: item.rules[0].rule_id)


def _bound_entities(rule: ExtractionRule) -> list[ExtractionEntity]:
    relation_terms = {
        term
        for relation in rule.relations
        if relation.binding_scope == "rule" and relation.rule_id in {None, rule.rule_id}
        for term in (relation.subject, relation.object_value)
    }
    return [
        entity
        for entity in rule.entities
        if entity.binding_scope == "rule"
        or entity.entity_id in relation_terms
        or entity.name in relation_terms
    ]


def extract_partition_candidates(
    group: ConflictCandidateGroup,
    axis_registry: AxisConceptRegistry,
    measure_registry: MeasureConceptRegistry,
) -> list[PartitionCandidate]:
    candidates: list[PartitionCandidate] = []
    for rule in group.rules:
        value = normalize_rule_value(
            rule.rule_value,
            rule_type=rule.rule_type,
            rule_unit=rule.rule_unit,
        )
        for entity in _bound_entities(rule):
            year_match = re.fullmatch(r"(\d{4})年", entity.name.strip())
            if year_match:
                year = year_match.group(1)
                candidates.append(PartitionCandidate(
                    axis_key="policy_year",
                    axis_code="policy_year",
                    axis_name="政策年份",
                    canonical_phrase=year,
                    display_phrase=f"{year}年",
                    source_phrase=f"{year}年",
                    measure_core="policy_year",
                    rule_id=rule.rule_id,
                    canonical_value=_value_key(value),
                    source_entity_ids=[entity.entity_id],
                ))
                continue
            # 提取契约 prompt 把比例度量实体（如「大额医疗互助资金支付比例」）
            # 标注为 RATIO；度量拆分注册表命中后才可能成为分区候选。
            if entity.entity_type.upper() not in {"AMOUNT", "SERVICE", "RATIO"}:
                continue
            split = measure_registry.split(entity.name)
            if split is None:
                continue
            core, qualifier = split
            resolved = axis_registry.resolve(qualifier)
            if resolved:
                axis, axis_value = resolved
                axis_key = axis.code
                axis_code = axis.code
                axis_name = axis.name
                canonical_phrase = axis_value.code
                display_phrase = axis_value.label
            else:
                axis_key = f"manual:{core}"
                axis_code = axis_name = None
                canonical_phrase = " ".join(qualifier.casefold().split())
                display_phrase = qualifier
            candidates.append(PartitionCandidate(
                axis_key=axis_key,
                axis_code=axis_code,
                axis_name=axis_name,
                canonical_phrase=canonical_phrase,
                display_phrase=display_phrase,
                source_phrase=qualifier,
                measure_core=core,
                rule_id=rule.rule_id,
                canonical_value=_value_key(value),
                source_entity_ids=[entity.entity_id],
            ))
    return candidates


def _evaluate_axis(
    group: ConflictCandidateGroup,
    candidates: list[PartitionCandidate],
) -> PartitionEvaluation:
    by_rule: dict[str, list[PartitionCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_rule[candidate.rule_id].append(candidate)
    rule_ids = [rule.rule_id for rule in group.rules]
    uncovered = sorted(rule_id for rule_id in rule_ids if not by_rule[rule_id])
    ambiguous = sorted(
        rule_id
        for rule_id in rule_ids
        if len({item.canonical_phrase for item in by_rule[rule_id]}) != 1
    )
    covered = len(rule_ids) - len(uncovered)
    exclusive = covered - len(ambiguous)
    coverage = Decimal(covered) / Decimal(len(rule_ids))
    exclusivity = Decimal(exclusive) / Decimal(covered) if covered else Decimal("0")

    phrase_values: dict[str, set[str]] = defaultdict(set)
    value_phrases: dict[str, set[str]] = defaultdict(set)
    phrase_rules: dict[str, set[str]] = defaultdict(set)
    phrase_entities: dict[str, set[str]] = defaultdict(set)
    phrase_labels: dict[str, str] = {}
    measure_cores: set[str] = set()
    for candidate in candidates:
        phrase_values[candidate.canonical_phrase].add(candidate.canonical_value)
        value_phrases[candidate.canonical_value].add(candidate.canonical_phrase)
        phrase_rules[candidate.canonical_phrase].add(candidate.rule_id)
        phrase_entities[candidate.canonical_phrase].update(candidate.source_entity_ids)
        phrase_labels.setdefault(candidate.canonical_phrase, candidate.display_phrase)
        measure_cores.add(candidate.measure_core)

    mappings = [
        PartitionMapping(
            canonical_phrase=phrase,
            display_phrase=phrase_labels[phrase],
            canonical_value=next(iter(values)) if len(values) == 1 else "",
            rule_ids=sorted(phrase_rules[phrase]),
            source_entity_ids=sorted(phrase_entities[phrase]),
        )
        for phrase, values in sorted(phrase_values.items())
    ]
    one_to_one = (
        not uncovered
        and not ambiguous
        and all(len(values) == 1 for values in phrase_values.values())
        and all(len(phrases) == 1 for phrases in value_phrases.values())
        and len(phrase_values) == len(group.distinct_values)
        and coverage == 1
        and exclusivity == 1
    )
    if ambiguous:
        diagnosis = ConflictDiagnosis.RULE_BINDING_AMBIGUOUS
    elif len(measure_cores) > 1:
        diagnosis = ConflictDiagnosis.METRIC_SPLIT_REQUIRED
    elif uncovered:
        diagnosis = ConflictDiagnosis.EXTRACTION_INCOMPLETE
    elif not one_to_one:
        diagnosis = ConflictDiagnosis.INSUFFICIENT_EVIDENCE
    else:
        diagnosis = ConflictDiagnosis.MISSING_DIMENSION
    first = candidates[0] if candidates else None
    return PartitionEvaluation(
        candidate_axis_code=first.axis_code if first else None,
        candidate_axis_name=first.axis_name if first else None,
        mappings=mappings,
        coverage=coverage,
        exclusivity=exclusivity,
        value_count=len(group.distinct_values),
        phrase_count=len(phrase_values),
        support_per_phrase={
            phrase: len(rule_ids_value) for phrase, rule_ids_value in sorted(phrase_rules.items())
        },
        uncovered_rule_ids=uncovered,
        ambiguous_rule_ids=ambiguous,
        diagnosis=diagnosis,
        eligible_for_proposal=one_to_one and len(measure_cores) == 1,
    )


def evaluate_partition(
    group: ConflictCandidateGroup,
    candidates: list[PartitionCandidate],
) -> PartitionEvaluation:
    by_axis: dict[str, list[PartitionCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_axis[candidate.axis_key].append(candidate)
    evaluations = [_evaluate_axis(group, items) for _axis, items in sorted(by_axis.items())]
    eligible = [item for item in evaluations if item.eligible_for_proposal]
    if len(eligible) > 1:
        competing = sorted(item.candidate_axis_code or "manual_required" for item in eligible)
        return eligible[0].model_copy(update={
            "diagnosis": ConflictDiagnosis.MULTIPLE_PARTITIONS,
            "eligible_for_proposal": False,
            "competing_axis_candidates": competing,
        })
    if len(eligible) == 1:
        return eligible[0]
    if evaluations:
        priority = {
            ConflictDiagnosis.RULE_BINDING_AMBIGUOUS: 0,
            ConflictDiagnosis.METRIC_SPLIT_REQUIRED: 1,
            ConflictDiagnosis.EXTRACTION_INCOMPLETE: 2,
            ConflictDiagnosis.INSUFFICIENT_EVIDENCE: 3,
        }
        return min(evaluations, key=lambda item: priority.get(item.diagnosis, 9))
    has_unbound_entities = any(rule.entities for rule in group.rules)
    return PartitionEvaluation(
        value_count=len(group.distinct_values),
        uncovered_rule_ids=[rule.rule_id for rule in group.rules],
        diagnosis=(
            ConflictDiagnosis.RULE_BINDING_AMBIGUOUS
            if has_unbound_entities
            else ConflictDiagnosis.EXTRACTION_INCOMPLETE
        ),
    )


def _fingerprint(
    document_id: str,
    signature: IdentitySignature,
    values: list[CanonicalRuleValue],
    phrases: list[str],
) -> str:
    raw = json.dumps(
        [
            document_id,
            signature.model_dump(mode="json"),
            sorted(_value_key(value) for value in values),
            sorted(phrases),
            ProposalKind.NEW_DIMENSION,
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _uncertainty(
    group: ConflictCandidateGroup,
    evaluation: PartitionEvaluation,
) -> ConflictUncertainty:
    first = group.rules[0]
    fingerprint = _fingerprint(
        first.document_id,
        group.identity_signature,
        group.distinct_values,
        [mapping.canonical_phrase for mapping in evaluation.mappings],
    )
    return ConflictUncertainty(
        fingerprint=fingerprint,
        document_id=first.document_id,
        extraction_snapshot_id=first.snapshot_id,
        diagnosis=evaluation.diagnosis,
        identity_signature=group.identity_signature,
        conflict_values=group.distinct_values,
        rule_ids=[rule.rule_id for rule in group.rules],
        competing_axis_candidates=evaluation.competing_axis_candidates,
        message=f"冲突未生成维度候选：{evaluation.diagnosis.value}",
    )


def discover_conflict_partitions(
    rules: list[ExtractionRule],
    axis_registry: AxisConceptRegistry | None = None,
    measure_registry: MeasureConceptRegistry | None = None,
) -> DiscoveryReport:
    axis_registry = axis_registry or AxisConceptRegistry()
    measure_registry = measure_registry or MeasureConceptRegistry()
    proposals: list[DimensionCandidateProposal] = []
    uncertainties: list[ConflictUncertainty] = []
    for group in group_conflict_candidates(rules):
        candidates = extract_partition_candidates(group, axis_registry, measure_registry)
        evaluation = evaluate_partition(group, candidates)
        if not evaluation.eligible_for_proposal:
            uncertainties.append(_uncertainty(group, evaluation))
            continue

        first = group.rules[0]
        grade: Literal["single_observation", "repeated_within_document"] = (
            "repeated_within_document"
            if evaluation.support_per_phrase
            and min(evaluation.support_per_phrase.values()) >= 2
            else "single_observation"
        )
        candidate_values: list[CandidateDomainValue] = []
        for mapping in evaluation.mappings:
            registered = (
                axis_registry.value(evaluation.candidate_axis_code, mapping.canonical_phrase)
                if evaluation.candidate_axis_code
                else None
            )
            raw_aliases = sorted({
                candidate.source_phrase
                for candidate in candidates
                if candidate.canonical_phrase == mapping.canonical_phrase
                and candidate.source_phrase != (registered.label if registered else mapping.display_phrase)
            })
            candidate_values.append(CandidateDomainValue(
                code=registered.code if registered else None,
                label=registered.label if registered else mapping.display_phrase,
                aliases=raw_aliases,
            ))

        fingerprint = _fingerprint(
            first.document_id,
            group.identity_signature,
            group.distinct_values,
            [mapping.canonical_phrase for mapping in evaluation.mappings],
        )
        evidence = ConflictPartitionEvidence(
            document_id=first.document_id,
            extraction_snapshot_id=first.snapshot_id,
            extraction_contract_version=first.extraction_contract_version,
            identity_signature=group.identity_signature,
            conflict_values=group.distinct_values,
            partition_mappings=evaluation.mappings,
            coverage=evaluation.coverage,
            exclusivity=evaluation.exclusivity,
            evidence_grade=grade,
            rule_ids=[rule.rule_id for rule in group.rules],
            source_clause_ids=list(dict.fromkeys(rule.source_clause_id for rule in group.rules)),
            evidence_texts=list(dict.fromkeys(rule.evidence_text for rule in group.rules)),
            unknown_identity_fields=list(group.identity_signature.unknown_fields),
            competing_axis_candidates=[],
            diagnosis=ConflictDiagnosis.MISSING_DIMENSION,
        )
        proposals.append(DimensionCandidateProposal(
            fingerprint=fingerprint,
            suggested_name=evaluation.candidate_axis_name,
            suggested_code=evaluation.candidate_axis_code,
            candidate_values=candidate_values,
            evidence=evidence,
            evidence_grade=grade,
            naming_status=(
                "resolved"
                if evaluation.candidate_axis_name and evaluation.candidate_axis_code
                else "manual_required"
            ),
        ))

    return DiscoveryReport(
        proposals=sorted(proposals, key=lambda item: item.fingerprint),
        uncertainties=sorted(uncertainties, key=lambda item: item.fingerprint),
    )
