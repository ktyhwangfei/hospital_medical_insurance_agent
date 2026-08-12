"""PolicyCompilationService 适配层与 fail-closed 拦截测试。

复现 rule_8f94f240d5da7fb6：dummy 模式提取产出 topic_concept=unclassified，
_to_fact 适配后 subject 落入哨兵，compiler 必须在 Canonicalize 拦截，禁止进入 Release。
"""
from __future__ import annotations

from typing import Any

from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeConfidence,
    KnowledgeField,
    KnowledgeItem,
)
from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
    PolicyRuleCompiler,
)
from src.knowledge_extension.rule_explanation.policy_compiler.service import (
    PolicyCompilationService,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    InMemoryCompilationTraceStore,
)


class _StubPipeline:
    """模拟 ExtractionReadPort，返回固定 extraction dict。"""

    def __init__(self, extraction: dict[str, Any]) -> None:
        self._extraction = extraction

    def get_extraction(self, extraction_id: str) -> dict[str, Any] | None:
        return self._extraction if extraction_id == self._extraction.get("extraction_id") else None


def _confidence() -> KnowledgeConfidence:
    return KnowledgeConfidence(
        completeness=0.5,
        source_fidelity=0.5,
        model_confidence=0.5,
        overall=0.5,
    )


def _knowledge(
    *,
    knowledge_id: str = "kn_dummy",
    topic_concept: str | None = "unclassified",
    fields: list[KnowledgeField] | None = None,
    business_sentence: str = "退休人员个人支付比例 = 职工支付比例 × 60%。",
) -> KnowledgeItem:
    return KnowledgeItem(
        knowledge_id=knowledge_id,
        unit_id="unit_x",
        extraction_id="ext_dummy",
        relationship_source="persisted",
        business_sentence=business_sentence,
        source_text="dummy source",
        fields=fields or [KnowledgeField(field_code="payment_ratio", field_name="比例", raw_value="30%")],
        confidence=_confidence(),
        citations=[],
        topic_concept=topic_concept,
    )


def _unit(knowledge: KnowledgeItem) -> ApprovedUnit:
    return ApprovedUnit(
        unit_id="unit_x",
        doc_id="doc_dummy",
        doc_title="dummy",
        path=["root"],
        source_text="dummy source",
        order_no=1,
        status="reviewed",
        knowledge_count=1,
        knowledge=[knowledge],
    )


def _service(extraction: dict[str, Any]) -> PolicyCompilationService:
    return PolicyCompilationService(
        _StubPipeline(extraction),
        PolicyRuleCompiler(),
        InMemoryCompilationTraceStore(),
    )


def test_unclassified_without_any_numeric_field_is_fail_closed() -> None:
    """rule_type 模糊且无任何数值字段/原文数值时必须 FAIL（fail-closed）。"""
    extraction = {
        "extraction_id": "ext_dummy",
        "doc_id": "doc_dummy",
        "source_text": "无具体数值的通用规定",
        "extracted_fields": {
            "rules": [{"psn_type": "退休人员", "rule_type": "通用规则"}],
        },
    }
    # 无 payment_ratio/deductible/cap 字段,原文无数值 → 推断不出 → 哨兵 FAIL
    knowledge = _knowledge(
        fields=[KnowledgeField(field_code="psn_type", field_name="人群", raw_value="退休人员")],
        business_sentence="该规定适用于全体参保人员，具体办法另行制定。",
    )
    service = _service(extraction)

    candidates = service.compile_units([_unit(knowledge)])

    candidate = candidates["kn_dummy"]
    assert candidate.status == "FAIL"
    assert "SUBJECT_MISSING" in {issue.code for issue in candidate.issues}
    assert candidate.canonical_rules == []


def test_unclassified_with_numeric_field_infers_subject() -> None:
    """rule_type 模糊但有 payment_ratio 数值字段时,_infer_subject 推断主体,不再 FAIL。"""
    extraction = {
        "extraction_id": "ext_dummy",
        "doc_id": "doc_dummy",
        "source_text": "退休人员支付比例 30%",
        "extracted_fields": {"rules": [{"psn_type": "退休人员", "payment_ratio": "30%", "rule_type": "通用规则"}]},
    }
    service = _service(extraction)

    candidates = service.compile_units([_unit(_knowledge(topic_concept="UNCLASSIFIED"))])

    candidate = candidates["kn_dummy"]
    # 推断出 payment_ratio 主体 → 不该是 SUBJECT_MISSING
    assert "SUBJECT_MISSING" not in {issue.code for issue in candidate.issues}


def test_realistic_extraction_passes_subject_resolution() -> None:
    """正常结构化提取（含 subject）不应被哨兵误伤。"""
    extraction = {
        "extraction_id": "ext_dummy",
        "doc_id": "doc_dummy",
        "source_text": "退休人员个人支付比例为职工的60%",
        "extracted_fields": {
            "rules": [{
                "subject": "personal_payment_ratio",
                "psn_type": "退休人员",
                "ratio": "0.3",
            }],
        },
    }
    knowledge = _knowledge(
        topic_concept="PAYMENT_RATIO",
        fields=[KnowledgeField(field_code="ratio", field_name="比例", raw_value="0.3")],
    )
    service = _service(extraction)

    candidates = service.compile_units([_unit(knowledge)])

    candidate = candidates["kn_dummy"]
    assert "SUBJECT_MISSING" not in {issue.code for issue in candidate.issues}
    assert candidate.status != "FAIL" or candidate.canonical_rules
