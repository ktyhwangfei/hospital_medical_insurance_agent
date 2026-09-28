"""值域配置加载器单元测试（Issue #78）。

覆盖：关键域存在、代码→名称解析、停用标记、派生分组 candidate 状态、
未覆盖代码如实记录、非 str 键归一。
"""
from __future__ import annotations

from src.adapters.data_supply.value_domains import load_value_domains


def test_key_domains_present() -> None:
    vd = load_value_domains()
    for name in ("item_type", "fee_category", "service_item_level", "drug_class",
                 "person_type", "cure_type", "hospital_level", "hospital_type",
                 "reversal_flag", "insurance_type_hospital"):
        assert name in vd.domains, name
        assert vd.domains[name]["values"], name


def test_item_type_names() -> None:
    """k10：0=药品 1=诊疗项目 2=服务设施 3=耗材——解锁非药品目录分解的关键值域。"""
    vd = load_value_domains()
    assert vd.name_of("item_type", "0") == "药品"
    assert vd.name_of("item_type", "1") == "诊疗项目"
    assert vd.name_of("item_type", "2") == "服务设施"
    assert vd.name_of("item_type", "3") == "耗材"


def test_service_item_level_names() -> None:
    vd = load_value_domains()
    assert vd.name_of("service_item_level", "1") == "无自付"
    assert vd.name_of("service_item_level", "2") == "有自付"
    assert vd.name_of("service_item_level", "3") == "全自付"


def test_unknown_code_returns_none_not_guess() -> None:
    vd = load_value_domains()
    assert vd.name_of("item_type", "9") is None
    assert vd.name_of("no_such_domain", "0") is None
    assert vd.name_of("cure_type", "17") is None  # 生产存在但字典未覆盖


def test_numeric_looking_keys_normalized_to_str() -> None:
    """YAML 键如 0508 可能被解析为数字样式，加载后统一按 str 命中。"""
    vd = load_value_domains()
    assert vd.name_of("fee_category", "0508") == "等级医院住院床位费加收"
    assert vd.name_of("fee_category", "0510") == "三人间床位费"


def test_disabled_codes_marked() -> None:
    vd = load_value_domains()
    assert vd.is_disabled("person_type", "13")  # 在职二等乙级伤残军人 sybz=0
    assert not vd.is_disabled("person_type", "11")
    assert vd.is_disabled("cure_type", "11")  # 字典停用但生产在用，如实保留标记


def test_derived_groups_are_candidate() -> None:
    """派生分组一律 candidate：签核前不得静默生效（加载器如实暴露状态）。"""
    vd = load_value_domains()
    for name in ("person_employment_group", "item_type_to_catalog_kind",
                 "community_institution_rule", "fee_category_self_pay_group"):
        assert vd.derived_status(name) == "candidate", name
    assert vd.derived_values("item_type_to_catalog_kind") == {
        "0": "drug", "1": "service", "2": "service", "3": "material"}
    assert vd.derived_values("person_employment_group")["11"] == "在职"
    assert vd.derived_values("person_employment_group")["21"] == "退休"


def test_unresolved_codes_recorded() -> None:
    vd = load_value_domains()
    assert vd.unresolved_codes("cure_type") == ("17", "18", "19")
    assert "0" in vd.unresolved_codes("service_item_level")
