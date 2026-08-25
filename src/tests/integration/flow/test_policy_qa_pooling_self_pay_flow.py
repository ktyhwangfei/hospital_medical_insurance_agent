"""政策问答统筹自付样板链路 Flow 测试。"""

from copy import deepcopy

import pytest
from pydantic import ValidationError


def _valid_public_result_payload() -> dict:
    return {
        "answer": "统筹自付解释",
        "answer_status": "complete",
        "case_context": {
            "person_type": "退休人员",
            "basic_pooling_self_pay": 4962.67,
        },
        "calculation_steps": [
            {"step_name": "分段计算", "description": "按政策区间核对"},
        ],
        "definition": {
            "name": "统筹自付",
            "plain_text": "个人按政策承担的部分。",
            "excludes": ["起付线"],
        },
        "warnings": [],
        "policy_evidence": [
            {"title": "职工医保住院待遇政策", "excerpt": "按规定比例承担。", "score": 0.98},
        ],
        "citations": [
            {"title": "职工医保住院待遇政策", "excerpt": "按规定比例承担。"},
        ],
        "uncertainties": [],
        "verification_summary": {
            "settlement_checked": True,
            "calculation_checked": True,
            "policy_count": 1,
            "message": "已完成核对。",
        },
    }


@pytest.mark.parametrize(
    ("field", "extra_key", "extra_value"),
    [
        ("case_context", "query_trace", {"sql": "SELECT * FROM yb_zyfdxx"}),
        ("calculation_steps", "raw_sql", "SELECT * FROM yb_zyfdxx"),
        ("definition", "raw_field", "bdtczf"),
        ("policy_evidence", "query_trace", {"sql_profile": "settlement_context"}),
    ],
)
def test_public_contract_forbids_nested_internal_fields(field, extra_key, extra_value):
    from src.runtime.policy_qa.public_contract import PolicyQAPublicResult

    payload = deepcopy(_valid_public_result_payload())
    target = payload[field][0] if isinstance(payload[field], list) else payload[field]
    target[extra_key] = extra_value

    with pytest.raises(ValidationError):
        PolicyQAPublicResult.model_validate(payload)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_public_contract_rejects_non_finite_policy_score(score):
    from src.runtime.policy_qa.public_contract import PolicyQAPublicResult

    payload = _valid_public_result_payload()
    payload["policy_evidence"][0]["score"] = score

    with pytest.raises(ValidationError):
        PolicyQAPublicResult.model_validate(payload)


def test_public_contract_accepts_valid_nested_result():
    from src.runtime.policy_qa.public_contract import PolicyQAPublicResult

    result = PolicyQAPublicResult.model_validate(_valid_public_result_payload())

    assert result.case_context.basic_pooling_self_pay == 4962.67
    assert result.calculation_steps[0].step_name == "分段计算"
    assert result.policy_evidence[0].score == 0.98


@pytest.mark.parametrize(
    (
        "can_answer",
        "partial_answer",
        "policy_status",
        "real_case_data",
        "public_evidence",
        "has_calculation",
        "expected_status",
    ),
    [
        (True, False, "full_policy_matched", True, "valid", True, "complete"),
        (True, False, "full_policy_matched", True, "valid", False, "partial"),
        (True, False, "full_policy_matched", True, "none", True, "partial"),
        (True, False, "full_policy_matched", True, "internal", True, "partial"),
        (False, False, "full_policy_matched", True, "valid", True, "unavailable"),
        (True, False, "full_policy_matched", False, "valid", True, "unavailable"),
        (False, True, "partial_policy_matched", True, "valid", True, "partial"),
        (False, False, "no_policy_matched", False, "none", False, "unavailable"),
    ],
)
def test_public_result_status_and_verification_truth_table(
    can_answer,
    partial_answer,
    policy_status,
    real_case_data,
    public_evidence,
    has_calculation,
    expected_status,
):
    from src.runtime.api.policy_qa_routes import _build_public_result

    evidence_by_kind = {
        "valid": [
            {
                "title": "职工医保住院待遇政策",
                "clause": "起付线以上部分按规定比例由个人承担。",
                "score": 0.98,
            }
        ],
        "internal": [
            {
                "title": "SQL_PROFILE",
                "clause": "SELECT * FROM yb_zyfdxx",
                "score": 0.98,
            }
        ],
        "none": [],
    }
    result = _build_public_result(
        answer=(
            "统筹自付解释"
            if can_answer or partial_answer
            else "当前信息不足，无法可靠解释该费用。"
        ),
        can_answer=can_answer,
        partial_answer=partial_answer,
        policy_status=policy_status,
        policy_evidence=evidence_by_kind[public_evidence],
        calculation_steps=(
            [{"label": "统筹自付", "formula": "按政策区间分段计算"}]
            if has_calculation
            else []
        ),
        definition={"name": "统筹自付", "plain_text": "个人按政策承担的部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 0.0} if real_case_data else None,
    )

    assert result.answer_status == expected_status
    assert result.citations or result.uncertainties
    assert result.verification_summary.settlement_checked is real_case_data
    assert result.verification_summary.calculation_checked is has_calculation
    assert result.verification_summary.policy_count == (1 if public_evidence == "valid" else 0)
    if expected_status == "complete":
        assert "已完成核对" in result.verification_summary.message
    elif expected_status == "partial":
        assert "不完整" in result.verification_summary.message
    else:
        assert "不足" in result.verification_summary.message


def test_sql_placeholder_answer_cannot_make_result_complete():
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="SELECT * FROM yb_zyfdxx",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[
            {"title": "职工医保住院政策", "clause": "按规定比例承担。", "score": 0.9},
        ],
        calculation_steps=[{"description": "按政策比例计算。"}],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 4962.67},
    )

    assert result.answer_status == "unavailable"
    assert result.uncertainties


@pytest.mark.parametrize(
    "internal_description",
    ["SELECT * FROM yb_zyfdxx", "bdtczf"],
)
def test_placeholder_only_calculation_step_is_dropped(internal_description):
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="统筹自付按政策比例计算。",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[
            {"title": "职工医保住院政策", "clause": "按规定比例承担。", "score": 0.9},
        ],
        calculation_steps=[{"description": internal_description}],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 4962.67},
    )

    assert result.calculation_steps == []
    assert result.verification_summary.calculation_checked is False
    assert result.answer_status == "partial"
    assert result.uncertainties


def test_overview_result_is_complete_without_claiming_policy_or_calculation_verification():
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="本次住院费用构成总览。",
        can_answer=True,
        partial_answer=False,
        policy_status="no_policy_matched",
        policy_evidence=[],
        calculation_steps=[],
        definition={"name": "住院费用构成", "plain_text": "真实结算金额汇总。"},
        warnings=[],
        case_context={"total_amount": 0.0},
        is_overview=True,
    )

    assert result.answer_status == "complete"
    assert result.verification_summary.settlement_checked is True
    assert result.verification_summary.calculation_checked is False
    assert result.verification_summary.policy_count == 0
    assert "不涉及单项政策" in result.verification_summary.message
    assert result.uncertainties


@pytest.mark.parametrize(
    ("location", "unsafe_text", "forbidden_token"),
    [
        ("answer", "说明来源yb_zyfdxx。", "yb_zyfdxx"),
        ("warning", "请查YB_DYXXZY!", "yb_dyxxzy"),
        ("calculation", "金额来自bdtczf，", "bdtczf"),
        ("calculation", "起付线来自BCQFJE。", "bcqfje"),
        ("answer", "内部basic_pooling_self_pay。", "basic_pooling_self_pay"),
        ("warning", "使用sql_profile配置。", "sql_profile"),
        ("evidence", "tables_queried列表。", "tables_queried"),
    ],
)
def test_public_text_sanitizer_handles_chinese_ascii_boundaries(
    location, unsafe_text, forbidden_token
):
    from src.runtime.api.policy_qa_routes import _build_public_result

    kwargs = {
        "answer": "正常政策解释。",
        "can_answer": True,
        "partial_answer": False,
        "policy_status": "full_policy_matched",
        "policy_evidence": [
            {"title": "医保政策", "clause": "按规定比例承担。", "score": 0.9},
        ],
        "calculation_steps": [{"step_name": "核对", "description": "按比例计算。"}],
        "definition": {"name": "统筹自付", "plain_text": "个人承担部分。"},
        "warnings": [],
        "case_context": {"basic_pooling_self_pay": 0.0},
    }
    if location == "answer":
        kwargs["answer"] = unsafe_text
    elif location == "warning":
        kwargs["warnings"] = [unsafe_text]
    elif location == "calculation":
        kwargs["calculation_steps"] = [{"step_name": "核对", "description": unsafe_text}]
    else:
        kwargs["policy_evidence"] = [
            {"title": "医保政策", "clause": unsafe_text, "score": 0.9},
        ]

    result = _build_public_result(**kwargs)
    if location == "answer":
        public_text = result.answer
    elif location == "warning":
        public_text = result.warnings[0]
    elif location == "calculation":
        public_text = result.calculation_steps[0].description
    else:
        assert result.policy_evidence == []
        assert result.citations == []
        return

    assert forbidden_token not in public_text.casefold()


@pytest.mark.parametrize(
    ("unsafe_text", "forbidden_token"),
    [
        ("来源zyfdxx.bdgryf。", "zyfdxx.bdgryf"),
        ("来源ZYDYXX.BCYBNJE!", "zydyxx.bcybnje"),
        ("来源zyjyxx.rylb，", "zyjyxx.rylb"),
        ("来源DJXX.FUND_TYPE。", "djxx.fund_type"),
        ("来源yb_brdjxx.FUND_TYPE。", "yb_brdjxx.fund_type"),
        ("金额bddezf。", "bddezf"),
        ("金额BDGRYF，", "bdgryf"),
        ("字段bdtczfje。", "bdtczfje"),
        ("字段bddegwyzf。", "bddegwyzf"),
        ("字段bddegwyzfje。", "bddegwyzfje"),
        ("字段bcybnje。", "bcybnje"),
        ("字段bctcje。", "bctcje"),
        ("字段bczfje。", "bczfje"),
        ("字段debxbxje。", "debxbxje"),
        ("字段dezfje。", "dezfje"),
        ("字段grzfje。", "grzfje"),
        ("字段PER_TYPE。", "per_type"),
        ("字段FUND_TYPE。", "fund_type"),
        ("字段yllb。", "yllb"),
        ("字段rylb。", "rylb"),
        ("字段medical_insurance_inner_amount。", "medical_insurance_inner_amount"),
        ("字段basic_pooling_payment。", "basic_pooling_payment"),
        ("字段large_amount_payment。", "large_amount_payment"),
        ("字段large_amount_self_pay。", "large_amount_self_pay"),
        ("字段personal_total_pay。", "personal_total_pay"),
        ("字段person_type。", "person_type"),
        ("字段insurance_type。", "insurance_type"),
        ("字段service_type。", "service_type"),
        ("字段hospital_level。", "hospital_level"),
    ],
)
def test_public_text_sanitizer_blocks_mapped_internal_identifiers(
    unsafe_text, forbidden_token
):
    from src.runtime.api.policy_qa_routes import _public_text

    public_text = _public_text(unsafe_text)

    assert forbidden_token not in public_text.casefold()


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "WITH claims AS (SELECT * FROM yb_zyfdxx) SELECT * FROM claims",
        "请执行MERGE INTO claims USING source ON claims.id=source.id。",
        "请执行DROP TABLE claims。",
        "请执行ALTER TABLE claims ADD secret varchar(20)。",
        "请执行CREATE TABLE claims(id int)。",
        "请执行TRUNCATE TABLE claims。",
        "请执行EXEC claim_proc。",
        "请执行CALL claim_proc()。",
        "连接DSN=hospital;password=secret;token=abc123。",
    ],
)
def test_public_text_sanitizer_blocks_sql_and_credentials(unsafe_text):
    from src.runtime.api.policy_qa_routes import _public_text

    public_text = _public_text(unsafe_text).casefold()

    assert all(
        token not in public_text
        for token in (
            "with",
            "select",
            "merge",
            "drop",
            "alter",
            "create",
            "truncate",
            "exec",
            "call",
            "dsn",
            "password",
            "token",
            "secret",
            "abc123",
        )
    )


@pytest.mark.parametrize(
    "safe_text",
    [
        "The financial review is complete.",
        "Nonetheless, the deductible remains unchanged.",
        "The deductible is 650 yuan.",
        "Please call the hospital insurance office.",
        "This policy update takes effect in August.",
        "Select the applicable settlement record.",
        "Create an appeal if the claim is denied.",
        "The two benefit pools merge after the threshold.",
    ],
)
def test_public_text_sanitizer_preserves_legal_natural_language(safe_text):
    from src.runtime.api.policy_qa_routes import _public_text

    assert _public_text(safe_text) == safe_text


@pytest.mark.parametrize(
    "sql_text",
    [
        "SELECT 1",
        "SELECT @@VERSION",
        "INSERT claims VALUES (1)",
        "CREATE PROCEDURE claim_proc AS BEGIN RETURN END",
    ],
)
@pytest.mark.parametrize("location", ["answer", "calculation", "evidence"])
def test_sql_statement_variants_are_rejected_at_public_contract_boundaries(
    sql_text, location
):
    from src.runtime.api.policy_qa_routes import _build_public_result

    kwargs = {
        "answer": "The settlement result can be explained.",
        "can_answer": True,
        "partial_answer": False,
        "policy_status": "full_policy_matched",
        "policy_evidence": [
            {
                "title": "Published insurance policy",
                "clause": "The deductible is 650 yuan.",
                "score": 0.9,
            },
        ],
        "calculation_steps": [
            {"step_name": "Check", "description": "Apply the published percentage."},
        ],
        "definition": {
            "name": "Pooling self-pay",
            "plain_text": "The amount paid by the insured person.",
        },
        "warnings": [],
        "case_context": {"basic_pooling_self_pay": 123.45},
    }
    if location == "answer":
        kwargs["answer"] = sql_text
    elif location == "calculation":
        kwargs["calculation_steps"] = [
            {"step_name": "Check", "description": sql_text},
        ]
    else:
        kwargs["policy_evidence"] = [
            {
                "title": "Published insurance policy",
                "clause": sql_text,
                "score": 0.9,
            },
        ]

    result = _build_public_result(**kwargs)

    if location == "answer":
        assert result.answer_status == "unavailable"
        assert result.uncertainties
    elif location == "calculation":
        assert result.calculation_steps == []
        assert result.verification_summary.calculation_checked is False
        assert result.answer_status == "partial"
    else:
        assert result.policy_evidence == []
        assert result.citations == []
        assert result.verification_summary.policy_count == 0
        assert result.answer_status == "partial"


def test_internal_only_evidence_is_dropped_instead_of_becoming_placeholder_citation():
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="可核对真实金额。",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[
            {"title": "SQL_PROFILE", "clause": "SELECT * FROM yb_zyfdxx", "score": 0.9},
        ],
        calculation_steps=[{"step_name": "核对", "description": "按比例计算。"}],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 0.0},
    )

    assert result.policy_evidence == []
    assert result.citations == []
    assert result.verification_summary.policy_count == 0
    assert result.uncertainties


@pytest.mark.parametrize(
    "internal_excerpt",
    [
        "MERGE INTO claims USING source ON claims.id=source.id",
        "DSN=hospital;password=secret;token=abc123",
    ],
)
def test_sql_or_credential_only_evidence_is_dropped(internal_excerpt):
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="可核对真实金额。",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[
            {"title": "内部实现", "clause": internal_excerpt, "score": 0.9},
        ],
        calculation_steps=[{"step_name": "核对", "description": "按比例计算。"}],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 0.0},
    )

    assert result.policy_evidence == []
    assert result.citations == []


@pytest.mark.parametrize(
    "internal_excerpt",
    [
        "zyfdxx.bdgryf",
        "yb_zyfdxx.bdtczf",
        "tables_queried",
    ],
)
def test_table_or_field_only_evidence_cannot_make_answer_complete(internal_excerpt):
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="统筹自付按政策比例计算。",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[
            {"title": "内部字段", "clause": internal_excerpt, "score": 0.9},
        ],
        calculation_steps=[{"step_name": "核对", "description": "按比例计算。"}],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 4962.67},
    )

    assert result.policy_evidence == []
    assert result.citations == []
    assert result.verification_summary.policy_count == 0
    assert result.answer_status == "partial"
    assert result.uncertainties


def test_legal_policy_excerpt_remains_public_evidence():
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="统筹自付按政策比例计算。",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[
            {
                "title": "职工医保住院待遇政策",
                "clause": "起付线以上部分按规定比例由个人承担。",
                "score": 0.9,
            },
        ],
        calculation_steps=[{"step_name": "核对", "description": "按比例计算。"}],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 4962.67},
    )

    assert len(result.policy_evidence) == 1
    assert len(result.citations) == 1
    assert result.verification_summary.policy_count == 1
    assert result.answer_status == "complete"


def test_internal_identifier_in_evidence_title_drops_whole_evidence():
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="统筹自付按政策比例计算。",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[
            {
                "title": "zyfdxx.bdgryf",
                "clause": "内部字段说明。",
                "score": 0.9,
            },
        ],
        calculation_steps=[{"step_name": "核对", "description": "按比例计算。"}],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 4962.67},
    )

    assert result.policy_evidence == []
    assert result.citations == []
    assert result.verification_summary.policy_count == 0


@pytest.mark.parametrize(
    ("internal_excerpt", "forbidden_tokens"),
    [
        ("Milvus policy_rules", ("milvus", "policy_rules")),
        (
            "postgresql://postgres:postgres@127.0.0.1:5432/hospital_mcp",
            ("postgresql", "postgres:postgres", "hospital_mcp"),
        ),
        (
            "redis://:hunter2@localhost:6379/0",
            ("redis", "hunter2", "localhost"),
        ),
    ],
)
def test_storage_or_connection_only_evidence_is_dropped(
    internal_excerpt, forbidden_tokens
):
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="统筹自付按政策比例计算。",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[
            {"title": "内部来源", "clause": internal_excerpt, "score": 0.9},
        ],
        calculation_steps=[{"description": "按政策比例计算。"}],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 4962.67},
    )

    dumped = result.model_dump_json().casefold()
    assert result.policy_evidence == []
    assert result.citations == []
    assert result.verification_summary.policy_count == 0
    assert result.answer_status == "partial"
    assert result.uncertainties
    assert all(token not in dumped for token in forbidden_tokens)


def test_public_text_sanitizer_preserves_normal_chinese_and_zero_amount():
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="本次统筹自付为 0 元。",
        can_answer=True,
        partial_answer=True,
        policy_status="no_policy_matched",
        policy_evidence=[],
        calculation_steps=[],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=["零金额是合法结算结果。"],
        case_context={"basic_pooling_self_pay": 0.0},
    )

    assert result.answer == "本次统筹自付为 0 元。"
    assert result.case_context.basic_pooling_self_pay == 0.0


def test_zero_amount_completeness_reaches_public_partial_status():
    from types import SimpleNamespace

    from skills.settlement_explain_skill.strategies.registry import get_strategy
    from src.runtime.api.policy_qa_routes import (
        _answerability_from_completeness,
        _build_public_result,
    )

    context = SimpleNamespace(
        basic_pooling_self_pay=0.0,
        tables_queried=["yb_zyfdxx"],
    )
    completeness = get_strategy("pooling_self_pay").build_completeness(context, [])
    can_answer, partial_answer = _answerability_from_completeness(completeness, [])
    result = _build_public_result(
        answer="本次统筹自付为 0.00 元。",
        can_answer=can_answer,
        partial_answer=partial_answer,
        policy_status="no_policy_matched",
        policy_evidence=[],
        calculation_steps=[],
        definition={"name": "统筹自付", "plain_text": "个人承担部分。"},
        warnings=[],
        case_context={"basic_pooling_self_pay": 0.0},
    )

    assert completeness["has_real_data"] is True
    assert result.answer_status == "partial"
    assert result.verification_summary.settlement_checked is True
    assert "0.00" in result.answer


@pytest.mark.asyncio
