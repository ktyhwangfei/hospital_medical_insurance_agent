"""知识答案验证服务（MVU-1：引用真实性；MVU-2：结论/计算/覆盖确定性断言）。

引用真实性四级关联（fail-closed）：
1. ``internal_id_match``        内部证据 rule_id + source_text_hash 查知识源，
                               存在且 hash/文本一致才通过；
2. ``normalized_exact_match``   归一化后 excerpt 是某条 source_text 的连续片段；
3. ``metadata_constrained_match`` title 映射 + 原文包含 + 规则条件一致；
4. ``vector_candidate_fallback`` 仅候选发现，必须再经文本/元数据一致，
                               否则 ``CITATION_UNVERIFIED`` fail-closed。

MVU-2 新增三个确定性维度（限定 pooling_self_pay 支持场景）：
- conclusion_consistency   内部证据的结构化值（payment_ratio/amount_band/rule_value）
                           必须与知识源当前规则一致（防止回答使用过期/错误值）；
- calculation_consistency  重算计算轨迹中的退休折算比例
                           实际比例 = 职工自付比例 × 退休系数，且职工比例必须有证据支撑；
- coverage_completeness    必需查询全部命中且无缺失必需规则；未声明场景/无查询计划
                           时 not_evaluable，绝不判 passed。

纯向量命中不得证明引用真实；找不到原文一律判失败，不降级为 warning。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    AnswerEvidenceRef,
    CitationLinkMethod,
    CitationVerification,
    KnowledgeAnswerDimensionResult,
    KnowledgeAnswerEvalFailure,
    KnowledgeAnswerVerificationDimension,
    KnowledgeAnswerVerificationInput,
    KnowledgeAnswerVerificationResult,
    KnowledgeAnswerVerificationStatus,
    RuleKnowledgePort,
    RuleRecord,
)

# 引用真实性失败码（稳定、可断言）
CITATION_MISSING_SOURCE = "CITATION_MISSING_SOURCE"          # 规则知识源未配置，无法验证
CITATION_NO_EVIDENCE_LINK = "CITATION_NO_EVIDENCE_LINK"      # 公开引用与内部证据无法配对
CITATION_RULE_MISSING = "CITATION_RULE_MISSING"              # 证据指向的规则在知识源中不存在
CITATION_TEXT_MISMATCH = "CITATION_TEXT_MISMATCH"            # 证据原文与知识源规则原文不一致（hash/文本）
CITATION_EXCERPT_NOT_FOUND = "CITATION_EXCERPT_NOT_FOUND"    # 归一化后 excerpt 不是任何 source_text 连续片段
CITATION_METADATA_MISMATCH = "CITATION_METADATA_MISMATCH"    # title 元数据约束不满足
CITATION_UNVERIFIED = "CITATION_UNVERIFIED"                  # 仅向量候选，fail-closed

# 结论一致性失败码
CONCLUSION_MISSING_SOURCE = "CONCLUSION_MISSING_SOURCE"      # 规则知识源未配置，无法校验结论
CONCLUSION_RULE_MISSING = "CONCLUSION_RULE_MISSING"          # 证据指向的规则已从知识源移除
CONCLUSION_RULE_UNLOCATED = "CONCLUSION_RULE_UNLOCATED"      # 证据无 rule_id 且文本查找失败
CONCLUSION_VALUE_MISMATCH = "CONCLUSION_VALUE_MISMATCH"      # 证据值与知识源规则值不一致

# 计算一致性失败码
CALCULATION_RATIO_MISMATCH = "CALCULATION_RATIO_MISMATCH"    # 退休折算比例重算不一致
CALCULATION_SEGMENT_UNSUPPORTED = "CALCULATION_SEGMENT_UNSUPPORTED"  # 轨迹比例在证据中无支撑

# 覆盖完整性失败码
COVERAGE_MISSING_REQUIRED_QUERY = "COVERAGE_MISSING_REQUIRED_QUERY"  # 必需查询未命中
COVERAGE_MISSING_REQUIRED_RULE = "COVERAGE_MISSING_REQUIRED_RULE"    # 存在缺失的必需规则


def normalize_rule_text(text: str) -> str:
    """NFKC 归一化（全角→半角）+ 折叠空白，用于引用原文比对。"""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def source_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# 退休折算分段步骤：例「职工自付比例 15%，退休人员系数 60%，实际 9%」
_CALC_RETIREE_STEP_RE = re.compile(
    r"职工自付比例\s*(\d+(?:\.\d+)?)%\s*[，,]\s*退休人员系数\s*(\d+(?:\.\d+)?)%"
    r"\s*[，,]\s*实际\s*(\d+(?:\.\d+)?)%"
)


def _ratio_to_decimal(value: Any) -> Decimal | None:
    """比例文本归一化为 0~1 Decimal：支持 '0.85' / '85%' / '85'（>1 视为百分数）。"""
    text = str(value or "").strip()
    if not text or text.lower() in ("nan", "none", "null"):
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if number > 1:
        number = number / 100
    return number.quantize(Decimal("0.0001"))


def _texts_consistent(left: str, right: str) -> bool:
    """两段原文归一化后互为包含关系（任一方向）即视为一致。"""
    norm_left = normalize_rule_text(left)
    norm_right = normalize_rule_text(right)
    if not norm_left or not norm_right:
        return False
    return norm_left in norm_right or norm_right in norm_left


def _structured_value_equal(field: str, evidence_value: Any, rule_value: Any) -> bool:
    """结构化值一致性：payment_ratio 按 Decimal 比对；文本字段按归一化相等比对。"""
    ev = str(evidence_value or "").strip()
    rv = str(rule_value or "").strip()
    if not ev and not rv:
        return True
    if field == "payment_ratio":
        ev_decimal, rv_decimal = _ratio_to_decimal(ev), _ratio_to_decimal(rv)
        if ev_decimal is None or rv_decimal is None:
            return False
        return ev_decimal == rv_decimal
    return normalize_rule_text(ev) == normalize_rule_text(rv)


def _find_matching_evidence(
    evidence_list: list[AnswerEvidenceRef], excerpt: str
) -> AnswerEvidenceRef | None:
    """按归一化包含关系把公开引用配对到内部证据；优先带 rule_id 的证据。"""
    norm_excerpt = normalize_rule_text(excerpt)
    if not norm_excerpt:
        return None
    candidates = [
        evidence for evidence in evidence_list
        if norm_excerpt in normalize_rule_text(evidence.source_text)
    ]
    if not candidates:
        return None
    return next((item for item in candidates if item.rule_id), candidates[0])


class KnowledgeAnswerVerifier:
    """答案验证器。MVU-1 实现 citation_authenticity 维度；其余维度后续 MVU 扩展。"""

    def __init__(self, port: RuleKnowledgePort | None = None) -> None:
        self._port = port

    def verify(
        self, envelope: KnowledgeAnswerVerificationInput
    ) -> KnowledgeAnswerVerificationResult:
        """对一次回答执行全部已实现维度的验证并聚合整体状态。"""
        dimensions: list[KnowledgeAnswerDimensionResult] = [
            self._verify_citation_authenticity(envelope),
            self._verify_conclusion_consistency(envelope),
            self._verify_calculation_consistency(envelope),
            self._verify_coverage_completeness(envelope),
        ]
        return KnowledgeAnswerVerificationResult(
            verification_id=f"kav_{uuid4().hex}",
            qa_turn_id=envelope.qa_turn_id,
            status=_aggregate(dimensions),
            dimensions={dimension.dimension.value: dimension for dimension in dimensions},
        )

    # ── 维度：引用真实性 ──────────────────────────────────────────────

    def _verify_citation_authenticity(
        self, envelope: KnowledgeAnswerVerificationInput
    ) -> KnowledgeAnswerDimensionResult:
        if not envelope.citations:
            return KnowledgeAnswerDimensionResult(
                dimension=KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY,
                status=KnowledgeAnswerVerificationStatus.NOT_EVALUABLE,
                details={"reason": "无公开引用可验证"},
            )
        if self._port is None:
            return KnowledgeAnswerDimensionResult(
                dimension=KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY,
                status=KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR,
                failures=[
                    KnowledgeAnswerEvalFailure(
                        CITATION_MISSING_SOURCE, "规则知识源未配置，无法验证引用真实性"
                    )
                ],
            )
        port = self._port  # 已排除 None

        verifications = [
            self._verify_one_citation(envelope, index, citation, port)
            for index, citation in enumerate(envelope.citations)
        ]
        failures = [
            KnowledgeAnswerEvalFailure(failure.code, f"引用 #{verification.citation_index}：{failure.message}")
            for verification in verifications
            for failure in verification.failures
        ]
        status = (
            KnowledgeAnswerVerificationStatus.PASSED
            if all(verification.verified for verification in verifications)
            else KnowledgeAnswerVerificationStatus.FAILED
        )
        return KnowledgeAnswerDimensionResult(
            dimension=KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY,
            status=status,
            failures=failures,
            details={"citations": [verification.model_dump() for verification in verifications]},
        )

    def _verify_one_citation(
        self,
        envelope: KnowledgeAnswerVerificationInput,
        index: int,
        citation: Any,
        port: RuleKnowledgePort,
    ) -> CitationVerification:
        excerpt = citation.excerpt
        title = citation.title

        # 1. internal_id_match：公开引用 → 内部证据 → 规则 ID 查知识源
        evidence = _find_matching_evidence(envelope.internal_evidence, excerpt)
        if evidence is not None:
            linked = self._verify_evidence_link(index, title, excerpt, evidence, port)
            if linked is not None:
                return linked

        # 2. normalized_exact_match：excerpt 为某条 source_text 的连续片段
        rule = _find_exact_text_rule(port, excerpt)
        if rule is not None:
            return _verified(index, title, excerpt, CitationLinkMethod.NORMALIZED_EXACT_MATCH, rule)

        # 3. metadata_constrained_match：title 映射 + 原文包含
        rule = _find_title_constrained_rule(port, title, excerpt)
        if rule is not None:
            return _verified(index, title, excerpt, CitationLinkMethod.METADATA_CONSTRAINED_MATCH, rule)

        # 4. vector_candidate_fallback：仅候选发现，文本未重叠 → fail-closed
        if port.find_similar_rules(excerpt):
            return _unverified(
                index, title, excerpt, CitationLinkMethod.VECTOR_CANDIDATE_FALLBACK,
                [KnowledgeAnswerEvalFailure(CITATION_UNVERIFIED, "仅找到语义相似候选，原文未精确命中")],
            )
        return _unverified(
            index, title, excerpt, CitationLinkMethod.UNVERIFIED,
            [KnowledgeAnswerEvalFailure(CITATION_EXCERPT_NOT_FOUND, "知识源中找不到引用原文")],
        )

    def _verify_evidence_link(
        self,
        index: int,
        title: str,
        excerpt: str,
        evidence: AnswerEvidenceRef,
        port: RuleKnowledgePort,
    ) -> CitationVerification | None:
        """按内部证据的 rule_id 查知识源；无 rule_id 时返回 None 降级到文本级关联。"""
        if not evidence.rule_id:
            return None
        rule = port.get_rule_by_id(evidence.rule_id)
        if rule is None:
            return _unverified(
                index, title, excerpt, CitationLinkMethod.INTERNAL_ID_MATCH,
                [KnowledgeAnswerEvalFailure(CITATION_RULE_MISSING, f"证据指向的规则已不在知识源：{evidence.rule_id}")],
            )
        if not _evidence_matches_rule(evidence, rule):
            return _unverified(
                index, title, excerpt, CitationLinkMethod.INTERNAL_ID_MATCH,
                [KnowledgeAnswerEvalFailure(CITATION_TEXT_MISMATCH, "证据原文与知识源规则原文不一致（hash/文本）")],
            )
        return _verified(index, title, excerpt, CitationLinkMethod.INTERNAL_ID_MATCH, rule)

    # ── 维度：结论一致性 ──────────────────────────────────────────────

    def _verify_conclusion_consistency(
        self, envelope: KnowledgeAnswerVerificationInput
    ) -> KnowledgeAnswerDimensionResult:
        if not envelope.internal_evidence:
            return _not_evaluable(
                KnowledgeAnswerVerificationDimension.CONCLUSION_CONSISTENCY,
                "无内部证据可校验结论一致性",
            )
        if self._port is None:
            return _blocked(
                KnowledgeAnswerVerificationDimension.CONCLUSION_CONSISTENCY,
                CONCLUSION_MISSING_SOURCE,
                "规则知识源未配置，无法校验结论一致性",
            )
        port = self._port  # 已排除 None
        failures: list[KnowledgeAnswerEvalFailure] = []
        verified_count = 0
        for evidence in envelope.internal_evidence:
            rule = _locate_rule(port, evidence)
            if rule is None:
                code = CONCLUSION_RULE_MISSING if evidence.rule_id else CONCLUSION_RULE_UNLOCATED
                message = (
                    f"证据规则无法定位：{evidence.rule_id}"
                    if evidence.rule_id
                    else "证据无 rule_id 且文本查找失败"
                )
                failures.append(KnowledgeAnswerEvalFailure(code, message))
                continue
            verified_count += 1
            for field in ("payment_ratio", "amount_band", "rule_value"):
                if not _structured_value_equal(field, getattr(evidence, field), getattr(rule, field)):
                    failures.append(KnowledgeAnswerEvalFailure(
                        CONCLUSION_VALUE_MISMATCH,
                        f"{field} 不一致：证据 {getattr(evidence, field)!r} vs 知识源 {getattr(rule, field)!r}",
                    ))
        status = (
            KnowledgeAnswerVerificationStatus.FAILED
            if failures
            else KnowledgeAnswerVerificationStatus.PASSED
        )
        return KnowledgeAnswerDimensionResult(
            dimension=KnowledgeAnswerVerificationDimension.CONCLUSION_CONSISTENCY,
            status=status,
            failures=failures,
            details={
                "verified_evidence_count": verified_count,
                "total_evidence_count": len(envelope.internal_evidence),
            },
        )

    # ── 维度：计算一致性（pooling_self_pay 退休折算重算）───────────────

    def _verify_calculation_consistency(
        self, envelope: KnowledgeAnswerVerificationInput
    ) -> KnowledgeAnswerDimensionResult:
        trace = envelope.calculation_trace
        if not trace or not isinstance(trace, dict):
            return _not_evaluable(
                KnowledgeAnswerVerificationDimension.CALCULATION_CONSISTENCY,
                "无内部计算轨迹",
            )
        ratio_steps = [
            (float(match.group(1)), float(match.group(2)), float(match.group(3)))
            for step in (trace.get("steps") or [])
            if (match := _CALC_RETIREE_STEP_RE.search(str(step.get("description", ""))))
        ]
        if not ratio_steps:
            return _not_evaluable(
                KnowledgeAnswerVerificationDimension.CALCULATION_CONSISTENCY,
                "计算轨迹无退休折算分段步骤（超出 pooling_self_pay 支持场景）",
            )
        failures: list[KnowledgeAnswerEvalFailure] = []
        for employee_ratio, retiree_coefficient, claimed_actual in ratio_steps:
            expected = round(employee_ratio * retiree_coefficient / 100, 1)
            if abs(claimed_actual - expected) > 0.05:
                failures.append(KnowledgeAnswerEvalFailure(
                    CALCULATION_RATIO_MISMATCH,
                    f"职工 {employee_ratio:g}% × 退休系数 {retiree_coefficient:g}% 应得 {expected:g}%，轨迹声称 {claimed_actual:g}%",
                ))
            if not _segment_ratio_supported(envelope, employee_ratio):
                failures.append(KnowledgeAnswerEvalFailure(
                    CALCULATION_SEGMENT_UNSUPPORTED,
                    f"计算轨迹使用职工自付比例 {employee_ratio:g}%，内部证据中无对应原文支撑",
                ))
        status = (
            KnowledgeAnswerVerificationStatus.FAILED
            if failures
            else KnowledgeAnswerVerificationStatus.PASSED
        )
        return KnowledgeAnswerDimensionResult(
            dimension=KnowledgeAnswerVerificationDimension.CALCULATION_CONSISTENCY,
            status=status,
            failures=failures,
            details={"verified_ratio_steps": len(ratio_steps)},
        )

    # ── 维度：覆盖完整性（必需查询 + 缺失规则）────────────────────────

    def _verify_coverage_completeness(
        self, envelope: KnowledgeAnswerVerificationInput
    ) -> KnowledgeAnswerDimensionResult:
        if not envelope.scenario or not envelope.planned_queries:
            return _not_evaluable(
                KnowledgeAnswerVerificationDimension.COVERAGE_COMPLETENESS,
                "未声明支持场景或查询计划，覆盖完整性无法评估",
            )
        failures: list[KnowledgeAnswerEvalFailure] = []
        for query in envelope.planned_queries:
            if query.required and query.hit_count <= 0:
                failures.append(KnowledgeAnswerEvalFailure(
                    COVERAGE_MISSING_REQUIRED_QUERY, f"必需查询未命中：{query.query_name}"
                ))
        for missing in envelope.missing_required_rules:
            failures.append(KnowledgeAnswerEvalFailure(
                COVERAGE_MISSING_REQUIRED_RULE, f"缺失必需规则：{missing}"
            ))
        status = (
            KnowledgeAnswerVerificationStatus.FAILED
            if failures
            else KnowledgeAnswerVerificationStatus.PASSED
        )
        return KnowledgeAnswerDimensionResult(
            dimension=KnowledgeAnswerVerificationDimension.COVERAGE_COMPLETENESS,
            status=status,
            failures=failures,
            details={
                "query_count": len(envelope.planned_queries),
                "missing_rule_count": len(envelope.missing_required_rules),
            },
        )


def _locate_rule(port: RuleKnowledgePort, evidence: AnswerEvidenceRef) -> RuleRecord | None:
    """按 rule_id 查知识源；无 rule_id 时降级按原文文本查找。"""
    if evidence.rule_id:
        return port.get_rule_by_id(evidence.rule_id)
    return _find_exact_text_rule(port, evidence.source_text)


def _segment_ratio_supported(envelope: KnowledgeAnswerVerificationInput, employee_ratio: float) -> bool:
    """职工自付比例需在内部证据原文中有支撑（职工支付X% / 职工个人支付X%）。"""
    ratio_text = f"{employee_ratio:g}%"
    for evidence in envelope.internal_evidence:
        text = normalize_rule_text(evidence.source_text)
        if f"职工支付{ratio_text}" in text or f"职工个人支付{ratio_text}" in text:
            return True
    return False


def _not_evaluable(dimension: KnowledgeAnswerVerificationDimension, reason: str) -> KnowledgeAnswerDimensionResult:
    return KnowledgeAnswerDimensionResult(
        dimension=dimension,
        status=KnowledgeAnswerVerificationStatus.NOT_EVALUABLE,
        details={"reason": reason},
    )


def _blocked(
    dimension: KnowledgeAnswerVerificationDimension, code: str, message: str
) -> KnowledgeAnswerDimensionResult:
    return KnowledgeAnswerDimensionResult(
        dimension=dimension,
        status=KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR,
        failures=[KnowledgeAnswerEvalFailure(code, message)],
    )


def _evidence_matches_rule(evidence: AnswerEvidenceRef, rule: RuleRecord) -> bool:
    """hash 一致（双方都有 hash 时）或归一化原文互为包含关系，两者满足其一。"""
    if evidence.source_text_hash and rule.source_text_hash:
        return evidence.source_text_hash == rule.source_text_hash
    return _texts_consistent(evidence.source_text, rule.source_text)


def _find_exact_text_rule(port: RuleKnowledgePort, excerpt: str) -> RuleRecord | None:
    """归一化后 excerpt 为候选规则 source_text 的连续片段。"""
    norm_excerpt = normalize_rule_text(excerpt)
    if not norm_excerpt:
        return None
    for rule in port.find_rules_by_text(excerpt):
        if norm_excerpt in normalize_rule_text(rule.source_text):
            return rule
    return None


def _find_title_constrained_rule(port: RuleKnowledgePort, title: str, excerpt: str) -> RuleRecord | None:
    """title 可映射到规则且原文包含 excerpt 时返回规则；title 为空则不适用。"""
    if not title:
        return None
    norm_excerpt = normalize_rule_text(excerpt)
    if not norm_excerpt:
        return None
    for rule in port.find_rules_by_title(title):
        if norm_excerpt in normalize_rule_text(rule.source_text):
            return rule
    return None


def _verified(
    index: int, title: str, excerpt: str, method: CitationLinkMethod, rule: RuleRecord
) -> CitationVerification:
    return CitationVerification(
        citation_index=index,
        title=title,
        excerpt=excerpt,
        link_method=method,
        verified=True,
        matched_rule_id=rule.rule_id,
    )


def _unverified(
    index: int, title: str, excerpt: str, method: CitationLinkMethod, failures: list[KnowledgeAnswerEvalFailure]
) -> CitationVerification:
    return CitationVerification(
        citation_index=index,
        title=title,
        excerpt=excerpt,
        link_method=method,
        verified=False,
        failures=failures,
    )


def _aggregate(dimensions: list[KnowledgeAnswerDimensionResult]) -> KnowledgeAnswerVerificationStatus:
    """整体状态聚合：任一 failed → failed；否则按最高保证缺口取最严重状态。"""
    statuses = {dimension.status for dimension in dimensions}
    if KnowledgeAnswerVerificationStatus.FAILED in statuses:
        return KnowledgeAnswerVerificationStatus.FAILED
    if KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR in statuses:
        return KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR
    if KnowledgeAnswerVerificationStatus.NOT_EVALUABLE in statuses:
        return KnowledgeAnswerVerificationStatus.NOT_EVALUABLE
    if KnowledgeAnswerVerificationStatus.REVIEW_REQUIRED in statuses:
        return KnowledgeAnswerVerificationStatus.REVIEW_REQUIRED
    return KnowledgeAnswerVerificationStatus.PASSED
