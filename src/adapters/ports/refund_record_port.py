"""退费/冲正记录端口：按结算单或人员标识查询已发生的退费记录。"""

from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult


@runtime_checkable
class RefundRecordPort(Protocol):
    """退费记录适配器端口。

    封装「结算单 / 人员身份 → 已发生退费记录」的查询职责，供 Tool 层薄包装。
    数据源现状（2026-09-16 盘点，见 docs/reviews/2026-09-16-tool69-real-capability-vs-4-questions.md）：
    - 住院：yb_zyjyxx.tflydjh（退费来源登记号）直连 djh，可按结算单查；
    - 门诊：HIS 收费端 o_Trade 自带退费链路（TR_OraginalTradeNo / T_HasRefundmented /
      T_PartialReturnFlag），但测试库中医保端 djh 与 HIS 端 T_TradeNo 无直接 join，
      门诊退费查询需人员身份 + 就诊日期窗口。
    无数据源时实现返回 data_quality=MISSING，不编造记录。
    """

    def query_refund_records(
        self,
        *,
        settlement_id: str = "",
        id_card: str = "",
        insurance_card_no: str = "",
        visit_date: str = "",
    ) -> AdapterCallResult:
        """查询退费/冲正记录。

        settlement_id（djh）与人员标识（id_card/insurance_card_no）至少提供其一：
        - settlement_id：走医保端退费链路（住院 tflydjh）；
        - 人员标识 + visit_date：走 HIS 收费端 o_Trade 退费交易链路（门诊）。

        返回 data 契约：
        {
            "records": [  # 退费交易列表（不含患者身份原文）
                {"trade_no", "trade_date", "fee_all", "original_trade_no",
                 "partial_return_flag", "refund_side"}
            ],
            "refunded_count": int,
            "conclusion": str,      # 确定性摘要（有/无退费记录）
            "uncertainties": [str], # 数据源边界声明（如退费重算规则未接入）
        }
        """
        ...
