"""计算展示名称注册表（解释投影 1.1，方案 §中文公式与统一字段名）。

formula_id → 公开中文展示名与算式布局。约束：
- 中文名复用结算事实字段的公开名称口径，不另起一套命名；
- 未注册的 formula_id 一律回落"计算步骤"，不回显内部实现名；
- 本表只做显示映射：不另行算钱、不补比例、不猜未知公式；
- layout 仅描述操作数展示方式：sum=操作数带符号相连（减项已存负值）；
  subtract_rest=首项减其余各项（操作数符号统一归一化）；product=基数×比例；
  generic=逐项列出（不断言加减方向）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormulaDisplay:
    display_name: str
    layout: str  # "sum" / "subtract_rest" / "product" / "generic"


#: 未注册公式的保守回落（不回显内部实现名）
_FALLBACK = FormulaDisplay(display_name="计算步骤", layout="generic")

_REGISTRY: dict[str, FormulaDisplay] = {
    "ordinary_first_segment_base_v1": FormulaDisplay("基金累计2万元以内段基数", "generic"),
    "ordinary_segment_pay_v1": FormulaDisplay("本段基金支付", "product"),
    "age_full_years_v1": FormulaDisplay("结算日已满周岁", "generic"),
    "special_retire_supplement_total_v1": FormulaDisplay("退休补助合计", "sum"),
    "secondary_db_deductible_v1": FormulaDisplay("大病本次起付标准", "generic"),
    "secondary_db_first_rate_v1": FormulaDisplay("大病首段采用比例", "generic"),
    "secondary_db_second_rate_v1": FormulaDisplay("大病第二段采用比例", "generic"),
    "secondary_personal_base_v1": FormulaDisplay("补助后合规个人负担", "generic"),
    "secondary_resident_personal_base_v1": FormulaDisplay("合规个人负担", "sum"),
    "secondary_current_base_v1": FormulaDisplay("本笔合规个人负担总基数", "sum"),
    "secondary_remaining_base_v1": FormulaDisplay("大病后合规剩余总基数", "sum"),
    "secondary_first_band_base_v1": FormulaDisplay("大病首段费用交集", "generic"),
    "secondary_second_band_base_v1": FormulaDisplay("大病第二段费用交集", "generic"),
    "copay_base_v1": FormulaDisplay("报销基数（扣减后）", "subtract_rest"),
    "cycle_coordinate_exact_v1": FormulaDisplay("周期内交易前费用坐标", "generic"),
    "cycle_coordinate_lower_bound_v1": FormulaDisplay("周期费用坐标下界", "generic"),
    "special_segment_base_v1": FormulaDisplay("本段报销基数", "generic"),
    "special_segment_self_ratio_v1": FormulaDisplay("本段实际自付比例", "generic"),
    "special_pool_base_v1": FormulaDisplay("统筹段报销基数", "generic"),
    # 职工/居民普通门诊共享模块
    "deductible_split_v1": FormulaDisplay("起付线拆分", "generic"),
    "resident_deductible_interval_v1": FormulaDisplay("居民起付线（分档）", "generic"),
    "big_pay_capped_v1": FormulaDisplay("大额支付（封顶后）", "generic"),
    "big_pay_segmented_v1": FormulaDisplay("大额分段支付", "generic"),
    "big_self_pay_v1": FormulaDisplay("大额自付（差额）", "subtract_rest"),
    "resident_big_pay_clamp_v1": FormulaDisplay("居民大额支付（封顶）", "generic"),
    "cap_room_v1": FormulaDisplay("年度封顶余额（封顶线−交易前已支付）", "generic"),
    "retire_supplement_v1": FormulaDisplay("退休补助", "product"),
    "military_supplement_v1": FormulaDisplay("军残补助", "product"),
    "public_medical_topup_v1": FormulaDisplay("公疗补助", "generic"),
    # 目录划分（明细级）
    "catalog_self_pay_2_v1": FormulaDisplay("明细先行自付", "product"),
    "drug_unit_price_limit_v1": FormulaDisplay("药品单价限额调整", "generic"),
    "catalog_unit_price_limit_v1": FormulaDisplay("单价限额调整", "generic"),
    "material_price_limit_v1": FormulaDisplay("材料单价限额调整", "generic"),
    "ncp_excess_final_ratio_v1": FormulaDisplay("超限额最终比例", "generic"),
    "material_included_ratio_v1": FormulaDisplay("材料纳入比例", "product"),
    # 目录划分汇总（逐行合计，解释投影 1.1）
    "catalog_total_fee_v1": FormulaDisplay("费用明细合计", "sum"),
    "catalog_total_in_scope_v1": FormulaDisplay("医保内费用合计", "sum"),
    "catalog_total_out_scope_v1": FormulaDisplay("医保外费用合计", "sum"),
    "catalog_total_self_pay_2_v1": FormulaDisplay("先行自付合计", "sum"),
    "catalog_total_proportional_self_pay_v1": FormulaDisplay("比例先行负担合计", "sum"),
    # 职工门特（按项目付费）
    "observed_deductible_passthrough_v1": FormulaDisplay("起付线（按结算记录）", "generic"),
    "special_deductible_split_v1": FormulaDisplay("门特起付线拆分", "generic"),
    "special_pool_segmented_v1": FormulaDisplay("统筹基金分段支付", "generic"),
    "special_pool_self_pay_v1": FormulaDisplay("统筹自付（支付后差额）", "sum"),
    "special_pool_self_pay_residual_v1": FormulaDisplay("统筹剩余自付（扣除退休补助）", "sum"),
    "special_large_self_pay_residual_v1": FormulaDisplay("大额剩余自付（扣除退休补助）", "sum"),
    "special_large_self_pay_zero_v1": FormulaDisplay("大额自付（未进入大额段）", "generic"),
    "special_large_settle_zero_v1": FormulaDisplay("大额基金支付（未进入大额段）", "generic"),
    "special_large_fund_v1": FormulaDisplay("大额基金支付", "generic"),
    "special_retire_supplement_pool_v1": FormulaDisplay("退休补助（统筹段）", "generic"),
    "special_retire_supplement_large_v1": FormulaDisplay("退休补助（大额段）", "generic"),
    "special_military_supplement_v1": FormulaDisplay("军残补助", "product"),
    "special_public_medical_v1": FormulaDisplay("公疗补助", "generic"),
    "special_detail_sum_v1": FormulaDisplay("明细医保内费用合计", "sum"),
    "special_detail_fee_sum_v1": FormulaDisplay("总费用（明细逐行合计）", "sum"),
    "special_detail_out_sum_v1": FormulaDisplay("医保外费用合计", "sum"),
    "special_detail_advance_sum_v1": FormulaDisplay("个人自付二合计", "sum"),
    # 肾/肝肾定额
    "fixed_quota_minus_original_self_pay": FormulaDisplay("医院定额基金（定额口径）", "generic"),  # 含限额坐标，不是各操作数相加
    "fixed_actual_self_pay": FormulaDisplay("定额范围内原始自付（含起付）", "sum"),
    # 居民普通门诊
    "resident_bigill_pay_v1": FormulaDisplay("大病保险支付", "product"),
    "resident_bigill_sp2_v1": FormulaDisplay("大病先行自付", "product"),
    "resident_bigill_excluded_plus_advance_v1": FormulaDisplay("医保外费用（含先行自付）", "sum"),
    "resident_bigill_personal_remainder_v1": FormulaDisplay("大病后个人剩余", "subtract_rest"),
    "resident_bigill_self_pay_all_v1": FormulaDisplay("大病后最终个人承担（差额）", "subtract_rest"),
    "resident_msf_full_pay_v1": FormulaDisplay("医事服务费支付（限额内全额）", "product"),
    # 居民门特
    "resident_special_deductible_v1": FormulaDisplay("居民门特起付线", "generic"),
    "resident_special_big_pay_clamp_v1": FormulaDisplay("居民门特大额支付（封顶）", "generic"),
    # 二次保障（大病/救助，secondary_coverage 按 name 动态生成 formula_id）
    "secondary_self_pay_1_v1": FormulaDisplay("补助后合规自付一", "generic"),
    "secondary_proportional_self_pay_2_v1": FormulaDisplay("比例先行自付", "generic"),
    "secondary_annual_prior_v1": FormulaDisplay("交易前年度累计", "generic"),
    "secondary_db_band_total_v1": FormulaDisplay("大病分段支付合计", "generic"),
    "secondary_feein_db_pay_v1": FormulaDisplay("大病支付（医保内）", "product"),
    "secondary_feeout_db_pay_v1": FormulaDisplay("大病支付（医保外）", "product"),
    "secondary_big_ill_pay_v1": FormulaDisplay("大病保险支付合计", "sum"),
    "secondary_feein_maf_pay_v1": FormulaDisplay("救助支付（医保内）", "generic"),
    "secondary_feeout_maf_pay_v1": FormulaDisplay("救助支付（医保外）", "generic"),
    "secondary_civil_in_v1": FormulaDisplay("民政救助", "generic"),
    "secondary_person_payable_v1": FormulaDisplay("二次保障后个人应付", "generic"),
    "secondary_after_db_one_v1": FormulaDisplay("大病后医保内剩余自付", "generic"),
    "secondary_after_db_two_v1": FormulaDisplay("大病后比例先行负担剩余", "generic"),
    "secondary_civil_cap_room_v1": FormulaDisplay("救助剩余额度", "generic"),
    # 账面恒等式（各链通用；仅核对账面分量关系）
    "identity_fee_all_v1": FormulaDisplay("总费用账面恒等（医保内＋医保外）", "sum"),
    "identity_self_pay_1_v1": FormulaDisplay("自付一账面勾稽", "subtract_rest"),
    "identity_fund_pay_v1": FormulaDisplay("基金合计账面勾稽", "sum"),
    # 自付一按本单独立计算分量分解（起付承担＋大额个人自付），非账面恒等
    "self_pay_1_components_v1": FormulaDisplay("个人支付自付（一）金额", "sum"),
    # 最终个人承担按本单独立计算分量重算（起付＋医保外＋大额自付－补助）
    "self_pay_all_components_v1": FormulaDisplay("最终个人承担", "sum"),
    # 基金合计按已列示基金渠道重算（统筹/大额/补助）
    "fund_total_components_v1": FormulaDisplay("基金支付金额", "sum"),
    "identity_listed_fund_pay_v1": FormulaDisplay("基金合计（按原单已列示支付构成）", "sum"),
    "identity_self_pay_all_v1": FormulaDisplay("最终个人承担账面勾稽", "sum"),
    "identity_self_pay_all_vs_fund_v1": FormulaDisplay("最终个人承担对照（总费用−基金）", "sum"),
    "identity_self_pay_channel_v1": FormulaDisplay("最终个人承担渠道勾稽（账户＋现金）", "sum"),
    "identity_xjzf_channel_v1": FormulaDisplay("现金＋账户支付账面勾稽", "sum"),
    "identity_agency_pay_v1": FormulaDisplay("机构支付合计账面勾稽", "sum"),
    "identity_fixed_agency_pay_v1": FormulaDisplay("医院垫付基金合计勾稽", "sum"),
    "identity_quota_balance_v1": FormulaDisplay("医院定额账面勾稽", "sum"),
}

#: 动态 formula_id 前缀回落（预留；当前 secondary_* 已逐项登记）
_PREFIX_REGISTRY: tuple[tuple[str, FormulaDisplay], ...] = ()


def formula_display(formula_id: str) -> FormulaDisplay:
    """按 formula_id 取公开展示名与布局；未注册回落保守默认。"""
    hit = _REGISTRY.get(formula_id)
    if hit is not None:
        return hit
    for prefix, display in _PREFIX_REGISTRY:
        if formula_id.startswith(prefix):
            return display
    return _FALLBACK


def rounding_display(rule: str | None) -> str | None:
    """只翻译已记录的取整方式，保留待确认说明及规则编号。"""
    if rule is None:
        return None
    if rule == "settlement_record":
        return "按本单结算金额"
    for code, label in {"round_half_up": "四舍五入到分", "round_half_even": "五成双舍入到分",
                        "round_up": "远离零方向进位到分", "round_down": "向零方向截取到分",
                        "explicit:": "按本次配置：", "not_applicable": "无取整"}.items():
        rule = rule.replace(code, label)
    return rule
