"""
值域标准化映射表
将中文值映射到标准化的英文键

使用场景：
- 规则结构化时，将提取的中文值转换为英文键
- 规则查询时，支持中英文双向查询
"""

from typing import Dict, List, Optional


# ============================================================
# 参保体系
# ============================================================
INSURANCE_SYSTEM_MAP: Dict[str, str] = {
    # 标准全称
    "城镇职工基本医疗保险": "urban_employee",
    "城乡居民基本医疗保险": "urban_rural_resident",
    "职工基本医疗保险": "urban_employee",
    "城乡居民医保": "urban_rural_resident",
    "职工医保": "urban_employee",
    "居民医保": "urban_rural_resident",
    # 补充保险
    "城乡居民大病保险": "serious_disease",
    "大病保险": "serious_disease",
    "生育保险": "maternity",
    "企业补充医疗保险": "enterprise_supplement",
    # 特殊保障
    "超转人员医疗保障": "retired_military",
    "离休人员医疗保障": "retired_cadre",
    "公费医疗": "free_medical",
}

# ============================================================
# 人群标签
# ============================================================
POPULATION_TAGS_MAP: Dict[str, str] = {
    # 职工医保人群
    "退休人员": "retired",
    "退休职工": "retired",
    "在职人员": "working",
    "在职职工": "working",
    "灵活就业人员": "flexible_employment",
    # 居民医保人群
    "城乡老年人": "urban_rural_elderly",
    "老年人": "urban_rural_elderly",
    "劳动年龄内居民": "working_age_resident",
    "学生儿童": "student_child",
    "学生": "student",
    "儿童": "child",
    "少年儿童": "student_child",
    # 困难人群
    "特困供养人员": "extreme_poverty",
    "特困人员": "extreme_poverty",
    "最低生活保障人员": "minimum_living",
    "低保人员": "minimum_living",
    "低收入救助人员": "low_income",
    "低收入农户": "low_income",
    "残疾人员": "disabled",
    "残疾人": "disabled",
    # 特殊人群
    "优抚对象": "veteran",
    "建国前老工人": "pre_1949_worker",
}

# ============================================================
# 医疗机构等级
# ============================================================
HOSPITAL_LEVEL_MAP: Dict[str, str] = {
    # 三级
    "三级定点医疗机构": "tertiary",
    "三级医疗机构": "tertiary",
    "三级医院": "tertiary",
    "三级": "tertiary",
    # 二级
    "二级定点医疗机构": "secondary",
    "二级医疗机构": "secondary",
    "二级医院": "secondary",
    "二级": "secondary",
    "二级及以上": "secondary_and_above",
    "二级及以上定点医疗机构": "secondary_and_above",
    "二级及以上医疗机构": "secondary_and_above",
    # 一级及以下
    "一级及以下定点医疗机构": "primary",
    "一级及以下医疗机构": "primary",
    "一级医院": "primary",
    "一级": "primary",
    # 基层
    "社区卫生服务中心": "community_center",
    "社区卫生服务站": "community_station",
    "基层医疗机构": "primary",
    # 统称
    "定点医疗机构": "designated_hospital",
    "定点医院": "designated_hospital",
    "定点零售药店": "designated_pharmacy",
    "定点药店": "designated_pharmacy",
}

# ============================================================
# 医疗类别
# ============================================================
MEDICAL_CATEGORY_MAP: Dict[str, str] = {
    # 住院
    "住院": "inpatient",
    "普通住院": "inpatient",
    "住院治疗": "inpatient",
    # 门诊
    "门诊": "outpatient",
    "门诊治疗": "outpatient",
    "门诊特殊病": "special_outpatient",
    "门特": "special_outpatient",
    "门诊慢性病": "chronic_outpatient",
    "门慢": "chronic_outpatient",
    # 急诊
    "急诊": "emergency",
    "急诊治疗": "emergency",
    "急诊抢救": "emergency_rescue",
    "急诊留观": "emergency_observation",
    "留观": "emergency_observation",
    # 特殊医疗
    "家庭病床": "home_bed",
    "家床": "home_bed",
    "日间手术": "day_surgery",
    "日间病房": "day_surgery",
    # 门急诊合并
    "门（急）诊": "outpatient_emergency",
    "门急诊": "outpatient_emergency",
}

# ============================================================
# 结算方式
# ============================================================
SETTLEMENT_METHOD_MAP: Dict[str, str] = {
    "按项目付费": "ffs",
    "按病种付费": "drg",
    "按床日付费": "per_diem",
    "床日定额": "per_diem",
    "按人头付费": "capitation",
    "按服务单元付费": "service_unit",
    "DRG付费": "drg",
    "DRG": "drg",
    "DIP付费": "dip",
    "DIP": "dip",
    "单病种付费": "single_disease",
    "单病种": "single_disease",
    "总额预付": "global_budget",
    "总额控制": "global_budget",
    "总额预算": "global_budget",
    "定额付费": "fixed_amount",
    "限额付费": "capped_amount",
}

# ============================================================
# 目录属性标签
# ============================================================
CATALOG_TAGS_MAP: Dict[str, str] = {
    # 药品目录
    "甲类药品": "class_a_drug",
    "甲类药": "class_a_drug",
    "甲类": "class_a_drug",
    "乙类药品": "class_b_drug",
    "乙类药": "class_b_drug",
    "乙类": "class_b_drug",
    "丙类药品": "class_c_drug",
    "丙类药": "class_c_drug",
    "丙类": "class_c_drug",
    # 特殊药品
    "国家谈判药品": "national_negotiated",
    "国谈药品": "national_negotiated",
    "国谈药": "national_negotiated",
    "集中带量采购药品": "vbp",
    "集采药品": "vbp",
    "集中带量采购": "vbp",
    "集采": "vbp",
    # 目录范围
    "医保目录内": "in_catalog",
    "目录内": "in_catalog",
    "医保目录外": "out_catalog",
    "目录外": "out_catalog",
    # 目录类型
    "医保药品目录": "drug_catalog",
    "医保目录": "drug_catalog",
    "药品目录": "drug_catalog",
    "诊疗项目目录": "service_catalog",
    "诊疗目录": "service_catalog",
    "医疗服务设施目录": "facility_catalog",
    "设施目录": "facility_catalog",
    # 用药范围
    "门诊特殊病用药": "special_outpatient_drug",
    "门特用药": "special_outpatient_drug",
    "门诊慢性病用药": "chronic_outpatient_drug",
    "门慢用药": "chronic_outpatient_drug",
}

# ============================================================
# 费用范围
# ============================================================
COST_SCOPE_MAP: Dict[str, str] = {
    "医保范围内": "in_scope",
    "医保内": "in_scope",
    "目录内费用": "in_scope",
    "医保范围外": "out_scope",
    "医保外": "out_scope",
    "目录外费用": "out_scope",
    "个人自付": "self_payment",
    "自付": "self_payment",
    "个人自费": "self_pay",
    "自费": "self_pay",
}

# ============================================================
# 费用标准
# ============================================================
COST_STANDARD_MAP: Dict[str, str] = {
    "起付标准": "deductible",
    "起付线": "deductible",
    "起付金额": "deductible",
    "最高支付限额": "annual_cap",
    "封顶线": "annual_cap",
    "累计最高支付": "annual_cap",
    "最高支付数额": "annual_cap",
}

# ============================================================
# 住院次数
# ============================================================
ADMISSION_ORDER_MAP: Dict[str, str] = {
    "首次住院": 1,
    "第一次住院": 1,
    "第二次及以后住院": 2,
    "第二次住院": 2,
    "再次住院": 2,
}

# ============================================================
# 时间周期
# ============================================================
TIME_PERIOD_MAP: Dict[str, str] = {
    "医疗保险年度": "annual",
    "医保年度": "annual",
    "年度": "annual",
    "结算周期": "settlement_cycle",
    "治疗周期": "treatment_cycle",
}

# ============================================================
# 规则类型
# ============================================================
RULE_TYPE_MAP: Dict[str, str] = {
    "起付线规则": "deductible_rule",
    "报销比例规则": "ratio_rule",
    "封顶线规则": "cap_rule",
    "周期规则": "period_rule",
    "适用对象规则": "eligibility_rule",
    "例外规则": "exception_rule",
    "经办流程规则": "process_rule",
}

# ============================================================
# 所有映射表
# ============================================================
ALL_VALUE_MAPS = {
    "insurance_system": INSURANCE_SYSTEM_MAP,
    "population_tags": POPULATION_TAGS_MAP,
    "hospital_level": HOSPITAL_LEVEL_MAP,
    "medical_category": MEDICAL_CATEGORY_MAP,
    "settlement_method": SETTLEMENT_METHOD_MAP,
    "catalog_tags": CATALOG_TAGS_MAP,
    "cost_scope": COST_SCOPE_MAP,
    "cost_standard": COST_STANDARD_MAP,
    "admission_order": ADMISSION_ORDER_MAP,
    "time_period": TIME_PERIOD_MAP,
    "rule_type": RULE_TYPE_MAP,
}


def normalize_value(field_name: str, chinese_value: str) -> Optional[str]:
    """
    将中文值转换为标准化英文键
    
    Args:
        field_name: 字段名
        chinese_value: 中文值
        
    Returns:
        标准化英文键，如果找不到映射则返回 None
    """
    value_map = ALL_VALUE_MAPS.get(field_name, {})
    return value_map.get(chinese_value)


def normalize_values(field_name: str, chinese_values: List[str]) -> List[str]:
    """
    批量将中文值转换为标准化英文键
    
    Args:
        field_name: 字段名
        chinese_values: 中文值列表
        
    Returns:
        标准化英文键列表
    """
    return [normalize_value(field_name, v) for v in chinese_values if normalize_value(field_name, v)]


def get_chinese_name(field_name: str, english_key: str) -> Optional[str]:
    """
    将英文键转换回中文值（用于显示）
    
    Args:
        field_name: 字段名
        english_key: 英文键
        
    Returns:
        中文值，如果找不到映射则返回 None
    """
    value_map = ALL_VALUE_MAPS.get(field_name, {})
    for chinese, english in value_map.items():
        if english == english_key:
            return chinese
    return None


def get_all_keys(field_name: str) -> List[str]:
    """
    获取字段的所有标准化英文键（去重）
    
    Args:
        field_name: 字段名
        
    Returns:
        英文键列表
    """
    value_map = ALL_VALUE_MAPS.get(field_name, {})
    return list(set(value_map.values()))
