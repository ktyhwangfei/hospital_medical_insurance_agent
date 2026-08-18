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

    candidate = candidates["unit_x::kn_dummy"]
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

    candidate = candidates["unit_x::kn_dummy"]
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

    candidate = candidates["unit_x::kn_dummy"]
    assert "SUBJECT_MISSING" not in {issue.code for issue in candidate.issues}
    assert candidate.status != "FAIL" or candidate.canonical_rules


def test_fund_dimension_without_amount_does_not_become_pseudo_rule() -> None:
    extraction = {
        "extraction_id": "ext_dummy",
        "doc_id": "doc_dummy",
        "source_text": "基本医疗保险统筹基金最高支付限额调整为10万元",
        "extracted_fields": {
            "rules": [{
                "jjgs": "统筹基金",
                "entities": [{
                    "name": "统筹基金最高支付限额",
                    "entity_type": "AMOUNT",
                    "highlight": "统筹基金最高支付限额调整为10万元",
                }],
            }],
        },
    }
    knowledge = _knowledge(
        topic_concept="CAP",
        fields=[KnowledgeField(field_code="jjgs", field_name="基金归属", raw_value="统筹基金")],
        business_sentence="jjgs为统筹基金。",
    )

    candidate = _service(extraction).compile_units([_unit(knowledge)])["unit_x::kn_dummy"]

    assert candidate.canonical_rules == []
    assert "RESULT_MISSING" in {issue.code for issue in candidate.issues}
    assert candidate.status == "REVIEW"


def test_same_knowledge_id_across_units_does_not_collide() -> None:
    """跨单元同名 knowledge_id（LLM 每单元都编 rule_001）不得互相覆盖。

    复现 2026-08-17 实例：两个单元的 rule_001 撞名 → runs dict 覆盖 →
    同一 run 重复 append 步骤 → 500「编译步骤已存在: run_xxx_3」。
    """
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        CompileStep,
    )

    extraction = {
        "extraction_id": "ext_dummy",
        "doc_id": "doc_dummy",
        "source_text": "在职职工支付比例 80%",
        "extracted_fields": {"rules": [{"psn_type": "在职职工", "payment_ratio": "80%"}]},
    }
    traces = InMemoryCompilationTraceStore()
    service = PolicyCompilationService(_StubPipeline(extraction), PolicyRuleCompiler(), traces)

    units = [_unit(_knowledge(knowledge_id="rule_001")), _unit(_knowledge(knowledge_id="rule_001"))]
    units[1] = ApprovedUnit(
        **{**units[1].model_dump(), "unit_id": "unit_y"},
    )

    candidates = service.compile_units(units)

    # 两个单元的候选都存在（scoped key 不覆盖）
    assert "unit_x::rule_001" in candidates
    assert "unit_y::rule_001" in candidates
    # 两个 run 各自完整写入步骤，无重复 append 异常
    run_ids = {candidates[k].compile_run_id for k in ("unit_x::rule_001", "unit_y::rule_001")}
    assert len(run_ids) == 2


def test_ratio_rules_keep_complete_business_subjects() -> None:
    """综合报销比例与基金分项比例不得压扁成同一 payment_ratio 主体。"""
    common = [
        KnowledgeField(field_code="insu_type", field_name="险种", raw_value="城镇职工基本医疗保险"),
        KnowledgeField(field_code="med_type", field_name="医疗类别", raw_value="住院-普通住院"),
        KnowledgeField(field_code="psn_type", field_name="人群", raw_value="退休人员"),
        KnowledgeField(field_code="jjgs", field_name="基金归属", raw_value="大额医疗互助资金"),
        KnowledgeField(field_code="amount_band", field_name="金额区间", raw_value="统筹封顶线以上至大额互助封顶线以下"),
    ]
    overall = _knowledge(
        knowledge_id="kn_overall",
        topic_concept="PAYMENT_RATIO",
        fields=[
            *common,
            KnowledgeField(field_code="payment_ratio", field_name="比例", raw_value="90"),
            KnowledgeField(field_code="rule_value", field_name="规则值", raw_value="90%（含退休人员统一补充医疗保险）"),
        ],
    )
    fund = _knowledge(
        knowledge_id="kn_fund",
        topic_concept="PAYMENT_RATIO",
        fields=[
            *common,
            KnowledgeField(field_code="payment_ratio", field_name="比例", raw_value="80"),
            KnowledgeField(field_code="rule_value", field_name="规则值", raw_value="住院大额医疗互助资金报销比例调整为80%"),
        ],
    )
    extraction = {
        "extraction_id": "ext_dummy",
        "doc_id": "doc_dummy",
        "source_text": "退休人员综合报销90%，其中住院大额医疗互助资金报销80%",
        "extracted_fields": {"rules": [
            {
                "knowledge_id": "kn_overall",
                "source_text": "退休人员报销比例调整为90%（含退休人员统一补充医疗保险）",
                "payment_ratio": "90",
                "rule_value": "90%（含退休人员统一补充医疗保险）",
            },
            {
                "knowledge_id": "kn_fund",
                "source_text": "其中：住院大额医疗互助资金报销比例调整为80%",
                "payment_ratio": "80",
                "rule_value": "住院大额医疗互助资金报销比例调整为80%",
            },
        ]},
    }
    unit = _unit(overall).model_copy(update={
        "knowledge_count": 2,
        "knowledge": [overall, fund],
    })

    service = _service(extraction)
    assert service._infer_subject(
        {"payment_ratio": "85"},
        {
            "source_text": (
                "超过统筹基金最高支付限额以上，大额医疗互助资金最高支付限额以下的"
                "医疗费用，在职职工报销比例调整为85%"
            ),
        },
        overall,
    ) == "overall_reimbursement_ratio"

    candidates = service.compile_units([unit])

    overall_rule = candidates["unit_x::kn_overall"].canonical_rules[0]
    fund_rule = candidates["unit_x::kn_fund"].canonical_rules[0]
    assert overall_rule.subject == "overall_reimbursement_ratio"
    assert fund_rule.subject == "large_medical_mutual_aid_payment_ratio"
    assert "jjgs" not in overall_rule.conditions
    assert fund_rule.conditions["jjgs"] == "大额医疗互助资金"
    assert not {
        issue.code
        for candidate in candidates.values()
        for issue in candidate.issues
    } & {"CONFLICT", "NO_RULE_PRODUCED"}
