"""Issue #78 职工门特（门诊特殊病，视同住院）待遇参数模块。

数值与规则 ID 的唯一来源：
``docs/superpowers/specs/2026-09-28-issue78-城镇职工门特待遇参数.csv``
（下称参数表，ESP-* 行）。本模块把参数表逐行编码为显式 Python 数据结构：

- 金额/比例一律 ``Decimal``（从 str/int 构造），禁止 float；
- 每条参数带 rule_id（与 CSV 一致）、生效/截止日期、支付层次、确认状态；
- 选择函数按结算日期/费用发生日期选适用版本；
- **门控规则**（与门诊参数模块一致）：确认状态为 ``待确认``，或
  ``文档明确-待官方核证`` 且生效日期未明确的参数不得静默生效——
  选择函数对其返回 unknown 轨迹而不是默认采用；
- 截止日期为「未知（不得默认长期有效）/未明确」的参数同样不得默认生效；
- 起付标准 ESP-DED-001/002 生效日期未明确且截止日期未知 → 恒被门控，
  内核在 confirmed 周期上下文之外不得假定 1300/650；
- 取整规则 ESP-RND-001 为待确认：取整模式由计算函数显式入参，本模块不提供默认。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    PersonKind,
)

# ── 参数记录（值对象） ─────────────────────────────────────────


@dataclass(frozen=True)
class EmployeeOutpatientSpecialParam:
    """门特参数表一行的显式编码。"""

    rule_id: str
    category: str  # 参数类别
    name: str  # 参数名称
    applies_to: str  # 适用对象/条件
    value: Decimal | None  # 数值型参数值（金额元 / 比例百分数 / 天数）
    value_text: str | None  # 文本型参数值（规则描述）
    unit: str  # 单位/类型
    payment_level: str  # 支付层次
    basis: str  # 计算基数或累计口径
    date_basis: str  # 日期依据
    effective_date: date | None
    effective_date_explicit: bool  # 生效日期是否明确
    expiry_date: date | None
    expiry_open_ended: bool  # True=「尚未终止」；False 且 expiry_date=None = 未知（不得默认长期有效）
    version: str
    validity_status: str  # 效力状态：现行/历史
    confirmation_status: str  # 确认状态
    source: str  # 依据来源
    remark: str = ""
    # 结构化选择维度（按需使用，其余为 None）
    person_kind: PersonKind | None = None
    institution_level: str | None = None  # 住院口径机构等级："3" 三级 / "2" 二级 / "1" 一级及家庭病床
    segment: str | None = None  # 统筹分段："seg1" 起付~1万 / "seg2" 1~3万 / "seg3" 3~4万 / "seg4" 4万~封顶
    cycle_position: str | None = None  # 起付线："first" 年度第一个住院类结算周期 / "subsequent" 第二及以后
    retirement_category: str | None = None  # 退休补助："normal" 普通 / "prepaid" 社会化（预提）
    supplement_segment: str | None = None  # 退休补助基数段："pool" 统筹共付段 / "large" 大额共付段

    @property
    def ratio(self) -> Decimal | None:
        """百分数参数值转比例（如 50 → 0.50）；单位以 % 开头即可。"""
        if self.value is None or not self.unit.startswith("%"):
            return None
        return self.value / Decimal("100")


# ── 参数表逐行编码 ─────────────────────────────────────────────

_D = date
_DEC = Decimal

#: mz.docx 住院章节来源（参数表统一依据来源）
_SRC_MZ = "《北京市医疗保障信息平台支付方式管理子系统用户需求规格说明书 - mz.docx》住院§"

PARAMS: tuple[EmployeeOutpatientSpecialParam, ...] = (
    # ── 结算周期 ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CYC-001", category="结算周期", name="门特结算周期-历史90/180天",
        applies_to="全部特殊病参保人",
        value=None, value_text="恶性肿瘤门诊放化疗90天；肾透析、肾移植术后抗排异180天",
        unit="规则", payment_level="不适用",
        basis="以第一次门诊特殊病就诊时间为周期开始时间",
        date_basis="费用发生日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2001, 9, 30), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "特殊病结算周期；京劳社医发【2001】19号",
        remark="2001-09-30 前未到期的结算周期自动延长为 360 天（京医保发【2001】25号问题解答二）",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CYC-002", category="结算周期", name="门特结算周期-360天",
        applies_to="全部特殊病参保人", value=_DEC("360"), value_text=None,
        unit="天/结算期", payment_level="不适用",
        basis="以第一次门诊特殊病就诊时间为周期开始时间",
        date_basis="费用发生日期", effective_date=_D(2001, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "特殊病结算周期；京劳社医保发【2001】129号",
        remark="特殊病患者在结算期内可结算治疗特殊疾病的门诊、住院费用和治疗其它疾病的住院费用",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CYC-003", category="结算周期", name="住院类结算周期数累加规则",
        applies_to="全部参保人",
        value=None, value_text="门诊特殊病、住院、家庭病床周期数累加计算",
        unit="规则", payment_level="不适用",
        basis="年度内住院类结算周期序号（决定起付标准 1300/650 档）",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知（不得默认长期有效）
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹起付线计算",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CYC-004", category="结算周期", name="跨年度特殊病费用连续计算",
        applies_to="跨年度连续看特殊病的参保人",
        value=None,
        value_text="按该病种周期天数为一个结算期；与上年住院次数连续计算起付线、个人支付比例不变；最高支付限额按 2 年的各自费用分别计算",
        unit="规则", payment_level="不适用", basis="结算周期跨年度累计",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "特殊病门诊的费用分解",
        remark="本周期特殊病结束后当年再次住院/门特/家庭病床按第一次计算起付标准",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CYC-005", category="结算周期", name="特殊病周期内住院起付规则",
        applies_to="特殊病周期内在特殊病定点医院住院",
        value=None,
        value_text="本周期已交足起付金额不另行起付；未交足按特殊病周期起付金额补足；费用与特殊病周期内累计连续计算统筹、大额",
        unit="规则", payment_level="不适用", basis="特殊病结算周期内起付已交累计",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "特殊病住院的费用分解",
        remark="特殊病周期内在其它医院住院按普通住院另起周期另行起付",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CYC-006", category="结算周期", name="门特待遇与政策变更口径",
        applies_to="全部特殊病参保人",
        value=None, value_text="待遇变更以结算时待遇为准；政策参数变更以结算时政策为准",
        unit="规则", payment_level="不适用", basis="不适用",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "待遇变更后的费用分解/政策参数发生变更后的费用分解",
        remark="住院以每周期第一天待遇/政策为准；门特与住院口径不同不得混用",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CYC-007", category="结算周期", name="门特病人结算期起始规则",
        applies_to="已办理特殊病申报审批的门特病人",
        value=None,
        value_text="特殊病门诊、特殊病住院、普通住院的起始日期均可作为特殊病结算期起始日期；周期内三类费用累加连续计算统筹、大额支付，以 360 天为一个结算周期",
        unit="规则", payment_level="不适用", basis="特殊病结算周期内医保内费用累计",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V2003-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "特殊病住院的费用分解",
        remark="生效日期未明确（京劳社医发[2003]119号）",
    ),
    # ── 起付线（ESP-DED-001/002 生效日期未明确且截止日期未知 → 恒被门控） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DED-001", category="起付线", name="住院类起付标准-年度第一个结算周期",
        applies_to="全部参保人", value=_DEC("1300"), value_text=None, unit="元/结算周期",
        payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计（交易前；跨院累计口径待与源系统核实）",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹起付线计算",
        remark="门特、住院、家庭病床周期数累加计算（ESP-CYC-003）",
        cycle_position="first",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DED-002", category="起付线", name="住院类起付标准-第二及以后结算周期",
        applies_to="全部参保人", value=_DEC("650"), value_text=None, unit="元/结算周期",
        payment_level="不适用",
        basis="特殊病结算周期内医保内费用累计（交易前；跨院累计口径待与源系统核实）",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹起付线计算",
        remark="bjyb 样本 djh=604 实测本年度第二次住院类结算起付 650（djh=602 同日住院已承担 1300）",
        cycle_position="subsequent",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DED-003", category="起付线", name="低保参保人员起付减半",
        applies_to="享受城镇最低生活保障的参保人员",
        value=None, value_text="起付标准为普通参保人员的 50%",
        unit="规则", payment_level="不适用", basis="同 ESP-DED-001/002",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹起付线计算",
        remark="低保资格字段未映射，未取得资格前不得减半",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DED-004", category="起付线", name="统筹封顶后直接进入大额免起付",
        applies_to="结算周期开始时年统筹基金支付累计已达统筹基金支付范围的参保人",
        value=None, value_text="不须另付起付",
        unit="规则", payment_level="不适用", basis="年度统筹基金支付累计（基金支付口径）",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "住院大额基金计算",
        remark="bjyb 样本 djh=681/723/813 起付 0 且全额进入大额互助段，与本规则方向一致；累计数据源不全时不得据此反推",
    ),
    # ── 统筹分段支付比例（在职自付%；退休自付=在职×60% 见 ESP-RATE-113） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-101", category="支付比例", name="统筹分段-三级-起付至1万段-在职",
        applies_to="在职职工·三级医院", value=_DEC("15"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在（起付值,10000] 区间的部分",
        date_basis="结算日期（门特以结算时政策为准）",
        effective_date=_D(2005, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2005-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算参数表（TABLE 7）；京劳社医发[2004]184号",
        remark="2001-04-01~2004-12-31 该段在职自付 20% 见 ESP-RATE-201",
        person_kind=PersonKind.EMPLOYED, institution_level="3", segment="seg1",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-102", category="支付比例", name="统筹分段-三级-1万至3万段-在职",
        applies_to="在职职工·三级医院", value=_DEC("15"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (10000,30000] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="3", segment="seg2",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-103", category="支付比例", name="统筹分段-三级-3万至4万段-在职",
        applies_to="在职职工·三级医院", value=_DEC("10"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (30000,40000] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="3", segment="seg3",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-104", category="支付比例", name="统筹分段-三级-4万至封顶段-在职",
        applies_to="在职职工·三级医院", value=_DEC("5"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (40000，统筹封顶] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="3", segment="seg4",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-105", category="支付比例", name="统筹分段-二级-起付至1万段-在职",
        applies_to="在职职工·二级医院", value=_DEC("13"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在（起付值,10000] 区间的部分",
        date_basis="结算日期", effective_date=_D(2005, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2005-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算参数表（TABLE 7）；京劳社医发[2004]184号",
        remark="历史 18% 见 ESP-RATE-202",
        person_kind=PersonKind.EMPLOYED, institution_level="2", segment="seg1",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-106", category="支付比例", name="统筹分段-二级-1万至3万段-在职",
        applies_to="在职职工·二级医院", value=_DEC("13"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (10000,30000] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="2", segment="seg2",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-107", category="支付比例", name="统筹分段-二级-3万至4万段-在职",
        applies_to="在职职工·二级医院", value=_DEC("8"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (30000,40000] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="2", segment="seg3",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-108", category="支付比例", name="统筹分段-二级-4万至封顶段-在职",
        applies_to="在职职工·二级医院", value=_DEC("3"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (40000，统筹封顶] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="2", segment="seg4",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-109", category="支付比例", name="统筹分段-一级及家庭病床-起付至1万段-在职",
        applies_to="在职职工·一级医院及家庭病床", value=_DEC("10"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在（起付值,10000] 区间的部分",
        date_basis="结算日期", effective_date=_D(2005, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2005-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算参数表（TABLE 7）；京劳社医发[2004]184号",
        remark="历史 15% 见 ESP-RATE-203",
        person_kind=PersonKind.EMPLOYED, institution_level="1", segment="seg1",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-110", category="支付比例", name="统筹分段-一级及家庭病床-1万至3万段-在职",
        applies_to="在职职工·一级医院及家庭病床", value=_DEC("10"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (10000,30000] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="1", segment="seg2",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-111", category="支付比例", name="统筹分段-一级及家庭病床-3万至4万段-在职",
        applies_to="在职职工·一级医院及家庭病床", value=_DEC("5"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (30000,40000] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="1", segment="seg3",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-112", category="支付比例", name="统筹分段-一级及家庭病床-4万至封顶段-在职",
        applies_to="在职职工·一级医院及家庭病床", value=_DEC("3"), value_text=None, unit="%",
        payment_level="基础支付",
        basis="结算周期内医保内费用扣除起付后落在 (40000，统筹封顶] 区间的部分",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        person_kind=PersonKind.EMPLOYED, institution_level="1", segment="seg4",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-113", category="支付比例", name="退休人员个人支付比例折算规则",
        applies_to="退休职工", value=_DEC("60"), value_text=None, unit="%",
        payment_level="基础支付", basis="与在职各分段相同基数（退休自付=在职自付×60%）",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2001-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
        remark="例：三级起付至1万段退休自付=15%×60%=9%（统筹 91%）；bjyb 样本 djh=705/707 实测 91% 吻合",
        person_kind=PersonKind.RETIRED,
    ),
    # ── 统筹分段历史版本（2001-04-01~2004-12-31） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-201", category="支付比例", name="统筹分段-三级-起付至1万段-在职（历史）",
        applies_to="在职职工·三级医院", value=_DEC("20"), value_text=None, unit="%",
        payment_level="基础支付", basis="同 ESP-RATE-101",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2004, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "统筹基金支付计算参数表（TABLE 6）",
        remark="2005-01-01 起失效（京劳社医发[2004]184号）",
        person_kind=PersonKind.EMPLOYED, institution_level="3", segment="seg1",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-202", category="支付比例", name="统筹分段-二级-起付至1万段-在职（历史）",
        applies_to="在职职工·二级医院", value=_DEC("18"), value_text=None, unit="%",
        payment_level="基础支付", basis="同 ESP-RATE-105",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2004, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "统筹基金支付计算参数表（TABLE 6）", remark="同上",
        person_kind=PersonKind.EMPLOYED, institution_level="2", segment="seg1",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RATE-203", category="支付比例", name="统筹分段-一级及家庭病床-起付至1万段-在职（历史）",
        applies_to="在职职工·一级医院及家庭病床", value=_DEC("15"), value_text=None, unit="%",
        payment_level="基础支付", basis="同 ESP-RATE-109",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2004, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "统筹基金支付计算参数表（TABLE 6）", remark="同上",
        person_kind=PersonKind.EMPLOYED, institution_level="1", segment="seg1",
    ),
    # ── 统筹封顶线 ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CAP-001", category="封顶线", name="统筹基金年度最高支付限额（历史）",
        applies_to="在职及退休职工", value=_DEC("50000"), value_text=None, unit="元/年度",
        payment_level="不适用",
        basis="年度统筹基金累计支付额（基金支付口径，非费用累计）",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2004, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "统筹基金支付计算", remark="按上一年本市职工平均工资 4 倍左右确定",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CAP-002", category="封顶线", name="统筹基金年度最高支付限额（历史）",
        applies_to="在职及退休职工", value=_DEC("70000"), value_text=None, unit="元/年度",
        payment_level="不适用",
        basis="年度统筹基金累计支付额（基金支付口径，非费用累计）",
        date_basis="结算日期", effective_date=_D(2005, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 4, 30), expiry_open_ended=False,
        version="V2005-01-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "统筹基金支付计算；京劳社医发[2004]184号",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CAP-003", category="封顶线", name="统筹基金年度最高支付限额",
        applies_to="在职及退休职工", value=_DEC("100000"), value_text=None, unit="元/年度",
        payment_level="不适用",
        basis="年度统筹基金累计支付额（基金支付口径，非费用累计）",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2010-05-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "统筹基金支付计算",
    ),
    # ── 大额医疗互助资金 ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-LGP-001", category="支付比例", name="大额医疗互助资金支付比例（历史）",
        applies_to="在职及退休职工", value=_DEC("70"), value_text=None,
        unit="%（大额资金支付，个人30%）", payment_level="基础支付",
        basis="年度统筹基金最高支付限额以上的住院类医保内费用",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 4, 30), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "住院大额基金计算",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-LGP-002", category="支付比例", name="大额医疗互助资金支付比例-在职",
        applies_to="在职职工", value=_DEC("85"), value_text=None,
        unit="%（大额资金支付，个人15%）", payment_level="基础支付",
        basis="年度统筹基金最高支付限额以上的住院类医保内费用",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2010-05-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "住院大额基金计算",
        person_kind=PersonKind.EMPLOYED,
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-LGP-003", category="支付比例", name="大额医疗互助资金支付比例-退休",
        applies_to="退休职工", value=_DEC("80"), value_text=None,
        unit="%（大额资金支付，个人20%；未扣除退休补助）", payment_level="基础支付",
        basis="年度统筹基金最高支付限额以上的住院类医保内费用",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2010-05-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "住院大额基金计算",
        remark="bjyb 样本 djh=681/723/813（退休）实测 degwyzhf=医保内×80% 吻合",
        person_kind=PersonKind.RETIRED,
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-LCAP-001", category="封顶线", name="大额医疗互助资金年度最高支付限额（历史）",
        applies_to="在职及退休职工", value=_DEC("100000"), value_text=None, unit="元/年度",
        payment_level="不适用", basis="年度大额医疗互助资金累计支付额（基金支付口径）",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 4, 30), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "住院大额基金计算",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-LCAP-002", category="封顶线", name="大额医疗互助资金年度最高支付限额（历史）",
        applies_to="在职及退休职工", value=_DEC("200000"), value_text=None, unit="元/年度",
        payment_level="不适用", basis="年度大额医疗互助资金累计支付额（基金支付口径）",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=_D(2018, 12, 31), expiry_open_ended=False,
        version="V2010-05-01", validity_status="历史", confirmation_status="文档明确",
        source=_SRC_MZ + "住院大额基金计算",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-LCAP-003", category="封顶线", name="大额医疗互助资金年度最高支付限额",
        applies_to="在职及退休职工", value=_DEC("400000"), value_text=None, unit="元/保险年度",
        payment_level="不适用", basis="年度大额医疗互助资金累计支付额（基金支付口径）",
        date_basis="结算日期", effective_date=_D(2019, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2019-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "住院大额基金计算",
    ),
    # ── 退休补充保险（门特以费用发生日期为准，ESP-RSUP-005） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RSUP-001", category="退休补充保险", name="退休补助-普通退休-统筹共付段",
        applies_to="普通退休人员", value=_DEC("50"), value_text=None, unit="%",
        payment_level="补充补助", basis="统筹共付段个人自付金额（扣起付后按比例个人分担部分）",
        date_basis="费用发生日期（门特以费用发生日期为准）",
        effective_date=_D(2006, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "退休补充费用分解",
        remark="bjyb 样本 djh=705/707 实测 bczhf=统筹自付×50% 吻合（114.805→114.81 四舍五入到分）",
        retirement_category="normal", supplement_segment="pool",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RSUP-002", category="退休补充保险", name="退休补助-普通退休-大额共付段",
        applies_to="普通退休人员", value=_DEC("50"), value_text=None, unit="%",
        payment_level="补充补助", basis="大额共付段个人自付金额",
        date_basis="费用发生日期", effective_date=_D(2006, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "退休补充费用分解",
        remark="bjyb 样本 djh=681/723/813 实测 bczhf=大额自付×50% 吻合（255.125→255.13）",
        retirement_category="normal", supplement_segment="large",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RSUP-003", category="退休补充保险", name="退休补助-社会化退休-统筹共付段",
        applies_to="原社会化（预提）退休人员", value=_DEC("50"), value_text=None, unit="%",
        payment_level="补充补助", basis="统筹共付段个人自付金额",
        date_basis="费用发生日期", effective_date=_D(2006, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "退休补充费用分解",
        remark="注意住院类社会化退休统筹段为 50%，与门诊口径（预提 60%）不同",
        retirement_category="prepaid", supplement_segment="pool",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RSUP-004", category="退休补充保险", name="退休补助-社会化退休-大额共付段",
        applies_to="原社会化（预提）退休人员", value=_DEC("60"), value_text=None, unit="%",
        payment_level="补充补助", basis="大额共付段个人自付金额",
        date_basis="费用发生日期", effective_date=_D(2006, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "退休补充费用分解",
        remark="社会化/预提类别字段未映射，类别未知时不得默认普通 50%",
        retirement_category="prepaid", supplement_segment="large",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RSUP-005", category="退休补充保险", name="退休补助资格时点规则",
        applies_to="退休人员",
        value=None,
        value_text="2006-04-01 实施；住院以出院日期为准；门特、家庭病床、七日留观以费用发生日期为准确定是否可分解退休补充",
        unit="规则", payment_level="补充补助", basis="不适用（资格规则）",
        date_basis="费用发生日期", effective_date=_D(2006, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "退休补充费用分解",
        remark="门特日期口径与普通门诊（结算日期）不同，禁止混用",
    ),
    # ── 残疾军人补助（资格字段未映射，内核一律 observed_only；编码供引用 rule_id） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DVET-001", category="残疾军人补助", name="军残补助-在职5-6级",
        applies_to="在职残疾军人（5-6级）", value=_DEC("70"), value_text=None, unit="%",
        payment_level="补充补助", basis="统筹起付标准、统筹共付段自付、大额共付段自付分别补助 70%",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "军残补助计算",
        remark="住院类军残含起付段补助，与普通门诊口径不同",
        person_kind=PersonKind.EMPLOYED,
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DVET-002", category="残疾军人补助", name="军残补助-在职1-4级",
        applies_to="在职残疾军人（1-4级）", value=_DEC("100"), value_text=None, unit="%",
        payment_level="补充补助", basis="统筹起付标准、统筹共付段自付、大额共付段自付分别补助 100%",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "军残补助计算",
        remark="bjyb 样本 djh=604（在职）实测 jczhf=起付650+统筹自付635.55=1285.55 全额补助，方向与 100% 档吻合；资格字段未确认，不得由金额反推",
        person_kind=PersonKind.EMPLOYED,
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DVET-003", category="残疾军人补助", name="军残补助-退休5-6级",
        applies_to="退休残疾军人（5-6级）", value=_DEC("50"), value_text=None, unit="%",
        payment_level="补充补助", basis="起付标准 50%、统筹共付段及大额共付段剩余自付（扣除退休补助后）50%",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "军残补助计算",
        remark="bjyb 样本 djh=707（退休）实测 jczhf=(354.24-177.12)×50%=88.56 吻合；资格字段未确认",
        person_kind=PersonKind.RETIRED,
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DVET-004", category="残疾军人补助", name="军残补助-退休1-4级",
        applies_to="退休残疾军人（1-4级）", value=_DEC("100"), value_text=None, unit="%",
        payment_level="补充补助", basis="起付标准及统筹/大额共付段剩余自付（扣除退休补助后）100%",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "军残补助计算",
        remark="依赖退休补助独立计算结果；R 未知时不得用零代替",
        person_kind=PersonKind.RETIRED,
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-DVET-005", category="残疾军人补助", name="军残补助边界规则",
        applies_to="全部残疾军人",
        value=None,
        value_text="超大额封顶线的医保内费用不参与补助；2006-10-01 实施；门特以费用发生日期确定是否可分解",
        unit="规则", payment_level="补充补助", basis="不适用（边界规则）",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "军残补助计算",
    ),
    # ── 单位补充险（原公疗）（资格字段未映射，内核一律 observed_only） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-PMED-001", category="单位补充险（原公疗）", name="公疗补助-一般公疗-起付线以下部分",
        applies_to="市级公费医疗及参加市级统筹的区级公费医疗人员",
        value=None, value_text="退休 95% / 在职 90%（含公疗后基金目标比例）",
        unit="规则", payment_level="补充补助", basis="起付线以下的医保内费用",
        date_basis="结算日期（本人定点关系判定时点待确认）",
        effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "公费医疗补助计算",
        remark="原文「2012月1日1日」按 2012-01-01 理解；须为本人定点医疗机构",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-PMED-002", category="单位补充险（原公疗）", name="公疗补助-一般公疗-起付线以上部分",
        applies_to="市级公费医疗及参加市级统筹的区级公费医疗人员",
        value=None, value_text="退休 97% / 在职 94%（含公疗后基金目标比例；按现行医保政策结算后医保支付已高于该比例时不再补助）",
        unit="规则", payment_level="补充补助", basis="起付线以上的医保内费用",
        date_basis="结算日期", effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "公费医疗补助计算",
        remark="bjyb 样本 djh=705 现金与 97% 目标精确吻合（580.94），但 gfylbchbx 账面为 0 且公疗资格字段未确认，不得据此反推资格",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-PMED-003", category="单位补充险（原公疗）", name="公疗补助-在乡残疾军人",
        applies_to="享受公费医疗的在乡残疾军人",
        value=None, value_text="100%（医保全额报销，含起付金额）",
        unit="规则", payment_level="补充补助", basis="全部医保内费用",
        date_basis="结算日期", effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "公费医疗补助计算",
        remark="不再结算军残补助（ESP-DVET 系列 not_applicable）",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-PMED-004", category="单位补充险（原公疗）", name="公疗结算顺序",
        applies_to="公疗人员",
        value=None,
        value_text="先统筹支付、大额支付、退休补助、军残补助，再计算公费医疗补充保险支付；跨年度或跨周期住院以交易为单位计算",
        unit="规则", payment_level="补充补助", basis="不适用（顺序规则）",
        date_basis="结算日期", effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "公费医疗补助计算",
        remark="适用于项目付费、单病种、特殊病定额管理、精神病总额付费、DRGS 付费",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-PMED-005", category="单位补充险（原公疗）", name="公疗资格前提",
        applies_to="公疗人员",
        value=None, value_text="参保人在本人定点医疗机构发生的住院类医疗费用",
        unit="规则", payment_level="补充补助", basis="不适用（资格规则）",
        date_basis="结算日期", effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "公费医疗补助计算",
        remark="本人定点资格字段未映射；单位未及时缴费时转手工报销",
    ),
    # ── 目录规则（门特明细 ybnje/ybwje 已为划分结果；独立重算待 ESP-CAT-001 标识确认） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CAT-001", category="目录规则", name="特殊病用药标识划分规则",
        applies_to="特殊病参保人",
        value=None,
        value_text="标有特殊病用药标识的药品：可报销部分划入住院医保内、不可报销划入住院医保外；无标识的：可报销部分划入门诊医保内、不可报销划入门诊医保外",
        unit="规则", payment_level="划分规则", basis="逐项药品费用×特殊病用药标识",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "药品目录/三大目录划分",
        remark="bjyb 门特明细 ybnje/ybwje 已为划分结果；标识物理列（tsbz 候选）与门诊/住院内外归集口径待确认",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CAT-002", category="目录规则", name="非特殊病费用按普通门诊处理",
        applies_to="特殊病参保人",
        value=None, value_text="门诊特殊病中非特殊病用药及诊疗费用按普通门诊进行处理",
        unit="规则", payment_level="划分规则", basis="逐项费用是否属于特殊病用药及诊疗",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "特殊病门诊的费用分解",
        remark="与 ESP-CAT-001 的判定依据（病种对应关系/标识字段）待确认",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CAT-003", category="目录规则", name="门特4+7集采药品限价分解",
        applies_to="职工参保人（军残人员除外）",
        value=None, value_text="同普通门诊 4+7 限价规则（EOP-NCP-001/002）",
        unit="规则", payment_level="划分规则", basis="逐项集采药品费用",
        date_basis="结算时间", effective_date=_D(2019, 3, 23), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=False,  # 截止日期未明确
        version="V2019-03-23", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 门诊§配合4+7药品限价管理的医保结算规则（门特同上）",
        remark="门特不再验证集采药品规格与目录对照规格一致",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CAT-004", category="目录规则", name="三大目录变更口径",
        applies_to="全部参保人",
        value=None, value_text="住院、门诊特殊病、家庭病床均以费用发生时为准",
        unit="规则", payment_level="划分规则", basis="不适用（全局口径）",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "三大目录发生变更的费用划分规则",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CAT-005", category="目录规则", name="贵重药品固定支付比例（门诊发生视同住院）",
        applies_to="到本人定点医疗机构门诊发生按固定比例支付贵重药品费用的参保人",
        value=_DEC("80"),
        value_text="按药品收费总金额的 80% 确定职工统筹基金/大额资金支付金额",
        unit="%", payment_level="基础支付",
        basis="逐项贵重药品收费总金额；基金支付计入年度住院统筹/大额累计",
        date_basis="结算日期", effective_date=_D(2020, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2020-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source=_SRC_MZ + "按固定比例支付的贵重药品",
        remark="受年度基金最高支付标准限制时应支付大于可支付按可支付支付；先统筹后大额顺序",
    ),
    # ── 码值映射（实测待码表确认） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CODE-001", category="码值映射", name="门特医疗类别码",
        applies_to="门特结算",
        value=None, value_text="门诊套表 yllb='12'（yb_brdjxx/yb_mzjyxx/yb_mzfymx，键 djh）",
        unit="码值", payment_level="不适用", basis="不适用", date_basis="不适用",
        effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-bjyb-2024", validity_status="现行", confirmation_status="实测待码表确认",
        source="bjyb 库 yb_brdjxx 实测；YLLB 码表 16=门特",
        remark="o_Trade 门诊交易表无门特（T_CureType 仅 11/17/18/19）；门特按项目付费走门诊套表",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CODE-002", category="码值映射", name="险种码-城镇职工",
        applies_to="城镇职工参保人",
        value=None, value_text="门诊套表 FUND_TYPE=3",
        unit="码值", payment_level="不适用", basis="不适用", date_basis="不适用",
        effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-bjyb-2024", validity_status="现行", confirmation_status="实测待码表确认",
        source="bjyb 库 yb_brdjxx/yb_mzjyxx 实测",
        remark="与门诊 o_Trade P_FundType='3' 口径一致性待码表确认",
    ),
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-CODE-003", category="码值映射", name="人员类别码-在职/退休候选",
        applies_to="城镇职工参保人",
        value=None, value_text="yb_brdjxx.cblb='11' 在职候选；'21'/'61' 退休候选",
        unit="码值", payment_level="不适用", basis="不适用", date_basis="不适用",
        effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-bjyb-2024", validity_status="现行", confirmation_status="实测待码表确认",
        source="bjyb 库 6 笔门特样本实测（11=在职；21/61=退休）",
        remark="与门诊 S1 候选集合（在职 11/12/40，退休含 21/61）一致；其他代码为未知不得默认在职",
    ),
    # ── 取整（待确认：模式必须由计算调用方显式传入） ──
    EmployeeOutpatientSpecialParam(
        rule_id="ESP-RND-001", category="取整", name="费用分解取整规则",
        applies_to="全部参保人",
        value=None, value_text="逐行/逐段/汇总取整的适用层级及取整模式文档均未明确",
        unit="规则", payment_level="不适用", basis="全部计算金额",
        date_basis="不适用", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="待确认",
        source="mz.docx 未记载；设计文档 §9 要求取整模式必须有版本",
        remark="bjyb 门特样本 2 例半分均符合四舍五入到分（255.125→255.13、114.805→114.81），仅为样本方向，不构成规则确认",
    ),
)

_PARAM_BY_ID = {p.rule_id: p for p in PARAMS}


def get_param(rule_id: str) -> EmployeeOutpatientSpecialParam:
    """按规则 ID 取参数（不存在抛 KeyError）。"""
    return _PARAM_BY_ID[rule_id]


def try_get_param(rule_id: str) -> EmployeeOutpatientSpecialParam | None:
    """按规则 ID 取参数，不存在返回 None。"""
    return _PARAM_BY_ID.get(rule_id)


# ── 选择结果与门控 ─────────────────────────────────────────────


@dataclass(frozen=True)
class ParamSelection:
    """参数选择结果：未通过门控时 outcome=unknown，绝不静默默认采用。"""

    param: EmployeeOutpatientSpecialParam | None
    outcome: BranchOutcome
    reason_code: str | None = None


def _gate(param: EmployeeOutpatientSpecialParam) -> str | None:
    """确认状态/日期门控。返回 None 表示可采用，否则返回 reason_code。"""
    if param.confirmation_status in ("待确认", "实测待码表确认"):
        return "PARAM_CONFIRMATION_PENDING"
    if param.confirmation_status == "文档明确-待官方核证" and not param.effective_date_explicit:
        return "PARAM_EFFECTIVE_DATE_UNCLEAR"
    if param.expiry_date is None and not param.expiry_open_ended:
        return "PARAM_EXPIRY_UNKNOWN"
    return None


def select_param(
    candidates: tuple[EmployeeOutpatientSpecialParam, ...],
    on_date: date,
) -> ParamSelection:
    """按日期在候选中选唯一适用版本；0 命中/多命中/未过门控均返回 unknown。"""
    in_window = [
        p
        for p in candidates
        if (p.effective_date is None or p.effective_date <= on_date)
        and (p.expiry_date is None or on_date <= p.expiry_date)
    ]
    if not in_window:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PARAM_VERSION_NOT_FOUND")
    if len(in_window) > 1:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PARAM_VERSION_AMBIGUOUS")
    param = in_window[0]
    reason = _gate(param)
    if reason is not None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, reason)
    return ParamSelection(param, BranchOutcome.TRUE, None)


def _by_prefix(prefix: str) -> tuple[EmployeeOutpatientSpecialParam, ...]:
    return tuple(p for p in PARAMS if p.rule_id.startswith(prefix))


def select_deductible_standard(cycle_position: str, on_date: date) -> ParamSelection:
    """住院类起付标准：第一个结算周期 1300 / 第二及以后 650（ESP-DED-001/002）。

    注意：两行均「生效日期未明确且截止日期未知」，按门控规则恒返回 unknown；
    只有 confirmed 周期上下文显式携带 deductible_standard 时内核才独立重算起付。
    """
    candidates = tuple(p for p in _by_prefix("ESP-DED-00") if p.cycle_position == cycle_position)
    if not candidates:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "CYCLE_POSITION_UNKNOWN")
    return select_param(candidates, on_date)


@dataclass(frozen=True)
class SegmentRate:
    """统筹分段在职自付比例：段边界为结算周期内医保内费用累计绝对坐标（含起付段）。"""

    segment: str  # seg1..seg4
    lower: Decimal | None  # None = 起付标准（动态，由内核代入）
    upper: Decimal | None  # None = 统筹封顶（动态）
    employed_self_pay_ratio: Decimal
    rule_id: str


@dataclass(frozen=True)
class SegmentRateSelection:
    """分段比例选择结果：任一段未能确定即整体 unknown。"""

    segments: tuple[SegmentRate, ...]
    outcome: BranchOutcome
    reason_code: str | None = None


_SEGMENT_BOUNDS: dict[str, tuple[Decimal | None, Decimal | None]] = {
    "seg1": (None, _DEC("10000")),
    "seg2": (_DEC("10000"), _DEC("30000")),
    "seg3": (_DEC("30000"), _DEC("40000")),
    "seg4": (_DEC("40000"), None),
}


def select_segment_rates(institution_level: str | None, on_date: date) -> SegmentRateSelection:
    """统筹四段在职自付比例（按机构等级 + 结算日期选版本）。

    退休自付 = 在职 × ESP-RATE-113 折算系数，由内核另行选择。
    """
    if institution_level not in ("1", "2", "3"):
        return SegmentRateSelection((), BranchOutcome.UNKNOWN, "INSTITUTION_LEVEL_UNKNOWN")
    segments: list[SegmentRate] = []
    for seg in ("seg1", "seg2", "seg3", "seg4"):
        candidates = tuple(
            p
            for p in _by_prefix("ESP-RATE-")
            if p.institution_level == institution_level and p.segment == seg
        )
        sel = select_param(candidates, on_date)
        if sel.outcome != BranchOutcome.TRUE or sel.param is None or sel.param.ratio is None:
            return SegmentRateSelection((), BranchOutcome.UNKNOWN,
                                        sel.reason_code or "PARAM_VERSION_NOT_FOUND")
        lower, upper = _SEGMENT_BOUNDS[seg]
        segments.append(SegmentRate(seg, lower, upper, sel.param.ratio, sel.param.rule_id))
    return SegmentRateSelection(tuple(segments), BranchOutcome.TRUE, None)


def select_retired_factor(on_date: date) -> ParamSelection:
    """退休人员个人支付比例折算系数（ESP-RATE-113：在职×60%）。"""
    return select_param((get_param("ESP-RATE-113"),), on_date)


def select_pool_cap(on_date: date) -> ParamSelection:
    """统筹基金年度最高支付限额（ESP-CAP-001/002/003，按结算日期选版本）。"""
    return select_param(_by_prefix("ESP-CAP-"), on_date)


def select_large_fund_rate(person_kind: PersonKind, on_date: date) -> ParamSelection:
    """大额医疗互助资金支付比例：在职 85% / 退休 80%（2010-05-01 起）。"""
    if person_kind == PersonKind.UNKNOWN:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PERSON_KIND_UNKNOWN")
    candidates = tuple(
        p
        for p in _by_prefix("ESP-LGP-")
        if p.person_kind is None or p.person_kind == person_kind
    )
    return select_param(candidates, on_date)


def select_large_cap(on_date: date) -> ParamSelection:
    """大额医疗互助资金年度最高支付限额（ESP-LCAP-001/002/003）。"""
    return select_param(_by_prefix("ESP-LCAP-"), on_date)


@dataclass(frozen=True)
class RetireSupplementRateSelection:
    """退休补助比例选择结果：统筹段与大额段分别选择。

    普通/社会化退休统筹段均为 50%（ESP-RSUP-001/003），类别未知不阻断统筹段；
    大额段 50%/60% 不同（ESP-RSUP-002/004），类别未知时大额段 unknown（不默认 50%）。
    """

    pool: ParamSelection
    large: ParamSelection


def select_retire_supplement_rates(
    retirement_category: str | None, on_date: date
) -> RetireSupplementRateSelection:
    """退休补助比例：按退休类别分别选统筹段/大额段参数。"""
    if retirement_category not in ("normal", "prepaid"):
        # 类别未知：统筹段两类同为 50%，取普通档作为代表引用；大额段 unknown
        pool_sel = select_param((get_param("ESP-RSUP-001"),), on_date)
        return RetireSupplementRateSelection(
            pool=pool_sel,
            large=ParamSelection(None, BranchOutcome.UNKNOWN, "RETIREMENT_CATEGORY_UNKNOWN"),
        )
    pool_id = "ESP-RSUP-001" if retirement_category == "normal" else "ESP-RSUP-003"
    large_id = "ESP-RSUP-002" if retirement_category == "normal" else "ESP-RSUP-004"
    return RetireSupplementRateSelection(
        pool=select_param((get_param(pool_id),), on_date),
        large=select_param((get_param(large_id),), on_date),
    )


def select_military_param(person_kind: PersonKind, grade: str, fee_date: date) -> ParamSelection:
    """军残补助比例档（ESP-DVET-001..004）。资格字段未映射，仅供 observed_only 引用。"""
    key = (person_kind, grade)
    rule_id = {
        (PersonKind.EMPLOYED, "5-6"): "ESP-DVET-001",
        (PersonKind.EMPLOYED, "1-4"): "ESP-DVET-002",
        (PersonKind.RETIRED, "5-6"): "ESP-DVET-003",
        (PersonKind.RETIRED, "1-4"): "ESP-DVET-004",
    }.get(key)
    if rule_id is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "MILITARY_GRADE_UNKNOWN")
    return select_param((get_param(rule_id),), fee_date)


def select_public_medical_param(branch: str, on_date: date) -> ParamSelection:
    """公疗补助参数（ESP-PMED-001/002/003）。资格字段未映射，仅供 observed_only 引用。"""
    rule_id = {
        "below_deductible": "ESP-PMED-001",
        "above_deductible": "ESP-PMED-002",
        "rural_disabled_veteran": "ESP-PMED-003",
    }.get(branch)
    if rule_id is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PUBLIC_MEDICAL_BRANCH_UNKNOWN")
    return select_param((get_param(rule_id),), on_date)


def select_rounding_param() -> ParamSelection:
    """取整规则 ESP-RND-001：待确认，永远返回 unknown；取整模式须显式传入。"""
    return ParamSelection(None, BranchOutcome.UNKNOWN, "PARAM_CONFIRMATION_PENDING")
