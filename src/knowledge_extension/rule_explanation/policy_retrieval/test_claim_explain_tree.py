from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from pprint import pprint
from typing import Any

from dotenv import load_dotenv

from .sqlserver_business_data_client import SqlServerBusinessDataClient


def D(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def money(v: Any) -> Decimal:
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class ExplainTreeResult:
    settlement_id: str
    tree: dict[str, Any]
    warnings: list[str]


class ClaimExplainTreeTester:
    def __init__(self, business_client: SqlServerBusinessDataClient):
        self.client = business_client

    def _query_many(self, query_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        sql = self.client.sql_store.get_sql(query_name)
        param_names = self.client.sql_store.get_params(query_name)
        values = [params.get(name) for name in param_names]

        with self.client._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, *values)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def build_tree(self, *, settlement_id: str, fsrq: str) -> ExplainTreeResult:
        warnings: list[str] = []

        settlement, _, _, _, _ = self.client._query_one(
            query_name="settlement_context",
            params={"djh": settlement_id},  # 如果你的 settlement_context 参数还是 djh，这里保持一致
        )

        if not settlement:
            raise ValueError(f"未查询到 settlement_context: {settlement_id}")

        catalog_rows = self._query_many(
            query_name="fee_catalog_context",
            params={
                "djh": settlement.get("djh") or settlement_id,
                "fsrq": fsrq,
            },
        )

        catalog_tree = self._build_catalog_tree(catalog_rows)
        benefit_tree = self._build_benefit_tree(settlement)

        tree = {
            "name": "医保费用解释树",
            "settlement_id": settlement.get("djh"),
            "case_context": {
                "fund_type": settlement.get("fund_type"),
                "yllb": settlement.get("yllb"),
                "person_type": settlement.get("PER_TYPE"),
                "fynd": settlement.get("fynd"),
                "bnzqslj": settlement.get("bnzqslj"),
                "zqxh": settlement.get("zqxh"),
                "bcqfje": float(money(settlement.get("bcqfje"))),
                "bcqsrq": settlement.get("bcqsrq"),
            },
            "children": [
                catalog_tree,
                benefit_tree,
            ],
        }

        return ExplainTreeResult(
            settlement_id=str(settlement.get("djh")),
            tree=tree,
            warnings=warnings,
        )

    def _build_catalog_tree(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        groups: dict[str, dict[str, Decimal]] = {}

        for r in rows:
            reason = r.get("ybwje_reason") or "99_其他未归因"
            if reason not in groups:
                groups[reason] = {
                    "zje": Decimal("0"),
                    "ybnje": Decimal("0"),
                    "ybwje": Decimal("0"),
                    "count": Decimal("0"),
                }

            groups[reason]["zje"] += D(r.get("zje"))
            groups[reason]["ybnje"] += D(r.get("ybnje"))
            groups[reason]["ybwje"] += D(r.get("ybwje"))
            groups[reason]["count"] += Decimal("1")

        outside_children = []
        for reason, g in sorted(groups.items()):
            outside_children.append(
                {
                    "name": reason,
                    "amount": float(money(g["ybwje"])),
                    "item_count": int(g["count"]),
                    "zje": float(money(g["zje"])),
                    "ybnje": float(money(g["ybnje"])),
                    "ybwje": float(money(g["ybwje"])),
                }
            )

        return {
            "name": "一、目录规则层",
            "description": "解释哪些费用能够进入医保，哪些费用形成医保外金额。",
            "children": [
                {
                    "name": "医保外费用归因",
                    "amount": float(money(sum((D(x["amount"]) for x in outside_children), Decimal("0")))),
                    "children": outside_children,
                }
            ],
        }

    def _build_benefit_tree(self, settlement: dict[str, Any]) -> dict[str, Any]:
        ybnje = money(settlement.get("bcybnje"))
        deductible = money(settlement.get("bcqfje"))

        basic_pay = money(settlement.get("bdtczfje"))
        basic_self = money(settlement.get("bdtczf"))

        large_pay = money(settlement.get("bddegwyzfje"))
        large_self = money(settlement.get("bddegwyzf"))

        benefit_base = money(ybnje - deductible)

        # 当前案例：北京城镇职工退休，三级医院，基本统筹分段
        seg1_fee = money(Decimal("30000") - deductible)
        seg1_fund_ratio = Decimal("0.91")
        seg1_self_ratio = Decimal("0.09")

        seg2_fee = Decimal("10000.00")
        seg2_fund_ratio = Decimal("0.94")
        seg2_self_ratio = Decimal("0.06")

        seg1_pay = money(seg1_fee * seg1_fund_ratio)
        seg1_self = money(seg1_fee * seg1_self_ratio)

        seg2_pay = money(seg2_fee * seg2_fund_ratio)
        seg2_self = money(seg2_fee * seg2_self_ratio)

        seg3_pay = money(basic_pay - seg1_pay - seg2_pay)
        seg3_fee = money(seg3_pay / Decimal("0.97"))
        seg3_self = money(seg3_fee * Decimal("0.03"))

        basic_fee = money(seg1_fee + seg2_fee + seg3_fee)
        large_fee = money(benefit_base - basic_fee)

        return {
            "name": "二、待遇分解层",
            "description": "解释医保内金额进入起付线、基本统筹、大额医疗互助后的分段计算过程。",
            "children": [
                {
                    "name": "医保内金额",
                    "amount": float(ybnje),
                },
                {
                    "name": "起付线",
                    "amount": float(deductible),
                },
                {
                    "name": "纳入待遇计算金额",
                    "amount": float(benefit_base),
                    "formula": "医保内金额 - 起付线",
                },
                {
                    "name": "基本统筹段",
                    "amount": float(basic_fee),
                    "fund_pay": float(basic_pay),
                    "self_pay": float(basic_self),
                    "children": [
                        {
                            "name": "第一分段：起付线～3万元",
                            "fee": float(seg1_fee),
                            "fund_ratio": "91%",
                            "self_ratio": "9%",
                            "fund_pay": float(seg1_pay),
                            "self_pay": float(seg1_self),
                        },
                        {
                            "name": "第二分段：3万元～4万元",
                            "fee": float(seg2_fee),
                            "fund_ratio": "94%",
                            "self_ratio": "6%",
                            "fund_pay": float(seg2_pay),
                            "self_pay": float(seg2_self),
                        },
                        {
                            "name": "第三分段：4万元～统筹封顶触发点",
                            "fee": float(seg3_fee),
                            "fund_ratio": "97%",
                            "self_ratio": "3%",
                            "fund_pay": float(seg3_pay),
                            "self_pay": float(seg3_self),
                            "formula": "第三段费用 = 第三段统筹支付 ÷ 97%",
                        },
                    ],
                },
                {
                    "name": "大额医疗互助段",
                    "amount": float(large_fee),
                    "fund_pay": float(large_pay),
                    "self_pay": float(large_self),
                    "formula": "大额段金额 = 纳入待遇计算金额 - 基本统筹段金额",
                },
            ],
        }


def main():
    BASE_DIR = Path(__file__).resolve().parent

    load_dotenv()

    client = SqlServerBusinessDataClient(
        sql_config_path=BASE_DIR / "config" / "business_sql.yaml",
    )

    tester = ClaimExplainTreeTester(client)

    result = tester.build_tree(
        settlement_id="1671213",
        fsrq="2025-06-29 00:00:00.000",
    )

    pprint(asdict(result), width=140)


if __name__ == "__main__":
    main()