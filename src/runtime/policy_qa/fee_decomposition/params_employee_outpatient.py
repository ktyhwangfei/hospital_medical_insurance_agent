"""Issue #78 职工门诊待遇参数模块。

数值与规则 ID 的唯一来源：
``docs/superpowers/specs/2026-09-28-issue78-城镇职工门诊待遇参数.csv``
（下称参数表）。本模块把参数表逐行编码为显式 Python 数据结构：

- 金额/比例一律 ``Decimal``（从 str/int 构造），禁止 float；
- 每条参数带 rule_id（与 CSV 一致）、生效/截止日期、支付层次、确认状态；
- 选择函数按结算日期/费用发生日期选适用版本；
- **门控规则**（任务硬约束）：确认状态为 ``待确认``，或
  ``文档明确-待官方核证`` 且生效日期未明确的参数不得静默生效——
  选择函数对其返回 unknown 轨迹而不是默认采用；
- 截止日期为「未知（不得默认长期有效）/未明确」的参数同样不得默认生效；
- **合计展示层次**（EOP-RATE-201/202/203/303）绝不进入计算，仅展示；
- 取整规则 EOP-RND-001 为待确认：取整模式由计算函数显式入参，本模块不提供默认。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    InstitutionKind,
    PersonKind,
)

# ── 参数记录（值对象） ─────────────────────────────────────────

#: 合计展示支付层次：仅用于展示口径，禁止进入计算（参数表 EOP-RATE-201/202/203/303）
PAYMENT_LEVEL_DISPLAY_ONLY = "合计展示"


@dataclass(frozen=True)
class EmployeeOutpatientParam:
    """参数表一行的显式编码。"""

    rule_id: str
    category: str  # 参数类别
    name: str  # 参数名称
    applies_to: str  # 适用对象/条件
    value: Decimal | None  # 数值型参数值（金额元 / 比例百分数）
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
    # 结构化选择维度（支付比例类使用，其余为 None）
    person_kind: PersonKind | None = None
    age_band: str | None = None  # "lt70" / "ge70"
    institution_kind: InstitutionKind | None = None
    segment: str = "base"  # "base" 基础段 / "excess_20k" 超 2 万基金支付段

    @property
    def ratio(self) -> Decimal | None:
        """百分数参数值转比例（如 50 → 0.50）；单位以 % 开头即可（如「%（含公疗后基金目标比例…）」）。"""
        if self.value is None or not self.unit.startswith("%"):
            return None
        return self.value / Decimal("100")


# ── 参数表逐行编码 ─────────────────────────────────────────────

_D = date
_DEC = Decimal

PARAMS: tuple[EmployeeOutpatientParam, ...] = (
    # ── 起付线 ──
    EmployeeOutpatientParam(
        rule_id="EOP-DED-001", category="起付线", name="门诊大额起付标准-在职（历史）",
        applies_to="在职职工", value=_DEC("2000"), value_text=None, unit="元/保险年度",
        payment_level="不适用",
        basis="医保内门诊费用年度累计（交易前；TB_FeeIn 口径及是否跨院累计待与源系统核实）",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2008, 6, 30), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额起付标准",
        remark="2008-07-01 起调整为 1800 元",
        person_kind=PersonKind.EMPLOYED,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-DED-002", category="起付线", name="门诊大额起付标准-在职",
        applies_to="在职职工", value=_DEC("1800"), value_text=None, unit="元/保险年度",
        payment_level="不适用",
        basis="医保内门诊费用年度累计（交易前；TB_FeeIn 口径及是否跨院累计待与源系统核实）",
        date_basis="结算日期", effective_date=_D(2008, 7, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2008-07-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额起付标准",
        person_kind=PersonKind.EMPLOYED,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-DED-003", category="起付线", name="门诊大额起付标准-退休（历史）",
        applies_to="退休职工", value=_DEC("1500"), value_text=None, unit="元/保险年度",
        payment_level="不适用",
        basis="医保内门诊费用年度累计（交易前；TB_FeeIn 口径及是否跨院累计待与源系统核实）",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2003, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额起付标准",
        remark="2004-01-01 起调整为 1300 元",
        person_kind=PersonKind.RETIRED,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-DED-004", category="起付线", name="门诊大额起付标准-退休",
        applies_to="退休职工", value=_DEC("1300"), value_text=None, unit="元/保险年度",
        payment_level="不适用",
        basis="医保内门诊费用年度累计（交易前；TB_FeeIn 口径及是否跨院累计待与源系统核实）",
        date_basis="结算日期", effective_date=_D(2004, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2004-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额起付标准",
        person_kind=PersonKind.RETIRED,
    ),
    # ── 支付比例（基础支付；合计展示的 EOP-RATE-2xx/303 见下方单独编码） ──
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-101", category="支付比例", name="门诊大额支付比例-在职-社区（历史）",
        applies_to="在职职工·享受社区门诊支付比例优惠的机构", value=_DEC("50"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2006, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（在职表）",
        person_kind=PersonKind.EMPLOYED, institution_kind=InstitutionKind.COMMUNITY,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-102", category="支付比例", name="门诊大额支付比例-在职-其他医院（历史）",
        applies_to="在职职工·其他定点医疗机构", value=_DEC("50"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 4, 30), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（在职表）",
        remark="2007/2008 两次调整仅上调社区档，其他档维持 50% 至 2010-04-30",
        person_kind=PersonKind.EMPLOYED, institution_kind=InstitutionKind.OTHER,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-103", category="支付比例", name="门诊大额支付比例-在职-社区（历史）",
        applies_to="在职职工·享受社区门诊支付比例优惠的机构", value=_DEC("60"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2007, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2008, 6, 30), expiry_open_ended=False,
        version="V2007-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（在职表）",
        person_kind=PersonKind.EMPLOYED, institution_kind=InstitutionKind.COMMUNITY,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-104", category="支付比例", name="门诊大额支付比例-在职-社区（历史）",
        applies_to="在职职工·享受社区门诊支付比例优惠的机构", value=_DEC("70"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2008, 7, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 4, 30), expiry_open_ended=False,
        version="V2008-07-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（在职表）",
        person_kind=PersonKind.EMPLOYED, institution_kind=InstitutionKind.COMMUNITY,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-105", category="支付比例", name="门诊大额支付比例-在职-社区",
        applies_to="在职职工·本市社区卫生服务机构", value=_DEC("90"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2010-05-01", validity_status="现行", confirmation_status="官方已核实",
        source="mz.docx 门诊大额支付标准（在职表）；京人社医发〔2010〕100号第三条",
        person_kind=PersonKind.EMPLOYED, institution_kind=InstitutionKind.COMMUNITY,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-106", category="支付比例", name="门诊大额支付比例-在职-其他医院",
        applies_to="在职职工·其他定点医疗机构", value=_DEC("70"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2010-05-01", validity_status="现行", confirmation_status="官方已核实",
        source="mz.docx 门诊大额支付标准（在职表）；京人社医发〔2010〕100号第三条",
        person_kind=PersonKind.EMPLOYED, institution_kind=InstitutionKind.OTHER,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-107", category="支付比例", name="门诊大额支付比例-退休-不满70周岁（历史）",
        applies_to="退休职工·不满70周岁", value=_DEC("60"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2003, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（退休表）",
        person_kind=PersonKind.RETIRED, age_band="lt70",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-108", category="支付比例", name="门诊大额支付比例-退休-70周岁以上（历史）",
        applies_to="退休职工·70周岁以上", value=_DEC("70"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2003, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（退休表）",
        person_kind=PersonKind.RETIRED, age_band="ge70",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-109", category="支付比例", name="门诊大额支付比例-退休-不满70周岁（历史）",
        applies_to="退休职工·不满70周岁（不区分机构）", value=_DEC("70"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2004, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 4, 30), expiry_open_ended=False,
        version="V2004-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（退休表）",
        remark="退休社区/其他拆分自 2010-05-01 开始；本档此前不区分机构；2010-05-01 起社区档 80%（EOP-RATE-111）、其他档延续为 EOP-RATE-112",
        person_kind=PersonKind.RETIRED, age_band="lt70",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-110", category="支付比例", name="门诊大额支付比例-退休-70周岁以上",
        applies_to="退休职工·70周岁以上", value=_DEC("80"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2004, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2004-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（退休表）",
        remark="2010 年通知未调整该档；docx 2010-05-01 行仍为 80%",
        person_kind=PersonKind.RETIRED, age_band="ge70",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-111", category="支付比例", name="门诊大额支付比例-退休-不满70周岁-社区",
        applies_to="退休职工·不满70周岁·本市社区卫生服务机构", value=_DEC("80"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2010-05-01", validity_status="现行", confirmation_status="官方已核实",
        source="mz.docx 门诊大额支付标准（退休表）；京人社医发〔2010〕100号第四条",
        remark="官方明确：报销比例 90% 含退休统一补充医疗保险，其中门诊大额（基础）支付 80%",
        person_kind=PersonKind.RETIRED, age_band="lt70", institution_kind=InstitutionKind.COMMUNITY,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-112", category="支付比例", name="门诊大额支付比例-退休-不满70周岁-其他医院",
        applies_to="退休职工·不满70周岁·其他定点医疗机构", value=_DEC("70"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用年度累计超起付标准部分（共付段）；2022-12-31 前另受 2 万元基金支付限额约束",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2010-05-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额支付标准（退休表）",
        remark="2010-05-01 起退休不满70周岁分社区（80%）/其他（70%）；2004~2010-04-30 的 70% 不区分机构见 EOP-RATE-109；2010 年通知未涉及该档",
        person_kind=PersonKind.RETIRED, age_band="lt70", institution_kind=InstitutionKind.OTHER,
    ),
    # ── 合计展示（绝不进入计算） ──
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-201", category="支付比例", name="门诊报销合计比例-退休-不满70周岁-社区",
        applies_to="退休职工·不满70周岁·本市社区卫生服务机构", value=_DEC("90"), value_text=None,
        unit="%", payment_level="合计展示",
        basis="展示口径=基础支付+剩余个人自付×退休补充补助比例；合计展示比例不得作为基础比例再次参与补助计算",
        date_basis="结算日期", effective_date=_D(2010, 5, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2010-05-01", validity_status="现行", confirmation_status="官方已核实",
        source="京人社医发〔2010〕100号第四条；docx 官方图片转录",
        remark="合计=大额互助 80%＋剩余 20%×退休补助 50%",
        person_kind=PersonKind.RETIRED, age_band="lt70", institution_kind=InstitutionKind.COMMUNITY,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-202", category="支付比例", name="门诊报销合计比例-退休-不满70周岁-其他医院",
        applies_to="退休职工·不满70周岁·其他定点医疗机构", value=_DEC("85"), value_text=None,
        unit="%", payment_level="合计展示",
        basis="展示口径=基础支付+剩余个人自付×退休补充补助比例；合计展示比例不得作为基础比例再次参与补助计算",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=True,
        version="V-未标注", validity_status="现行", confirmation_status="官方转录已核实",
        source="docx 官方图片表格复核转录（微信图片_20250120171650.png）",
        remark="合计=大额互助 70%＋剩余 30%×退休补助 50%=85%；正式文件出处待补",
        person_kind=PersonKind.RETIRED, age_band="lt70", institution_kind=InstitutionKind.OTHER,
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-203", category="支付比例", name="门诊报销合计比例-退休-70周岁以上",
        applies_to="退休职工·70周岁以上", value=_DEC("90"), value_text=None,
        unit="%", payment_level="合计展示",
        basis="展示口径=基础支付+剩余个人自付×退休补充补助比例；合计展示比例不得作为基础比例再次参与补助计算",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=True,
        version="V-未标注", validity_status="现行", confirmation_status="官方转录已核实",
        source="docx 官方图片表格复核转录（微信图片_20250120171650.png）",
        remark="合计=大额互助 80%＋剩余 20%×退休补助 50%=90%；正式文件出处待补",
        person_kind=PersonKind.RETIRED, age_band="ge70",
    ),
    # ── 超 2 万基金支付段 ──
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-301", category="支付比例", name="门诊大额支付比例-超2万元段-在职",
        applies_to="在职职工", value=_DEC("60"), value_text=None, unit="%", payment_level="基础支付",
        basis="基金年度累计支付达原最高支付限额 2 万元后的医保内费用；分段边界为基金支付累计口径，不得用医保内费用累计 TB_FeeIn 直接切档",
        date_basis="结算日期", effective_date=_D(2023, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2023-01-01", validity_status="现行", confirmation_status="官方已核实",
        source="京医保发〔2022〕28号第七条", remark="上不封顶；在职无退休补充，合计即 60%",
        person_kind=PersonKind.EMPLOYED, segment="excess_20k",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-302", category="支付比例", name="门诊大额支付比例-超2万元段-退休",
        applies_to="退休职工", value=_DEC("60"), value_text=None, unit="%", payment_level="基础支付",
        basis="基金年度累计支付达原最高支付限额 2 万元后的医保内费用；分段边界为基金支付累计口径，不得用医保内费用累计 TB_FeeIn 直接切档",
        date_basis="结算日期", effective_date=_D(2023, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2023-01-01", validity_status="现行", confirmation_status="官方已核实",
        source="京医保发〔2022〕28号第七条", remark="大额互助资金支付 60%，上不封顶",
        person_kind=PersonKind.RETIRED, segment="excess_20k",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RATE-303", category="支付比例", name="门诊报销合计比例-超2万元段-退休",
        applies_to="退休职工", value=_DEC("80"), value_text=None, unit="%", payment_level="合计展示",
        basis="展示口径=基础支付+剩余个人自付×退休补充补助比例；合计展示比例不得作为基础比例再次参与补助计算",
        date_basis="结算日期", effective_date=_D(2023, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2023-01-01", validity_status="现行", confirmation_status="官方已核实",
        source="北京市医保局政策问答第二问",
        remark="80% 已含退休统一补充医疗保险（60%＋40%×50%）；不得将 80% 当基础比例再补一次",
        person_kind=PersonKind.RETIRED, segment="excess_20k",
    ),
    # ── 封顶线 ──
    EmployeeOutpatientParam(
        rule_id="EOP-CAP-001", category="封顶线", name="门诊大额年度最高支付限额（历史）",
        applies_to="在职及退休职工", value=_DEC("20000"), value_text=None, unit="元/保险年度",
        payment_level="不适用",
        basis="大额医疗费用互助资金年度累计支付额（基金支付口径，非费用累计）",
        date_basis="结算日期", effective_date=_D(2001, 4, 1), effective_date_explicit=True,
        expiry_date=_D(2022, 12, 31), expiry_open_ended=False,
        version="V2001-04-01", validity_status="历史", confirmation_status="官方已核实",
        source="mz.docx 门诊大额最高支付标准；京医保发〔2022〕28号第七条",
        remark="2023-01-01 起不再设置门诊最高支付限额；不得以 TB_FeeIn 费用累计替代基金支付累计",
    ),
    # ── 年度口径 ──
    EmployeeOutpatientParam(
        rule_id="EOP-YEAR-001", category="年度口径", name="保险年度",
        applies_to="全部参保人", value=None, value_text="自然年度（1月1日-12月31日）",
        unit="规则", payment_level="不适用", basis="不适用",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知（不得默认长期有效）
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊收费结算/保险年度",
    ),
    # ── 挂号定额/医事服务费（首期计算内核不消费，编码仅供溯源） ──
    EmployeeOutpatientParam(
        rule_id="EOP-REG-001", category="挂号定额", name="普通医院门诊诊疗费定额支付",
        applies_to="全部参保人·普通医院", value=_DEC("2"), value_text=None, unit="元/次",
        payment_level="定额支付", basis="每次挂号门诊诊疗费；超出定额部分划入个人自付二",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额结算/挂号费结算/普通医院",
        remark="定额支付不计入年度门诊大额支付累计",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-101", category="挂号定额", name="医事服务费定额-三级-普通门诊",
        applies_to="三级定点医疗机构", value=_DEC("40"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="门诊医事服务费、中医辨证论治费；超出定额部分划入个人自付二",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费", remark="不累计门急诊医疗待遇",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-102", category="挂号定额", name="医事服务费定额-二级-普通门诊",
        applies_to="二级定点医疗机构", value=_DEC("28"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="门诊医事服务费、中医辨证论治费；超出定额部分划入个人自付二",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费", remark="不累计门急诊医疗待遇",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-103", category="挂号定额", name="医事服务费定额-二级-副主任及以上",
        applies_to="二级定点医疗机构", value=_DEC("30"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="副主任医师及以上门诊医事服务费、中医辨证论治费",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-104", category="挂号定额", name="医事服务费定额-一级及以下-普通门诊",
        applies_to="一级及以下定点医疗机构", value=_DEC("19"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="门诊医事服务费、中医辨证论治费；超出定额部分划入个人自付二",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费", remark="不累计门急诊医疗待遇",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-105", category="挂号定额", name="医事服务费定额-一级及以下-副主任及以上",
        applies_to="一级及以下定点医疗机构", value=_DEC("20"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="副主任医师及以上门诊医事服务费、中医辨证论治费",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-106", category="挂号定额", name="医事服务费定额-三级-急诊",
        applies_to="三级定点医疗机构", value=_DEC("60"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="急诊医事服务费、中医辨证论治费",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-107", category="挂号定额", name="医事服务费定额-二级-急诊",
        applies_to="二级定点医疗机构", value=_DEC("48"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="急诊医事服务费、中医辨证论治费",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-108", category="挂号定额", name="医事服务费定额-一级及以下-急诊",
        applies_to="一级及以下定点医疗机构", value=_DEC("39"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="急诊医事服务费、中医辨证论治费",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-109", category="挂号定额", name="门诊特殊病挂号医事服务费视同规则",
        applies_to="门诊特殊病病人", value=None, value_text="视作普通门急诊的医事服务费、中医辨证论治费处理",
        unit="规则", payment_level="定额支付", basis="不适用",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§医事服务费",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-201", category="挂号定额", name="县级医事服务费定额-门诊",
        applies_to="县级试点医院", value=_DEC("28"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="县级门诊医事服务费；超出定额部分划入个人自付二",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§县级医事服务费",
        remark="划入医保支付范围部分由门诊大额基金全额支付，且不计入门诊年度待遇累计",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-202", category="挂号定额", name="县级医事服务费定额-急诊",
        applies_to="县级试点医院", value=_DEC("48"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="县级急诊医事服务费；超出定额部分划入个人自付二",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§县级医事服务费",
        remark="划入医保支付范围部分由门诊大额基金全额支付，且不计入门诊年度待遇累计",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-301", category="挂号定额", name="医事服务费试点医院定额-门诊（历史/过渡）",
        applies_to="医事服务费试点医院（友谊医院）", value=_DEC("40"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="门诊诊疗费；超出定额部分划入个人自付二",
        date_basis="结算日期", effective_date=_D(2012, 7, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=False,  # 截止日期未明确
        version="V2012-07-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额结算/医事服务费试点医院",
        remark="2017-04-08 全市医事服务费实施后是否终止，文档未说明",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REG-302", category="挂号定额", name="医事服务费试点医院定额-急诊（历史/过渡）",
        applies_to="医事服务费试点医院（友谊医院）", value=_DEC("60"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="急诊诊疗费；超出定额部分划入个人自付二",
        date_basis="结算日期", effective_date=_D(2012, 7, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=False,
        version="V2012-07-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊大额结算/医事服务费试点医院",
        remark="原文「60无」按 60 元理解",
    ),
    # ── 目录规则（结构性划分语义；带数值阈值的经选择函数门控） ──
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-001", category="目录规则", name="药品目录分类及划分",
        applies_to="全部参保人",
        value=None, value_text="无自付→全额医保内；有自付→按比例划入个人自付二；全自付→全额个人自费",
        unit="规则", payment_level="划分规则", basis="逐项药品费用",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§药品收费的医保内外划分",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-002", category="目录规则", name="医院自制剂-使用范围",
        applies_to="全部参保人",
        value=None, value_text="医院自制剂在本院使用时纳入医保支付范围，否则全额个人自费",
        unit="规则", payment_level="划分规则", basis="自制剂药品费用；须取得费用发生机构与制剂所属机构的对应关系",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§药品收费的医保内外划分",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-003", category="目录规则", name="医院自制剂-价格限制",
        applies_to="全部参保人",
        value=None, value_text="单价≤目录标准价格方可纳入医保支付范围，超出全额个人自费",
        unit="规则", payment_level="划分规则", basis="自制剂药品单价与目录标准价格（bzjg）",
        date_basis="费用发生日期", effective_date=_D(2004, 3, 15), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2004-03-15", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§药品收费的医保内外划分；京劳社医保发〔2004〕3号",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-004", category="目录规则", name="社区药品目录适用范围",
        applies_to="社区卫生服务站/医务室/门诊所/卫生所",
        value=None, value_text="必须使用社区药品目录（医院目录子集）；开具社区目录外药品一律全额个人自费",
        unit="规则", payment_level="划分规则", basis="逐项药品费用×就诊机构类别",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§药品收费的医保内外划分",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-005", category="目录规则", name="社区慢病用药优惠",
        applies_to="高血压/糖尿病等慢病参保人·试点社区卫生机构",
        value=None, value_text="准许使用医院目录内非社区用药且负担比例降低；社区目录内药品个人负担比例降低（幅度视病种）",
        unit="规则", payment_level="划分规则", basis="逐项药品费用×慢病病种",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§药品收费的医保内外划分；京劳社医发〔2006〕24号",
        remark="文档仅给文号未给具体生效日期；各病种降低幅度未给出",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-006", category="目录规则", name="目录外药品",
        applies_to="全部参保人", value=None, value_text="医保药品目录中不存在的药品全额划入个人自费",
        unit="规则", payment_level="划分规则", basis="逐项药品费用",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§药品收费的医保内外划分",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-007", category="目录规则", name="诊疗项目及服务设施分类及划分",
        applies_to="全部参保人",
        value=None, value_text="无自付→全额医保内；有自付→按自付比例或按单价限额划入个人自付二；全自付→全额个人自费",
        unit="规则", payment_level="划分规则", basis="逐项诊疗/服务设施费用",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§诊疗项目及服务设施收费的医保内外划分",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-008", category="目录规则", name="门诊检查费单价限额",
        applies_to="全部参保人·门诊治疗检查费",
        value=None, value_text="单价≤200 元全额纳入医保；＞200 元按 8% 自付比例划入个人自付二",
        unit="规则", payment_level="划分规则", basis="单项检查费单价",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§诊疗项目及服务设施收费的医保内外划分",
        remark="生效日期未明确，选择函数对其返回 unknown，不得静默生效",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-CAT-009", category="目录规则", name="三大目录变更口径",
        applies_to="全部参保人",
        value=None, value_text="普通门急诊以费用发生时的三大目录医保政策为准",
        unit="规则", payment_level="划分规则", basis="不适用（全局口径）",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§三大目录发生变更的费用划分规则",
        remark="目录匹配用费用发生日期；集采规则例外（按结算时间）",
    ),
    # ── 医用材料 ──
    EmployeeOutpatientParam(
        rule_id="EOP-MAT-001", category="目录规则", name="贵重医用材料自付比例（历史）",
        applies_to="全部参保人",
        value=None, value_text="单价≥500 元按 50% 纳入医保（自付 50%）；＜500 元全额纳入",
        unit="规则", payment_level="划分规则", basis="单项材料单价",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=_D(2008, 6, 30), expiry_open_ended=False,
        version="V-未标注", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§诊疗项目及服务设施收费的医保内外划分",
        remark="纳入比例不是最终基金报销比例",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-MAT-002", category="目录规则", name="贵重医用材料自付比例（历史）",
        applies_to="全部参保人",
        value=None, value_text="单价≥500 元按 70% 纳入医保（自付 30%）；＜500 元全额纳入",
        unit="规则", payment_level="划分规则", basis="单项材料单价",
        date_basis="费用发生日期", effective_date=_D(2008, 7, 1), effective_date_explicit=True,
        expiry_date=_D(2022, 12, 31), expiry_open_ended=False,
        version="V2008-07-01", validity_status="历史", confirmation_status="官方已核实",
        source="mz.docx；北京经开区官方解读问题三", remark="纳入比例不是最终基金报销比例",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-MAT-003", category="目录规则", name="医用材料单价限额-低档",
        applies_to="全部参保人", value=_DEC("1000"), value_text="单价＜1000 元全额纳入医保支付范围",
        unit="元", payment_level="划分规则", basis="单项材料单价",
        date_basis="费用发生日期", effective_date=_D(2023, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2023-01-01", validity_status="现行", confirmation_status="官方已核实",
        source="北京经开区官方解读问题三", remark="纳入标准由 500 元提高至 1000 元（不含）",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-MAT-004", category="目录规则", name="医用材料纳入比例-高档",
        applies_to="全部参保人", value=_DEC("80"), value_text="单价≥1000 元按 80% 纳入医保支付范围（自付 20%）",
        unit="%", payment_level="划分规则", basis="单项材料单价",
        date_basis="费用发生日期", effective_date=_D(2023, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2023-01-01", validity_status="现行", confirmation_status="官方已核实",
        source="北京经开区官方解读问题三", remark="纳入比例由 70% 提高至 80%",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-MAT-005", category="目录规则", name="人工器官及集采中选材料例外",
        applies_to="全部参保人",
        value=None, value_text="人工器官按原有人工器官报销政策；集采中选产品按集采中选产品报销政策执行",
        unit="规则", payment_level="划分规则", basis="单项材料费用",
        date_basis="费用发生日期", effective_date=_D(2023, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2023-01-01", validity_status="现行", confirmation_status="官方已核实",
        source="北京经开区官方解读问题三", remark="具体政策参数未在本表覆盖，须另行取数",
    ),
    # ── 集采限价 ──
    EmployeeOutpatientParam(
        rule_id="EOP-NCP-001", category="集采限价", name="4+7药品门诊限价分解",
        applies_to="职工参保人（军残人员除外）",
        value=None, value_text="收费单价＞医保门诊限价：按超限价自付比例（=原自付比例+上浮 10%）划分；≤限价：按原自付比例划分",
        unit="规则", payment_level="划分规则",
        basis="逐项集采药品费用；包装类型整包→集采最小包装单位限价，拆包→集采最小制剂单位限价，未给包装类型默认整包",
        date_basis="结算时间（门诊退费以原交易结算时间为准）",
        effective_date=_D(2019, 3, 23), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=False,  # 截止日期未明确
        version="V2019-03-23", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§配合4+7药品限价管理的医保结算规则",
        remark="a_xbbl 语义（增量/最终比例、作用基数）未确认，超限价分支不编码公式",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-NCP-002", category="集采限价", name="4+7药品门诊限价分解-更新（包装类型比价）",
        applies_to="职工参保人（军残人员除外）",
        value=None, value_text="＞限价时：未通过一致性评价药品先将超限价部分划入自付二、剩余部分按药品等级划分，其他药品按超限价自付比例（原+10%）划分；≤限价按药品等级划分",
        unit="规则", payment_level="划分规则",
        basis="逐项集采药品费用；包装类型整包→集采最小包装单位限价，拆包→集采最小制剂单位限价，未给包装类型默认整包",
        date_basis="结算时间（门诊退费以原交易结算时间为准）",
        effective_date=None, effective_date_explicit=False,  # 生效日期未明确（晚于 2019-03-23）
        expiry_date=None, expiry_open_ended=True,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§配合4+7药品限价管理的医保结算规则更新",
        remark="生效日期文档未标注（Q8 遗留）；选择函数对其返回 unknown，不得静默生效",
    ),
    # ── 退休补充保险 ──
    EmployeeOutpatientParam(
        rule_id="EOP-RSUP-001", category="退休补充保险", name="退休补充保险补助-普通退休人员",
        applies_to="普通退休人员", value=_DEC("50"), value_text=None, unit="%",
        payment_level="补充补助", basis="门诊大额共付段个人自付金额",
        date_basis="结算日期", effective_date=_D(2006, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§退休补充保险补助结算",
        remark="开始纳入资格以就诊交费的结算日期判断",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-RSUP-002", category="退休补充保险", name="退休补充保险补助-预提退休人员",
        applies_to="原社会化（预提）退休人员", value=_DEC("60"), value_text=None, unit="%",
        payment_level="补充补助", basis="门诊大额共付段个人自付金额",
        date_basis="结算日期", effective_date=_D(2006, 4, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-04-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§退休补充保险补助结算",
        remark="退休身份已知但普通/预提类别未知时不得默认 50%",
    ),
    # ── 残疾军人补助 ──
    EmployeeOutpatientParam(
        rule_id="EOP-DVET-001", category="残疾军人补助", name="军残补助-在职5-6级",
        applies_to="在职残疾军人（5-6级）", value=_DEC("70"), value_text=None, unit="%",
        payment_level="补充补助", basis="门诊大额共付段个人自付金额",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§残疾军人伤残补助结算",
        person_kind=PersonKind.EMPLOYED, age_band="grade5-6",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-DVET-002", category="残疾军人补助", name="军残补助-在职1-4级",
        applies_to="在职残疾军人（1-4级）", value=_DEC("100"), value_text=None, unit="%",
        payment_level="补充补助", basis="门诊大额共付段个人自付金额",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§残疾军人伤残补助结算",
        person_kind=PersonKind.EMPLOYED, age_band="grade1-4",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-DVET-003", category="残疾军人补助", name="军残补助-退休5-6级",
        applies_to="退休残疾军人（5-6级）", value=_DEC("50"), value_text=None, unit="%",
        payment_level="补充补助", basis="门诊大额共付段扣除退休补充保险支付后的剩余自付",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§残疾军人伤残补助结算",
        remark="依赖退休补助独立计算结果；R 未知时不得用零代替；享受公疗的在乡残疾军人跳过本模块",
        person_kind=PersonKind.RETIRED, age_band="grade5-6",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-DVET-004", category="残疾军人补助", name="军残补助-退休1-4级",
        applies_to="退休残疾军人（1-4级）", value=_DEC("100"), value_text=None, unit="%",
        payment_level="补充补助", basis="门诊大额共付段扣除退休补充保险支付后的剩余自付",
        date_basis="费用发生日期", effective_date=_D(2006, 10, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2006-10-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§残疾军人伤残补助结算",
        person_kind=PersonKind.RETIRED, age_band="grade1-4",
    ),
    # ── 单位补充险（原公疗） ──
    EmployeeOutpatientParam(
        rule_id="EOP-PMED-001", category="单位补充险（原公疗）", name="公疗补助-一般公疗退休人员",
        applies_to="市级公费医疗及参加市级统筹的区级公费医疗·退休", value=_DEC("95"),
        value_text=None, unit="%（含公疗后基金目标比例，个人 5%）", payment_level="补充补助",
        basis="医保内门诊费用年度累计超 1300 元部分（未扣除统筹、大额、补充保险、军残补助之前的口径）",
        date_basis="结算日期（本人定点关系判定时点待确认）",
        effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§公费医疗补助结算",
        remark="1300 元以下部分基金 0%；基本医保待遇已达或超过公疗待遇时不再补助",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-PMED-002", category="单位补充险（原公疗）", name="公疗补助-一般公疗在职人员",
        applies_to="市级公费医疗及参加市级统筹的区级公费医疗·在职", value=_DEC("90"),
        value_text=None, unit="%（含公疗后基金目标比例，个人 10%）", payment_level="补充补助",
        basis="医保内门诊费用年度累计超 1300 元部分（未扣除统筹、大额、补充保险、军残补助之前的口径）",
        date_basis="结算日期（本人定点关系判定时点待确认）",
        effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§公费医疗补助结算",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-PMED-003", category="单位补充险（原公疗）", name="公疗补助-在乡残疾军人",
        applies_to="享受公费医疗的在乡残疾军人", value=_DEC("100"),
        value_text=None, unit="%（含公疗后基金目标比例，个人 0%）", payment_level="补充补助",
        basis="医保内门诊费用年度累计超 1300 元部分（未扣除统筹、大额、补充保险、军残补助之前的口径）",
        date_basis="结算日期（本人定点关系判定时点待确认）",
        effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§公费医疗补助结算",
        remark="1300 元（含）以下不予支付；不再结算残疾军人补助（EOP-DVET 系列 not_applicable）",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-PMED-004", category="单位补充险（原公疗）", name="公疗结算顺序",
        applies_to="公疗人员",
        value=None, value_text="门诊：大额→退休补充保险→残疾军人补助→单位补充险（原公疗）；跨年度/跨周期住院以交易为单位计算公疗补充",
        unit="规则", payment_level="补充补助", basis="不适用（顺序规则）",
        date_basis="结算日期", effective_date=_D(2012, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2012-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§公费医疗补助结算",
        remark="不得把门诊 1300 元门槛或 90%/95% 比例推算住院",
    ),
    # ── 退费/手工报销（首期不支持重算，编码仅供溯源） ──
    EmployeeOutpatientParam(
        rule_id="EOP-REF-001", category="退费", name="门诊退费-旧政策（历史）",
        applies_to="全部参保人",
        value=None, value_text="仅全额退费：按数量取负值形成退费发生额，以退费时卡内累计及原交易身份分解",
        unit="规则", payment_level="不适用", basis="被退交易明细费用（负值）",
        date_basis="原交易结算时间", effective_date=None, effective_date_explicit=False,
        expiry_date=_D(2017, 12, 31), expiry_open_ended=False,  # 2018 年 1 季度新政策前，具体日期未明确
        version="V-未标注", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊退费",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-REF-002", category="退费", name="门诊退费-新政策（部分退费）",
        applies_to="全部参保人",
        value=None, value_text="部分退费：先生成完全退费交易（按被退交易结算时身份与已分割明细、退费时点累计），再生成重收交易；跨年度以被退年度年终累计为基础",
        unit="规则", payment_level="不适用", basis="被退交易已医保分割的费用明细",
        date_basis="原交易结算时间", effective_date=None, effective_date_explicit=False,  # 2018 年第 1 季度，具体日期未明确
        expiry_date=None, expiry_open_ended=True,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§门诊退费",
    ),
    EmployeeOutpatientParam(
        rule_id="EOP-MAN-001", category="手工报销", name="退休人员手工报销在职门诊费用",
        applies_to="退休人员",
        value=None, value_text="先累加年内历次门诊起付金额补足在职起付标准，剩余部分按在职门诊大额比例计算",
        unit="规则", payment_level="不适用", basis="年内历次门诊交易起付金额累计",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城镇职工基本医疗保险-门诊§手工报销",
        remark="限费用发生年度历史交易中有退休身份门诊费用的情形",
    ),
    # ── 取整（待确认：模式必须由计算调用方显式传入） ──
    EmployeeOutpatientParam(
        rule_id="EOP-RND-001", category="取整", name="费用分解取整规则",
        applies_to="全部参保人",
        value=None, value_text="逐行/逐段/汇总取整的适用层级及取整模式（四舍五入/见分进角等）文档均未明确",
        unit="规则", payment_level="不适用", basis="全部计算金额",
        date_basis="不适用", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="待确认",
        source="mz.docx 未记载；设计文档 §9 要求取整模式必须有版本",
        remark="Q9 未解决：禁止凭习惯默认取整模式；一分钱差异保留不抹平",
    ),
)

_PARAM_BY_ID = {p.rule_id: p for p in PARAMS}


def get_param(rule_id: str) -> EmployeeOutpatientParam:
    """按规则 ID 取参数（不存在抛 KeyError）。"""
    return _PARAM_BY_ID[rule_id]


def try_get_param(rule_id: str) -> EmployeeOutpatientParam | None:
    """按规则 ID 取参数，不存在返回 None。"""
    return _PARAM_BY_ID.get(rule_id)


def display_only_params() -> tuple[EmployeeOutpatientParam, ...]:
    """合计展示层次参数：仅展示口径，绝不进入计算。"""
    return tuple(p for p in PARAMS if p.payment_level == PAYMENT_LEVEL_DISPLAY_ONLY)


# ── 选择结果与门控 ─────────────────────────────────────────────


@dataclass(frozen=True)
class ParamSelection:
    """参数选择结果：未通过门控时 outcome=unknown，绝不静默默认采用。"""

    param: EmployeeOutpatientParam | None
    outcome: BranchOutcome
    reason_code: str | None = None


def _gate(param: EmployeeOutpatientParam) -> str | None:
    """确认状态/日期门控。返回 None 表示可采用，否则返回 reason_code。"""
    if param.confirmation_status == "待确认":
        return "PARAM_CONFIRMATION_PENDING"
    if param.confirmation_status == "文档明确-待官方核证" and not param.effective_date_explicit:
        return "PARAM_EFFECTIVE_DATE_UNCLEAR"
    if param.expiry_date is None and not param.expiry_open_ended:
        return "PARAM_EXPIRY_UNKNOWN"
    return None


def select_param(
    candidates: tuple[EmployeeOutpatientParam, ...],
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


def _by_prefix(prefix: str) -> tuple[EmployeeOutpatientParam, ...]:
    return tuple(p for p in PARAMS if p.rule_id.startswith(prefix))


def select_deductible_param(person_kind: PersonKind, settlement_date: date) -> ParamSelection:
    """门诊大额起付标准：在职 1800（历史 2000）/退休 1300（历史 1500），按结算日期选版本。"""
    if person_kind == PersonKind.UNKNOWN:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PERSON_KIND_UNKNOWN")
    return select_param(
        tuple(p for p in _by_prefix("EOP-DED-") if p.person_kind == person_kind),
        settlement_date,
    )


def select_big_pay_rate_param(
    person_kind: PersonKind,
    age_band: str | None,
    institution_kind: InstitutionKind,
    settlement_date: date,
) -> ParamSelection:
    """门诊大额基础支付比例选择。

    合计展示层次（EOP-RATE-201/202/203/303）与超 2 万段（EOP-RATE-301/302）不在候选内。
    退休 ≥70 周岁档（EOP-RATE-110）不区分机构，机构维度不评估（not_evaluated 由调用方记录）。
    """
    if person_kind == PersonKind.UNKNOWN:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PERSON_KIND_UNKNOWN")
    candidates = [
        p
        for p in _by_prefix("EOP-RATE-1")
        if p.person_kind == person_kind and p.segment == "base"
    ]
    # 退休档按年龄带过滤；在职无年龄维度
    age_scoped = [p for p in candidates if p.age_band is None or p.age_band == age_band]
    if not age_scoped:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "AGE_BAND_UNKNOWN")
    inst_scoped = [
        p for p in age_scoped if p.institution_kind is None or p.institution_kind == institution_kind
    ]
    if not inst_scoped and age_scoped and any(p.institution_kind for p in age_scoped):
        return ParamSelection(None, BranchOutcome.UNKNOWN, "INSTITUTION_KIND_UNKNOWN")
    return select_param(tuple(inst_scoped), settlement_date)


def select_excess_segment_param(person_kind: PersonKind, settlement_date: date) -> ParamSelection:
    """2023-01-01 起超 2 万基金支付段比例（60%）。"""
    if person_kind == PersonKind.UNKNOWN:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PERSON_KIND_UNKNOWN")
    return select_param(
        tuple(
            p
            for p in PARAMS
            if p.segment == "excess_20k"
            and p.payment_level != PAYMENT_LEVEL_DISPLAY_ONLY
            and p.person_kind == person_kind
        ),
        settlement_date,
    )


def select_cap_param(settlement_date: date) -> ParamSelection:
    """门诊大额年度最高支付限额（2 万元，2022-12-31 前）。"""
    return select_param(_by_prefix("EOP-CAP-"), settlement_date)


def select_material_rule(fee_date: date) -> ParamSelection:
    """贵重医用材料门槛/纳入比例版本：按费用发生日期选择（500 元档历史 / 1000 元档现行）。"""
    if fee_date >= _D(2023, 1, 1):
        low = select_param(_by_prefix("EOP-MAT-003"), fee_date)
        high = select_param(_by_prefix("EOP-MAT-004"), fee_date)
        if low.outcome != BranchOutcome.TRUE:
            return low
        if high.outcome != BranchOutcome.TRUE:
            return high
        return select_param(_by_prefix("EOP-MAT-004"), fee_date)
    return select_param(
        tuple(p for p in _by_prefix("EOP-MAT-00") if p.rule_id in ("EOP-MAT-001", "EOP-MAT-002")),
        fee_date,
    )


def select_check_fee_param(fee_date: date) -> ParamSelection:
    """门诊检查费单价限额（200 元/8%）。生效日期未明确且待官方核证 → unknown。"""
    return select_param(_by_prefix("EOP-CAT-008"), fee_date)


def select_retire_supplement_param(retirement_category: str, settlement_date: date) -> ParamSelection:
    """退休补充保险比例：普通 50% / 预提 60%；类别未知不默认 50%。"""
    rule_id = {"normal": "EOP-RSUP-001", "prepaid": "EOP-RSUP-002"}.get(retirement_category)
    if rule_id is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "RETIREMENT_CATEGORY_UNKNOWN")
    return select_param((get_param(rule_id),), settlement_date)


def select_military_param(person_kind: PersonKind, grade: str, fee_date: date) -> ParamSelection:
    """军残补助比例：在职5-6级70%/在职1-4级100%/退休5-6级50%/退休1-4级100%。"""
    key = (person_kind, grade)
    rule_id = {
        (PersonKind.EMPLOYED, "5-6"): "EOP-DVET-001",
        (PersonKind.EMPLOYED, "1-4"): "EOP-DVET-002",
        (PersonKind.RETIRED, "5-6"): "EOP-DVET-003",
        (PersonKind.RETIRED, "1-4"): "EOP-DVET-004",
    }.get(key)
    if rule_id is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "MILITARY_GRADE_UNKNOWN")
    return select_param((get_param(rule_id),), fee_date)


def select_public_medical_param(branch: str, settlement_date: date) -> ParamSelection:
    """公疗目标基金比例：退休 95% / 在职 90% / 在乡残疾军人 100%。"""
    rule_id = {
        "retired": "EOP-PMED-001",
        "employed": "EOP-PMED-002",
        "rural_disabled_veteran": "EOP-PMED-003",
    }.get(branch)
    if rule_id is None:
        return ParamSelection(None, BranchOutcome.UNKNOWN, "PUBLIC_MEDICAL_BRANCH_UNKNOWN")
    return select_param((get_param(rule_id),), settlement_date)


def select_rounding_param() -> ParamSelection:
    """取整规则 EOP-RND-001：待确认，永远返回 unknown；取整模式须显式传入。"""
    return ParamSelection(
        None, BranchOutcome.UNKNOWN, "PARAM_CONFIRMATION_PENDING"
    )
