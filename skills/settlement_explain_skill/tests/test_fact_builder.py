"""
Unit tests for FactBuilder and FeeExplanationFact.

Tests cover:
- FeeExplanationFact serialization/deserialization (model_dump / model_dump_json)
- FactBuilder.build() with empty evidence + empty segment_ratios
- FactBuilder.build() with realistic mock data (settlement 1671213)
- Evidence boundary: 4 items, empty evidence, zero amounts
"""

import json
import pytest
from types import SimpleNamespace

from skills.settlement_explain_skill.fact_builder import FactBuilder, FeeExplanationFact


# ══════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def builder() -> FactBuilder:
    """Fresh FactBuilder instance per test."""
    return FactBuilder()


@pytest.fixture
def realistic_ctx():
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
def four_item_evidence():
    """Mock policy evidence with 4 items (3 segment ratios + 1 retiree rule)."""
    return [
        {
            "source_text": "三级医院住院费用分段：起付标准至3万元的部分，"
                           "统筹基金支付 85%，职工个人支付 15%",
            "applied_reason": "本次结算适用三级医院住院首段支付比例。",
            "rule_type": "支付比例",
        },
        {
            "source_text": "三级医院住院费用分段：超过3万元至4万元的部分，"
                           "统筹基金支付 90%，职工个人支付 10%",
            "applied_reason": "本次结算适用三级医院住院中段支付比例。",
            "rule_type": "支付比例",
        },
        {
            "source_text": "三级医院住院费用分段：超过4万元的部分，"
                           "统筹基金支付 95%，职工个人支付 5%",
            "applied_reason": "本次结算适用三级医院住院高段支付比例。",
            "rule_type": "支付比例",
        },
        {
            "source_text": "退休人员个人支付比例为在职职工个人支付比例的60%",
            "applied_reason": "退休人员享受优惠折算。",
            "rule_type": "计算公式",
            "rule_value": "retiree_60",
        },
    ]


@pytest.fixture
def realistic_segment_ratios():
    """Realistic segment ratios with retiree adjustment (三甲医院 退休)."""
    return {
        "employee": [
            {"min": 0, "max": 30000, "fund_ratio": 0.85, "personal_ratio": 0.15},
            {"min": 30000, "max": 40000, "fund_ratio": 0.90, "personal_ratio": 0.10},
            {"min": 40000, "max": None, "fund_ratio": 0.95, "personal_ratio": 0.05},
        ],
        "retiree": {
            "ratio": 60,
            "segments": [0.09, 0.06, 0.03],
        },
        "has_complete": True,
    }


# ══════════════════════════════════════════════════════════════════════════
# Tests: FeeExplanationFact serialization
# ══════════════════════════════════════════════════════════════════════════


class TestFeeExplanationFactSerialization:
    """FeeExplanationFact Pydantic model serialization/deserialization."""

    def test_model_dump_roundtrip(self):
        """model_dump() returns all fields, model_dump_json roundtrips."""
        fact = FeeExplanationFact(
            settlement_id="1671213",
            person_type="退休人员",
            insurance_type="城镇职工基本医疗保险",
            service_type="普通住院",
            hospital_level="三级医院",
            target_fee_item="pooling_self_pay",
            target_fee_label="统筹自付",
            target_fee_definition="基本医保统筹段内按政策比例由个人承担的金额",
            target_amount=4962.67,
            deductible=650.0,
            medical_insurance_inner_amount=50000.0,
            basic_pooling_payment=35000.0,
            basic_pooling_self_pay=4962.67,
            large_amount_payment=10000.0,
            large_amount_self_pay=1500.0,
            personal_total_pay=7112.67,
        )
        dumped = fact.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["settlement_id"] == "1671213"
        assert dumped["target_amount"] == 4962.67
        assert dumped["deductible"] == 650.0
        assert dumped["basic_pooling_self_pay"] == 4962.67
        assert dumped["personal_total_pay"] == 7112.67
        assert dumped["evidence_count"] == 0
        assert dumped["evidence_completeness"] == "none"
        assert dumped["segment_ratios"] == []

    def test_model_dump_json_roundtrip(self):
        """model_dump_json() produces valid JSON that can be deserialized back."""
        fact = FeeExplanationFact(
            settlement_id="1671213",
            target_fee_item="pooling_self_pay",
            target_amount=4962.67,
            deductible=650.0,
            personal_total_pay=7112.67,
            evidence_count=1,
            policy_evidence=[{"index": 1, "excerpt": "test excerpt", "applied_reason": "test reason"}],
        )
        json_str = fact.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["settlement_id"] == "1671213"
        assert parsed["target_amount"] == 4962.67
        assert parsed["deductible"] == 650.0
        assert parsed["evidence_count"] == 1
        assert len(parsed["policy_evidence"]) == 1
        assert parsed["policy_evidence"][0]["index"] == 1

    def test_default_values_not_none(self):
        """All fields default to non-None values (str/float/list)."""
        fact = FeeExplanationFact()
        dumped = fact.model_dump()
        # String fields default to ""
        assert dumped["settlement_id"] == ""
        assert dumped["person_type"] == ""
        # Float fields default to 0.0
        assert dumped["deductible"] == 0.0
        assert dumped["target_amount"] == 0.0
        # List fields default to []
        assert dumped["policy_evidence"] == []
        assert dumped["segment_ratios"] == []
        assert dumped["warnings"] == []
        # Integer fields default to 0
        assert dumped["evidence_count"] == 0
        # Optional fields default to None
        assert dumped["retiree_ratio"] is None
        assert dumped["retiree_adjusted_segments"] is None


# ══════════════════════════════════════════════════════════════════════════
# Tests: FactBuilder.build() edge cases
# ══════════════════════════════════════════════════════════════════════════


class TestFactBuilderEmptyEdgeCases:
    """FactBuilder.build() with minimal/empty inputs."""

    def test_empty_evidence_empty_segments(self, builder):
        """build() with empty evidence and empty segment_ratios works."""
        ctx = SimpleNamespace(
            settlement_id="1671213",
            deductible=650.0,
            basic_pooling_self_pay=4962.67,
            basic_pooling_payment=35000.0,
            large_amount_self_pay=1500.0,
            personal_total_pay=7112.67,
            person_type="退休人员",
            insurance_type="城镇职工基本医疗保险",
            service_type="普通住院",
            hospital_level="三级医院",
        )
        fact = builder.build(ctx, [], {}, "pooling_self_pay")

        assert fact.settlement_id == "1671213"
        assert fact.target_fee_item == "pooling_self_pay"
        assert fact.target_fee_label == "统筹自付"
        assert fact.target_amount == 4962.67
        assert fact.deductible == 650.0
        assert fact.personal_total_pay == 7112.67
        # Empty evidence
        assert fact.evidence_count == 0
        assert fact.policy_evidence == []
        assert fact.evidence_completeness == "none"
        # Empty segments
        assert fact.segment_ratios == []
        assert fact.has_retiree is False
        assert fact.retiree_ratio is None
        # Warning about incomplete
        assert len(fact.warnings) == 1
        assert "不完整" in fact.warnings[0]

    def test_zero_amounts(self, builder):
        """build() with zero amounts produces clean zero-valued fact."""
        ctx = SimpleNamespace(
            settlement_id="",
            deductible=0,
            medical_insurance_inner_amount=0,
            basic_pooling_payment=0,
            basic_pooling_self_pay=0,
            large_amount_payment=0,
            large_amount_self_pay=0,
            personal_total_pay=0,
            person_type="",
            insurance_type="",
            service_type="",
            hospital_level="",
        )
        fact = builder.build(ctx, [], {}, "pooling_self_pay")

        assert fact.settlement_id == ""
        assert fact.target_amount == 0.0
        assert fact.deductible == 0.0
        assert fact.basic_pooling_payment == 0.0
        assert fact.personal_total_pay == 0.0
        assert fact.person_type == ""
        assert fact.insurance_type == ""


# ══════════════════════════════════════════════════════════════════════════
# Tests: FactBuilder.build() with realistic data
# ══════════════════════════════════════════════════════════════════════════


class TestFactBuilderRealistic:
    """FactBuilder.build() with realistic settlement 1671213 data."""

    def test_pooling_self_pay_full(self, builder, realistic_ctx, four_item_evidence, realistic_segment_ratios):
        """build() with full realistic data — 统筹自付 target."""
        fact = builder.build(realistic_ctx, four_item_evidence, realistic_segment_ratios, "pooling_self_pay")

        # Identity
        assert fact.settlement_id == "1671213"
        assert fact.person_type == "退休人员"
        assert fact.insurance_type == "城镇职工基本医疗保险"
        assert fact.service_type == "普通住院"
        assert fact.hospital_level == "三级医院"

        # Target fee item
        assert fact.target_fee_item == "pooling_self_pay"
        assert fact.target_fee_label == "统筹自付"
        assert "按政策比例由个人承担" in fact.target_fee_definition
        assert fact.target_amount == 4962.67

        # Settlement amounts
        assert fact.deductible == 650.0
        assert fact.medical_insurance_inner_amount == 50000.0
        assert fact.basic_pooling_payment == 35000.0
        assert fact.basic_pooling_self_pay == 4962.67
        assert fact.large_amount_payment == 10000.0
        assert fact.large_amount_self_pay == 1500.0
        assert fact.personal_total_pay == 7112.67

        # Segment ratios (employee)
        assert len(fact.segment_ratios) == 3
        assert fact.segment_ratios[0]["personal_ratio"] == 0.15
        assert fact.segment_ratios[1]["personal_ratio"] == 0.10
        assert fact.segment_ratios[2]["personal_ratio"] == 0.05

        # Retiree adjustment
        assert fact.has_retiree is True
        assert fact.retiree_ratio == 60
        assert len(fact.retiree_adjusted_segments) == 3
        assert fact.retiree_adjusted_segments[0] == 0.09

        # Evidence
        assert fact.evidence_count == 4
        assert len(fact.policy_evidence) == 4
        # Evidence items are 1-indexed
        assert fact.policy_evidence[0]["index"] == 1
        assert fact.policy_evidence[3]["index"] == 4
        # Evidence excerpts are cleaned (no metadata suffixes)
        assert "退休人员" in fact.policy_evidence[3]["excerpt"]
        assert fact.evidence_completeness == "complete"

        # Warnings (none when has_complete=True)
        assert fact.warnings == []

    def test_deductible_target(self, builder, realistic_ctx, four_item_evidence, realistic_segment_ratios):
        """build() with deductible as target fee item."""
        fact = builder.build(realistic_ctx, four_item_evidence, realistic_segment_ratios, "deductible")

        assert fact.target_fee_item == "deductible"
        assert fact.target_fee_label == "起付线"
        assert "个人承担" in fact.target_fee_definition
        assert fact.target_amount == 650.0
        assert fact.deductible == 650.0

    def test_large_amount_self_pay_target(self, builder, realistic_ctx, four_item_evidence, realistic_segment_ratios):
        """build() with large_amount_self_pay as target fee item."""
        fact = builder.build(realistic_ctx, four_item_evidence, realistic_segment_ratios, "large_amount_self_pay")

        assert fact.target_fee_item == "large_amount_self_pay"
        assert fact.target_fee_label == "大额自付"
        assert fact.target_amount == 1500.0
        assert fact.large_amount_self_pay == 1500.0

    def test_pooling_payment_target(self, builder, realistic_ctx, four_item_evidence, realistic_segment_ratios):
        """build() with pooling_payment as target fee item."""
        fact = builder.build(realistic_ctx, four_item_evidence, realistic_segment_ratios, "pooling_payment")

        assert fact.target_fee_item == "pooling_payment"
        assert fact.target_fee_label == "统筹支付"
        assert fact.target_amount == 35000.0
        assert fact.basic_pooling_payment == 35000.0

    def test_personal_total_pay_target(self, builder, realistic_ctx, four_item_evidence, realistic_segment_ratios):
        """build() with personal_total_pay as target fee item."""
        fact = builder.build(realistic_ctx, four_item_evidence, realistic_segment_ratios, "personal_total_pay")

        assert fact.target_fee_item == "personal_total_pay"
        assert fact.target_fee_label == "个人总支付"
        assert fact.target_amount == 7112.67
        assert fact.personal_total_pay == 7112.67


# ══════════════════════════════════════════════════════════════════════════
# Tests: Evidence boundary conditions
# ══════════════════════════════════════════════════════════════════════════


class TestFactBuilderEvidenceBoundaries:
    """Evidence handling edge cases."""

    def test_four_item_evidence_complete(self, builder, realistic_ctx, realistic_segment_ratios):
        """Evidence with 4 items + has_complete=True → completeness='complete'."""
        evidence = [{"source_text": f"Rule {i}", "applied_reason": f"Reason {i}"} for i in range(4)]
        fact = builder.build(realistic_ctx, evidence, realistic_segment_ratios, "pooling_self_pay")

        assert fact.evidence_count == 4
        assert len(fact.policy_evidence) == 4
        assert fact.evidence_completeness == "complete"

    def test_evidence_partial_no_complete_flag(self, builder, realistic_ctx):
        """Evidence with items but no has_complete flag → completeness='partial'."""
        evidence = [{"source_text": "Partial rule", "applied_reason": "Partial reason"}]
        fact = builder.build(realistic_ctx, evidence, {}, "pooling_self_pay")

        assert fact.evidence_count == 1
        assert fact.evidence_completeness == "partial"

    def test_empty_evidence_no_complete(self, builder, realistic_ctx):
        """Empty evidence + no has_complete → completeness='none'."""
        fact = builder.build(realistic_ctx, [], {}, "pooling_self_pay")

        assert fact.evidence_count == 0
        assert fact.policy_evidence == []
        assert fact.evidence_completeness == "none"

    def test_evidence_source_text_cleaned(self, builder, realistic_ctx):
        """source_text metadata suffix {大额段} is stripped by _clean_excerpt."""
        evidence = [
            {
                "source_text": "三级医院住院费用分段：超过4万元的部分，"
                               "统筹基金支付 95%，职工个人支付 5%"
                               "\n{大额段}",
                "applied_reason": "适用高段比例。",
            }
        ]
        fact = builder.build(realistic_ctx, evidence, {}, "pooling_self_pay")

        assert fact.evidence_count == 1
        excerpt = fact.policy_evidence[0]["excerpt"]
        # The {大额段} metadata should be stripped
        assert "{大额段}" not in excerpt
        assert "三级医院" in excerpt
        assert "95%" in excerpt

    def test_fee_excludes_warnings(self, builder, realistic_ctx, realistic_segment_ratios):
        """fee_excludes parameter adds specific warnings."""
        fact = builder.build(
            realistic_ctx, [], realistic_segment_ratios, "pooling_self_pay",
            fee_excludes=["起付线", "大额自付"],
        )

        assert len(fact.warnings) == 2
        assert all("不包含" in w for w in fact.warnings)
        assert any("起付线" in w for w in fact.warnings)
        assert any("大额自付" in w for w in fact.warnings)
