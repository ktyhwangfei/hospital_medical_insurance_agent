"""
值域定义
定义所有需要从政策原文中提取的值域规则

设计原则：
- standard_name: 政策原文中的标准名称（通常是全称）
- aliases: 同义词/简称列表，匹配时会合并到标准名称
- 匹配优先级：长模式优先匹配，避免误匹配
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ValueDefinition:
    """值域定义"""
    standard_name: str  # 标准名称（政策原文中的正式表述）
    abbreviation: str  # 推荐简称
    aliases: List[str]  # 同义词/变体列表（用于匹配）
    category: str  # 分类
    description: str = ""  # 描述


@dataclass
class DomainConfig:
    """值域配置"""
    field_name: str  # 字段名
    field_name_cn: str  # 中文字段名
    description: str  # 描述
    values: List[ValueDefinition]  # 值域定义列表


def _build_domain(
    field_name: str,
    field_name_cn: str,
    description: str,
    values: List[dict]
) -> DomainConfig:
    """构建值域配置"""
    return DomainConfig(
        field_name=field_name,
        field_name_cn=field_name_cn,
        description=description,
        values=[
            ValueDefinition(
                standard_name=v["standard"],
                abbreviation=v.get("abbr", v["standard"]),
                aliases=v.get("aliases", [v["standard"]]),
                category=v.get("category", ""),
                description=v.get("desc", "")
            )
            for v in values
        ]
    )


# ============================================================
# 参保体系
# ============================================================
INSURANCE_SYSTEM = _build_domain(
    field_name="insurance_system",
    field_name_cn="参保体系",
    description="医疗保险的类型/体系",
    values=[
        {
            "standard": "城镇职工基本医疗保险",
            "abbr": "职工医保",
            "aliases": [
                "城镇职工基本医疗保险",
                "职工基本医疗保险",
                "职工医保",
                "城镇职工医保",
            ],
            "category": "基本医疗保险",
            "desc": "覆盖城镇用人单位职工和灵活就业人员"
        },
        {
            "standard": "城乡居民基本医疗保险",
            "abbr": "居民医保",
            "aliases": [
                "城乡居民基本医疗保险",
                "城乡居民医保",
                "居民医保",
                "居民基本医疗保险",
            ],
            "category": "基本医疗保险",
            "desc": "覆盖未就业居民、学生儿童、老年人等"
        },
        {
            "standard": "生育保险",
            "abbr": "生育险",
            "aliases": ["生育保险", "生育险"],
            "category": "专项保险",
            "desc": "覆盖生育医疗费用和生育津贴"
        },
        {
            "standard": "城乡居民大病保险",
            "abbr": "大病保险",
            "aliases": [
                "城乡居民大病保险",
                "大病保险",
                "大病医保",
            ],
            "category": "补充保险",
            "desc": "对高额医疗费用的二次报销"
        },
        {
            "standard": "超转人员医疗保障",
            "abbr": "超转",
            "aliases": ["超转人员", "超转人员医疗保障"],
            "category": "特殊保障",
            "desc": "超龄转业人员医疗保障"
        },
        {
            "standard": "离休人员医疗保障",
            "abbr": "离休",
            "aliases": ["离休人员", "离休人员医疗保障"],
            "category": "特殊保障",
            "desc": "离休干部医疗保障"
        },
        {
            "standard": "公费医疗",
            "abbr": "公费",
            "aliases": ["公费医疗"],
            "category": "特殊保障",
            "desc": "国家机关、事业单位人员医疗保障"
        },
        {
            "standard": "企业补充医疗保险",
            "abbr": "企补",
            "aliases": ["企业补充医疗保险", "企业补充医保"],
            "category": "补充保险",
            "desc": "企业自主建立的补充医疗保险"
        },
    ]
)

# ============================================================
# 人群标签
# ============================================================
POPULATION_TAGS = _build_domain(
    field_name="population_tags",
    field_name_cn="人群标签",
    description="参保人群分类",
    values=[
        # 职工医保人群
        {
            "standard": "退休人员",
            "abbr": "退休",
            "aliases": ["退休人员", "退休职工", "退休参保人员"],
            "category": "职工医保人群",
            "desc": "已退休的参保人员"
        },
        {
            "standard": "在职职工",
            "abbr": "在职",
            "aliases": ["在职人员", "在职职工", "在职参保人员"],
            "category": "职工医保人群",
            "desc": "在职的参保职工"
        },
        {
            "standard": "灵活就业人员",
            "abbr": "灵活就业",
            "aliases": ["灵活就业人员", "灵活就业参保人员"],
            "category": "职工医保人群",
            "desc": "以灵活就业形式参保的人员"
        },
        # 居民医保人群
        {
            "standard": "城乡老年人",
            "abbr": "城乡老年",
            "aliases": ["城乡老年人", "老年人", "老年参保人员"],
            "category": "居民医保人群",
            "desc": "城乡居民医保中的老年人群"
        },
        {
            "standard": "劳动年龄内居民",
            "abbr": "劳动年龄居民",
            "aliases": ["劳动年龄内居民", "劳动年龄居民"],
            "category": "居民医保人群",
            "desc": "城乡居民医保中劳动年龄内的非就业居民"
        },
        {
            "standard": "学生儿童",
            "abbr": "学生儿童",
            "aliases": ["学生儿童", "学生", "儿童", "少年儿童"],
            "category": "居民医保人群",
            "desc": "在校学生和少年儿童"
        },
        # 困难人群
        {
            "standard": "特困供养人员",
            "abbr": "特困",
            "aliases": ["特困人员", "特困供养人员", "特困供养"],
            "category": "困难人群",
            "desc": "特困供养人员"
        },
        {
            "standard": "最低生活保障人员",
            "abbr": "低保",
            "aliases": ["低保人员", "最低生活保障人员", "低保对象"],
            "category": "困难人群",
            "desc": "享受最低生活保障的人员"
        },
        {
            "standard": "低收入救助人员",
            "abbr": "低收入",
            "aliases": ["低收入救助人员", "低收入人员", "低收入农户"],
            "category": "困难人群",
            "desc": "低收入家庭成员"
        },
        {
            "standard": "残疾人员",
            "abbr": "残疾",
            "aliases": ["残疾人员", "残疾人"],
            "category": "困难人群",
            "desc": "持有残疾证的人员"
        },
        # 特殊人群
        {
            "standard": "优抚对象",
            "abbr": "优抚",
            "aliases": ["优抚对象", "优抚人员"],
            "category": "特殊人群",
            "desc": "享受优抚待遇的人员"
        },
        {
            "standard": "建国前老工人",
            "abbr": "建国前老工人",
            "aliases": ["建国前老工人"],
            "category": "特殊人群",
            "desc": "建国前参加工作的老工人"
        },
    ]
)

# ============================================================
# 医疗机构等级
# ============================================================
HOSPITAL_LEVEL = _build_domain(
    field_name="hospital_level",
    field_name_cn="医疗机构等级",
    description="定点医疗机构的级别",
    values=[
        # 医院等级（从高到低，长模式优先）
        {
            "standard": "三级定点医疗机构",
            "abbr": "三级",
            "aliases": [
                "三级定点医疗机构",
                "三级医疗机构",
                "三级医院",
                "三级",
            ],
            "category": "医院等级",
            "desc": "三级医院"
        },
        {
            "standard": "二级定点医疗机构",
            "abbr": "二级",
            "aliases": [
                "二级定点医疗机构",
                "二级医疗机构",
                "二级医院",
                "二级",
            ],
            "category": "医院等级",
            "desc": "二级医院"
        },
        {
            "standard": "一级及以下定点医疗机构",
            "abbr": "一级及以下",
            "aliases": [
                "一级及以下定点医疗机构",
                "一级及以下医疗机构",
                "一级医院",
                "一级",
                "及以下定点医疗机构",
            ],
            "category": "医院等级",
            "desc": "一级医院及未定级机构"
        },
        # 基层机构
        {
            "standard": "社区卫生服务中心",
            "abbr": "社区中心",
            "aliases": ["社区卫生服务中心"],
            "category": "基层机构",
            "desc": "社区卫生服务中心"
        },
        {
            "standard": "社区卫生服务站",
            "abbr": "社区站",
            "aliases": ["社区卫生服务站"],
            "category": "基层机构",
            "desc": "社区卫生服务站"
        },
        {
            "standard": "基层医疗机构",
            "abbr": "基层",
            "aliases": ["基层医疗机构", "基层医院", "基层卫生机构"],
            "category": "基层机构",
            "desc": "基层医疗卫生机构统称"
        },
        # 统称
        {
            "standard": "定点医疗机构",
            "abbr": "定点医院",
            "aliases": ["定点医疗机构", "定点医院", "医保定点机构"],
            "category": "统称",
            "desc": "医保定点医疗机构统称"
        },
        {
            "standard": "定点零售药店",
            "abbr": "定点药店",
            "aliases": ["定点零售药店", "定点药店", "医保定点药店"],
            "category": "药店",
            "desc": "医保定点零售药店"
        },
    ]
)

# ============================================================
# 医疗类别
# ============================================================
MEDICAL_CATEGORY = _build_domain(
    field_name="medical_category",
    field_name_cn="医疗类别",
    description="医疗服务的类别",
    values=[
        # 住院类（长模式优先）
        {
            "standard": "住院",
            "abbr": "住院",
            "aliases": ["住院", "普通住院", "住院治疗"],
            "category": "住院",
            "desc": "住院医疗服务"
        },
        # 门诊类（长模式优先）
        {
            "standard": "门诊特殊病",
            "abbr": "门特",
            "aliases": ["门诊特殊病", "门特"],
            "category": "门诊",
            "desc": "门诊特殊病种治疗"
        },
        {
            "standard": "门诊慢性病",
            "abbr": "门慢",
            "aliases": ["门诊慢性病", "门慢", "门诊慢性疾病"],
            "category": "门诊",
            "desc": "门诊慢性病治疗"
        },
        {
            "standard": "门诊",
            "abbr": "门诊",
            "aliases": ["门诊", "门诊治疗", "普通门诊"],
            "category": "门诊",
            "desc": "普通门诊医疗服务"
        },
        # 急诊类
        {
            "standard": "急诊抢救",
            "abbr": "急诊抢救",
            "aliases": ["急诊抢救"],
            "category": "急诊",
            "desc": "急诊抢救医疗服务"
        },
        {
            "standard": "急诊留观",
            "abbr": "留观",
            "aliases": ["急诊留观", "留观"],
            "category": "急诊",
            "desc": "急诊留观治疗"
        },
        {
            "standard": "急诊",
            "abbr": "急诊",
            "aliases": ["急诊", "急诊治疗"],
            "category": "急诊",
            "desc": "急诊医疗服务"
        },
        # 特殊医疗
        {
            "standard": "家庭病床",
            "abbr": "家床",
            "aliases": ["家庭病床", "家床"],
            "category": "特殊医疗",
            "desc": "家庭病床服务"
        },
        {
            "standard": "日间手术",
            "abbr": "日间",
            "aliases": ["日间手术", "日间病房"],
            "category": "特殊医疗",
            "desc": "日间手术/日间病房服务"
        },
    ]
)

# ============================================================
# 结算方式
# ============================================================
SETTLEMENT_METHOD = _build_domain(
    field_name="settlement_method",
    field_name_cn="结算方式",
    description="医保费用结算方式",
    values=[
        {
            "standard": "按项目付费",
            "abbr": "项目付费",
            "aliases": ["按项目付费"],
            "category": "付费方式",
            "desc": "按实际发生的医疗服务项目付费"
        },
        {
            "standard": "按病种付费",
            "abbr": "病种付费",
            "aliases": ["按病种付费"],
            "category": "付费方式",
            "desc": "按病种定额付费"
        },
        {
            "standard": "按床日付费",
            "abbr": "床日付费",
            "aliases": ["按床日付费", "床日定额"],
            "category": "付费方式",
            "desc": "按住院天数定额付费"
        },
        {
            "standard": "按人头付费",
            "abbr": "人头付费",
            "aliases": ["按人头付费"],
            "category": "付费方式",
            "desc": "按参保人头数定额付费"
        },
        {
            "standard": "DRG付费",
            "abbr": "DRG",
            "aliases": ["DRG付费", "DRG"],
            "category": "付费方式",
            "desc": "按疾病诊断相关分组付费"
        },
        {
            "standard": "DIP付费",
            "abbr": "DIP",
            "aliases": ["DIP付费", "DIP"],
            "category": "付费方式",
            "desc": "按病种分值付费"
        },
        {
            "standard": "单病种付费",
            "abbr": "单病种",
            "aliases": ["单病种付费", "单病种"],
            "category": "付费方式",
            "desc": "单一病种定额付费"
        },
        {
            "standard": "总额预付",
            "abbr": "总额预付",
            "aliases": ["总额预付", "总额控制", "总额预算"],
            "category": "付费方式",
            "desc": "按年度预算总额付费"
        },
    ]
)

# ============================================================
# 目录属性标签
# ============================================================
CATALOG_TAGS = _build_domain(
    field_name="catalog_tags",
    field_name_cn="目录属性标签",
    description="医保目录分类标签",
    values=[
        # 药品目录分类
        {
            "standard": "甲类药品",
            "abbr": "甲类",
            "aliases": ["甲类药品", "甲类药"],
            "category": "药品目录",
            "desc": "医保全额报销的药品"
        },
        {
            "standard": "乙类药品",
            "abbr": "乙类",
            "aliases": ["乙类药品", "乙类药"],
            "category": "药品目录",
            "desc": "医保部分报销的药品"
        },
        {
            "standard": "丙类药品",
            "abbr": "丙类",
            "aliases": ["丙类药品", "丙类药"],
            "category": "药品目录",
            "desc": "医保不报销的药品"
        },
        # 特殊药品
        {
            "standard": "国家谈判药品",
            "abbr": "国谈药",
            "aliases": ["国家谈判药品", "国谈药品", "国谈药"],
            "category": "药品目录",
            "desc": "国家医保谈判纳入的药品"
        },
        {
            "standard": "集中带量采购药品",
            "abbr": "集采药品",
            "aliases": ["集中带量采购药品", "集采药品", "集中带量采购", "集采"],
            "category": "药品目录",
            "desc": "集中带量采购中选药品"
        },
        # 目录范围
        {
            "standard": "医保目录内",
            "abbr": "目录内",
            "aliases": ["医保目录内", "目录内"],
            "category": "目录范围",
            "desc": "在医保目录范围内"
        },
        {
            "standard": "医保目录外",
            "abbr": "目录外",
            "aliases": ["医保目录外", "目录外"],
            "category": "目录范围",
            "desc": "在医保目录范围外"
        },
        # 目录类型
        {
            "standard": "医保药品目录",
            "abbr": "药品目录",
            "aliases": ["医保目录", "医保药品目录", "药品目录"],
            "category": "目录类型",
            "desc": "医保药品目录"
        },
        {
            "standard": "诊疗项目目录",
            "abbr": "诊疗目录",
            "aliases": ["诊疗项目目录", "诊疗目录"],
            "category": "目录类型",
            "desc": "医保诊疗项目目录"
        },
        {
            "standard": "医疗服务设施目录",
            "abbr": "设施目录",
            "aliases": ["医疗服务设施目录", "设施目录"],
            "category": "目录类型",
            "desc": "医保医疗服务设施目录"
        },
        # 用药范围
        {
            "standard": "门诊特殊病用药",
            "abbr": "门特用药",
            "aliases": ["门特用药", "门诊特殊病用药"],
            "category": "用药范围",
            "desc": "门诊特殊病种用药"
        },
        {
            "standard": "门诊慢性病用药",
            "abbr": "门慢用药",
            "aliases": ["门慢用药", "门诊慢性病用药"],
            "category": "用药范围",
            "desc": "门诊慢性病用药"
        },
    ]
)

# ============================================================
# 费用范围
# ============================================================
COST_SCOPE = _build_domain(
    field_name="cost_scope",
    field_name_cn="费用范围",
    description="医保费用的范围分类",
    values=[
        # 费用范围
        {
            "standard": "医保范围内",
            "abbr": "医保内",
            "aliases": ["医保范围内", "医保内", "目录内费用"],
            "category": "费用范围",
            "desc": "医保目录范围内的费用"
        },
        {
            "standard": "医保范围外",
            "abbr": "医保外",
            "aliases": ["医保范围外", "医保外", "目录外费用"],
            "category": "费用范围",
            "desc": "医保目录范围外的费用"
        },
        {
            "standard": "个人自付",
            "abbr": "自付",
            "aliases": ["个人自付", "自付"],
            "category": "费用范围",
            "desc": "个人按比例自付的费用"
        },
        {
            "standard": "个人自费",
            "abbr": "自费",
            "aliases": ["个人自费", "自费"],
            "category": "费用范围",
            "desc": "完全由个人承担的费用"
        },
        # 费用标准
        {
            "standard": "起付标准",
            "abbr": "起付线",
            "aliases": ["起付标准", "起付线", "起付金额"],
            "category": "费用标准",
            "desc": "医保报销的最低门槛金额"
        },
        {
            "standard": "最高支付限额",
            "abbr": "封顶线",
            "aliases": ["最高支付限额", "封顶线", "累计最高支付", "最高支付数额"],
            "category": "费用标准",
            "desc": "医保年度最高报销金额"
        },
    ]
)

# ============================================================
# 支付比例
# ============================================================
PAYMENT_RATIO = _build_domain(
    field_name="payment_ratio",
    field_name_cn="支付比例",
    description="医保基金支付比例",
    values=[
        {
            "standard": "支付比例",
            "abbr": "支付比例",
            "aliases": ["支付比例", "报销比例", "基金支付比例"],
            "category": "比例",
            "desc": "医保基金支付的比例"
        },
    ]
)

# ============================================================
# 时间周期
# ============================================================
TIME_PERIOD = _build_domain(
    field_name="time_period",
    field_name_cn="时间周期",
    description="医保相关的时间周期",
    values=[
        {
            "standard": "医疗保险年度",
            "abbr": "医保年度",
            "aliases": ["医疗保险年度", "医保年度", "年度"],
            "category": "时间周期",
            "desc": "医保结算的年度周期"
        },
        {
            "standard": "首次住院",
            "abbr": "首次",
            "aliases": ["首次住院", "第一次住院"],
            "category": "住院次数",
            "desc": "年度内第一次住院"
        },
        {
            "standard": "第二次及以后住院",
            "abbr": "二次及以上",
            "aliases": ["第二次及以后住院", "第二次住院", "再次住院"],
            "category": "住院次数",
            "desc": "年度内第二次及以后的住院"
        },
        {
            "standard": "结算周期",
            "abbr": "结算周期",
            "aliases": ["结算周期", "治疗周期"],
            "category": "时间周期",
            "desc": "医疗费用结算的周期"
        },
    ]
)

# ============================================================
# 所有值域规则
# ============================================================
VALUE_DOMAIN_RULES: Dict[str, DomainConfig] = {
    "insurance_system": INSURANCE_SYSTEM,
    "population_tags": POPULATION_TAGS,
    "hospital_level": HOSPITAL_LEVEL,
    "medical_category": MEDICAL_CATEGORY,
    "settlement_method": SETTLEMENT_METHOD,
    "catalog_tags": CATALOG_TAGS,
    "cost_scope": COST_SCOPE,
    "payment_ratio": PAYMENT_RATIO,
    "time_period": TIME_PERIOD,
}
