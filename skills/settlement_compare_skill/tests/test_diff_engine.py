"""diff_engine 单元测试：确定性逐字段 diff。"""

from types import SimpleNamespace

import pytest

from skills.settlement_compare_skill.diff_engine import (
    CATEGORICAL_FIELDS,
    NUMERIC_FIELDS,
    FieldDiff,
    coerce_number,
    diff_contexts,
    get_field_value,
)


def _ctx(**overrides) -> SimpleNamespace:
    """构造全字段 SettlementContext 替身（默认无差异基线）。"""
    base = dict(
        settlement_id="S001",
        person_type="退休人员",
        insurance_type="城镇职工基本医疗保险",
        service_type="普通住院",
        hospital_level="三级医院",
        deductible=650.0,
        medical_insurance_inner_amount=20000.0,
        basic_pooling_payment=15000.0,
        basic_pooling_self_pay=4962.67,
        large_amount_payment=0.0,
        large_amount_self_pay=0.0,
        personal_total_pay=6000.0,
        total_amount=21000.0,
        settlement_date="2025-03-15",
        yearly_cycle_count=1,
        cycle_no="1",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestGetFieldValue:
    def test_settlement_year_derived_from_date(self):
        ctx = _ctx(settlement_date="2026-01-20")
        assert get_field_value(ctx, "settlement_year") == "2026"

    def test_settlement_year_empty_when_date_missing(self):
        ctx = _ctx(settlement_date="")
        assert get_field_value(ctx, "settlement_year") == ""

    def test_normal_field_passthrough(self):
        ctx = _ctx(deductible=800.0)
        assert get_field_value(ctx, "deductible") == 800.0


class TestCoerceNumber:
    def test_numeric_string(self):
        assert coerce_number("2") == 2.0

    def test_non_numeric_string(self):
        assert coerce_number("退休人员") is None

    def test_bool_excluded(self):
        assert coerce_number(True) is None

    def test_none(self):
        assert coerce_number(None) is None


class TestDiffContexts:
    def test_identical_contexts_produce_no_diff(self):
        assert diff_contexts(_ctx(), _ctx()) == []

    def test_numeric_diff_has_delta_and_ratio(self):
        baseline = _ctx(deductible=650.0)
        current = _ctx(deductible=1300.0)
        diffs = diff_contexts(baseline, current)
        assert len(diffs) == 1
        d = diffs[0]
        assert d.field == "deductible"
        assert d.label == "起付线"
        assert d.delta == pytest.approx(650.0)
        assert d.delta_ratio == pytest.approx(2.0)

    def test_delta_ratio_none_when_baseline_zero(self):
        baseline = _ctx(large_amount_self_pay=0.0)
        current = _ctx(large_amount_self_pay=500.0)
        (d,) = diff_contexts(baseline, current)
        assert d.delta == pytest.approx(500.0)
        assert d.delta_ratio is None

    def test_categorical_diff_has_no_delta(self):
        baseline = _ctx(person_type="在职人员")
        current = _ctx(person_type="退休人员")
        (d,) = diff_contexts(baseline, current)
        assert d.field == "person_type"
        assert d.delta is None
        assert d.delta_ratio is None
        assert d.baseline_value == "在职人员"
        assert d.current_value == "退休人员"

    def test_numeric_string_fields_compared_as_numbers(self):
        # cycle_no 在 SettlementContext 中是 str，显式指定对比时应按数值比较
        baseline = _ctx(cycle_no="1")
        current = _ctx(cycle_no="2")
        (d,) = diff_contexts(baseline, current, fields=["cycle_no"])
        assert d.field == "cycle_no"
        assert d.delta == pytest.approx(1.0)

    def test_condition_only_fields_not_in_default_diff(self):
        # settlement_year / cycle_no / yearly_cycle_count 是归因规则的条件输入，
        # 不进入默认差异集（否则跨年对比永远触发 fallback）
        baseline = _ctx(settlement_date="2025-12-20", cycle_no="1", yearly_cycle_count=1)
        current = _ctx(settlement_date="2026-01-05", cycle_no="2", yearly_cycle_count=2)
        assert diff_contexts(baseline, current) == []

    def test_fields_subset_narrows_comparison(self):
        baseline = _ctx(deductible=650.0, person_type="在职人员")
        current = _ctx(deductible=1300.0, person_type="退休人员")
        diffs = diff_contexts(baseline, current, fields=["deductible"])
        assert [d.field for d in diffs] == ["deductible"]

    def test_multiple_diffs_keep_declared_order(self):
        baseline = _ctx()
        current = _ctx(deductible=1300.0, personal_total_pay=8000.0)
        diffs = diff_contexts(baseline, current)
        fields = [d.field for d in diffs]
        order = list(NUMERIC_FIELDS) + list(CATEGORICAL_FIELDS)
        assert fields == sorted(fields, key=order.index)

    def test_all_default_fields_covered(self):
        # 默认字段集 = 数值 + 类别，全部字段都被纳入对比
        baseline = _ctx()
        current = _ctx(
            deductible=1.0, medical_insurance_inner_amount=1.0,
            basic_pooling_payment=1.0, basic_pooling_self_pay=1.0,
            large_amount_payment=1.0, large_amount_self_pay=1.0,
            personal_total_pay=1.0, total_amount=1.0,
            person_type="X", insurance_type="X", service_type="X",
            hospital_level="X",
        )
        diffs = diff_contexts(baseline, current)
        assert {d.field for d in diffs} == set(NUMERIC_FIELDS) | set(CATEGORICAL_FIELDS)
