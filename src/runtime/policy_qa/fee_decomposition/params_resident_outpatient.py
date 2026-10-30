"""Issue #80 城乡居民门诊待遇参数模块。

数值与规则 ID 的唯一来源：
``docs/superpowers/specs/2026-10-13-issue80-城乡居民门诊待遇参数.csv``
（下称参数表）。本模块把参数表逐行编码为显式 Python 数据结构，复用职工门诊
参数基类与门控选择函数（``params_employee_outpatient`` 的 ParamSelection/
select_param/_gate），仅新增居民维度：

- 起付/支付比例按**机构等级档**（InstitutionLevelTier）分档，不区分在职/退休身份
  （2018-01-01 新政策，mz.docx 城乡居民基本医疗保险-门诊§）；
- 封顶线 3000（2018）→4000（2020-01-01）→4500（2021-01-01）按结算日期选版本；
- 目录划分规则（药品/诊疗/材料）与职工基本相同（mz.docx 居民节明示），
  计算层复用 ``catalog_split`` 与 EOP-CAT/EOP-MAT/EOP-NCP 系列规则（ROP-CAT-000），
  不重复编码；
- 医事服务费通道（ROP-MSF-001）：T_CureType=17/18 院内扩展码（字典 300 未覆盖，
  语义待确认，实证 100% 基金支付且不累计门急诊待遇）；
- 取整规则 ROP-RND-001 与职工 EOP-RND-001 同源待确认：取整模式显式入参，无默认。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    InstitutionLevelTier,
)
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient import (
    EmployeeOutpatientParam,
    ParamSelection,
    select_param,
)

#: 居民门诊参数记录类型（复用职工参数基类，机构等级档维度经 institution_tier 承载）
ResidentOutpatientParam = EmployeeOutpatientParam

#: Issue #80 居民人员类别候选集合（PN_PersonType；字典 290 全为城镇居民身份；
#: 2018 新政策起付/比例不区分人群，本集合仅用于留痕与核对，不进入支付计算）
RESIDENT_PERSON_TYPE_CODES = frozenset(
    {"14", "15", "16", "17", "18", "19", "20", "50", "70", "80"}
)

#: 医事服务费结算通道的院内医疗类别扩展码（字典 300 未覆盖，语义待确认，
#: 实证：明细全为医事服务费、T_BigPay=T_FeeIn 全额基金支付、T_FirstPay=0）
MSF_CURE_TYPE_CODES = frozenset({"17", "18"})

#: 普通门诊待遇通道的医疗类别码（11=字典确认普通门诊；19=院内扩展码，
#: 实证与 11 同一门诊大额待遇公式闭合，语义待确认）
OUTPATIENT_CURE_TYPE_CODES = frozenset({"11", "19"})


# ── 参数表逐行编码 ─────────────────────────────────────────────

_D = date
_DEC = Decimal
_TIER1 = InstitutionLevelTier.LEVEL_1_AND_BELOW
_TIER2 = InstitutionLevelTier.LEVEL_2_AND_ABOVE

PARAMS: tuple[ResidentOutpatientParam, ...] = (
    # ── 起付线（2018 新政策按机构等级档分档；历史档不区分机构） ──
    ResidentOutpatientParam(
        rule_id="ROP-DED-001", category="起付线", name="门诊起付标准-一级及以下医疗机构",
        applies_to="城乡居民·一级及以下（含未评级）定点医疗机构", value=_DEC("100"),
        value_text=None, unit="元/保险年度", payment_level="不适用",
        basis="医保内门诊费用年度累计（交易前；TB_FeeIn 口径实证交易前，同职工 D3/D5）；两类机构分别累计",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§新政策（2018年1月1日生效）",
        remark="未评级医疗机构与一级同档",
        institution_tier=_TIER1,
    ),
    ResidentOutpatientParam(
        rule_id="ROP-DED-002", category="起付线", name="门诊起付标准-二级及以上医疗机构",
        applies_to="城乡居民·二级及以上定点医疗机构", value=_DEC("550"),
        value_text=None, unit="元/保险年度", payment_level="不适用",
        basis="医保内门诊费用年度累计（交易前；TB_FeeIn 口径实证交易前，同职工 D3/D5）；两类机构分别累计",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§新政策（2018年1月1日生效）",
        remark="实证：样本 011100030X240913000154（TB_FeeIn=527，FirstPay=23=550-527）",
        institution_tier=_TIER2,
    ),
    ResidentOutpatientParam(
        rule_id="ROP-DED-101", category="起付线", name="门诊起付标准-老年人（历史）",
        applies_to="城镇居民老年人", value=_DEC("200"), value_text=None,
        unit="元/保险年度", payment_level="不适用", basis="医保内门诊费用年度累计",
        date_basis="结算日期", effective_date=_D(2009, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 12, 31), expiry_open_ended=False,
        version="V2009-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-门诊§旧政策（2009年1月1日生效）",
        remark="2011-01-01 起调整为 650 元",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-DED-102", category="起付线", name="门诊起付标准-全居民（历史）",
        applies_to="城镇居民（学生儿童/老年人/无业人员）", value=_DEC("650"), value_text=None,
        unit="元/保险年度", payment_level="不适用", basis="医保内门诊费用年度累计",
        date_basis="结算日期", effective_date=_D(2011, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2017, 12, 31), expiry_open_ended=False,
        version="V2011-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-门诊§旧政策（2011年1月1日生效）",
        remark="2018-01-01 起按机构等级分档（100/550）",
    ),
    # ── 支付比例（2018 新政策按机构等级档；历史档不区分机构） ──
    ResidentOutpatientParam(
        rule_id="ROP-RATE-001", category="支付比例", name="门诊基金支付比例-一级及以下（含未评级）",
        applies_to="城乡居民·一级及以下及未评级定点医疗机构", value=_DEC("55"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用超起付标准部分（共付段）；受年度封顶线约束",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§新政策（2018年1月1日生效）",
        institution_tier=_TIER1,
    ),
    ResidentOutpatientParam(
        rule_id="ROP-RATE-002", category="支付比例", name="门诊基金支付比例-二级及以上",
        applies_to="城乡居民·二级及以上定点医疗机构", value=_DEC("50"), value_text=None,
        unit="%", payment_level="基础支付",
        basis="医保内门诊费用超起付标准部分（共付段）；受年度封顶线约束",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§新政策（2018年1月1日生效）",
        remark="实证：011100030X240408000002（T_BigPay=1597.50=T_FeeIn 3195×50%，H_LEVEL=02）",
        institution_tier=_TIER2,
    ),
    ResidentOutpatientParam(
        rule_id="ROP-RATE-101", category="支付比例", name="门诊基金支付比例-全居民（历史）",
        applies_to="城镇居民", value=_DEC("50"), value_text=None,
        unit="%", payment_level="基础支付", basis="医保内门诊费用累计超起付标准部分",
        date_basis="结算日期", effective_date=_D(2011, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2017, 12, 31), expiry_open_ended=False,
        version="V2011-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-门诊§旧政策（2011年1月1日生效）",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-RATE-102", category="支付比例", name="门诊基金支付比例-老年人（历史）",
        applies_to="城镇居民老年人", value=_DEC("50"), value_text=None,
        unit="%", payment_level="基础支付", basis="起付标准以上部分门诊医疗费用",
        date_basis="结算日期", effective_date=_D(2009, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 12, 31), expiry_open_ended=False,
        version="V2009-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-门诊§旧政策（2009年1月1日生效）",
    ),
    # ── 封顶线 ──
    ResidentOutpatientParam(
        rule_id="ROP-CAP-001", category="封顶线", name="门诊基金年度最高支付限额（2018）",
        applies_to="城乡居民", value=_DEC("3000"), value_text=None, unit="元/保险年度",
        payment_level="不适用", basis="基金年度累计支付额（基金支付口径，非费用累计）",
        date_basis="结算日期", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2019, 12, 31), expiry_open_ended=False,
        version="V2018-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-门诊§封顶线",
        remark="2020-01-01 起调整为 4000 元",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-CAP-002", category="封顶线", name="门诊基金年度最高支付限额（2020）",
        applies_to="城乡居民", value=_DEC("4000"), value_text=None, unit="元/保险年度",
        payment_level="不适用", basis="基金年度累计支付额（基金支付口径，非费用累计）",
        date_basis="结算日期", effective_date=_D(2020, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2020, 12, 31), expiry_open_ended=False,
        version="V2020-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-门诊§封顶线",
        remark="2021-01-01 起调整为 4500 元",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-CAP-003", category="封顶线", name="门诊基金年度最高支付限额（2021 起）",
        applies_to="城乡居民", value=_DEC("4500"), value_text=None, unit="元/保险年度",
        payment_level="不适用",
        basis="基金年度累计支付额（基金支付口径；TB_BigPay 实证交易前口径，同职工 D4）",
        date_basis="结算日期", effective_date=_D(2021, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2021-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§封顶线",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-CAP-101", category="封顶线", name="门诊基金年度最高支付限额-老年人（历史）",
        applies_to="城镇居民老年人", value=_DEC("500"), value_text=None, unit="元/保险年度",
        payment_level="不适用", basis="基金年度累计支付额",
        date_basis="结算日期", effective_date=_D(2009, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2010, 12, 31), expiry_open_ended=False,
        version="V2009-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-门诊§旧政策（2009年1月1日生效）",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-CAP-102", category="封顶线", name="门诊基金年度最高支付限额-全居民（历史）",
        applies_to="城镇居民", value=_DEC("2000"), value_text=None, unit="元/保险年度",
        payment_level="不适用", basis="基金年度累计支付额",
        date_basis="结算日期", effective_date=_D(2011, 1, 1), effective_date_explicit=True,
        expiry_date=_D(2017, 12, 31), expiry_open_ended=False,
        version="V2011-01-01", validity_status="历史", confirmation_status="文档明确",
        source="mz.docx 城乡居民基本医疗保险-门诊§旧政策（2011年1月1日生效）",
    ),
    # ── 无待遇（居民口径：PN_NoRightReason 非空即全额自费） ──
    ResidentOutpatientParam(
        rule_id="ROP-NRB-001", category="无待遇", name="无待遇原因全额自费",
        applies_to="城乡居民·PN_NoRightReason 非空", value=None,
        value_text="PN_NoRightReason 有值时全部费用划入医保外个人自费（FeeIn=0/FeeOut=Fee）",
        unit="规则", payment_level="划分规则", basis="整笔交易费用",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知（不得默认长期有效）
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="GitHub Issue #80 原文；实证 25/25 笔非空交易全部 T_FeeIn=0 全额自费",
        remark="取值含 '3'/'4'/'5'/'3^5' 复合码；码值含义待签核",
    ),
    # ── 医事服务费通道 ──
    ResidentOutpatientParam(
        rule_id="ROP-MSF-001", category="医事服务费", name="医事服务费通道-基金全额支付",
        applies_to="城乡居民·医事服务费结算交易（T_CureType=17/18 院内扩展码，字典300未覆盖语义待确认）",
        value=_DEC("100"), value_text=None, unit="%", payment_level="基础支付",
        basis="划入医保支付范围的医事服务费（目录限额内部分）",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 医事服务费§划入医保支付范围部分全部由医保基金支付，个人无需负担",
        remark="实证：17/18 类交易 T_BigPay=T_FeeIn、T_FirstPay=0；不累计门急诊医疗待遇（不占起付/封顶累计）",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-MSF-101", category="医事服务费定额", name="医事服务费定额-三级-普通门诊",
        applies_to="三级定点医疗机构", value=_DEC("40"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="门诊医事服务费；超出定额部分划入个人自付二（医保外）",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 医事服务费；yb_xzzlfwxm 目录 w0101020010/0011 限额 xb=40 实证",
        remark="计算层经目录限额列（xb）分解，本参数仅溯源；副主任医师档同按 40 限额（账面实证）",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-MSF-106", category="医事服务费定额", name="医事服务费定额-三级-急诊",
        applies_to="三级定点医疗机构", value=_DEC("60"), value_text=None, unit="元/人次",
        payment_level="定额支付", basis="急诊医事服务费；超出定额部分划入个人自付二（医保外）",
        date_basis="结算日期", effective_date=_D(2017, 4, 8), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2017-04-08", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 医事服务费；yb_xzzlfwxm 目录 w0101020019 限额 xb=60 实证",
        remark="计算层经目录限额列（xb）分解，本参数仅溯源",
    ),
    # ── 大病保险（门诊大额封顶后渠道，候选口径） ──
    ResidentOutpatientParam(
        rule_id="ROP-BIGILL-001", category="大病保险", name="门诊大额封顶后大病保险支付",
        applies_to="城乡居民·门诊大额年度累计已达封顶（交易前 TB_BigPay≥封顶线）·救助渠道未支付",
        value=_DEC("75"), value_text=None, unit="%", payment_level="大病支付",
        basis="门诊大额封顶后合规费用（含先行自付纳入基数，住院式口径：FeeAll×比例）",
        date_basis="结算日期", effective_date=_D(2021, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2021-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="实证：240914 组 3 笔 FundPay=FeeAll×75%（135/67.5/−135 含退费镜像）；"
               "患者 TB_BigillComm 大病累计 18.8 万；75% 与居民住院三级比例一致",
        remark="候选口径（n=3 同人同日）；大病渠道字段 T_BigillPay；"
               "判定需同时满足救助渠道（NT_CivilPay）未支付，待签核",
    ),
    # ── 医疗救助（渠道存在性检测，口径未确认不计算） ──
    ResidentOutpatientParam(
        rule_id="ROP-CIVIL-001", category="医疗救助", name="民政救助支付渠道",
        applies_to="城乡居民·医疗救助对象（P_CivilFlag=1）",
        value=None,
        value_text="救助支付 NT_CivilPay 冲抵个人负担；年度救助封顶 8000 元（实证 6401.64+1598.36=8000.00 截断）",
        unit="规则", payment_level="救助支付", basis="救助口径与冲抵顺序未确认",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="待确认",
        source="实证：5975 救助 8 元冲抵自付二（10→2）；6969 救助 1598.36 被 8000 封顶截断",
        remark="救助存在时交易级 FeeOut/SelfPay2/SelfPay1/BigSelfPay 口径含救助冲抵，"
               "内核这些字段标 not_verifiable 不判定对错",
    ),
    # ── 退费 ──
    ResidentOutpatientParam(
        rule_id="ROP-REF-001", category="退费", name="门诊退费-完全退费",
        applies_to="城乡居民",
        value=None,
        value_text="以原交易明细费用按数量取负值形成退费发生额；以退费时卡内门诊年度待遇累计为准，按原交易参保身份与医保政策分解",
        unit="规则", payment_level="不适用",
        basis="被退交易明细费用（负值）；退费时点 TB_FeeIn/TB_BigPay 交易前口径累计",
        date_basis="原交易结算时间", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§退费",
        remark="内核以区间重叠公式统一正负交易（实证 8 笔退费全闭合）",
    ),
    ResidentOutpatientParam(
        rule_id="ROP-REF-002", category="退费", name="门诊退费-部分退费（2018年1季度）",
        applies_to="城乡居民",
        value=None,
        value_text="先以退费时点累计生成完全退费交易，再以完全退费后累计生成重收交易；跨年度以被退年度年终累计为基础",
        unit="规则", payment_level="不适用", basis="被退交易已医保分割的费用明细",
        date_basis="原交易结算时间", effective_date=_D(2018, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2018Q1", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§部分退费",
        remark="实证：T_PartialReturnFlag=1 交易为完全退费形态（000155 退 000154、000156 重收），区间公式闭合",
    ),
    # ── 目录划分沿用（计算层复用 split_catalog，EOP-CAT/MAT/NCP 系列） ──
    ResidentOutpatientParam(
        rule_id="ROP-CAT-000", category="目录规则", name="目录划分沿用职工规则",
        applies_to="城乡居民",
        value=None,
        value_text="药品与诊疗服务设施的医保内外划分同城镇职工基本相同，但不执行社区慢病用药优惠与社区慢病干预治疗政策",
        unit="规则", payment_level="划分规则", basis="逐项药品/诊疗/材料费用",
        date_basis="费用发生日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§药品的医保内外划分/诊疗服务设施的医保内外划分",
        remark="社区慢病优惠在职工实现中本未编码（EOP-CAT-005 无计算分支），复用零差异",
    ),
    # ── 医疗类别扩展码（字典未覆盖，语义待确认） ──
    ResidentOutpatientParam(
        rule_id="ROP-CURE-001", category="医疗类别", name="门诊医疗类别院内扩展码",
        applies_to="城乡居民",
        value=None,
        value_text="T_CureType=19 实证为普通门诊待遇通道（与 11 同一公式闭合）；17/18 实证为医事服务费结算通道；字典 300 未覆盖 17/18/19",
        unit="规则", payment_level="不适用", basis="不适用",
        date_basis="结算日期", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="待确认",
        source="yb_zdxm flid=300 字典未覆盖；59 笔回放公式闭合实证",
        remark="签核前全部结果附 CURE_TYPE_EXTENSION_SEMANTICS_UNCONFIRMED 不确定性",
    ),
    # ── 保险年度 ──
    ResidentOutpatientParam(
        rule_id="ROP-YEAR-001", category="年度口径", name="保险年度",
        applies_to="全部参保人", value=None,
        value_text="自然年度（1月1日-12月31日）；学生儿童 2007-09-01 起曾为学年，2011-01-01 起统一自然年",
        unit="规则", payment_level="不适用", basis="不适用",
        date_basis="结算日期", effective_date=_D(2011, 1, 1), effective_date_explicit=True,
        expiry_date=None, expiry_open_ended=True,
        version="V2011-01-01", validity_status="现行", confirmation_status="文档明确-待官方核证",
        source="mz.docx 城乡居民基本医疗保险-门诊§保险年度",
    ),
    # ── 取整（待确认：模式必须由计算调用方显式传入） ──
    ResidentOutpatientParam(
        rule_id="ROP-RND-001", category="取整", name="费用分解取整规则",
        applies_to="全部参保人",
        value=None,
        value_text="逐行/逐段/汇总取整的适用层级及取整模式文档均未明确（与职工 EOP-RND-001 同源待确认）",
        unit="规则", payment_level="不适用", basis="全部计算金额",
        date_basis="不适用", effective_date=None, effective_date_explicit=False,
        expiry_date=None, expiry_open_ended=False,  # 未知
        version="V-未标注", validity_status="现行", confirmation_status="待确认",
        source="mz.docx 未记载；设计文档 §9 要求取整模式必须有版本",
        remark="禁止凭习惯默认取整模式；一分钱差异保留不抹平",
    ),
)

_PARAM_BY_ID = {p.rule_id: p for p in PARAMS}


def get_param(rule_id: str) -> ResidentOutpatientParam:
    """按规则 ID 取参数（不存在抛 KeyError）。"""
    return _PARAM_BY_ID[rule_id]


def try_get_param(rule_id: str) -> ResidentOutpatientParam | None:
    """按规则 ID 取参数，不存在返回 None。"""
    return _PARAM_BY_ID.get(rule_id)


# ── 机构等级档分类与参数选择 ────────────────────────────────────


def classify_institution_tier(h_level: str | None) -> InstitutionLevelTier:
    """机构等级档分类：H_LEVEL>=10（含 14=未评级）→ 一级及以下；0<=level<10 → 二级及以上；
    缺失/非法 → 未知（不默认任何档）。
    """
    if h_level is None:
        return InstitutionLevelTier.UNKNOWN
    try:
        level = int(str(h_level).strip())
    except ValueError:
        return InstitutionLevelTier.UNKNOWN
    if level < 0:
        return InstitutionLevelTier.UNKNOWN
    return (
        InstitutionLevelTier.LEVEL_1_AND_BELOW
        if level >= 10
        else InstitutionLevelTier.LEVEL_2_AND_ABOVE
    )


def _by_prefix(prefix: str) -> tuple[ResidentOutpatientParam, ...]:
    return tuple(p for p in PARAMS if p.rule_id.startswith(prefix))


def select_resident_deductible_param(
    tier: InstitutionLevelTier, settlement_date: date
) -> ParamSelection:
    """居民门诊起付标准：2018 起一级及以下 100 / 二级及以上 550；历史档 200/650。

    机构档未知时：若该日期只有不分档历史版本适用仍可选择（历史档 tier=None）；
    2018 起必须已知机构档，否则 unknown（不默认任何档）。
    """
    if tier == InstitutionLevelTier.UNKNOWN:
        tier_scoped = tuple(p for p in _by_prefix("ROP-DED-") if p.institution_tier is None)
        if not tier_scoped:
            return ParamSelection(None, BranchOutcome.UNKNOWN, "INSTITUTION_TIER_UNKNOWN")
        sel = select_param(tier_scoped, settlement_date)
        if sel.outcome == BranchOutcome.TRUE:
            return sel
        return ParamSelection(None, BranchOutcome.UNKNOWN, "INSTITUTION_TIER_UNKNOWN")
    return select_param(
        tuple(
            p
            for p in _by_prefix("ROP-DED-")
            if p.institution_tier is None or p.institution_tier == tier
        ),
        settlement_date,
    )


def select_resident_big_pay_rate_param(
    tier: InstitutionLevelTier, settlement_date: date
) -> ParamSelection:
    """居民门诊基金支付比例：2018 起一级及以下（含未评级）55% / 二级及以上 50%；历史档 50%。"""
    if tier == InstitutionLevelTier.UNKNOWN:
        tier_scoped = tuple(p for p in _by_prefix("ROP-RATE-") if p.institution_tier is None)
        if not tier_scoped:
            return ParamSelection(None, BranchOutcome.UNKNOWN, "INSTITUTION_TIER_UNKNOWN")
        sel = select_param(tier_scoped, settlement_date)
        if sel.outcome == BranchOutcome.TRUE:
            return sel
        return ParamSelection(None, BranchOutcome.UNKNOWN, "INSTITUTION_TIER_UNKNOWN")
    return select_param(
        tuple(
            p
            for p in _by_prefix("ROP-RATE-")
            if p.institution_tier is None or p.institution_tier == tier
        ),
        settlement_date,
    )


def select_resident_cap_param(settlement_date: date) -> ParamSelection:
    """居民门诊基金年度封顶线：3000（2018）→4000（2020-01-01）→4500（2021-01-01）。"""
    return select_param(_by_prefix("ROP-CAP-"), settlement_date)
