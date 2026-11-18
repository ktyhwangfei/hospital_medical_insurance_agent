from __future__ import annotations

from types import SimpleNamespace

from src.runtime.policy_qa.settlement_bill_compare import (
    MAX_PROMPT_FEE_ITEMS,
    bill_compare_data_notes,
    build_bill_compare_prompt,
    generate_bill_compare_answer,
)
from src.runtime.policy_qa.settlement_data_provider import (
    SettlementBill,
    SettlementBillFeeItem,
    SettlementBillField,
)


def _bill(
    settlement_id: str,
    *,
    date: str = "2024-09-19 14:21:26",
    service_type: str = "门诊特殊病",
    amount: str = "1520.00",
    items: list[SettlementBillFeeItem] | None = None,
    fee_items_state: str = "complete",
) -> SettlementBill:
    return SettlementBill(
        settlement_id=settlement_id,
        service_type=service_type,
        settlement_date=date,
        fields=[
            SettlementBillField(key="zje", label="费用总金额", amount=amount),
            SettlementBillField(key="personal_total_pay", label="个人支付总金额", amount="68.85"),
        ],
        fee_items=items
        if items is not None
        else [
            SettlementBillFeeItem(
                item_code="XL04ADT002E001020304641",
                item_name="他克莫司胶囊",
                item_type="药品",
                quantity="10",
                unit_price="152.00",
                total_amount="1520.00",
                insurance_inner="1520.00",
                insurance_outer="0.00",
            )
        ],
        fee_items_state=fee_items_state,
    )


def test_prompt_contains_both_bills_and_hard_rules():
    older = _bill("609")
    newer = _bill("814", date="2024-10-20 17:18:18", amount="1050.00")

    prompt, notes = build_bill_compare_prompt("为什么个人支付差这么多", [older, newer])

    assert notes == []
    assert "为什么个人支付差这么多" in prompt
    assert '"结算单": "609"' in prompt
    assert '"结算单": "814"' in prompt
    assert "他克莫司胶囊" in prompt
    assert "禁止把两张单的金额相加" in prompt
    assert "不判断结算是否合规" in prompt
    assert "不解释政策原因" in prompt


def test_prompt_marks_missing_fee_items_and_truncates_large_bills():
    missing = _bill("609", items=[], fee_items_state="missing")
    many_items = [
        SettlementBillFeeItem(
            item_code=f"ITEM-{index}",
            item_name=f"项目{index}",
            item_type="诊疗项目",
            quantity="1",
            unit_price="1.00",
            total_amount=f"{index + 1}.00",
            insurance_inner="1.00",
            insurance_outer="0.00",
        )
        for index in range(MAX_PROMPT_FEE_ITEMS + 5)
    ]
    large = _bill("814", items=many_items)

    prompt, notes = build_bill_compare_prompt("问题", [missing, large])

    assert any("609 的费用明细缺失" in note for note in notes)
    assert any("仅提供金额绝对值最大的前" in note for note in notes)
    # 截断后明细行数不超过上限
    assert prompt.count('"项目编码"') == MAX_PROMPT_FEE_ITEMS
    public_notes = bill_compare_data_notes([missing, large])
    assert any("609 的费用明细缺失" in note for note in public_notes)
    assert any("814" in note and "前 60 条" in note for note in public_notes)


def test_generate_calls_gateway_with_compare_scene():
    captured = {}

    class Gateway:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content="  模型解释  ")

    answer = generate_bill_compare_answer(
        "问题", [_bill("609"), _bill("814")], gateway=Gateway()
    )

    assert answer == "模型解释"
    assert captured["model_type"] == "llm"
    assert captured["scene"] == "settlement_compare_answer"
    assert "两张结算单的费用分解数据" in captured["messages"][0].content
