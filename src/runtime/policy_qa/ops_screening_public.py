"""把筛查问数回答收成政策问答公开结果。不把表名和内部字段写进 SSE。"""

from __future__ import annotations

from src.interaction.ops_screening.service import answer_screening
from src.runtime.policy_qa.public_contract import (
    OpsDataQueryBlock,
    OpsDataQueryChart,
    OpsDataQueryColumn,
    OpsDataQueryRow,
    OpsDataQuerySeries,
    OpsDataQueryTable,
    PolicyCitation,
    PolicyQAPublicResult,
    VerificationSummary,
)


def answer_ops_screening(question: str):
    """不是筛查问法时返回 None。"""
    answered = answer_screening(question)
    if answered is None:
        return None
    block = None
    if answered.show_table:
        chart = None
        if answered.chart_labels and answered.chart_values:
            chart = OpsDataQueryChart(
                type="bar",
                x_axis=list(answered.chart_labels),
                series=[OpsDataQuerySeries(name=answered.chart_name or "金额", data=list(answered.chart_values))],
            )
        block = OpsDataQueryBlock(
            metric_id=answered.metric_id,
            metric_name=answered.metric_name,
            summary=answered.summary,
            caliber=answered.caliber,
            table=OpsDataQueryTable(
                columns=[OpsDataQueryColumn(key=key, title=title) for key, title in answered.columns],
                rows=[OpsDataQueryRow.model_validate(row) for row in answered.rows],
            ),
            chart=chart,
        )
    citations = []
    if answered.caliber:
        citations.append(PolicyCitation(title="筛查结果口径", excerpt=answered.caliber))
    elif answered.answer_status == "unavailable":
        citations.append(PolicyCitation(title="筛查结果", excerpt=answered.answer))
    return PolicyQAPublicResult(
        answer=answered.answer,
        answer_status=answered.answer_status,
        citations=citations,
        uncertainties=list(answered.uncertainties),
        data_query_result=block,
        verification_summary=VerificationSummary(
            settlement_checked=answered.settlement_checked,
            calculation_checked=answered.calculation_checked,
            policy_count=len(citations),
            message="条数与金额已按同一口径对账" if answered.calculation_checked else "本次没有可对账的数字",
        ),
    )
