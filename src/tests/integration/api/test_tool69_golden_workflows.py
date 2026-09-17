"""Tool-69 四问 Golden 回归（同型数据替代，见 docs/reviews/2026-09-16-tool69-golden-cases.md）。

TOOL69_LIVE_DB=1 时对真实 SQL Server 基线库执行；默认跳过（CI 无库环境）。
身份字段在测试内动态取用，不落盘不打印（脱敏硬约束）。
"""

import os

import pytest

if os.getenv("TOOL69_LIVE_DB"):
    # 结算事实工具走语义层，需 real_db 模式（与后端服务运行态一致）
    os.environ.setdefault("DATA_SOURCE_MODE", "real_db")

pytestmark = pytest.mark.skipif(
    not os.getenv("TOOL69_LIVE_DB"), reason="需真实基线库：设置 TOOL69_LIVE_DB=1 启用"
)

# Golden 常量（2026-09-16 挖掘，见 golden 用例文档）
G_Q1_SETTLEMENT_IDS = ["687", "689", "691"]
G_Q3_SETTLEMENT_ID = "687"
G_ORIGINAL_TRADE_NO = "011100030X240914000007"
G_REFUND_TRADE_NO = "011100030X240914000008"
G_REOPEN_TRADE_NO = "011100030X240914000009"
G_VISIT_DATE = "2024-09-14"


def _open_conn():
    from src.runtime.discovery.semantic_source import get_semantic_data_source

    return get_semantic_data_source().connect_datasource("bjybdb")


def _golden_id_card() -> str:
    """测试内取原交易患者身份证（不打印不落盘）。"""
    conn = _open_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT P_IDNo FROM dbo.o_Trade WHERE T_TradeNo = ?", [G_ORIGINAL_TRADE_NO])
        row = cur.fetchone()
        assert row and row[0], "golden 原交易不存在（库已刷新？按文档重新挖掘）"
        return row[0]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_gq1_same_item_cross_settlement_diff() -> None:
    from src.runtime.workflow.definitions import WF_SETTLEMENT_REIMBURSEMENT_DIFF
    from src.runtime.workflow.service import execute_workflow
    from src.runtime.workflow.public_result import build_workflow_public_result

    result = await execute_workflow(
        WF_SETTLEMENT_REIMBURSEMENT_DIFF,
        context={
            "question": "同一患者同项目三次结算费用不同",
            "settlement_ids": G_Q1_SETTLEMENT_IDS,
            "settlement_id": "",
            "id_card": "",
            "visit_date": "",
        },
    )
    pub = build_workflow_public_result(result)

    assert result.status.value == "complete"
    outputs = {s.step_id: s.output for s in result.step_results}
    compare = outputs["same_drug_compare"]
    assert compare["comparison_count"] >= 1
    assert compare["all_match"] is False  # 1500/900/660 必然命中数量差异
    assert "事实差异" in pub.answer
    assert any("归因" in u for u in pub.uncertainties)


@pytest.mark.asyncio
async def test_gq2_refund_pair_by_identity() -> None:
    from src.runtime.policy_qa.settlement_record_lookup import get_refund_record

    data = get_refund_record(id_card=_golden_id_card(), visit_date=G_VISIT_DATE)

    trades = {r["trade_no"]: r for r in data["records"]}
    assert G_REFUND_TRADE_NO in trades, "退费交易缺失（库已刷新？）"
    assert G_REOPEN_TRADE_NO in trades, "同日重开交易缺失"
    assert float(trades[G_REFUND_TRADE_NO]["fee_all"]) < 0  # 退费负金额
    assert float(trades[G_REOPEN_TRADE_NO]["fee_all"]) > 0  # 重开正金额
    assert trades[G_REFUND_TRADE_NO]["original_trade_no"] == G_ORIGINAL_TRADE_NO
    assert any("退费重算规则" in u for u in data["uncertainties"])


@pytest.mark.asyncio
async def test_gq3_benefit_stacking_facts() -> None:
    from src.runtime.policy_qa.settlement_record_lookup import get_benefit_stacking
    from src.runtime.workflow.definitions import WF_BENEFIT_STACKING_ATTRIBUTION
    from src.runtime.workflow.service import execute_workflow

    facts = get_benefit_stacking(G_Q3_SETTLEMENT_ID)
    assert facts["special_disease_registered"] is True
    assert "502" in facts["special_disease_codes"]
    assert facts["big_ill_pay"] == pytest.approx(5161.16, abs=0.01)
    assert facts["civil_assistance_amount"] == pytest.approx(16756.09, abs=0.01)
    assert any("低保" in u for u in facts["uncertainties"])

    result = await execute_workflow(
        WF_BENEFIT_STACKING_ATTRIBUTION,
        context={
            "question": "特病低保二次报销个人支付偏高",
            "settlement_id": G_Q3_SETTLEMENT_ID,
            "settlement_ids": [],
            "id_card": "",
            "visit_date": "",
        },
    )
    assert result.status.value == "complete"


def test_gq4_refund_carries_deductible_facts() -> None:
    from src.runtime.policy_qa.settlement_record_lookup import get_refund_record

    data = get_refund_record(settlement_id=G_ORIGINAL_TRADE_NO)
    records = [r for r in data["records"] if r["original_trade_no"] == G_ORIGINAL_TRADE_NO]
    assert len(records) >= 2, "退费+重开两单并存事实缺失（Q4 型）"
    for r in records:
        # 原交易起付线/年度累计事实字段必须随退费记录返回（LEFT JOIN 原交易）
        assert "original_first_pay" in r
        assert "original_year" in r
