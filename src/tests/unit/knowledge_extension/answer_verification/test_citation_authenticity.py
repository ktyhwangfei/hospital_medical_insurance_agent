"""知识答案验证：引用真实性（citation_authenticity）维度单元测试。

覆盖：四级引用关联（internal_id_match → normalized_exact_match →
metadata_constrained_match → vector_candidate_fallback fail-closed）、
归一化、空引用/缺知识源边界与整体状态聚合。
"""
from __future__ import annotations

import hashlib
from typing import Any

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    AnswerCitation,
    AnswerEvidenceRef,
    CitationLinkMethod,
    KnowledgeAnswerVerificationDimension,
    KnowledgeAnswerVerificationInput,
    KnowledgeAnswerVerificationStatus,
    RuleRecord,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    CITATION_EXCERPT_NOT_FOUND,
    CITATION_RULE_MISSING,
    CITATION_TEXT_MISMATCH,
    CITATION_UNVERIFIED,
    KnowledgeAnswerVerifier,
    normalize_rule_text,
    source_text_hash,
)
from src.knowledge_extension.rule_explanation.answer_verification.models import (
    KnowledgeAnswerVerificationResult,
)

SRC_TEXT = "在三级医院发生的医疗费用：起付标准至3万元的部分，统筹基金支付85%，职工支付15%。"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rule(rule_id: str = "rule_001", **overrides: Any) -> RuleRecord:
    base: dict[str, Any] = {
        "rule_id": rule_id,
        "rule_instance_key": f"inst_{rule_id}",
        "policy_id": "doc_001",
        "clause_id": "clause_36_3",
        "title": "城镇职工医保统筹基金支付比例",
        "source_text": SRC_TEXT,
        "source_text_hash": _hash(SRC_TEXT),
        "rule_value": "统筹基金支付85%，职工支付15%",
        "payment_ratio": "0.85",
        "amount_band": "起付标准至3万元",
        "psn_type": "在职职工",
    }
    base.update(overrides)
    return RuleRecord(**base)


def _evidence(rule_id: str = "rule_001", **overrides: Any) -> AnswerEvidenceRef:
    base: dict[str, Any] = {
        "evidence_id": "ev_001",
        "rule_id": rule_id,
        "rule_instance_key": f"inst_{rule_id}",
        "policy_id": "doc_001",
        "clause_id": "clause_36_3",
        "query_name": "三级医院分段支付比例",
        "source_text": SRC_TEXT,
        "source_text_hash": _hash(SRC_TEXT),
        "rule_value": "统筹基金支付85%，职工支付15%",
        "payment_ratio": "0.85",
        "amount_band": "起付标准至3万元",
        "psn_type": "在职职工",
    }
    base.update(overrides)
    return AnswerEvidenceRef(**base)


def _citation(excerpt: str = SRC_TEXT, title: str = "城镇职工医保统筹基金支付比例") -> AnswerCitation:
    return AnswerCitation(title=title, excerpt=excerpt)


class FakeRuleKnowledgePort:
    """内存规则知识源：按 rule_id / 文本 / 标题 / 相似（仅候选）查找。"""

    def __init__(self, rules: list[RuleRecord] | None = None) -> None:
        self._rules = {rule.rule_id: rule for rule in (rules or [])}
        # 相似候选由测试显式构造：normalized 文本 → 候选规则列表
        self._similar: dict[str, list[RuleRecord]] = {}

    def get_rule_by_id(self, rule_id: str) -> RuleRecord | None:
        return self._rules.get(rule_id)

    def find_rules_by_text(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        norm = normalize_rule_text(text)
        return [
            rule for rule in self._rules.values()
            if norm and norm in normalize_rule_text(rule.source_text)
        ][:limit]

    def find_similar_rules(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        return self._similar.get(normalize_rule_text(text), [])[:limit]

    def find_rules_by_title(self, title: str, *, limit: int = 5) -> list[RuleRecord]:
        return [rule for rule in self._rules.values() if rule.title == title][:limit]


def _verify(input_data: KnowledgeAnswerVerificationInput, port: FakeRuleKnowledgePort) -> KnowledgeAnswerVerificationResult:
    result = KnowledgeAnswerVerifier(port=port).verify(input_data)  # type: ignore[arg-type]
    dimension = result.dimensions[KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY.value]
    assert dimension.dimension == KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY
    return result


# ── 1. internal_id_match：证据规则在知识源中存在且 hash 一致 ─────────────

def test_internal_id_match_passes_when_rule_exists_and_hash_matches() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_001",
        answer="统筹基金支付85%",
        answer_status="complete",
        citations=[_citation()],
        internal_evidence=[_evidence()],
    )
    result = _verify(envelope, port)

    assert result.dimensions["citation_authenticity"].status == KnowledgeAnswerVerificationStatus.PASSED
    citation = result.dimensions["citation_authenticity"].details["citations"][0]
    assert citation["verified"] is True
    assert citation["link_method"] == CitationLinkMethod.INTERNAL_ID_MATCH.value
    assert citation["matched_rule_id"] == "rule_001"


# ── 2. internal_id_match：规则已从知识源下线 → fail ──────────────────────

def test_internal_id_match_fails_when_rule_missing_from_source() -> None:
    # 知识源不含 rule_001（回答生成后规则被移除/版本重建）
    port = FakeRuleKnowledgePort(rules=[_rule(rule_id="rule_999")])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_002",
        answer="统筹基金支付85%",
        answer_status="complete",
        citations=[_citation()],
        internal_evidence=[_evidence(rule_id="rule_001")],
    )
    result = _verify(envelope, port)

    assert result.status == KnowledgeAnswerVerificationStatus.FAILED
    codes = [failure.code for failure in result.dimensions["citation_authenticity"].failures]
    assert CITATION_RULE_MISSING in codes


# ── 3. internal_id_match：原文被修改（hash 不一致）→ fail ────────────────

def test_internal_id_match_fails_when_source_text_changed() -> None:
    changed_text = SRC_TEXT + "。本款自2026年起执行。"
    port = FakeRuleKnowledgePort(rules=[_rule(source_text=changed_text, source_text_hash=_hash(changed_text))])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_003",
        answer="统筹基金支付85%",
        answer_status="complete",
        citations=[_citation()],
        internal_evidence=[_evidence()],
    )
    result = _verify(envelope, port)

    assert result.status == KnowledgeAnswerVerificationStatus.FAILED
    codes = [failure.code for failure in result.dimensions["citation_authenticity"].failures]
    assert CITATION_TEXT_MISMATCH in codes


# ── 4. normalized_exact_match：内部证据无 rule_id → 文本级关联通过 ────────
def test_normalized_exact_match_passes_without_rule_id_in_evidence() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_004",
        answer="统筹基金支付85%",
        answer_status="complete",
        citations=[_citation(excerpt="统筹基金支付85%，职工支付15%")],
        internal_evidence=[_evidence(rule_id="", rule_instance_key="")],
    )
    result = _verify(envelope, port)

    assert result.dimensions["citation_authenticity"].status == KnowledgeAnswerVerificationStatus.PASSED
    citation = result.dimensions["citation_authenticity"].details["citations"][0]
    assert citation["link_method"] == CitationLinkMethod.NORMALIZED_EXACT_MATCH.value


# ── 5. metadata_constrained_match：title 约束 + 原文包含 → 通过 ──────────

class TitleOnlyPort(FakeRuleKnowledgePort):
    """文本精确索引失效（如短语索引 miss），仅 title 枚举可命中。"""

    def find_rules_by_text(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        return []


def test_metadata_constrained_match_passes_via_title() -> None:
    port = TitleOnlyPort(rules=[_rule()])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_005",
        answer="统筹基金支付85%",
        answer_status="complete",
        citations=[_citation(excerpt="统筹基金支付85%，职工支付15%")],
        # 无任何内部证据 → 直接落到文本/标题级关联
        internal_evidence=[],
    )
    result = _verify(envelope, port)

    assert result.dimensions["citation_authenticity"].status == KnowledgeAnswerVerificationStatus.PASSED
    citation = result.dimensions["citation_authenticity"].details["citations"][0]
    assert citation["link_method"] == CitationLinkMethod.METADATA_CONSTRAINED_MATCH.value


# ── 6. vector_candidate_fallback：仅语义相近候选 → fail-closed ──────────

def test_vector_fallback_fails_closed_on_candidate_only() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    # 语义相似但无文本包含的候选（仅证明"有候选"，不能证明真实性）
    port._similar[normalize_rule_text("统筹基金支付比例85%")] = [_rule(rule_id="rule_sim")]
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_006",
        answer="统筹基金支付85%",
        answer_status="complete",
        citations=[_citation(excerpt="统筹基金支付比例85%")],
        internal_evidence=[],
    )
    result = _verify(envelope, port)

    assert result.status == KnowledgeAnswerVerificationStatus.FAILED
    citation = result.dimensions["citation_authenticity"].details["citations"][0]
    assert citation["link_method"] == CitationLinkMethod.VECTOR_CANDIDATE_FALLBACK.value
    codes = [failure.code for failure in result.dimensions["citation_authenticity"].failures]
    assert CITATION_UNVERIFIED in codes


# ── 7. 全链路找不回原文 → unverified fail ───────────────────────────────

def test_excerpt_not_found_anywhere_fails_closed() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_007",
        answer="统筹基金支付99%",
        answer_status="complete",
        citations=[_citation(excerpt="统筹基金支付99%")],
        internal_evidence=[_evidence(source_text="完全无关的另一段政策原文")],
    )
    result = _verify(envelope, port)

    assert result.status == KnowledgeAnswerVerificationStatus.FAILED
    codes = [failure.code for failure in result.dimensions["citation_authenticity"].failures]
    assert CITATION_EXCERPT_NOT_FOUND in codes


# ── 8. 空引用 → not_evaluable ───────────────────────────────────────────

def test_empty_citations_is_not_evaluable() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_008",
        answer="当前信息不足以形成可靠结论",
        answer_status="unavailable",
        citations=[],
        internal_evidence=[],
    )
    result = _verify(envelope, port)

    assert result.status == KnowledgeAnswerVerificationStatus.NOT_EVALUABLE


# ── 9. 归一化：全角/空白差异不影响匹配 ──────────────────────────────────

def test_normalization_ignores_whitespace_and_fullwidth() -> None:
    # 全角逗号/全角百分号 + 全角空格 + 首尾空白，NFKC 归一化后与 SRC_TEXT 一致
    messy = "  统筹基金支付85%，职工支付15％  "
    assert normalize_rule_text(messy) == "统筹基金支付85%,职工支付15%"

    port = FakeRuleKnowledgePort(rules=[_rule()])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_009",
        answer="统筹基金支付85%",
        answer_status="complete",
        citations=[_citation(excerpt="统筹基金支付85%，职工支付15％")],
        internal_evidence=[_evidence()],
    )
    result = _verify(envelope, port)

    assert result.dimensions["citation_authenticity"].status == KnowledgeAnswerVerificationStatus.PASSED


# ── 10. 混合：部分引用通过、部分失败 → 整体 failed，逐条保留状态 ─────────

def test_mixed_citations_overall_failed_with_per_citation_status() -> None:
    port = FakeRuleKnowledgePort(rules=[_rule()])
    envelope = KnowledgeAnswerVerificationInput(
        qa_turn_id="qat_010",
        answer="统筹基金支付85%",
        answer_status="complete",
        citations=[
            _citation(excerpt=SRC_TEXT),                                  # 通过
            _citation(excerpt="统筹基金支付99%"),                          # 失败
        ],
        internal_evidence=[_evidence()],
    )
    result = _verify(envelope, port)

    assert result.status == KnowledgeAnswerVerificationStatus.FAILED
    citations = result.dimensions["citation_authenticity"].details["citations"]
    assert citations[0]["verified"] is True
    assert citations[1]["verified"] is False


# ── 11. 知识源未配置 → blocked_by_evaluator，绝不 passed ────────────────

def test_missing_port_is_blocked_by_evaluator() -> None:
    result = KnowledgeAnswerVerifier(port=None).verify(
        KnowledgeAnswerVerificationInput(
            qa_turn_id="qat_011",
            answer="统筹基金支付85%",
            answer_status="complete",
            citations=[_citation()],
            internal_evidence=[_evidence()],
        )
    )

    assert result.status == KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR
    codes = [failure.code for failure in result.dimensions["citation_authenticity"].failures]
    assert "CITATION_MISSING_SOURCE" in codes
