"""policy_rules_v2 维度值标准化测试（政策原文值 → 业务字典值）。

对齐 semantic_layer/seed.py 业务字典，让结算上下文（业务值）能精确命中政策规则。
不依赖 Milvus（纯函数）。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    normalize_hosp_lv,
    normalize_med_type,
)


# ── hosp_lv ──

def test_hosp_lv_standard_values_unchanged():
    """seed.py 标准 hosp_lv 值（三级/二级/一级）保持不变。"""
    assert normalize_hosp_lv("三级") == "三级"
    assert normalize_hosp_lv("二级") == "二级"
    assert normalize_hosp_lv("一级") == "一级"


def test_hosp_lv_community_and_undefined_mapped():
    """社区→一级，未定级→无等级（对齐 seed.py 标准 [三级/二级/一级/无等级]）。"""
    assert normalize_hosp_lv("社区") == "一级"
    assert normalize_hosp_lv("未定级") == "无等级"


def test_hosp_lv_hospital_suffix_is_removed():
    assert normalize_hosp_lv("三级医院") == "三级"
    assert normalize_hosp_lv("二级医院") == "二级"
    assert normalize_hosp_lv("一级医院") == "一级"


def test_hosp_lv_empty_passthrough():
    assert normalize_hosp_lv("") == ""


# ── med_type ──

def test_med_type_category_to_subcategory():
    """政策大类 → seed.py 业务细类。"""
    assert normalize_med_type("住院") == "住院-普通住院"
    assert normalize_med_type("门诊") == "门诊-普通门急诊"
    assert normalize_med_type("门特") == "门诊-一般门特"
    assert normalize_med_type("急诊") == "门诊-急诊留观"


def test_med_type_compound_takes_first_mappable():
    """复合值（含分隔符）取第一个可映射的大类。"""
    assert normalize_med_type("住院,门特") == "住院-普通住院"
    assert normalize_med_type("门诊,急诊,住院") == "门诊-普通门急诊"


def test_med_type_already_standard_unchanged():
    """已是标准细类的值不变（二次标准化幂等）。"""
    assert normalize_med_type("住院-普通住院") == "住院-普通住院"
    assert normalize_med_type("门诊-普通门急诊") == "门诊-普通门急诊"


def test_med_type_empty_passthrough():
    assert normalize_med_type("") == ""
