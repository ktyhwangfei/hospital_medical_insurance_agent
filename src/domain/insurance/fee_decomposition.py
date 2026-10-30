"""结算费用分解领域值对象（Issue #78）。

依据 docs/superpowers/specs/2026-09-24-issue78-outpatient-fee-decomposition-design.md：
- §5 输入快照、§8 分支轨迹三值逻辑、§9 精度（Decimal、取整模式显式）、§10 核对结果。

本模块只放不可变业务值对象（frozen dataclass）与纯值函数，不含任何计算流程编排；
编排与规则计算在 ``src/runtime/policy_qa/fee_decomposition/``。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
from enum import StrEnum


# ── 枚举（值对象） ─────────────────────────────────────────────


class BranchOutcome(StrEnum):
    """分支轨迹三值逻辑及扩展状态（设计 §8）。"""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"
    NOT_EVALUATED = "not_evaluated"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class CheckType(StrEnum):
    """核对类型（设计 §10 固定三类）。"""

    INDEPENDENT_RECALCULATION = "independent_recalculation"
    DETAIL_AGGREGATION = "detail_aggregation"
    IDENTITY_CHECK = "identity_check"


class CheckStatus(StrEnum):
    """单字段核对结果（设计 §10）。"""

    MATCHED = "matched"
    MISMATCHED = "mismatched"
    NOT_VERIFIABLE = "not_verifiable"
    NOT_APPLICABLE = "not_applicable"


class ExecutionStatus(StrEnum):
    """总体执行状态轴（设计 §10）。"""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ExplanationLevel(StrEnum):
    """字段解释等级（设计 §11）。"""

    CAUSALLY_EXPLAINED = "causally_explained"
    AMOUNT_RECONCILED = "amount_reconciled"
    OBSERVED_ONLY = "observed_only"
    UNEXPLAINED = "unexplained"


class RoundingMode(StrEnum):
    """取整模式。EOP-RND-001 待确认，必须显式传入，无默认值（设计 §9）。"""

    HALF_UP = "round_half_up"
    HALF_EVEN = "round_half_even"
    UP = "round_up"
    DOWN = "round_down"


class PersonKind(StrEnum):
    """人员身份分类（在职/退休/未知；未知不默认在职）。"""

    EMPLOYED = "employed"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class InstitutionKind(StrEnum):
    """机构类别（社区/其他/未知）。"""

    COMMUNITY = "community"
    OTHER = "other"
    UNKNOWN = "unknown"


class InstitutionLevelTier(StrEnum):
    """机构等级档（居民门诊起付/支付比例分档维度，Issue #80）。

    按 m_institution.H_LEVEL 数值分档：>=10 为一级及以下（含 14=未评级，
    政策明确未评级与一级同档 55%）；<10 为二级及以上；缺失/非法为未知。
    """

    LEVEL_1_AND_BELOW = "level_1_and_below"
    LEVEL_2_AND_ABOVE = "level_2_and_above"
    UNKNOWN = "unknown"


class CatalogKind(StrEnum):
    """明细所属目录类别。"""

    DRUG = "drug"
    SERVICE = "service"
    MATERIAL = "material"
    UNKNOWN = "unknown"


class PackagingType(StrEnum):
    """集采药品包装类型（整包/拆包；未给定时按规则默认整包）。"""

    WHOLE_PACK = "whole_pack"
    SPLIT_PACK = "split_pack"


# ── 输入快照（值对象） ─────────────────────────────────────────


@dataclass(frozen=True)
class TradeAnchor:
    """交易锚点：唯一定位、时点与冲正识别（设计 §5.2）。"""

    trade_no: str
    trade_date: date  # 结算日期候选（T_TradeDate，是否即结算日期须适配层核实）
    hospital_code: str  # 费用发生机构
    is_reversal: bool = False  # 冲正/退款交易标记
    original_trade_no: str | None = None  # 原交易关联单号
    # 无待遇原因码（PN_NoRightReason）：'4'/'5' 实证为全额自费结算（决策记录 D15）；
    # 居民口径（Issue #80）：非空即全额自费（取值含 '3'/'4'/'5'/'3^5' 复合码）
    no_right_reason: str | None = None
    # 医疗类别码原值（T_CureType，Issue #80 居民通道分流依据：11/19 门诊大额通道、
    # 17/18 医事服务费通道候选）；职工内核不消费该字段
    cure_type: str | None = None
    # 险种码原值（P_FundType；居民='91'/'92'/'93'），仅留痕核对，不作分流依据
    fund_type: str | None = None


@dataclass(frozen=True)
class PersonProfile:
    """人员身份与特殊待遇资格快照。未知一律 None，禁止由金额反推资格。"""

    person_type_code: str | None  # PN_PersonType 原始代码
    birth_date: date | None
    # 退休补充保险：普通 normal / 预提 prepaid；退休身份已知但类别未知时为 None
    retirement_category: str | None = None
    retire_supplement_enroll_date: date | None = None  # 纳入补充保险起始日期
    # 军残资格
    is_disabled_veteran: bool | None = None
    military_disability_grade: str | None = None  # "1-4" / "5-6"
    military_disability_level_code: str | None = None  # 原始伤残待遇等级，0=不享受；空值不是0
    military_eligible_from: date | None = None  # 军残资格生效日期（费用发生日期口径）
    military_eligible_to: date | None = None
    # 公疗资格
    is_rural_disabled_veteran: bool | None = None  # 在乡残疾军人
    public_medical_eligible: bool | None = None  # 公疗资格（派生口径，受门控）
    public_medical_designated: bool | None = None  # 费用发生在本人定点医疗机构
    # 原单资格码表事实：只用于解释“为什么是 0”，不据此派生资格（派生仍受门控）
    public_medical_flag: str | None = None
    public_medical_treatment_code: str | None = None
    retire_officer_flag: str | None = None  # 原单退役医疗费标志，仅保留事实，不由此推导待遇


@dataclass(frozen=True)
class InstitutionProfile:
    """机构快照：H_LEVEL/H_TYPE 原值保留，分支判断在计算层完成。

    H_TYPE 为社区判定主依据（字典 k80：04=社区卫生站 06=村卫生室，决策记录 D9）；
    H_LEVEL=14 实测为「未评级」而非社区，S1 候选「14=社区」假设已废弃。
    """

    hospital_code: str
    h_level: str | None  # 医院等级（字典 310），保留原值
    h_type: str | None = None  # 医院类型（字典 k80），社区判定主依据


@dataclass(frozen=True)
class AnnualAccumulation:
    """年度累计上下文。口径未确认的标志位为 False 时计算层保留轨迹不硬算。"""

    # 交易前同年度医保内费用累计（起付 A 与公疗 A_in；口径一致须显式确认）
    prior_in_scope_fee: Decimal | None
    prior_in_scope_fee_is_pre_trade: bool = False
    # 交易前同年度基金支付累计（封顶与超 2 万段口径；不得以费用累计替代）
    prior_fund_payment: Decimal | None = None
    prior_fund_payment_is_pre_trade: bool = False
    # 起付累计口径与公疗 1300 门槛累计口径是否确认一致（设计 §7.5.4）
    in_scope_basis_aligned: bool = False
    # 累计值是否为“可证下界”（如仅同人同年本院历史推导，跨院缺失）：下界不等于真实累计，
    # 依赖它的支付/封顶结论不得标记为已独立算平。
    prior_is_lower_bound: bool = False
    # 本交易增量恒等式自证（阶段 E）：TB_Year==交易年且 TA−TB==T 两条恒等式成立
    # （容差 0.005，与探针一致）时由服务层置 True。仅证明院内 HIS 表内一致；
    # 跨院累计不在本院库，口径待业务签核。
    self_proven: bool = False


@dataclass(frozen=True)
class OriginalPolicyContext:
    """退费原单的已确认政策身份；累计年度属于被退年度，非退费当天年度。"""

    policy_date: date
    person: PersonProfile
    institution: InstitutionProfile
    insurance_type: str
    medical_category: str
    accumulation_year: int | None
    cure_type: str | None = None
    no_right_reason: str | None = None


@dataclass(frozen=True)
class FeeLineItem:
    """费用明细行快照：账面值原样保留，独立计算值另存。"""

    line_key: str  # 候选行键（ItemId/ItemNo），重复即数据异常
    item_code: str
    catalog_kind: CatalogKind  # 目录类别由适配层按 ItemType 等确认后给出
    fee: Decimal  # 账面费用
    fee_occurrence_date: date  # 费用发生日期（目录匹配与军残资格的日期依据）
    item_type: str | None = None  # ItemType 原值（0=药品）
    fee_type: str | None = None  # 账面收费类别（与目录 sflb 冲突时停未知）
    unit_price: Decimal | None = None
    count: Decimal | None = None
    fee_in: Decimal | None = None
    fee_out: Decimal | None = None
    self_pay_2: Decimal | None = None
    # 明细行结算事实（决策记录 D17/D18）：实际先行自付比例 / 结算时限价；None 或 0 = 未维护
    medic_l: Decimal | None = None
    sp_scale: Decimal | None = None
    packaging_type: PackagingType | None = None  # 集采包装类型，None 按规则默认整包
    consistency_evaluation_passed: bool | None = None  # 集采一致性评价
    is_check_fee: bool = False  # 门诊检查费（EOP-CAT-008 单价限额候选）


@dataclass(frozen=True)
class DrugCatalogEntry:
    """药品目录条目。expiry_date 为 None 时不默认永久有效（设计 §5.3）。"""

    entry_id: str
    item_code: str
    effective_date: date | None
    expiry_date: date | None
    sflb: str | None = None  # 收费类别：无自付/有自付/全自付（或甲/乙/丙）
    self_pay_ratio: Decimal | None = None  # 原自付比例
    a_ypbs: bool = False  # 集采标识
    a_mzxj: Decimal | None = None  # 门诊限价（整包：最小包装单位）
    a_xbbl: Decimal | None = None  # 集采超限价自付比例（最终比例语义，决策记录 D19）
    ncp_unit_limit: Decimal | None = None  # 拆包：最小制剂单位限价
    ypfl: str | None = None  # 药品分类（16/6 为自制剂候选）
    bzjg: Decimal | None = None  # 自制剂标准价格
    preparation_hospital_code: str | None = None  # 自制剂所属机构
    special_disease_marker: str | None = None  # tsbyybz，特殊病适用标志原值，普通门诊不消费
    a_ypbs_known: bool = False  # 仅解释用：空值/未识别值不能陈述为已确认非集采
    a_ypbs_raw: str | None = None  # 原始标志仅留在快照，不改变既有真假映射


@dataclass(frozen=True)
class ServiceCatalogEntry:
    """诊疗项目及服务设施目录条目。"""

    entry_id: str
    item_code: str
    effective_date: date | None
    expiry_date: date | None
    sfxmdj: str | None = None  # 1=无自付 2=有自付 3=全自付；空必须未知
    self_pay_ratio: Decimal | None = None
    unit_price_limit: Decimal | None = None  # 单价限额（超出部分入自付二）
    special_disease_marker: str | None = None  # tsbbz，特殊病适用标志


@dataclass(frozen=True)
class MaterialCatalogEntry:
    """医用材料目录条目。"""

    entry_id: str
    item_code: str
    effective_date: date | None
    expiry_date: date | None
    is_artificial_organ: bool = False  # 人工器官（EOP-MAT-005 例外，政策参数未覆盖）
    is_centralized_selected: bool = False  # 集采中选（同上例外）
    special_disease_marker: str | None = None  # tsbbz，特殊病适用标志
    sfxmdj: str | None = None  # 收费项目等级（同表 yb_xzzlfwxm：1 无自付/2 有自付/3 全自付），仅用于目录属性展示


@dataclass(frozen=True)
class ObservedSettlementAmounts:
    """结算账面观测值：仅作核对目标，不作为同字段重算输入。None 表示未知（不是零）。"""

    fee_all: Decimal | None = None  # T_FeeAll 总费用
    fee_in: Decimal | None = None  # T_FeeIn 医保内
    fee_out: Decimal | None = None  # T_FeeOut 医保外
    self_pay_2: Decimal | None = None  # T_SelfPay2 自付二
    first_pay: Decimal | None = None  # T_FirstPay 本次起付承担
    big_pay: Decimal | None = None  # T_BigPay 大额支付
    big_self_pay: Decimal | None = None  # T_BigSelfPay 大额个人自付
    bc_pay: Decimal | None = None  # T_BCPay 退休补充补助
    jc_pay: Decimal | None = None  # T_JCPay 军残支付
    official_pay: Decimal | None = None  # T_OfficalPay 公疗补充支付
    self_pay_1: Decimal | None = None  # T_SelfPay1 自付一
    fund_pay: Decimal | None = None  # T_FundPay 基金合计
    self_pay_all: Decimal | None = None  # T_SelfPayAll 最终个人承担
    person_count_pay: Decimal | None = None  # T_PersonCountPay 账户支付
    cash_pay: Decimal | None = None  # T_CashPay 现金支付
    # 居民门诊扩展渠道观测值（Issue #80）：大病保险支付（T_BigillPay）与
    # 民政救助支付（NT_CivilPay）。仅用于渠道存在性检测与账面恒等核对，
    # 不作同字段重算输入；None=未知不是零
    bigill_pay: Decimal | None = None
    civil_pay: Decimal | None = None
    retire_officer_pay: Decimal | None = None  # 退役医疗费支付：可参与其他金额的账面构成，不独立推导本项待遇


@dataclass(frozen=True)
class DecompositionSnapshot:
    """固定输入快照：同一快照无论问哪个字段都得到同一计算结果（设计 §4/§9）。"""

    settlement_ref: str
    insurance_type: str  # 标准险种：employee（首期唯一支持）
    medical_category: str  # 标准医疗类别：outpatient（首期唯一支持）
    trade: TradeAnchor
    person: PersonProfile
    institution: InstitutionProfile
    accumulation: AnnualAccumulation
    items: tuple[FeeLineItem, ...]
    observed: ObservedSettlementAmounts
    rounding_mode: RoundingMode  # 取整模式显式传入（EOP-RND-001 待确认，无默认）
    drug_catalog: tuple[DrugCatalogEntry, ...] = ()
    service_catalog: tuple[ServiceCatalogEntry, ...] = ()
    material_catalog: tuple[MaterialCatalogEntry, ...] = ()
    # 本单是否另有非零基金渠道（T_FundPay 候选公式适用性；None=未知）
    has_other_fund_channels: bool | None = None
    original_policy_context: OriginalPolicyContext | None = None


# ── 门特（门诊特殊病，视同住院）输入快照（Issue #78 第二流程） ──
#
# 字段语义均为 bjyb 门诊套表（yb_brdjxx/yb_mzjyxx/yb_mzfymx）实测候选口径，
# 待数据字典确认（参数表 ESP-CODE-001..003，实测待码表确认）。


@dataclass(frozen=True)
class SpecialFeeLineItem:
    """门特费用明细行快照（yb_mzfymx）。账面值原样保留，行键重复即数据异常。"""

    line_key: str  # djh+xh 中的 xh（行号）
    item_code: str  # xmdm 项目编码
    fee: Decimal  # zje 金额
    item_name: str | None = None  # xmmc 项目名称
    sflb: str | None = None  # 收费类别
    self_pay_level: str | None = None  # sfxmdj 自付档：1 无自付/2 有自付/3 全自付；空=未知
    in_scope_fee: Decimal | None = None  # ybnje 医保内
    out_scope_fee: Decimal | None = None  # ybwje 医保外
    full_self_pay_advance: Decimal | None = None  # grziftw 先行自付（ybwje 中先行自付部分）
    unit_price: Decimal | None = None  # dj 单价
    quantity: Decimal | None = None  # sl 数量
    fee_date: date | None = None  # fsrq 费用发生日期


@dataclass(frozen=True)
class SpecialObservedAmounts:
    """门特结算账面观测值（yb_mzjyxx，14 字段）：仅作核对目标，None=未知不是零。"""

    zje: Decimal | None = None  # 总费用
    ybn: Decimal | None = None  # 医保内
    ybw: Decimal | None = None  # 医保外
    ybnqfje: Decimal | None = None  # 本次起付金额
    tczhf: Decimal | None = None  # 统筹基金支付
    tczif: Decimal | None = None  # 统筹自付
    degwyzhf: Decimal | None = None  # 大额互助支付
    degwyzif: Decimal | None = None  # 大额自付
    bczhf: Decimal | None = None  # 退休补助
    jczhf: Decimal | None = None  # 军残补助
    gfylbchbx: Decimal | None = None  # 公疗补助
    xjzf: Decimal | None = None  # 现金支付
    zhzf: Decimal | None = None  # 账户支付
    grziftw: Decimal | None = None  # 先行自付（结算口径，=Σ明细 grziftw）
    big_ill_pay: Decimal | None = None  # 基本医保和补助后的二次大病保险
    civil_in: Decimal | None = None  # 医疗救助
    feein_db_pay: Decimal | None = None
    feeout_db_pay: Decimal | None = None
    feein_maf_pay: Decimal | None = None
    feeout_maf_pay: Decimal | None = None
    retire_officer_pay: Decimal | None = None  # 军休渠道仅作账面渠道核对，不反推其规则


@dataclass(frozen=True)
class SecondaryCoverageContext:
    """二次保障年度快照；时点未知时不把累计当作交易前事实。"""

    big_ill_scope_total: Decimal | None = None  # BIG_ILL_SUM_IN 合规个人负担累计
    civil_fund_payment_total: Decimal | None = None  # CIVIL_SUM_PAY 年度救助支付
    is_post_trade: bool | None = None
    evidence_status: str = "unknown"
    evidence_note: str = ""


@dataclass(frozen=True)
class SpecialCycleContext:
    """门特结算周期/年度累计上下文。

    院端数据抽取无法完整重建周期状态（第几周期、周期内已交起付、年度基金累计），
    evidence_status 三态：
    - "confirmed"：累计证据完整，可独立重算；
    - "assumed"：评估口径假定值，可算但全部下游字段仅为勾稽级（amount_reconciled）；
    - "unknown"：证据不足，起付及统筹/大额字段 not_verifiable。
    """

    deductible_standard: Decimal | None = None  # 适用起付标准（1300/650）
    prior_cycle_deductible_paid: Decimal | None = None  # 本周期内交易前已交起付
    prior_annual_pool_fund_payment: Decimal | None = None  # 交易前年度统筹基金累计支付
    prior_annual_large_fund_payment: Decimal | None = None  # 交易前年度大额互助基金累计支付
    # 周期内交易前医保内费用累计（yb_dyxxtsb.bqljybnje 交易后口径 − 本笔 tsbybn）：
    # confirmed 时给出，作为统筹分段绝对坐标起点；None=未知（按下界/守卫规则处理）
    prior_cycle_in_scope_total: Decimal | None = None
    # 周期位置（Issue #81 居民门特起付分档判定）："first" 年度第一个住院类结算周期
    # （bnzqslj<=1）/ "subsequent" 第二及以后；None=未知（职工流程不使用，保持 None）
    cycle_position: str | None = None
    evidence_status: str = "unknown"
    evidence_note: str = ""
    confirmed_fields: tuple[str, ...] = ()  # 分字段证据，稀疏累计仅阻断依赖缺项的计算

    def is_confirmed(self, *fields: str) -> bool:
        """字段非空且有已确认来源；其他累计缺失不抹掉本字段证据。"""
        return all(getattr(self, name) is not None for name in fields) and (
            self.evidence_status == "confirmed"
            or all(name in self.confirmed_fields for name in fields)
        )


@dataclass(frozen=True)
class SpecialPersonProfile:
    """门特人员快照（yb_brdjxx）。未知一律 None，禁止由金额反推资格。"""

    cblb: str | None  # 人员类别码（'11' 在职候选；'21'/'61' 退休候选；其他=未知）
    birth_date: date | None = None  # csrq 出生日期
    special_record_start: date | None = None  # tsbqsrq 特殊病备案起始（备案有效期，非结算周期）
    special_record_end: date | None = None  # tsbjzrq 特殊病备案截止
    # 退休补充类别：normal 普通 / prepaid 社会化（预提）；字段未映射时 None=未知（不默认 50%）
    retirement_category: str | None = None
    # 军残等级组（Issue #79 字段映射候选口径：yb_brdjxx.cjjrdj）：
    # "1-4" / "5-6"；None=无资格或未知（raw 为空/'0' 视为无资格候选）
    military_grade: str | None = None
    military_grade_raw: str | None = None  # cjjrdj 原值留痕
    # 公疗（公务员/公费医疗）资格（Issue #79 字段映射候选口径：yb_brdjxx.gwydybz，
    # 与红名单相反：0=享受，1=不享受）；None=字段缺失未知
    civil_medical_eligible: bool | None = None
    civil_type: str | None = None  # v_CIVIL_TYPE 救助身份；None不默认非救助


@dataclass(frozen=True)
class SpecialInstitutionProfile:
    """门特机构快照。h_level 原值保留，住院口径等级映射在计算层完成。"""

    hospital_code: str
    h_level: str | None  # m_institution H_LEVEL 原值


@dataclass(frozen=True)
class KidneyFixedQuotaContext:
    """肾/肝肾抗排异定额条件输入；定额账面值不等于独立核定的日标准。"""

    special_codes: tuple[str, ...] = ()
    designated_hospital_flag: str | None = None
    quota_amount: Decimal | None = None
    medication_start: date | None = None
    medication_end: date | None = None
    cycle_start: date | None = None
    initial_self_pay_observed: Decimal | None = None
    agency_pay_observed: Decimal | None = None


@dataclass(frozen=True)
class OutpatientSpecialSnapshot:
    """门特（职工×门诊特殊病）固定输入快照。"""

    settlement_ref: str
    insurance_type: str  # 标准险种：employee
    medical_category: str  # 标准医疗类别：outpatient_special
    djh: str  # 登记号（门诊套表键）
    settle_date: date  # jyrq 结算日期
    admit_date: date | None  # ryrq 入院/登记日期
    yllb: str | None  # 医疗类别码（'12'=门诊特殊病）
    fund_type: str | None  # 险种码（'3'=城镇职工）
    person: SpecialPersonProfile
    institution: SpecialInstitutionProfile
    cycle: SpecialCycleContext
    items: tuple[SpecialFeeLineItem, ...]
    observed: SpecialObservedAmounts
    rounding_mode: RoundingMode  # 取整模式显式传入（ESP-RND-001 待确认，无默认）
    # 评估口径开关（默认 False）：cycle context 非 confirmed 时允许取账面 ybnqfje
    # 作为条件输入继续计算（deductible.source=observed_book，勾稽级非因果级）
    allow_observed_deductible: bool = False
    # 评估口径开关（默认 False，Issue #79 mz 套表流程启用）：分段绝对坐标
    # （cycle.prior_cycle_in_scope_total）未知时，若无法证明唯一比例分配，
    # 统筹/大额字段 not_verifiable（SEGMENT_COORDINATE_UNDERDETERMINED），
    # 不按坐标下界硬算（与封顶「未跨界可证明才可算」同一原则）
    segment_coordinate_guard: bool = False
    secondary_coverage: SecondaryCoverageContext = SecondaryCoverageContext()
    proportional_self_pay_2: Decimal | None = None  # 目录独立划分的合规先行负担，不含超限价
    kidney_fixed_quota: KidneyFixedQuotaContext | None = None


# ── 轨迹与核对记录（值对象） ───────────────────────────────────


@dataclass(frozen=True)
class BranchCondition:
    """分支条件：条件代码、中文含义、比较操作及左右值（设计 §8）。"""

    code: str
    description: str
    operator: str  # in / eq / ge / lt / range_contains 等
    actual_value: str | None = None
    expected_ref: str | None = None  # 期望值或规则引用


@dataclass(frozen=True)
class BranchTrace:
    """分支轨迹记录（设计 §8）。父分支未进入的子分支为 not_evaluated 并注明原因。"""

    step_id: str
    module_id: str
    outcome: BranchOutcome
    parent_step_id: str | None = None
    scope_ref: str | None = None  # 交易或具体明细行引用
    condition: BranchCondition | None = None
    reason_code: str | None = None
    input_refs: tuple[str, ...] = ()
    rule_refs: tuple[str, ...] = ()
    calculation_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CalculationOperand:
    """计算操作数：引用与值同时保留（设计 §8）。"""

    ref: str
    value: str  # 十进制字符串


@dataclass(frozen=True)
class CalculationRecord:
    """计算记录：公式标识/版本、操作数、未取整结果、取整规则、最终金额（设计 §8/§9）。"""

    calculation_id: str
    formula_id: str
    formula_version: str
    operands: tuple[CalculationOperand, ...] = ()
    unrounded_result: str | None = None
    rounding_rule: str | None = None
    result: str | None = None  # 十进制字符串；未得出结果时为 None


@dataclass(frozen=True)
class DecompositionUncertainty:
    """不确定性声明：缺规则/缺数据必须显式列出，不得静默补全。"""

    id: str
    code: str
    message: str
    affected_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecompositionCitation:
    """证据引用（设计 §9：来源区分 issue_note/approved_business_rule/policy_document/source_catalog）。"""

    id: str
    kind: str
    ref: str
    value: str | None = None
    values: tuple[str, ...] = ()
    approval_status: str | None = None


@dataclass(frozen=True)
class FieldReconciliation:
    """字段级核对结果（设计 §10）：difference 统一为 calculated - observed，一分钱差异保留。"""

    field_code: str
    label: str
    check_type: CheckType
    check_status: CheckStatus
    observed_amount: str | None = None
    calculated_amount: str | None = None
    difference: str | None = None
    explanation_level: ExplanationLevel = ExplanationLevel.UNEXPLAINED
    reason_code: str | None = None
    calculation_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()
    uncertainty_refs: tuple[str, ...] = ()


# ── 纯值函数 ──────────────────────────────────────────────────

ROUNDING_MODE_MAP = {
    RoundingMode.HALF_UP: ROUND_HALF_UP,
    RoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
    RoundingMode.UP: ROUND_UP,
    RoundingMode.DOWN: ROUND_DOWN,
}

CENT = Decimal("0.01")


def apply_rounding(value: Decimal, mode: RoundingMode, quantum: Decimal = CENT) -> Decimal:
    """按显式取整模式取整（默认到分）。取整规则 EOP-RND-001 待确认，模式无默认值。"""
    return value.quantize(quantum, rounding=ROUNDING_MODE_MAP[mode])


def decimal_to_str(value: Decimal) -> str:
    """金额/比例统一输出十进制字符串（如 "123.45"、"0.80"），不经过 float。

    负零保留符号（"-0.00"）：恒等式/差额记录的减项取负后经本函数落记录，
    公开公式按值是否以 "-" 开头渲染 ＋/－，丢符号会把减项渲染成加号。
    注意一元取负 ``-x`` 对零丢符号（十进制上下文 0-x 语义），减项取负必须用
    ``value.copy_negate()``。
    """
    if value == 0 and value.is_signed():
        return "-" + format(value.copy_abs(), "f")
    return format(value, "f")
