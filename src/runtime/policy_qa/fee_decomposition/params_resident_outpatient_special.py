"""Issue #81 城乡居民门特（门诊特殊病·按项目付费）待遇参数模块。

数值与规则 ID 的唯一来源：
``docs/superpowers/specs/2026-10-13-issue81-城乡居民门特待遇参数.csv``
（下称参数表）。复用职工门诊参数基类与门控选择函数
（``params_employee_outpatient`` 的 EmployeeOutpatientParam/ParamSelection/
select_param/_gate），仅新增居民门特维度：

- 起付标准按**人员类别**（学生儿童集合 vs 老年/无业）×**机构等级档**（住院口径）
  ×**周期位置**（第一周期/第二及以后）三维度选择（mz.docx 居民住院§起付标准）；
- 大病基金支付比例按机构档（住院口径 2018 起：三级 75%/二级 78%/一级及未评级 80%）；
- 年度基金封顶 20 万（2018）→25 万（2019-01-01）；
- 目录划分规则（甲乙丙/集采/自制剂/限额）同职工门特及居民门诊，计算层复用
  ``catalog_split.split_catalog``（RSP-CAT-001），不重复编码；
- 取整规则 RSP-RND-001 与 EOP/ROP-RND-001 同源待确认：取整模式显式入参，无默认。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import BranchOutcome
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient import (
    EmployeeOutpatientParam,
    ParamSelection,
    select_param,
)

#: 居民门特参数记录类型（复用职工参数基类）
ResidentOutpatientSpecialParam = EmployeeOutpatientParam

#: 学生儿童人员类别集合（Issue #81 + 字典 290）：起付标准分档判定维度
STUDENT_CHILD_PERSON_TYPE_CODES = frozenset({"14", "15", "16", "18", "19", "50"})

#: 住院口径机构等级档映射（m_institution.H_LEVEL → "3"/"2"/"1"，同职工门特
#: employee_outpatient_special._classify_institution 的住院口径：01-05 三级、06-09 二级、10+ 一级）
_H_LEVEL_TO_INSTITUTION_LEVEL = {
    "01": "3", "02": "3", "03": "3", "04": "3", "05": "3",
    "06": "2", "07": "2", "08": "2", "09": "2",
}


def institution_level_from_h_level(h_level: str | None) -> str | None:
    """H_LEVEL → 住院口径机构等级（"3" 三级 / "2" 二级 / "1" 一级及未评级家庭病床）；未知 None。"""
    if h_level is None:
        return None
    code = str(h_level).strip()
    if code in _H_LEVEL_TO_INSTITUTION_LEVEL:
        return _H_LEVEL_TO_INSTITUTION_LEVEL[code]
    try:
        level = int(code)
    except ValueError:
        return None
    if level >= 10:
        return "1"
    return None


_D = date
_DEC = Decimal

PARAMS: tuple[ResidentOutpatientSpecialParam, ...] = (
    # ── 起付线（人员类别×机构档×周期位置） ──
    ResidentOutpatientSpecialParam(
        rule_id="RSP-DED-001", category="起付线",
        name="门特起付标准-老年/无业-三级-年度第一个结算周期",
        applies_to="城乡居民·老年/劳动年龄内无业居民·三级医疗机构·年度第一个住院类结算周期",
        value=_DEC("1300"), value_text=None, unit="元/结算周期", payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计（yb_dyxxtsb.bqljybnje 交易后口径−本笔 tsbybn，含跨院）",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§起付标准（新2018年1月1日）",
        remark="实证：dyxxtsb.bqqfje=1300（688/690/718 周期序号=1）",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-DED-002", category="起付线",
        name="门特起付标准-老年/无业-三级-第二及以后结算周期",
        applies_to="城乡居民·老年/无业居民·三级医疗机构·年度第二个及以后住院类结算周期",
        value=_DEC("650"), value_text=None, unit="元/结算周期", payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§起付标准（新2018年1月1日）",
        remark="起付标准减半",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-DED-003", category="起付线", name="门特起付标准-学生儿童-三级",
        applies_to="城乡居民·学生儿童（14/15/16/18/19/50）·三级医疗机构",
        value=_DEC("650"), value_text=None, unit="元/结算周期", payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§学生儿童起付标准",
        remark="每次结算均收取，不再减半",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-DED-101", category="起付线",
        name="门特起付标准-老年/无业-二级-年度第一个结算周期",
        applies_to="城乡居民·老年/无业居民·二级医疗机构·年度第一个住院类结算周期",
        value=_DEC("800"), value_text=None, unit="元/结算周期", payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§起付标准（新2018年1月1日）",
        remark="一级及未评级 300；第二周期起减半",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-DED-102", category="起付线",
        name="门特起付标准-老年/无业-一级及未评级-年度第一个结算周期",
        applies_to="城乡居民·老年/无业居民·一级及未评级医疗机构·年度第一个住院类结算周期",
        value=_DEC("300"), value_text=None, unit="元/结算周期", payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§起付标准（新2018年1月1日）",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-DED-103", category="起付线", name="门特起付标准-学生儿童-二级",
        applies_to="城乡居民·学生儿童·二级医疗机构",
        value=_DEC("400"), value_text=None, unit="元/结算周期", payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§学生儿童起付标准",
        remark="一级及未评级 150",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-DED-104", category="起付线", name="门特起付标准-学生儿童-一级及未评级",
        applies_to="城乡居民·学生儿童·一级及未评级医疗机构",
        value=_DEC("150"), value_text=None, unit="元/结算周期", payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§学生儿童起付标准",
    ),
    # ── 大病基金支付比例（住院口径机构档） ──
    ResidentOutpatientSpecialParam(
        rule_id="RSP-RATE-001", category="支付比例", name="门特大病基金支付比例-三级医疗机构",
        applies_to="城乡居民·三级定点医疗机构", value=_DEC("75"), value_text=None,
        unit="%", payment_level="大病支付",
        basis="特殊病医保内费用扣除起付后部分；受年度基金最高支付限额约束",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§新政策（2018年1月1日按医院等级区分）",
        remark="实证：688/690/718 degwyzhf=tsbybn×75%（837.83/3646.50/2517.90 全闭合）",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-RATE-002", category="支付比例", name="门特大病基金支付比例-二级医疗机构",
        applies_to="城乡居民·二级定点医疗机构", value=_DEC("78"), value_text=None,
        unit="%", payment_level="大病支付", basis="特殊病医保内费用扣除起付后部分",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§新政策（2018年1月1日按医院等级区分）",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-RATE-003", category="支付比例",
        name="门特大病基金支付比例-一级及未评级（含家庭病床）",
        applies_to="城乡居民·一级及未评级定点医疗机构", value=_DEC("80"), value_text=None,
        unit="%", payment_level="大病支付", basis="特殊病医保内费用扣除起付后部分",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§新政策（2018年1月1日按医院等级区分）",
    ),
    # ── 封顶线 ──
    ResidentOutpatientSpecialParam(
        rule_id="RSP-CAP-001", category="封顶线", name="居民基金年度最高支付限额（2018）",
        applies_to="城乡居民", value=_DEC("200000"), value_text=None, unit="元/保险年度",
        payment_level="不适用",
        basis="大病基金年度累计支付（yb_dyxxnd.bndezfje 交易后口径−本笔 degwyzhf，含跨院）",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2018, 12, 31), expiry_open_ended=False,
        version="V2018-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-住院§封顶线",
    ),
    ResidentOutpatientSpecialParam(
        rule_id="RSP-CAP-002", category="封顶线", name="居民基金年度最高支付限额（2019 起）",
        applies_to="城乡居民", value=_DEC("250000"), value_text=None, unit="元/保险年度",
        payment_level="不适用", basis="大病基金年度累计支付",
        date_basis="结算日期", effective_date=_D(2019, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2019-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§新政策（2019年1月1日）",
    ),
    # ── 统筹通道（居民门特不设统筹分段） ──
    ResidentOutpatientSpecialParam(
        rule_id="RSP-POOL-001", category="统筹通道", name="居民门特不设统筹分段",
        applies_to="城乡居民·门诊特殊病按项目付费", value=None,
        value_text="tczhf=0/tczif=0：特殊病医保内费用全额进入大病基金通道，不经统筹分段",
        unit="规则", payment_level="不适用", basis="不适用",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="GitHub Issue #81 原文；实证 3/3 笔账面统筹字段为 0",
    ),
    # ── 特殊病费用划分 ──
    ResidentOutpatientSpecialParam(
        rule_id="RSP-CAT-001", category="目录规则", name="特殊病费用划分",
        applies_to="城乡居民·门诊特殊病", value=None,
        value_text="特殊病用药及诊疗费用纳入大病报销范围；非特殊病用药及诊疗费用按普通门诊费用结算（本期不支持）",
        unit="规则", payment_level="划分规则",
        basis="逐项费用×特殊病用药标识（yb_ypzdml.tsbyybz 非空/诊疗目录对应标识）",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-住院§门诊特殊病的费用分解；Issue #81 flid=250",
        remark="目录划分规则（甲乙丙/集采/自制剂/限额）同职工门特及居民门诊（复用 split_catalog）",
    ),
    # ── 补充待遇（居民无） ──
    ResidentOutpatientSpecialParam(
        rule_id="RSP-SUP-001", category="补充待遇", name="居民无退休/军残/公疗补充待遇",
        applies_to="城乡居民", value=None,
        value_text="bczhf/jczhf/gfylbchbx 恒 0（not_applicable）；账面非零另报资格与账面冲突",
        unit="规则", payment_level="不适用", basis="不适用",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="居民门诊（Issue #80）同口径；实证 3/3 笔账面补充待遇字段为 0",
    ),
    # ── 取整（待确认：模式必须由计算调用方显式传入） ──
    ResidentOutpatientSpecialParam(
        rule_id="RSP-RND-001", category="取整", name="费用分解取整规则",
        applies_to="全部参保人", value=None,
        value_text="逐行/逐段/汇总取整的适用层级及取整模式文档均未明确（与 EOP/ROP-RND-001 同源待确认）",
        unit="规则", payment_level="不适用", basis="全部计算金额",
        date_basis="不适用", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="待确认",
        source="mz.docx 未记载；设计文档 §9 要求取整模式必须有版本",
        remark="688 degwyzhf 837.825→837.83 实证支持 HALF_UP；禁止凭习惯默认取整模式",
    ),
)

_PARAM_BY_ID = {p.rule_id: p for p in PARAMS}


def get_param(rule_id: str) -> ResidentOutpatientSpecialParam:
    """按规则 ID 取参数（不存在抛 KeyError）。"""
    return _PARAM_BY_ID[rule_id]


def try_get_param(rule_id: str) -> ResidentOutpatientSpecialParam | None:
    """按规则 ID 取参数，不存在返回 None。"""
    return _PARAM_BY_ID.get(rule_id)


def is_student_child(cblb: str | None) -> bool:
    """人员类别 → 学生儿童档（Issue #81 集合）。"""
    return cblb is not None and cblb.strip() in STUDENT_CHILD_PERSON_TYPE_CODES


def select_resident_special_deductible_param(
    cblb: str | None,
    institution_level: str | None,
    cycle_position: str,
    settlement_date: date,
) -> ParamSelection:
    """居民门特起付标准：人员类别×机构档×周期位置三维选择。

    - 学生儿童（14/15/16/18/19/50）：三级 650 / 二级 400 / 一级及未评级 150（每次均收不再减半，
      cycle_position 不影响）；
    - 老年/无业（其他 cblb）：第一周期 三级 1300/二级 800/一级 300，第二及以后减半
      （三级 650；二级/一级减半档未单独立项，本期数据均为第一周期三级）；
    - cblb/机构档未知 → unknown，不默认任何档。
    """
    if cblb is None or institution_level is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PERSON_OR_INSTITUTION_UNKNOWN")
    if is_student_child(cblb):
        rule_id = {"3": "RSP-DED-003", "2": "RSP-DED-103", "1": "RSP-DED-104"}.get(
            institution_level)
    else:
        if cycle_position == "first":
            rule_id = {"3": "RSP-DED-001", "2": "RSP-DED-101", "1": "RSP-DED-102"}.get(
                institution_level)
        else:
            rule_id = {"3": "RSP-DED-002"}.get(institution_level)
    if rule_id is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "DEDUCTIBLE_TIER_NOT_COVERED")
    return select_param((get_param(rule_id),), settlement_date)


def select_resident_special_big_pay_rate_param(
    institution_level: str | None, settlement_date: date
) -> ParamSelection:
    """居民门特大病基金支付比例：三级 75% / 二级 78% / 一级及未评级 80%（住院口径 2018 起）。"""
    if institution_level is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "INSTITUTION_LEVEL_UNKNOWN")
    rule_id = {"3": "RSP-RATE-001", "2": "RSP-RATE-002", "1": "RSP-RATE-003"}.get(
        institution_level)
    if rule_id is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "INSTITUTION_LEVEL_UNKNOWN")
    return select_param((get_param(rule_id),), settlement_date)


def select_resident_special_cap_param(settlement_date: date) -> ParamSelection:
    """居民基金年度最高支付限额：20 万（2018）→25 万（2019-01-01）。"""
    return select_param(tuple(p for p in PARAMS if p.rule_id.startswith("RSP-CAP-")),
                        settlement_date)
