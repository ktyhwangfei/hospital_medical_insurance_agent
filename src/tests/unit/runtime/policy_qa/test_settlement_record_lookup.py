"""同药跨单费用对比纯逻辑单元测试（无数据库依赖）。"""

from src.runtime.policy_qa.settlement_record_lookup import compare_same_drug_fee_details


def _detail(items: list[dict]) -> dict:
    return {"items": items, "item_count": len(items)}


def _item(code: str, *, qty=1, price=100.0, total=100.0, inner=85.0, pre_self=0.0, name="达克罗宁") -> dict:
    return {
        "item_code": code,
        "nation_code": code,
        "item_name": name,
        "quantity": qty,
        "unit_price": price,
        "total_amount": total,
        "insurance_inner_amount": inner,
        "pre_self_pay_amount": pre_self,
        "service_type": "门诊",
    }


def test_compare_flags_price_difference_for_same_drug() -> None:
    result = compare_same_drug_fee_details(
        {
            "S1": _detail([_item("X001", price=100.0, total=100.0)]),
            "S2": _detail([_item("X001", price=80.0, total=80.0)]),
        }
    )

    assert result["comparison_count"] == 1
    assert result["all_match"] is False
    comparison = result["comparisons"][0]
    assert comparison["drug_key"] == "X001"
    assert comparison["match"] is False
    assert any("单价不一致" in diff for diff in comparison["differences"])


def test_compare_all_match_when_facts_identical() -> None:
    result = compare_same_drug_fee_details(
        {
            "S1": _detail([_item("X001")]),
            "S2": _detail([_item("X001")]),
            "S3": _detail([_item("X001")]),
        }
    )

    assert result["comparison_count"] == 1
    assert result["all_match"] is True
    assert result["comparisons"][0]["match"] is True
    assert result["comparisons"][0]["settlement_ids"] == ["S1", "S2", "S3"]


def test_compare_ignores_single_settlement_items() -> None:
    result = compare_same_drug_fee_details(
        {
            "S1": _detail([_item("X001"), _item("X002")]),
            "S2": _detail([_item("X001")]),
        }
    )

    assert result["comparison_count"] == 1
    assert result["comparisons"][0]["drug_key"] == "X001"


def test_compare_without_cross_settlement_drugs_returns_none_all_match() -> None:
    result = compare_same_drug_fee_details(
        {
            "S1": _detail([_item("X001")]),
            "S2": _detail([_item("X009")]),
        }
    )

    assert result["comparison_count"] == 0
    assert result["all_match"] is None
    assert "无法做同药对比" in result["conclusion"]


def test_compare_declares_attribution_uncertainty() -> None:
    result = compare_same_drug_fee_details(
        {
            "S1": _detail([_item("X001")]),
            "S2": _detail([_item("X001", price=50.0, total=50.0)]),
        }
    )

    assert any("归因" in u for u in result["uncertainties"])
    assert any("权威规则" in u for u in result["uncertainties"])
