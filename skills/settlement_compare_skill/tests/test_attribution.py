"""归因规则匹配单元测试：6 条规则命中/不命中边界 + 优先级 + 兜底。"""

from types import SimpleNamespace

import pytest

from skills.settlement_compare_skill.diff_engine import diff_contexts
from skills.settlement_compare_skill.strategies.compare.strategy import (
    Attribution,
    load_attribution_config,
    match_attribution,
)


@pytest.fixture(scope="module")
def config():
    return load_attribution_config()


def _ctx(**overrides) -> SimpleNamespace:
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


def _match(config, baseline, current, field):
    """对指定字段跑 diff + 归因匹配，返回 Attribution。"""
    diffs = diff_contexts(baseline, current, fields=[field])
    assert len(diffs) == 1, f"字段 {field} 应存在差异"
    attribution, warnings = match_attribution(diffs[0], baseline, current, "S002", config)
    return attribution, warnings


class TestCrossYearDeductible:
    def test_hit(self, config):
        baseline = _ctx(deductible=325.0, settlement_date="2025-12-20", yearly_cycle_count=2)
        current = _ctx(deductible=650.0, settlement_date="2026-01-05", yearly_cycle_count=1)
        attr, _ = _match(config, baseline, current, "deductible")
        assert attr.rule_id == "deductible_cross_year_reset"
        assert attr.policy_topic == "起付线"
        assert not attr.is_fallback

    def test_no_hit_same_year(self, config):
        baseline = _ctx(deductible=325.0, settlement_date="2025-03-01")
        current = _ctx(deductible=650.0, settlement_date="2025-08-01")
        attr, _ = _match(config, baseline, current, "deductible")
        assert attr.rule_id == "fallback"


class TestRepeatHospitalization:
    def test_hit(self, config):
        baseline = _ctx(deductible=650.0, cycle_no="1")
        current = _ctx(deductible=325.0, cycle_no="2")
        attr, _ = _match(config, baseline, current, "deductible")
        assert attr.rule_id == "deductible_repeat_hospitalization_reduced"

    def test_no_hit_same_cycle(self, config):
        # 起付线降低但住院次数未增加 → 不命中
        baseline = _ctx(deductible=650.0, cycle_no="1")
        current = _ctx(deductible=325.0, cycle_no="1")
        attr, _ = _match(config, baseline, current, "deductible")
        assert attr.rule_id == "fallback"


class TestPersonTypeChanged:
    def test_hit(self, config):
        attr, _ = _match(config, _ctx(person_type="在职人员"), _ctx(person_type="退休人员"), "person_type")
        assert attr.rule_id == "person_type_changed"


class TestHospitalLevelChanged:
    def test_hit(self, config):
        attr, _ = _match(config, _ctx(hospital_level="三级医院"), _ctx(hospital_level="二级医院"), "hospital_level")
        assert attr.rule_id == "hospital_level_changed"


class TestNewReimbursementSegment:
    def test_hit_over_threshold(self, config):
        baseline = _ctx(basic_pooling_self_pay=5000.0)
        current = _ctx(basic_pooling_self_pay=6100.0)  # +22%
        attr, _ = _match(config, baseline, current, "basic_pooling_self_pay")
        assert attr.rule_id == "new_reimbursement_segment"

    def test_no_hit_under_threshold(self, config):
        baseline = _ctx(basic_pooling_self_pay=5000.0)
        current = _ctx(basic_pooling_self_pay=5900.0)  # +18%
        attr, _ = _match(config, baseline, current, "basic_pooling_self_pay")
        assert attr.rule_id == "fallback"

    def test_no_hit_when_baseline_zero(self, config):
        baseline = _ctx(basic_pooling_self_pay=0.0)
        current = _ctx(basic_pooling_self_pay=5000.0)
        attr, _ = _match(config, baseline, current, "basic_pooling_self_pay")
        assert attr.rule_id == "fallback"


class TestOutOfScopeIncrease:
    def test_hit(self, config):
        baseline = _ctx(medical_insurance_inner_amount=20000.0, personal_total_pay=6000.0)
        current = _ctx(medical_insurance_inner_amount=15000.0, personal_total_pay=9000.0)  # 医保内 -25%
        attr, _ = _match(config, baseline, current, "personal_total_pay")
        assert attr.rule_id == "out_of_scope_increase"

    def test_no_hit_when_inner_amount_stable(self, config):
        baseline = _ctx(medical_insurance_inner_amount=20000.0, personal_total_pay=6000.0)
        current = _ctx(medical_insurance_inner_amount=20000.0, personal_total_pay=9000.0)
        attr, _ = _match(config, baseline, current, "personal_total_pay")
        assert attr.rule_id == "fallback"


class TestPriorityAndFallback:
    def test_priority_competition_picks_highest(self, config):
        # deductible 升高 + 跨年 + 基准当年已住院：只命中 cross_year（100）；
        # 构造同时满足 repeat_reduced 的场景不可能（一个要求 gt 一个 lt），
        # 改为验证排序逻辑：两条规则命中同一字段时取 priority 高者
        config2 = {
            "rules": [
                {"rule_id": "low", "name": "低优先级", "applies_to": ["deductible"],
                 "when": {"all": [{"field": "deductible", "op": "gt"}]},
                 "attribution": "低", "policy_topic": "起付线", "priority": 10},
                {"rule_id": "high", "name": "高优先级", "applies_to": ["deductible"],
                 "when": {"all": [{"field": "deductible", "op": "gt"}]},
                 "attribution": "高", "policy_topic": "起付线", "priority": 90},
            ],
            "fallback": {"name": "兜底", "attribution": "兜底说明", "uncertainty": True},
        }
        baseline = _ctx(deductible=650.0)
        current = _ctx(deductible=1300.0)
        diffs = diff_contexts(baseline, current, fields=["deductible"])
        attr, warnings = match_attribution(diffs[0], baseline, current, "S002", config2)
        assert attr.rule_id == "high"
        assert len(warnings) == 1
        assert "低优先级" in warnings[0]

    def test_fallback_declares_uncertainty_fields(self, config):
        # large_amount_self_pay 仍无任何规则覆盖，走 fallback
        baseline = _ctx(large_amount_self_pay=0.0)
        current = _ctx(large_amount_self_pay=500.0)
        attr, warnings = _match(config, baseline, current, "large_amount_self_pay")
        assert attr.is_fallback
        assert attr.rule_id == "fallback"
        assert warnings == []
        assert attr.settlement_id == "S002"
        assert attr.baseline_value == 0.0
        assert attr.current_value == 500.0

    def test_total_amount_matches_composite_rule_not_fallback(self, config):
        # total_amount 现在有合计规则覆盖，不再 fallback
        baseline = _ctx(total_amount=21000.0)
        current = _ctx(total_amount=30000.0)
        attr, _ = _match(config, baseline, current, "total_amount")
        assert attr.rule_id == "total_amount_composite_change"
        assert attr.policy_topic == ""  # 非政策字段，不挂 citation

    def test_inner_amount_matches_volume_rule(self, config):
        baseline = _ctx(medical_insurance_inner_amount=5241.60)
        current = _ctx(medical_insurance_inner_amount=6890.40)
        attr, _ = _match(config, baseline, current, "medical_insurance_inner_amount")
        assert attr.rule_id == "inner_amount_volume_change"
        assert attr.policy_topic == ""

    def test_personal_total_pay_volume_when_inner_rises(self, config):
        # 医保内费用上升时 personal_total_pay 走量变规则（out_of_scope 只在内费用下降时命中）
        baseline = _ctx(medical_insurance_inner_amount=5000.0, personal_total_pay=6000.0)
        current = _ctx(medical_insurance_inner_amount=6500.0, personal_total_pay=9000.0)
        attr, _ = _match(config, baseline, current, "personal_total_pay")
        assert attr.rule_id == "personal_total_pay_volume_change"
