"""
Unit tests for all 6 fee explanation strategies.

Tests cover:
- Each strategy's execute() method with proper evidence
- Edge cases (no evidence, missing fields)
- Registry loading and fallback behavior
- All 6 abstract methods are implemented
"""

import pytest
from types import SimpleNamespace

from skills.settlement_explain_skill.strategies.registry import get_strategy, list_strategies


# ══════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def settlement_context():
    """Mock settlement context with realistic values matching settlement 1671213."""
    return SimpleNamespace(
        settlement_id="1671213",
        deductible=650.0,
        medical_insurance_inner_amount=50000.0,
        basic_pooling_payment=35000.0,
        basic_pooling_self_pay=4962.67,
        large_amount_payment=10000.0,
        large_amount_self_pay=1500.0,
        personal_total_pay=7112.67,
        insurance_type="城镇职工基本医疗保险",
        person_type="退休人员",
        service_type="普通住院",
        hospital_level="三级医院",
    )


@pytest.fixture
def mock_evidence():
    """Mock policy evidence with 3 segment ratios + retiree 60% rule.

    Segment 1: 起付标准~3万元 → 85% fund / 15% personal
    Segment 2: 3万元~4万元   → 90% fund / 10% personal
    Segment 3: 4万元以上     → 95% fund /  5% personal
    Retiree:   personal pay = 60% of employee personal pay
    """
    return [
        {
            "source_text": "三级医院住院费用分段：起付标准至3万元的部分，"
                           "统筹基金支付 85%，职工个人支付 15%",
            "applied_reason": "本次结算适用三级医院住院首段支付比例。",
            "rule_type": "支付比例",
            "psn_type": "",
        },
        {
            "source_text": "三级医院住院费用分段：超过3万元至4万元的部分，"
                           "统筹基金支付 90%，职工个人支付 10%",
            "applied_reason": "本次结算适用三级医院住院中段支付比例。",
            "rule_type": "支付比例",
            "psn_type": "",
        },
        {
            "source_text": "三级医院住院费用分段：超过4万元的部分，"
                           "统筹基金支付 95%，职工个人支付 5%",
            "applied_reason": "本次结算适用三级医院住院高段支付比例。",
            "rule_type": "支付比例",
            "psn_type": "",
        },
        {
            "source_text": "退休人员个人支付比例为在职职工个人支付比例的60%",
            "applied_reason": "退休人员享受优惠折算。",
            "rule_type": "计算公式",
            "psn_type": "退休人员",
            "rule_value": "retiree_60",
        },
    ]


@pytest.fixture
def ctx_no_out_of_scope():
    """Context without out_of_scope field to test graceful fallback."""
    return SimpleNamespace(
        settlement_id="1671213",
        deductible=650.0,
        basic_pooling_self_pay=4962.67,
        large_amount_self_pay=1500.0,
        personal_total_pay=7112.67,
        insurance_type="城镇职工基本医疗保险",
        person_type="退休人员",
        service_type="普通住院",
        hospital_level="三级医院",
    )


# ══════════════════════════════════════════════════════════════════════════
# Registry
# ══════════════════════════════════════════════════════════════════════════


class TestRegistry:
    """Tests for strategy registry."""

    def test_registry_lists_all(self):
        """Verify list_strategies() returns all 6 registered strategies."""
        strategies = list_strategies()
        assert len(strategies) == 6
        expected = {
            "pooling_self_pay",
            "deductible",
            "large_amount_self_pay",
            "out_of_scope",
            "pooling_payment",
            "personal_total_pay",
        }
        assert set(strategies) == expected

    def test_unknown_fee_item_fallback(self):
        """Verify get_strategy("unknown") falls back to pooling_self_pay."""
        strategy = get_strategy("this_is_not_a_real_fee_item")
        assert strategy.fee_item == "pooling_self_pay"
        assert strategy.fee_label == "统筹自付"
        assert strategy.fee_field == "basic_pooling_self_pay"

    def test_all_strategies_have_single_answer_contract(self):
        """Verify each strategy exposes only the single-answer contract."""
        required_methods = [
            "build_definition",
            "build_policy_queries",
            "build_answer",
            "build_calculation_trace",
            "build_warnings",
            "build_completeness",
        ]
        for name in list_strategies():
            strategy = get_strategy(name)
            for method in required_methods:
                assert callable(getattr(strategy, method))
            assert not hasattr(strategy, "build_patient_answer")
            assert not hasattr(strategy, "build_office_answer")

    def test_all_strategies_execute_with_one_answer(
        self, settlement_context, mock_evidence
    ):
        """Verify every strategy returns exactly one answer field."""
        for name in list_strategies():
            result = get_strategy(name).execute(
                settlement_context,
                mock_evidence,
                "full_policy_matched",
            )
            assert result.answer
            assert not hasattr(result, "patient_answer")
            assert not hasattr(result, "office_answer")


def test_output_schema_requires_answer_only():
    import json
    from pathlib import Path

    schema_path = Path(__file__).parents[1] / "schemas" / "output.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required = set(schema["required"])
    properties = set(schema["properties"])
    assert "answer" in required
    assert "patient_answer" not in required | properties
    assert "office_answer" not in required | properties


def test_output_schema_accepts_answer_and_rejects_legacy_fields():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator, ValidationError

    schema_path = Path(__file__).parents[1] / "schemas" / "output.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    payload = {
        "skill_id": "policy-fee-explanation",
        "target_fee_item": "pooling_self_pay",
        "target_field": "basic_pooling_self_pay",
        "target_amount": 4962.67,
        "data_source": "REAL_DB",
        "mock_used": False,
        "can_answer": True,
        "partial_answer": False,
        "case_context": {},
        "policy_evidence": [],
        "evidence_completeness": {},
        "recalculation_completeness": {},
        "answer": "本次结算的统筹自付金额已确认。",
        "calculation_trace": {},
        "ratio_explanation": {},
        "explanation_completeness": {},
        "definition": {},
        "policy_status": "full_policy_matched",
        "policy_status_message": "已匹配完整政策依据。",
        "llm_readable_context": "当前结算上下文。",
        "warnings": [],
        "trace_events": [],
        "validation": {"passed": True, "checks": []},
    }

    validator.validate(payload)
    with pytest.raises(ValidationError):
        validator.validate(
            {
                **payload,
                "patient_answer": "旧患者答案",
                "office_answer": "旧医保办答案",
            }
        )


def test_prompt_requires_single_conclusion_only():
    import yaml
    from pathlib import Path

    prompt_path = Path(__file__).parents[1] / "prompt_template.yaml"
    prompt_config = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
    prompt = prompt_config["system_prompt"] + prompt_config["user_prompt"]
    assert "[CONCLUSION]" in prompt
    assert "[OFFICE_NOTE]" not in prompt
    assert "院端备注" not in prompt
    assert "面向当前院端经办角色的单一自然语言解释" in prompt_config["user_prompt"]


def test_pooling_prompt_is_reloaded_for_each_generation(
    monkeypatch, settlement_context, mock_evidence
):
    from skills.settlement_explain_skill.strategies.pooling_self_pay import (
        strategy as strategy_module,
    )
    from src.model_service import gateway as gateway_module

    prompt_configs = iter(
        [
            {"system_prompt": "动态模板 A", "user_prompt": "{{ fact_json }}"},
            {"system_prompt": "动态模板 B", "user_prompt": "{{ fact_json }}"},
        ]
    )
    monkeypatch.setattr(strategy_module.yaml, "safe_load", lambda _text: next(prompt_configs))
    captured_system_prompts = []

    class FakeGateway:
        _config = SimpleNamespace(base_url="https://model.test")

        def generate(self, *, messages, **_kwargs):
            captured_system_prompts.append(messages[0].content)
            return SimpleNamespace(content="[CONCLUSION]\n模板已刷新")

    monkeypatch.setattr(strategy_module, "ModelGateway", FakeGateway)
    monkeypatch.setattr(gateway_module, "ModelGateway", FakeGateway)
    strategy = get_strategy("pooling_self_pay")

    strategy._generate_via_llm(
        settlement_context, mock_evidence, "full_policy_matched"
    )
    strategy._generate_via_llm(
        settlement_context, mock_evidence, "full_policy_matched"
    )

    assert captured_system_prompts == ["动态模板 A", "动态模板 B"]


@pytest.mark.parametrize(
    ("strategy_name", "amount_field"),
    [
        ("deductible", "deductible"),
        ("pooling_self_pay", "basic_pooling_self_pay"),
        ("pooling_payment", "basic_pooling_payment"),
        ("large_amount_self_pay", "large_amount_self_pay"),
        ("personal_total_pay", "personal_total_pay"),
        ("out_of_scope", "out_of_scope"),
    ],
)
def test_zero_amount_from_queried_context_is_real_data(
    strategy_name, amount_field, mock_evidence
):
    context_values = {
        "deductible": 0.0,
        "basic_pooling_self_pay": 0.0,
        "basic_pooling_payment": 0.0,
        "large_amount_self_pay": 0.0,
        "personal_total_pay": 0.0,
        "out_of_scope": 0.0,
        "tables_queried": ["yb_zyfdxx"],
    }
    context_values[amount_field] = 0.0
    context = SimpleNamespace(**context_values)

    completeness = get_strategy(strategy_name).build_completeness(
        context,
        mock_evidence,
    )

    assert completeness["has_real_data"] is True
    assert completeness["level"] != "incomplete"


def test_default_unqueried_settlement_context_is_not_real_data():
    from src.runtime.policy_qa.settlement_data_provider import SettlementContext

    completeness = get_strategy("pooling_self_pay").build_completeness(
        SettlementContext(),
        [],
    )

    assert completeness["has_real_data"] is False


def test_zero_amount_formats_as_zero_not_missing():
    assert get_strategy("pooling_self_pay")._fmt_money(0.0) == "0.00"


def test_pooling_self_pay_missing_conclusion_uses_safe_fallback(
    monkeypatch, settlement_context, mock_evidence
):
    from skills.settlement_explain_skill.output_parser import OutputParser

    strategy = get_strategy("pooling_self_pay")
    monkeypatch.setattr(
        strategy,
        "_generate_via_llm",
        lambda *_args: OutputParser.parse("模型未返回结论标记"),
    )

    result = strategy.execute(
        settlement_context, mock_evidence, "full_policy_matched"
    )

    assert result.answer.strip()
    assert "统筹自付" in result.answer


def test_all_strategies_filter_forbidden_tokens_from_evidence(settlement_context):
    malicious_evidence = [
        {
            "source_text": "内部来源 yb_zyfdxx，规则编号 rule_id",
            "applied_reason": "按 rule_id 命中内部字段 yb_zyfdxx",
        }
    ]

    for name in list_strategies():
        result = get_strategy(name).execute(
            settlement_context,
            malicious_evidence,
            "partial_policy_matched",
        )
        assert result.answer.strip()
        assert "yb_zyfdxx" not in result.answer
        assert "rule_id" not in result.answer


@pytest.mark.parametrize(
    "internal_identifier",
    [
        "yb_brdjxx",
        "bdtczf",
        "basic_pooling_self_pay",
        "RuLe_Id",
        "SQL_PROFILE",
        "tables_queried",
        "Clause_ID",
    ],
)
def test_strategy_filters_internal_identifiers_case_insensitively(
    internal_identifier, settlement_context
):
    evidence = [
        {
            "source_text": f"内部实现标识{internal_identifier}字段",
            "applied_reason": f"通过{internal_identifier}命中",
        }
    ]

    result = get_strategy("deductible").execute(
        settlement_context,
        evidence,
        "partial_policy_matched",
    )

    assert result.answer.strip()
    assert internal_identifier.casefold() not in result.answer.casefold()


@pytest.mark.parametrize(
    "answer",
    [
        "Your deductible is 650 yuan.",
        "We provide financial assistance.",
        "Nonetheless, the result is confirmed.",
    ],
)
def test_validator_and_strategy_allow_legal_english(
    answer, monkeypatch, settlement_context
):
    from skills.settlement_explain_skill.scripts.validate_skill_result import (
        validate_answer,
    )

    validation = validate_answer(
        answer,
        target_fee_item="deductible",
        skip_for_llm=True,
    )
    assert validation.passed

    strategy = get_strategy("deductible")
    monkeypatch.setattr(strategy, "build_answer", lambda *_args: answer)
    result = strategy.execute(
        settlement_context,
        [],
        "no_policy_matched",
    )

    assert result.answer == answer
    assert not any("安全降级" in warning for warning in result.warnings)


# ══════════════════════════════════════════════════════════════════════════
# PoolingSelfPayStrategy — 统筹自付
# ══════════════════════════════════════════════════════════════════════════


class TestPoolingSelfPay:
    """Tests for PoolingSelfPayStrategy."""

    def test_execute(self, settlement_context, mock_evidence):
        """Verify answer contains amount and conclusion section."""
        strategy = get_strategy("pooling_self_pay")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        # Structural checks: non-empty output
        assert result.answer

        # Correct fee item identification
        assert result.target_fee_item == "pooling_self_pay"
        assert result.target_field == "basic_pooling_self_pay"

        # Amount presence (flexible format)
        assert "4962" in result.answer or "4,962" in result.answer

        # Conclusion section — text after [CONCLUSION] marker; no longer includes header
        assert len(result.answer) > 20

    def test_no_evidence(self, settlement_context):
        """Verify graceful handling when no policy evidence is available."""
        strategy = get_strategy("pooling_self_pay")
        result = strategy.execute(
            settlement_context, [], "no_policy_matched"
        )

        # Structural check: non-empty output
        assert result.answer

        # Amount presence (flexible format)
        assert "4962" in result.answer or "4,962" in result.answer

        # Should not contain ratio details without evidence
        assert "85%" not in result.answer
        assert result.warnings
        assert result.completeness["level"] == "real_data_only"

    def test_definition(self):
        """Verify build_definition returns correct structure."""
        strategy = get_strategy("pooling_self_pay")
        definition = strategy.build_definition()
        assert definition["name"] == "统筹自付"
        assert "统筹" in definition["plain_text"]
        assert "起付线" in definition["excludes"]

    def test_policy_queries(self):
        """Verify build_policy_queries returns StructuredPolicyQuery list."""
        strategy = get_strategy("pooling_self_pay")
        queries = strategy.build_policy_queries()
        assert len(queries) >= 2
        for q in queries:
            assert hasattr(q, "query_name")
            assert hasattr(q, "required")


# ══════════════════════════════════════════════════════════════════════════
# DeductibleStrategy — 起付线
# ══════════════════════════════════════════════════════════════════════════


class TestDeductible:
    """Tests for DeductibleStrategy."""

    def test_execute(self, settlement_context, mock_evidence):
        """Verify answer contains 起付线 with amount."""
        strategy = get_strategy("deductible")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        assert "起付线" in result.answer
        assert "650.00" in result.answer
        assert result.target_fee_item == "deductible"
        assert result.target_field == "deductible"

    def test_completeness_with_evidence(self, settlement_context, mock_evidence):
        """Verify completeness level with evidence."""
        strategy = get_strategy("deductible")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        assert result.completeness["level"] == "full_policy_matched"
        assert result.completeness["has_real_data"] is True
        assert result.completeness["message"]

    def test_completeness_no_evidence(self, settlement_context):
        """Verify completeness level without evidence."""
        strategy = get_strategy("deductible")
        result = strategy.execute(
            settlement_context, [], "no_policy_matched"
        )

        assert result.completeness["level"] == "real_data_only"
        assert result.completeness["has_real_data"] is True

    def test_warnings(self, settlement_context):
        """Verify build_warnings returns appropriate warnings."""
        strategy = get_strategy("deductible")
        warnings = strategy.build_warnings(settlement_context, "policy_matched")
        assert len(warnings) >= 2
        assert any("起付线" in w for w in warnings)


# ══════════════════════════════════════════════════════════════════════════
# LargeAmountSelfPayStrategy — 大额自付
# ══════════════════════════════════════════════════════════════════════════


class TestLargeAmountSelfPay:
    """Tests for LargeAmountSelfPayStrategy."""

    def test_execute(self, settlement_context, mock_evidence):
        """Verify answer contains 大额自付 with amount."""
        strategy = get_strategy("large_amount_self_pay")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        assert "大额自付" in result.answer
        assert "1,500.00" in result.answer
        assert result.target_fee_item == "large_amount_self_pay"
        assert result.target_field == "large_amount_self_pay"

    def test_all_methods(self, settlement_context, mock_evidence):
        """Call all 6 methods directly and verify non-empty results."""
        strategy = get_strategy("large_amount_self_pay")

        definition = strategy.build_definition()
        assert definition["name"] == "大额自付"
        assert isinstance(definition["excludes"], list)

        queries = strategy.build_policy_queries()
        assert isinstance(queries, list)

        answer = strategy.build_answer(
            settlement_context, mock_evidence, "policy_matched"
        )
        assert len(answer) > 50

        trace = strategy.build_calculation_trace(
            settlement_context, mock_evidence
        )
        assert isinstance(trace, dict)
        assert "steps" in trace
        assert len(trace["steps"]) >= 3

        warnings = strategy.build_warnings(settlement_context, "policy_matched")
        assert len(warnings) >= 2

        completeness = strategy.build_completeness(
            settlement_context, mock_evidence
        )
        assert isinstance(completeness, dict)
        assert "level" in completeness
        assert "has_real_data" in completeness

    def test_no_evidence(self, settlement_context):
        """Verify graceful handling with no evidence."""
        strategy = get_strategy("large_amount_self_pay")
        result = strategy.execute(
            settlement_context, [], "no_policy_matched"
        )

        assert "大额自付" in result.answer
        assert "1,500.00" in result.answer
        assert result.completeness["level"] == "real_data_only"


# ══════════════════════════════════════════════════════════════════════════
# PoolingPaymentStrategy — 统筹支付
# ══════════════════════════════════════════════════════════════════════════


class TestPoolingPayment:
    """Tests for PoolingPaymentStrategy."""

    def test_execute(self, settlement_context, mock_evidence):
        """Verify answer contains 统筹支付 with amount and fund ratios."""
        strategy = get_strategy("pooling_payment")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        assert "统筹支付" in result.answer
        assert "35,000.00" in result.answer
        assert "85%" in result.answer
        assert "90%" in result.answer
        assert "95%" in result.answer
        assert "退休人员" in result.answer
        assert result.target_fee_item == "pooling_payment"
        assert result.target_field == "basic_pooling_payment"

    def test_completeness(self, settlement_context, mock_evidence):
        """Verify completeness with 3 segments of evidence."""
        strategy = get_strategy("pooling_payment")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        # With 3 segments, has_complete should be True
        assert "full_policy" in result.completeness["level"]
        assert result.completeness["has_real_data"] is True

    def test_definition(self):
        """Verify definition mentions 统筹基金."""
        strategy = get_strategy("pooling_payment")
        definition = strategy.build_definition()
        assert "统筹基金" in definition["plain_text"]
        assert "统筹自付" in definition["excludes"]

    def test_relationship_section(self, settlement_context, mock_evidence):
        """Verify amount relationship section is present."""
        strategy = get_strategy("pooling_payment")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        answer = result.answer
        # Should mention related fee items
        assert "起付线" in answer
        assert "统筹自付" in answer
        assert "大额自付" in answer


# ══════════════════════════════════════════════════════════════════════════
# PersonalTotalPayStrategy — 个人总支付
# ══════════════════════════════════════════════════════════════════════════


class TestPersonalTotalPay:
    """Tests for PersonalTotalPayStrategy."""

    def test_execute(self, settlement_context, mock_evidence):
        """Verify answer contains 个人总支付 with amount and composition."""
        strategy = get_strategy("personal_total_pay")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        assert "个人总支付" in result.answer
        assert "7,112.67" in result.answer
        assert "起付线" in result.answer
        assert result.target_fee_item == "personal_total_pay"
        assert result.target_field == "personal_total_pay"

    def test_composition_breakdown(self, settlement_context, mock_evidence):
        """Verify it mentions deductible + pooling_self_pay + large_self."""
        strategy = get_strategy("personal_total_pay")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        answer = result.answer
        assert "650.00" in answer
        assert "4,962.67" in answer
        assert "1,500.00" in answer

    def test_completeness(self, settlement_context, mock_evidence):
        """Verify completeness level with all components present."""
        strategy = get_strategy("personal_total_pay")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        assert "full_policy" in result.completeness["level"]
        assert result.completeness["has_real_data"] is True

    def test_completeness_no_evidence(self, settlement_context):
        """Verify completeness without evidence drops to real_data_only."""
        strategy = get_strategy("personal_total_pay")
        result = strategy.execute(
            settlement_context, [], "no_policy_matched"
        )

        assert result.completeness["level"] == "real_data_only"
        assert result.completeness["has_real_data"] is True

    def test_warnings_distinguish_pooling_self_pay(self, settlement_context):
        """Verify warnings clarify that personal_total_pay != pooling_self_pay."""
        strategy = get_strategy("personal_total_pay")
        warnings = strategy.build_warnings(settlement_context, "policy_matched")
        assert any("不等于" in w and ("统筹自付" in w) for w in warnings)


# ══════════════════════════════════════════════════════════════════════════
# OutOfScopeStrategy — 医保外费用
# ══════════════════════════════════════════════════════════════════════════


class TestOutOfScope:
    """Tests for OutOfScopeStrategy."""

    def test_execute(self, settlement_context, mock_evidence):
        """Verify concept-driven explanation works with evidence."""
        strategy = get_strategy("out_of_scope")
        result = strategy.execute(
            settlement_context, mock_evidence, "policy_matched"
        )

        assert "医保外费用" in result.answer
        assert result.target_fee_item == "out_of_scope"
        assert result.target_field == "out_of_scope"
        assert len(result.answer) > 50

    def test_no_amount_field(self, ctx_no_out_of_scope):
        """Verify graceful handling when ctx has no out_of_scope field."""
        strategy = get_strategy("out_of_scope")
        result = strategy.execute(
            ctx_no_out_of_scope, [], "no_policy_matched"
        )

        assert "医保外费用" in result.answer
        # Should still produce concept-level explanation
        assert len(result.answer) > 50
        assert result.completeness["level"] == "incomplete"
        assert result.completeness["has_real_data"] is False

        # Should have additional warning about missing amount field
        warnings = result.warnings
        assert any("未提供独立的医保外费用金额字段" in w for w in warnings)

    def test_definition(self):
        """Verify definition mentions 目录外 and 自费."""
        strategy = get_strategy("out_of_scope")
        definition = strategy.build_definition()
        # plain_text says "不在医保报销目录范围内" not 医保外 explicitly
        assert "目录" in definition["plain_text"]
        assert "自费" in definition["plain_text"]
        assert definition["name"] == "医保外费用"

    def test_calculation_trace_no_amount(self, ctx_no_out_of_scope):
        """Verify calculation trace handles missing amount field."""
        strategy = get_strategy("out_of_scope")
        trace = strategy.build_calculation_trace(ctx_no_out_of_scope, [])
        assert isinstance(trace, dict)
        assert "steps" in trace
        # Should have step about missing field
        step_descriptions = " ".join(
            s["description"] for s in trace["steps"]
        )
        assert "未获取" in step_descriptions or "概念" in step_descriptions
