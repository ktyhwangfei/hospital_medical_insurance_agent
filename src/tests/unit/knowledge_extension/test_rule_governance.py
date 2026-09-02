from datetime import datetime, timedelta, timezone

from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileRun,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    InMemoryCompilationTraceStore,
)
from src.knowledge_extension.rule_explanation.rule_governance import (
    diagnose_rule_governance,
)


RELEASE_ID = "REL_202608182"


def _save_rule(
    store: InMemoryCompilationTraceStore,
    rule: CanonicalRule,
    *,
    unit_id: str,
) -> None:
    run_id = f"run_{rule.rule_id}"
    extraction_id = f"ext_{unit_id}"
    store.create_run(CompileRun(
        run_id=run_id,
        document_id="doc_policy",
        unit_id=unit_id,
        extraction_id=extraction_id,
        raw_input={"source_text": rule.evidence[0]},
        llm_output={},
    ))
    store.save_lineage(
        rule=rule,
        run_id=run_id,
        extraction_id=extraction_id,
        document_id="doc_policy",
        release_id=RELEASE_ID,
    )


def _database_fields() -> list[dict]:
    return [
        {
            "table_name": "m_institution",
            "field_name": "H_TYPE",
            "description": "医疗机构类型",
            "non_null_rate": 1,
            "distinct_count": 4,
            "sample_values": ["01", "02", "03", "05", "患者姓名：张三"],
        },
        {
            "table_name": "m_institution",
            "field_name": "H_LEVEL",
            "description": "医院等级",
            "non_null_rate": 1,
            "distinct_count": 3,
            "sample_values": ["一级", "二级", "三级"],
        },
    ]


def _save_newer_candidate(
    store: InMemoryCompilationTraceStore,
    rule: CanonicalRule,
) -> None:
    run_id = f"candidate_{rule.rule_id}"
    store.create_run(CompileRun(
        run_id=run_id,
        document_id="doc_policy",
        unit_id="unit_candidate",
        extraction_id="ext_candidate",
        raw_input={"source_text": rule.evidence[0]},
        llm_output={},
        started_at=datetime.now(timezone.utc) + timedelta(seconds=1),
    ))
    store.save_candidate_lineage(
        rule_id=rule.rule_id,
        rule=rule,
        run_id=run_id,
        extraction_id="ext_candidate",
        document_id="doc_policy",
    )


def test_diagnosis_groups_institution_rules_and_recommends_category_field() -> None:
    store = InMemoryCompilationTraceStore()
    _save_rule(store, CanonicalRule(
        rule_id="rule_69fc18433e6a7364",
        subject="门诊报销比例",
        conditions={"hosp_lv": "一级"},
        result={"ratio": "0.9"},
        evidence=["在本市社区卫生服务机构就医，统筹基金支付90%。"],
    ), unit_id="unit_inst")
    _save_rule(store, CanonicalRule(
        rule_id="rule_63e89e926492ebd8",
        subject="门诊报销比例",
        conditions={"hosp_lv": "一级"},
        result={"ratio": "0.7"},
        evidence=["在本市社区卫生服务机构以外的其他定点医疗机构就医，统筹基金支付70%。"],
    ), unit_id="unit_inst")
    _save_newer_candidate(store, CanonicalRule(
        rule_id="rule_69fc18433e6a7364",
        subject="候选规则",
        result={"ratio": "0.5"},
        evidence=["尚未发布的候选抽取。"],
    ))
    assert store.get_rule_trace("rule_69fc18433e6a7364").publication is None

    diagnosis = diagnose_rule_governance(
        RELEASE_ID,
        ["rule_69fc18433e6a7364", "rule_63e89e926492ebd8"],
        store,
        _database_fields(),
    )

    assert len(diagnosis.items) == 1
    issue = diagnosis.items[0]
    assert issue.issue_type == "institution_category"
    assert issue.rule_ids == ["rule_63e89e926492ebd8", "rule_69fc18433e6a7364"]
    assert issue.missing_concept == "医疗机构类别"
    evidence = {item.source_ref: item for item in issue.database_evidence}
    assert evidence["database:m_institution.H_TYPE"].evidence_grade == "strong"
    assert "患者姓名：张三" not in evidence["database:m_institution.H_TYPE"].sample_values
    assert evidence["database:m_institution.H_LEVEL"].evidence_grade == "rejected"


def test_diagnosis_keeps_mutual_aid_and_overall_benefit_as_separate_issues() -> None:
    store = InMemoryCompilationTraceStore()
    _save_rule(store, CanonicalRule(
        rule_id="rule_3222a148156d8c7d",
        subject="大额医疗互助资金支付比例",
        result={"ratio": "0.8"},
        evidence=["超过统筹基金最高支付限额的费用，由大额医疗互助资金支付80%。"],
    ), unit_id="unit_fund")
    _save_rule(store, CanonicalRule(
        rule_id="rule_4df372b59673556e",
        subject="综合报销比例",
        result={"ratio": "0.85"},
        evidence=["退休人员门诊医疗费用综合报销比例为85%。"],
    ), unit_id="unit_benefit")

    diagnosis = diagnose_rule_governance(
        RELEASE_ID,
        ["rule_3222a148156d8c7d", "rule_4df372b59673556e"],
        store,
        [],
    )

    assert [item.issue_type for item in diagnosis.items] == [
        "benefit_ratio",
        "mutual_aid_fund",
    ]
    mutual_aid = next(item for item in diagnosis.items if item.issue_type == "mutual_aid_fund")
    overall = next(item for item in diagnosis.items if item.issue_type == "benefit_ratio")
    assert "大额医疗互助" in mutual_aid.recommended_reason
    assert "统筹基金" not in mutual_aid.proposed_changes
    assert "基金归属" not in overall.proposed_changes
