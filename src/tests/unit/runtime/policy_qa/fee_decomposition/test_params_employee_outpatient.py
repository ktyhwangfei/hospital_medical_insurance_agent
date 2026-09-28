"""参数模块单元测试：版本选择、门控（不静默生效）、合计展示隔离、CSV 一致性。

参数表 CSV 是 spec：断言 params 模块每条参数的 rule_id 都存在于 CSV，且双向一致。
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    InstitutionKind,
    PersonKind,
)
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient import (
    PARAMS,
    display_only_params,
    get_param,
    select_big_pay_rate_param,
    select_cap_param,
    select_check_fee_param,
    select_deductible_param,
    select_excess_segment_param,
    select_material_rule,
    select_param,
    select_retire_supplement_param,
    select_rounding_param,
)

_CSV_PATH = (
    Path(__file__).resolve().parents[6]
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-09-28-issue78-城镇职工门诊待遇参数.csv"
)


def _csv_rule_ids() -> set[str]:
    with open(_CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return {row["规则ID"] for row in csv.DictReader(f)}


def test_params_rule_ids_match_csv_bidirectionally():
    csv_ids = _csv_rule_ids()
    param_ids = {p.rule_id for p in PARAMS}
    assert param_ids == csv_ids  # 参数模块每条 rule_id 都在 CSV，且无遗漏
    assert len(PARAMS) == len(csv_ids)


def test_params_amounts_are_decimal():
    for p in PARAMS:
        if p.value is not None:
            assert isinstance(p.value, Decimal), p.rule_id


def test_deductible_version_by_settlement_date():
    sel = select_deductible_param(PersonKind.EMPLOYED, date(2024, 5, 1))
    assert sel.outcome == BranchOutcome.TRUE
    assert sel.param.rule_id == "EOP-DED-002" and sel.param.value == Decimal("1800")
    sel_hist = select_deductible_param(PersonKind.EMPLOYED, date(2005, 5, 1))
    assert sel_hist.param.rule_id == "EOP-DED-001" and sel_hist.param.value == Decimal("2000")
    sel_ret = select_deductible_param(PersonKind.RETIRED, date(2024, 5, 1))
    assert sel_ret.param.rule_id == "EOP-DED-004" and sel_ret.param.value == Decimal("1300")


def test_deductible_unknown_person_kind_not_defaulted():
    sel = select_deductible_param(PersonKind.UNKNOWN, date(2024, 5, 1))
    assert sel.outcome == BranchOutcome.UNKNOWN
    assert sel.reason_code == "PERSON_KIND_UNKNOWN"


def test_big_pay_rate_selection_current():
    # 在职社区 90% / 在职其他 70%（官方已核实）
    assert select_big_pay_rate_param(
        PersonKind.EMPLOYED, None, InstitutionKind.COMMUNITY, date(2024, 1, 1)
    ).param.rule_id == "EOP-RATE-105"
    assert select_big_pay_rate_param(
        PersonKind.EMPLOYED, None, InstitutionKind.OTHER, date(2024, 1, 1)
    ).param.rule_id == "EOP-RATE-106"
    # 退休 <70 社区 80% / 其他 70%；≥70 单一档 80%（不区分机构）
    assert select_big_pay_rate_param(
        PersonKind.RETIRED, "lt70", InstitutionKind.COMMUNITY, date(2024, 1, 1)
    ).param.rule_id == "EOP-RATE-111"
    assert select_big_pay_rate_param(
        PersonKind.RETIRED, "lt70", InstitutionKind.OTHER, date(2024, 1, 1)
    ).param.rule_id == "EOP-RATE-112"
    sel = select_big_pay_rate_param(
        PersonKind.RETIRED, "ge70", InstitutionKind.UNKNOWN, date(2024, 1, 1)
    )
    assert sel.outcome == BranchOutcome.TRUE and sel.param.rule_id == "EOP-RATE-110"


def test_big_pay_rate_historical_versions():
    # 2005 年在职其他 50%（EOP-RATE-102）
    sel = select_big_pay_rate_param(
        PersonKind.EMPLOYED, None, InstitutionKind.OTHER, date(2005, 6, 1)
    )
    assert sel.param.rule_id == "EOP-RATE-102" and sel.param.ratio == Decimal("0.50")


def test_employed_other_hospital_50pct_extends_to_2010_04_30():
    # 2007/2008 两次调整只动社区档；在职其他医院 50% 应一直适用到 2010-04-30（EOP-RATE-102）
    sel = select_big_pay_rate_param(
        PersonKind.EMPLOYED, None, InstitutionKind.OTHER, date(2010, 3, 15)
    )
    assert sel.outcome == BranchOutcome.TRUE
    assert sel.param.rule_id == "EOP-RATE-102" and sel.param.ratio == Decimal("0.50")
    # 2010-05-01 起切换为 70% 档
    sel_new = select_big_pay_rate_param(
        PersonKind.EMPLOYED, None, InstitutionKind.OTHER, date(2010, 5, 1)
    )
    assert sel_new.param.rule_id == "EOP-RATE-106" and sel_new.param.ratio == Decimal("0.70")


def test_retired_lt70_rate_2004_2010_applies_to_all_institutions():
    # 退休社区/其他拆分从 2010-05-01 才开始；2004-01-01~2010-04-30 的 70% 档不区分机构
    for inst in (InstitutionKind.COMMUNITY, InstitutionKind.OTHER):
        sel = select_big_pay_rate_param(PersonKind.RETIRED, "lt70", inst, date(2005, 6, 1))
        assert sel.outcome == BranchOutcome.TRUE, sel.reason_code
        assert sel.param.rule_id == "EOP-RATE-109" and sel.param.ratio == Decimal("0.70")
    # 窗口内不得与现行其他档（EOP-RATE-112）双命中歧义
    sel_boundary = select_big_pay_rate_param(
        PersonKind.RETIRED, "lt70", InstitutionKind.OTHER, date(2010, 4, 30)
    )
    assert sel_boundary.param.rule_id == "EOP-RATE-109"


def test_retired_lt70_other_hospital_rate_current_from_2010_05_01():
    sel = select_big_pay_rate_param(
        PersonKind.RETIRED, "lt70", InstitutionKind.OTHER, date(2010, 5, 1)
    )
    assert sel.param.rule_id == "EOP-RATE-112" and sel.param.ratio == Decimal("0.70")


def test_display_only_rates_never_selected_for_calculation():
    # 合计展示层次（90%/85%/80%）绝不进入计算：退休<70社区 基础档必须是 80% 的 EOP-RATE-111
    sel = select_big_pay_rate_param(
        PersonKind.RETIRED, "lt70", InstitutionKind.COMMUNITY, date(2024, 1, 1)
    )
    assert sel.param.rule_id == "EOP-RATE-111"
    assert sel.param.payment_level == "基础支付"
    assert {p.rule_id for p in display_only_params()} == {
        "EOP-RATE-201", "EOP-RATE-202", "EOP-RATE-203", "EOP-RATE-303",
    }
    for p in display_only_params():
        assert p.payment_level == "合计展示"
    # 超 2 万段基础支付是 60%（EOP-RATE-301/302），不是合计展示 80%（EOP-RATE-303）
    excess = select_excess_segment_param(PersonKind.RETIRED, date(2024, 1, 1))
    assert excess.param.rule_id == "EOP-RATE-302" and excess.param.ratio == Decimal("0.60")


def test_pending_confirmation_param_not_silently_applied():
    # EOP-RND-001 取整规则：待确认 → unknown
    sel = select_param((get_param("EOP-RND-001"),), date(2024, 1, 1))
    assert sel.outcome == BranchOutcome.UNKNOWN
    assert sel.reason_code == "PARAM_CONFIRMATION_PENDING"
    assert select_rounding_param().outcome == BranchOutcome.UNKNOWN


def test_unclear_effective_date_param_not_silently_applied():
    # EOP-CAT-008（检查费 200 元/8%）：文档明确-待官方核证 且 生效日期未明确 → unknown
    sel = select_check_fee_param(date(2024, 1, 1))
    assert sel.outcome == BranchOutcome.UNKNOWN
    assert sel.reason_code == "PARAM_EFFECTIVE_DATE_UNCLEAR"
    # EOP-NCP-002（未通过一致性评价分支）：同样门控
    sel2 = select_param((get_param("EOP-NCP-002"),), date(2024, 1, 1))
    assert sel2.outcome == BranchOutcome.UNKNOWN


def test_expiry_unknown_param_not_silently_applied():
    # EOP-YEAR-001 截止日期未知（不得默认长期有效）→ unknown
    sel = select_param((get_param("EOP-YEAR-001"),), date(2024, 1, 1))
    assert sel.outcome == BranchOutcome.UNKNOWN


def test_material_rule_version_by_fee_date():
    # 2008-06-30 边界：仍适用 MAT-001（500 元/50%）；2008-07-01 起 MAT-002（70%）
    assert select_material_rule(date(2008, 6, 30)).param.rule_id == "EOP-MAT-001"
    assert select_material_rule(date(2008, 7, 1)).param.rule_id == "EOP-MAT-002"
    assert select_material_rule(date(2022, 12, 31)).param.rule_id == "EOP-MAT-002"
    # 2023-01-01 起 1000 元/80% 档
    assert select_material_rule(date(2023, 1, 1)).param.rule_id == "EOP-MAT-004"


def test_cap_param_only_before_2023():
    assert select_cap_param(date(2022, 12, 31)).param.rule_id == "EOP-CAP-001"
    assert select_cap_param(date(2023, 1, 1)).outcome == BranchOutcome.UNKNOWN


def test_retire_supplement_param_by_category():
    normal = select_retire_supplement_param("normal", date(2024, 1, 1))
    assert normal.param.rule_id == "EOP-RSUP-001" and normal.param.ratio == Decimal("0.50")
    prepaid = select_retire_supplement_param("prepaid", date(2024, 1, 1))
    assert prepaid.param.rule_id == "EOP-RSUP-002" and prepaid.param.ratio == Decimal("0.60")
    unknown = select_retire_supplement_param("", date(2024, 1, 1))
    assert unknown.outcome == BranchOutcome.UNKNOWN
