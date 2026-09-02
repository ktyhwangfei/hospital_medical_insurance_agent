from decimal import Decimal
from pathlib import Path

import yaml

from skills.mzsettlement_verify_skill.models import OutpatientSettlementContext
from skills.mzsettlement_verify_skill.verifier import state_of, verify_settlement


def test_image_golden_case_checks_every_displayed_amount():
    case = yaml.safe_load(
        (Path(__file__).parent / "case_image_golden.yaml").read_text(encoding="utf-8")
    )

    result = verify_settlement(
        OutpatientSettlementContext(**case["amounts"]),
        scenario_id=case["scenario_id"],
        policy_evidence=case["policy_evidence"],
    )

    assert len(result.field_explanations) == 19
    assert {item.status for item in result.amount_checks} == {"passed"}
    assert next(
        item for item in result.amount_checks if item.name == "门诊大额基金支付比例"
    ).actual == Decimal("681.67")
    assert all(item.field_name != "统筹自付" for item in result.field_explanations)
    assert all(item.name != "统筹自付组成勾稽" for item in result.amount_checks)
    assert all(item.name != "个人自付一组成勾稽" for item in result.amount_checks)
    assert next(
        item for item in result.field_explanations if item.field_name == "现金支付"
    ).state == "reported_zero"
    assert any("单位补充医疗" in item for item in result.uncertainties)


def test_decompose_personal_payment_solves_channels_and_handles_zeros():
    """多渠道抵扣用连减号呈现；零值自付二不报「无法拆解」噪音。"""
    from skills.mzsettlement_verify_skill.verifier import decompose_personal_payment

    multi_channel = OutpatientSettlementContext(
        total_amount="2554.76", in_scope_amount="2554.76", out_of_scope_amount="0.00",
        self_pay_one="510.96", self_pay_two="0.00",
        personal_total_amount="510.96",
        large_fund_payment="1788.33", unit_supplement_payment="255.47",
    )
    lines, uncertainties = decompose_personal_payment(multi_channel)
    assert any(
        "个人自付一 510.96 元 = 医保范围内金额 2554.76 元"
        " - 门诊大额基金支付 1788.33 元 - 单位补充医疗支付 255.47 元" in line
        for line in lines
    ), lines
    assert any("个人自付二 0.00 元" in line for line in lines)
    assert not any("无法拆解" in line for line in lines)

    retired = OutpatientSettlementContext(
        total_amount="100.00", in_scope_amount="100.00", out_of_scope_amount="0.00",
        self_pay_one="0.00", self_pay_two="0.00",
        personal_total_amount="0.00", large_fund_payment="100.00",
    )
    lines, uncertainties = decompose_personal_payment(retired)
    assert not any("无法拆解" in line for line in lines), lines


def test_money_state_keeps_zero_missing_and_not_applicable_distinct():
    assert state_of("1.00") == "non_zero"
    assert state_of(0) == "reported_zero"
    assert state_of(None) == "missing"
    assert state_of(0, applicable=False) == "not_applicable"


def test_amount_tolerance_is_one_cent():
    passing = verify_settlement(OutpatientSettlementContext(
        total_amount="100.01", in_scope_amount="90.00", out_of_scope_amount="10.00",
    ))
    failing = verify_settlement(OutpatientSettlementContext(
        total_amount="100.02", in_scope_amount="90.00", out_of_scope_amount="10.00",
    ))

    assert passing.amount_checks[0].status == "passed"
    assert failing.amount_checks[0].status == "failed"


def test_policy_ratio_accepts_blank_and_percent_text():
    blank = verify_settlement(
        OutpatientSettlementContext(total_amount="100.00"),
        policy_evidence=[{"source_id": "POLICY-1", "payment_ratio": ""}],
    )
    percent = verify_settlement(
        OutpatientSettlementContext(
            in_scope_amount="100.00", deductible_amount="0.00",
            large_fund_payment="4.80",
        ),
        policy_evidence=[{
            "source_id": "POLICY-2", "payment_ratio": "4.8%",
            "calculation_base": "in_scope_minus_deductible",
        }],
    )

    assert blank.citations == ["POLICY-1"]
    assert percent.amount_checks[-1].status == "passed"


def test_each_field_explanation_has_its_own_traceable_citations():
    result = verify_settlement(
        OutpatientSettlementContext(
            total_amount="100.00",
            big_disease_payment=0,
            applicability={"big_disease_payment": False},
        ),
        policy_evidence=[{"source_id": "POLICY-1"}],
    )

    total = next(item for item in result.field_explanations if item.field_name == "费用总金额")
    special = next(item for item in result.field_explanations if item.field_name == "大病支付")

    assert total.citations == ["settlement-data"]
    assert special.citations == ["settlement-data", "POLICY-1"]


def test_missing_required_core_amount_makes_result_unavailable():
    result = verify_settlement(
        OutpatientSettlementContext(record_found=True, total_amount=None),
        policy_evidence=[{"source_id": "POLICY-1"}],
    )

    assert result.status == "unavailable"


def test_self_pay_two_is_decomposed_from_fee_items_when_details_are_available():
    result = verify_settlement(
        OutpatientSettlementContext(
            total_amount="100.00",
            personal_total_amount="25.00",
            self_pay_one="15.00",
            self_pay_two="10.00",
            fee_items=[
                {"ItemName": "乙类药品", "FeeItem_SelfPay2": "6.00"},
                {"ItemName": "诊疗项目", "FeeItem_SelfPay2": "4.00"},
            ],
        )
    )

    check = next(
        item for item in result.amount_checks if item.name == "个人自付二明细勾稽"
    )
    assert check.expected == Decimal("10.00")
    assert check.status == "passed"


def test_self_pay_one_keeps_reported_value_when_supplementary_payment_is_in_fund_total():
    result = verify_settlement(
        OutpatientSettlementContext(
            total_amount="2613.23",
            in_scope_amount="2554.76",
            out_of_scope_amount="58.47",
            fund_total_amount="2427.02",
            personal_total_amount="186.21",
            self_pay_one="510.96",
            self_pay_two="22.48",
            supplementary_insurance_payment="383.22",
            unit_supplement_payment="255.47",
        )
    )

    self_pay_one = next(
        item for item in result.field_explanations if item.field_name == "个人自付一"
    )
    assert self_pay_one.value == Decimal("510.96")
    assert all(item.name != "个人自付一组成勾稽" for item in result.amount_checks)
