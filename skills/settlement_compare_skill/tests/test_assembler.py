"""assembler 单元测试：结算对比全流程（输入校验/diff/归因/渲染/可答性）。"""

from types import SimpleNamespace

import pytest

from skills.settlement_compare_skill.assembler import (
    CompareSkillResult,
    SettlementCompareAssembler,
    load,
)


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


@pytest.fixture()
def assembler():
    return SettlementCompareAssembler()


class TestLoad:
    def test_load_returns_assembler(self):
        assert isinstance(load(), SettlementCompareAssembler)


class TestInputValidation:
    def test_single_context_cannot_answer(self, assembler):
        result = assembler.execute([_ctx()])
        assert result.can_answer is False
        assert "至少需要两张" in result.answer

    def test_empty_contexts_cannot_answer(self, assembler):
        result = assembler.execute([])
        assert result.can_answer is False

    def test_over_limit_truncates_with_warning(self, assembler):
        contexts = [_ctx(settlement_id=f"S{i:03d}") for i in range(7)]
        result = assembler.execute(contexts)
        assert result.can_answer is True
        assert any("上限" in w for w in result.warnings)
        # 基准 + 前 4 张对比 = 5 张
        compared_ids = {
            item["settlement_id"]
            for item in result.diff_items
        } | {a["settlement_id"] for a in result.attributions}
        assert "S006" not in compared_ids


class TestCompareFlow:
    def test_identical_settlements_no_diff(self, assembler):
        result = assembler.execute([_ctx(), _ctx(settlement_id="S002")])
        assert result.can_answer is True
        assert result.partial_answer is False
        assert result.diff_items == []
        assert "未发现差异" in result.answer

    def test_cross_year_deductible_attributed(self, assembler):
        baseline = _ctx(deductible=325.0, settlement_date="2025-12-20", yearly_cycle_count=2)
        current = _ctx(settlement_id="S002", deductible=650.0, settlement_date="2026-01-05")
        result = assembler.execute([baseline, current])
        assert result.can_answer is True
        rule_ids = {a["rule_id"] for a in result.attributions}
        assert "deductible_cross_year_reset" in rule_ids
        assert "起付线" in result.answer
        assert "跨年" in result.answer or "重新累计" in result.answer

    def test_fallback_marks_partial(self, assembler):
        # large_amount_self_pay 仍无规则覆盖，走 fallback → partial
        baseline = _ctx(large_amount_self_pay=0.0)
        current = _ctx(settlement_id="S002", large_amount_self_pay=500.0)
        result = assembler.execute([baseline, current])
        assert result.partial_answer is True
        assert any(a["is_fallback"] for a in result.attributions)
        assert "暂无明确政策归因" in result.answer

    def test_three_settlements_two_compared_sections(self, assembler):
        baseline = _ctx()
        second = _ctx(settlement_id="S002", deductible=1300.0)
        third = _ctx(settlement_id="S003", person_type="在职人员")
        result = assembler.execute([baseline, second, third])
        assert "【结算单 S002】" in result.answer
        assert "【结算单 S003】" in result.answer
        compared_ids = {a["settlement_id"] for a in result.attributions}
        assert compared_ids == {"S002", "S003"}

    def test_target_fee_item_narrows_diff(self, assembler):
        baseline = _ctx(deductible=650.0, personal_total_pay=6000.0)
        current = _ctx(settlement_id="S002", deductible=1300.0, personal_total_pay=9000.0)
        result = assembler.execute([baseline, current], target_fee_item="deductible")
        assert {d["field"] for d in result.diff_items} == {"deductible"}
        assert result.target_field == "deductible"

    def test_unknown_fee_item_degrades_to_full_compare(self, assembler):
        baseline = _ctx()
        current = _ctx(settlement_id="S002", deductible=1300.0)
        result = assembler.execute([baseline, current], target_fee_item="out_of_scope")
        assert any("退化为全字段对比" in w for w in result.warnings)
        assert {d["field"] for d in result.diff_items} == {"deductible"}


class TestOutputShape:
    def test_result_fields_compatible_with_public_payload(self, assembler):
        baseline = _ctx(deductible=325.0, settlement_date="2025-12-20", yearly_cycle_count=2)
        current = _ctx(settlement_id="S002", deductible=650.0, settlement_date="2026-01-05")
        result = assembler.execute([baseline, current], policy_status="full_policy_matched")
        assert isinstance(result, CompareSkillResult)
        assert result.policy_status == "full_policy_matched"
        assert result.definition.get("name") == "结算对比"
        assert result.calculation_trace["baseline_settlement_id"] == "S001"
        assert result.diff_items and result.attributions

    def test_build_policy_queries_for_hit_topics(self, assembler):
        queries = assembler.build_policy_queries(["起付线", "医保目录", "未知主题"])
        names = [q.query_name for q in queries]
        assert "compare_deductible_standard" in names
        assert "compare_catalog_scope" in names
        # 起付线 1 + 医保目录 1 + 未知主题 0 = 2
        assert len(names) == 2
