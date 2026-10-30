"""四链路 84 项目标验收预期与当前展示模板的一致性（R7）。

- 预期表必须覆盖每条链路当前可见模板的全部展示字段（section != basic），
  既不能漏目标，也不能用响应临时增删目标；
- 每个 explainable 目标必须登记必要构成（否则配置本身报错）；
- 目标 ID 稳定（case + template.key / line 序号），中文标签相同也不能合并。
"""
from __future__ import annotations

import pytest

from src.config.settlement_templates import get_settlement_template
from src.tests.fixtures.four_chain_acceptance import ACCEPTANCE_EXPECTATIONS
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_acceptance_grading import (
    TargetRequirement)

CASE_TEMPLATE = {
    "resident-outpatient-0408": "resident_outpatient",
    "resident-special-688": "resident_special",
    "employee-outpatient-000008": "employee_outpatient",
    "employee-special-567": "employee_special",
}
#: 门诊两条链路的展示模板与配置一一对应，可在单元层直接比对；
#: 门特两条链路的运行时展示模板由套表变体在装配层裁剪（normal/special/pool 等别名收起），
#: 一致性在 `scripts/eval/four_chain_acceptance.py` 用真实面板模板比对（见该脚本）。
UNIT_TEMPLATE_CASES = ("resident-outpatient-0408", "employee-outpatient-000008")


@pytest.mark.parametrize("case", UNIT_TEMPLATE_CASES)
def test_expectations_cover_every_visible_template_field(case: str):
    template = get_settlement_template(CASE_TEMPLATE[case])
    visible = [f for f in template.fields if f.section != "basic"]
    expected_keys = [entry["key"] for entry in ACCEPTANCE_EXPECTATIONS[case]["fields"]]
    assert expected_keys == [f"{case}.{field.key}" for field in visible]


@pytest.mark.parametrize("case", sorted(CASE_TEMPLATE))
def test_every_target_has_stable_id_and_valid_requirement(case: str):
    entries = ACCEPTANCE_EXPECTATIONS[case]["fields"] + ACCEPTANCE_EXPECTATIONS[case]["lines"]
    keys = [entry["key"] for entry in entries]
    assert len(keys) == len(set(keys))
    for entry in entries:
        TargetRequirement.check(entry)


def test_case_totals_are_74_fields_and_10_lines():
    fields = sum(len(value["fields"]) for value in ACCEPTANCE_EXPECTATIONS.values())
    lines = sum(len(value["lines"]) for value in ACCEPTANCE_EXPECTATIONS.values())
    assert (fields, lines) == (74, 10)


def test_registry_marks_known_gaps_and_channels_independently():
    """三项 0 元缺口与支付渠道在预期表中是固定状态，不随响应变化。"""
    employee = ACCEPTANCE_EXPECTATIONS["employee-outpatient-000008"]["fields"]
    kinds = {entry["key"]: entry["kind"] for entry in employee}
    assert kinds["employee-outpatient-000008.military_pay"] == "missing"
    # 退役医疗费 0 元由原单标志解释，归为原单事实而非缺证
    assert kinds["employee-outpatient-000008.retire_officer_pay"] == "observed_only"
    assert kinds["employee-outpatient-000008.official_pay"] == "missing"
    assert kinds["employee-outpatient-000008.account_pay"] == "observed_only"
    resident = ACCEPTANCE_EXPECTATIONS["resident-outpatient-0408"]["fields"]
    assert {e["key"]: e["kind"] for e in resident}["resident-outpatient-0408.big_pay"] == "explainable"
