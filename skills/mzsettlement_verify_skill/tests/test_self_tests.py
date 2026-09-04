from decimal import Decimal

from skills.mzsettlement_verify_skill.self_tests import (
    build_eval_tasks,
    load_self_test_cases,
    run_self_tests,
)


def test_fixed_cases_cover_every_person_type_and_keep_target_settlement_value():
    cases = load_self_test_cases()

    assert len({case.context.person_type for case in cases}) == 28
    target = next(
        case for case in cases if case.settlement_id == "011100030X260417004975"
    )
    assert target.expected_self_pay_one == Decimal("510.96")
    assert target.context.supplementary_insurance_payment == Decimal("383.22")


def test_every_enabled_fixed_case_preserves_reported_self_pay_one():
    result = run_self_tests()

    assert result.total == 31
    assert result.failed == 0
    assert result.passed == 31


def test_fixed_cases_convert_to_generic_eval_tasks():
    tasks = build_eval_tasks("EVS_mz", created_by="quality-user")

    assert len(tasks) == 31
    target = next(
        task
        for task in tasks
        if task.input.settlement_id == "011100030X260417004975"
    )
    self_pay_one = next(
        assertion
        for assertion in target.assertions
        if assertion.output_adapter == "self_pay_one"
    )
    assert self_pay_one.expected.expected_value == 510.96
    assert target.target_skill_id == "mzsettlement_verify_skill"
