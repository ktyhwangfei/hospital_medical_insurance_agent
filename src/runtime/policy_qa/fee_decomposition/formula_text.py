"""已执行算式的中文代入展示；仅格式化操作数和结果，不重新算钱。"""
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from src.runtime.policy_qa.fee_decomposition.formula_display import formula_display


_EXCESS_DECIMALS = re.compile(r"(?<![\d.])(-?\d+)\.(\d{2})(0+)(?![\d])")


def trim_trailing_zeros(text: str | None) -> str | None:
    """只压缩“两位小数之外的纯 0”冗余（3195.000000→3195.00，2304.500000→2304.50）。

    - 金额展示保留两位小数；
    - 数量/单价/比例的有效精度（0.125、0.0005、0.090）保持原值；
    - 版本、编码、日期等非数值文本不匹配（2024.0101、12.34567 原样保留）。
    """
    if not text:
        return text
    return _EXCESS_DECIMALS.sub(lambda m: f"{m.group(1)}.{m.group(2)}", text)


def calculation_formula(calc: Any, operands: list[dict[str, Any]]) -> str | None:
    if calc.result is None:
        return None
    values = [op.value for op in calc.operands]
    fid = calc.formula_id
    name = formula_display(fid).display_name
    if calc.rounding_rule == "settlement_record":
        return f"{name}：按本单结算记录采用 {calc.result} 元"
    expression = None
    if fid == "ordinary_first_segment_base_v1" and len(values) == 4:
        expression = f"较小值（总基数 {values[0]}，最大值（基金分界 {values[3]}－交易前基金累计 {values[1]}，0）÷基础比例 {values[2]}）"
    if fid == "age_full_years_v1" and len(values) == 2:
        return f"{name}＝年份差 {values[0]}－本年生日未到扣减 {values[1]}＝{calc.result} 周岁"
    if fid in ("secondary_db_first_rate_v1", "secondary_db_second_rate_v1") and len(values) == 2:
        return f"{name}＝基础比例 {values[0]}＋身份加成 {values[1]}＝{calc.result}"
    if fid == "secondary_db_deductible_v1" and len(values) == 2:
        expression = f"基础起付标准 {values[0]}÷身份除数 {values[1]}"
    elif fid == "secondary_personal_base_v1" and len(values) == 6:
        expression = f"最大值（本次起付 {values[0]}＋统筹自付 {values[1]}＋大额自付 {values[2]}－退休补助 {values[3]}－军残补助 {values[4]}－公疗补助 {values[5]}，0）"
    elif fid in ("secondary_first_band_base_v1", "secondary_second_band_base_v1") and len(values) == 4:
        prior, base, deductible, width = values
        expression = (f"最大值（较小值（{prior}＋{base}，{deductible}＋{width}）－最大值（{prior}，{deductible}），0）" if fid == "secondary_first_band_base_v1" else
                      f"最大值（{prior}＋{base}－最大值（{prior}，{deductible}＋{width}），0）")
    if fid == "special_segment_self_ratio_v1" and len(values) == 3:
        return f"{name}＝最大值（在职自付比例 {values[0]}×身份折算系数 {values[1]}－减点 {values[2]}，0）＝{calc.result}"
    elif fid == "special_segment_base_v1" and len(values) == 5:
        prior, paid, base, lower, upper = values
        end = f"{prior}＋{paid}＋{base}"
        expression = f"最大值（较小值（{end}，{upper}）－最大值（{prior}＋{paid}，{lower}），0）"
    elif fid == "cycle_coordinate_exact_v1" and len(values) == 1:
        expression = f"交易前周期医保内累计 {values[0]}"
    elif fid == "cycle_coordinate_lower_bound_v1" and len(values) == 2:
        expression = f"最大值（起付标准 {values[0]}－本次起付 {values[1]}，0）（仅下界）"
    elif fid == "special_pool_base_v1" and len(values) == 3:
        expression = f"交易前统筹支付累计 {values[1]} 已达封顶 {values[2]} 时为0，否则采用本次共付基数 {values[0]}（本笔跨封顶时阻断）"
    elif fid in ("deductible_split_v1", "special_deductible_split_v1", "resident_special_deductible_v1") and len(values) == 3:
        e, a, d = values
        expression = f"较小值（医保内费用 {e} 元，最大值（起付标准 {d} 元－交易前已累计 {a} 元，0））"
    elif fid == "resident_deductible_interval_v1" and len(values) == 3:
        e, a, d = values
        # 交易前累计已覆盖起付标准时直说"已达到标准"，不让用户从区间端点自行推断（评审问题 3）。
        try:
            if Decimal(a) >= Decimal(d) and Decimal(e) > 0 and Decimal(calc.result) == 0:
                return (f"{name}：交易前已累计 {a} 元已达到起付标准 {d} 元，"
                        f"本次费用 {e} 元无需再承担起付，本次起付 {calc.result} 元")
        except InvalidOperation:
            pass
        expression = f"费用方向×最大值（较小值（累计区间上端，标准 {d}）－最大值（累计区间下端，0），0）；本次费用 {e} 元，累计区间端点为 {a} 与 {a}＋（{e}）"
    elif fid == "big_pay_capped_v1" and len(values) == 4:
        base, rate, prior, cap = values
        expression = f"较小值（基数 {base} 元×支付比例 {rate}，最大值（封顶 {cap} 元－已支付 {prior} 元，0）），再按本次规则取整"
    elif fid == "cap_room_v1" and len(values) == 2:
        expression = f"封顶 {values[0]} 元－交易前已支付 {values[1]} 元"
    elif fid in ("resident_big_pay_clamp_v1", "resident_special_big_pay_clamp_v1") and len(values) >= 4:
        base, rate, prior, cap = values[:4]
        expression = f"较小值（最大值（取整（基数 {base} 元×比例 {rate}），－交易前已支付 {prior} 元），最大值（封顶 {cap} 元－已支付 {prior} 元，0））"
    elif fid == "big_pay_segmented_v1" and len(values) >= 8:
        # 逐段给出"段内基金×比例＝段基金支付"，并代入交易前基金累计，全部可复算。
        # 交易前累计放段首括注：拼在尾部会被函数末尾的"＝结果"读成"累计＝结果"假等式；
        # 末尾等号挂在两段合计上（合计＝首段＋后段，恒为真实末项）。
        _, rate, prior, excess, first_pay, rest_pay, first_base, rest_base = values[:8]
        expression = (f"（交易前基金累计 {prior} 元）"
                      f"首段基金支付＝基金累计2万元以内段基数 {first_base} 元×首段比例 {rate}＝{first_pay} 元；"
                      f"后段基金支付＝超2万元段基数 {rest_base} 元×后段比例 {excess}＝{rest_pay} 元；"
                      f"两段合计 {first_pay}＋{rest_pay}")
    elif fid == "big_pay_segmented_v1" and len(values) >= 6:
        # 分段基金支付已各自算出：直接相加，不再留"首段费用/后段费用"符号（否则无法复算）。
        base, rate, prior, excess, first_pay, rest_pay = values[:6]
        expression = (f"首段基金支付 {first_pay} 元＋后段基金支付 {rest_pay} 元；"
                      f"总基数 {base} 元、交易前基金累计 {prior} 元、首段比例 {rate}、后段比例 {excess}")
    elif fid == "big_pay_segmented_v1" and len(values) >= 4:
        base, rate, prior, excess = values[:4]
        expression = f"取整（首段费用×{rate}）＋取整（后段费用×{excess}）；总基数 {base} 元、交易前基金累计 {prior} 元，首段费用＝较小值（总基数，最大值（20000－累计，0）÷{rate}），后段费用＝总基数－首段费用"
    elif fid == "special_pool_segmented_v1":
        terms = []
        for i, op in enumerate(calc.operands):
            if op.ref.endswith(".self_ratio") and i:
                terms.append(f"取整（本段费用 {values[i-1]} 元×（1－本段实际自付比例 {values[i]}））")
        if terms:
            expression = "＋".join(terms)
    elif fid == "special_large_fund_v1" and len(values) == 3:
        expression = f"取整（大额段基数 {values[0]} 元×（1－最大值（1－基本支付比例 {values[1]}－自付比例降低值 {values[2]}，0）））"
    elif fid == "special_large_self_pay_zero_v1" and len(values) == 1:
        expression = f"本笔大额段基数 {values[0]} 元，未进入大额段，自付为0"
    elif fid == "special_large_settle_zero_v1" and len(values) == 1:
        expression = f"本笔大额段基数 {values[0]} 元，未进入大额段，基金支付为 0"
    elif fid == "military_supplement_v1" and len(values) == 3:
        expression = f"取整（（共付段自付 {values[0]} 元－退休补助 {values[1]} 元）×军残补助比例 {values[2]}）"
    elif fid == "special_military_supplement_v1" and len(values) == 4:
        labels = ("起付自付",
                  "统筹剩余自付" if calc.operands[1].ref.endswith("_residual") else "统筹自付",
                  "大额剩余自付" if calc.operands[2].ref.endswith("_residual") else "大额自付")
        expression = "＋".join(f"取整（{label} {value} 元×补助比例 {values[3]}）" for label, value in zip(labels, values[:3]))
    elif fid == "public_medical_topup_v1" and len(values) == 3:
        expression = f"取整（最大值（公疗基数 {values[0]} 元×目标比例 {values[1]}－该范围已支付 {values[2]} 元，0））"
    elif fid == "special_public_medical_v1" and len(values) == 9:
        f, b, pool, large, rsup, dvet, c, d, a = values
        expression = f"取整（起付 {f} 元×最大值（起付内目标比例 {c}－军残比例 {a}，0））＋取整（最大值（支付基数 {b} 元×起付外目标比例 {d}－统筹 {pool} 元－大额 {large} 元－退休 {rsup} 元－军残 {dvet} 元＋起付 {f} 元×军残比例 {a}，0））"
    elif fid == "fixed_quota_minus_original_self_pay" and len(values) >= 2:
        expression = f"医院核定定额 {values[0]} 元－定额范围原始自付 {values[1]} 元"
    elif fid in ("special_retire_supplement_pool_v1", "special_retire_supplement_large_v1") and len(values) == 2:
        expression = f"取整（本段个人自付 {values[0]} 元×退休补助比例 {values[1]}）"
    elif fid == "secondary_person_payable_v1" and len(values) == 4:
        expression = f"补助后合规自付一 {values[0]} 元＋医保外费用 {values[1]} 元－大病支付 {values[2]} 元－医疗救助 {values[3]} 元"
    elif fid == "secondary_civil_in_v1" and len(values) == 2:
        expression = f"医保内分桶救助 {values[0]} 元＋比例先行负担分桶救助 {values[1]} 元"
    elif fid in ("secondary_feein_db_pay_v1", "secondary_feeout_db_pay_v1") and len(values) == 3:
        expression = ("合规基数为零，不发生本桶大病支付" if Decimal(values[1]) == 0 else
            f"取整（本笔大病分段支付 {values[2]} 元×本桶合规自付 {values[0]} 元÷本笔合规总基数 {values[1]} 元）")
    elif fid == "secondary_db_band_total_v1" and len(values) == 8:
        prior, base, threshold, width, first, rate1, second, rate2 = values
        expression = f"第一段重叠 {first} 元×比例 {rate1}＋第二段重叠 {second} 元×比例 {rate2}；交易前累计 {prior} 元、本笔合规基数 {base} 元、起付标准 {threshold} 元、首段宽度 {width} 元"
    elif fid == "secondary_annual_prior_v1" and len(values) == 3:
        expression = f"来源累计 {values[0]} 元－本笔合规基数 {values[1]} 元" if values[2] == "1" else f"直接采用交易前累计 {values[0]} 元"
    elif fid in ("secondary_self_pay_1_v1", "secondary_proportional_self_pay_2_v1") and len(values) == 1:
        expression = f"直接采用已分解的合规负担 {values[0]} 元"
    elif fid in ("secondary_after_db_one_v1", "secondary_after_db_two_v1") and len(values) == 2:
        expression = f"本桶原合规负担 {values[0]} 元－本桶大病支付 {values[1]} 元"
    elif fid == "secondary_civil_cap_room_v1" and len(values) == 3:
        expression = f"最大值（救助封顶 {values[0]} 元－来源累计 {values[1]} 元，0）" + ("（交易后累计，仅作不跨封顶上界证明）" if values[2] == "1" else "")
    elif fid in ("secondary_feein_maf_pay_v1", "secondary_feeout_maf_pay_v1") and len(values) in (2, 4):
        expression = f"取整（本桶大病后自付 {values[0]} 元×救助比例 {values[1]}）"
        if len(values) == 4:
            expression += f"；剩余额度 {values[2]} 元、两桶剩余基数 {values[3]} 元。若两桶取整合计超额度，医保内桶按额度×本桶基数÷两桶基数取整，医保外桶取额度减医保内桶；本桶最终支付"
    if expression is None:
        layout = formula_display(fid).layout
        if layout in ("sum", "subtract_rest", "product"):
            terms = []
            for i, op in enumerate(operands):
                value, label = op["value"], op["display_name"]
                negative = value.startswith("-")
                text = f"{label} {value[1:] if negative and layout in ('sum', 'subtract_rest') else value}"
                sign = "" if i == 0 else " × " if layout == "product" else " － " if layout == "subtract_rest" or negative else " ＋ "
                if i == 0 and negative and layout == "sum":
                    sign = "－"
                terms.append(sign + text)
            expression = "".join(terms) if terms else None
    return f"{name}＝{expression}＝{calc.result} 元" if expression else None
