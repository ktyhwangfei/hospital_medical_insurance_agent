"""费用分解结果的公开视图映射与确定性模板渲染（Issue #78 设计 §11/§12，步骤 5）。

边界：
- 本模块为纯函数，不查数据库、不调用模型；
- 金额为十进制字符串原样透传，不做 float 转换；
- 模板渲染是模型不可用时的确定性基线（设计 §12：模型关闭仍能提供金额和条件解释）；
- 差异只原样呈现（实际值/计算值/差额），不判定医保系统对错；
- 物理表/列、快照引用不进入公开视图（留在受权限控制的审计轨迹）。
"""
from __future__ import annotations

from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult

#: 执行状态 → 用户可读状态词（may_claim_full_explanation=False 时不得出现"完整解释"，
#: 由 answer_constraints 保证 execution_status=complete 且核对一致才可宣称）
_EXECUTION_WORDS = {
    "complete": "完整解释",
    "partial": "部分解释",
    "unavailable": "暂不可用",
}

#: 核对状态 → 用户可读状态词
_RECONCILIATION_WORDS = {
    "matched": "核对一致",
    "mismatched": "存在差异",
    "not_verifiable": "暂不能核对",
}

#: 核对类型 → 计算来源措辞
_CHECK_TYPE_WORDS = {
    "independent_recalculation": "按规则重算",
    "detail_aggregation": "明细合计",
    "identity_check": "账面勾稽",
}


def _field_line(field) -> str:
    """单字段一句话（设计 §12：一致/差异/缺项各有固定措辞）。"""
    source = _CHECK_TYPE_WORDS.get(field.check_type, "计算")
    observed = (
        f"结算记录 {field.observed_amount} 元"
        if field.observed_amount is not None
        else "结算记录缺失"
    )
    if field.check_status == "matched":
        return f"{field.label}：{observed}，{source} {field.calculated_amount} 元，一致。"
    if field.check_status == "mismatched":
        return (
            f"{field.label}：{observed}，{source} {field.calculated_amount} 元，"
            f"差额 {field.difference} 元（仅呈现差异，不判定对错）。"
        )
    if field.check_status == "not_applicable":
        return f"{field.label}：本单不适用。"
    # not_verifiable：区分"已算出但无法核对"与"无法独立计算"
    if field.calculated_amount is not None:
        return f"{field.label}：{observed}，{source} {field.calculated_amount} 元，暂不能与账面核对。"
    return f"{field.label}：{observed}，暂不能独立计算。"


def render_summary(result: SettlementDecompositionResult) -> str:
    """确定性模板渲染：总览状态行 + 逐字段行 + 未决事项。

    只使用结果中已有的事实与金额，不补全任何缺失规则或比例。
    """
    status_word = _EXECUTION_WORDS.get(result.execution_status, result.execution_status)
    recon_word = _RECONCILIATION_WORDS.get(
        result.reconciliation_status, result.reconciliation_status)

    if result.execution_status == "unavailable" or not result.fields:
        lines = [f"费用分解{status_word}（算法版本 {result.algorithm_version}）。"]
    else:
        lines = [
            f"费用分解（算法版本 {result.algorithm_version}）：{status_word}，账面核对{recon_word}。",
            *(f"- {_field_line(field)}" for field in result.fields),
        ]
    if result.uncertainties:
        lines.append("未决事项：" + "；".join(u.message for u in result.uncertainties))
    return "\n".join(lines)


def build_public_view_dict(
    result: SettlementDecompositionResult,
    *,
    summary_text: str,
    summary_source: str,
) -> dict:
    """结果 → 公开视图 dict（纯映射；文本消毒与契约校验由路由层统一把关）。

    不含分支轨迹、计算记录、快照引用等审计级细节（设计 §12：用户端呈现业务名称，
    物理表/列和 SQL 留在受权限控制的审计视图）。
    """
    return {
        "schema_version": result.schema_version,
        "algorithm_version": result.algorithm_version,
        "execution_status": result.execution_status,
        "reconciliation_status": result.reconciliation_status,
        "summary_text": summary_text,
        "summary_source": summary_source,
        "may_claim_full_explanation": result.answer_constraints.may_claim_full_explanation,
        "fields": [
            {
                "field_code": f.field_code,
                "label": f.label,
                "check_type": f.check_type,
                "check_status": f.check_status,
                "observed_amount": f.observed_amount,
                "calculated_amount": f.calculated_amount,
                "difference": f.difference,
                "explanation_level": f.explanation_level,
            }
            for f in result.fields
        ],
        "uncertainties": [
            {"code": u.code, "message": u.message} for u in result.uncertainties
        ],
        "coverage": {
            "target_field_count": result.coverage.target_field_count,
            "independently_explained_count": result.coverage.independently_explained_count,
            "amount_reconciled_count": result.coverage.amount_reconciled_count,
            "observed_only_count": result.coverage.observed_only_count,
        },
    }
