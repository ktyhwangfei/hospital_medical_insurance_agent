"""人员结算单定位端口：按人员唯一标识 + 就诊日期解析结算单。"""

from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult


@runtime_checkable
class SettlementResolverPort(Protocol):
    """结算单定位适配器端口。

    封装「人员身份 + 就诊时间 → 结算单」的定位职责，供 Tool 层薄包装。
    数据源要求：患者主索引（身份证/医保卡号/患者ID 唯一确认人）与结算事实
    （人员 → 结算单号/日期/金额）关联可查。平台当前数据模型尚无人员身份
    字段（见 tool_resolve_settlement_by_person 执行细节盘点），未接入前
    Tool 不绑定实现，调用即降级 unavailable（fail-closed，不编造结果）。
    """

    def resolve_settlements(
        self,
        *,
        id_card: str = "",
        patient_id: str = "",
        insurance_card_no: str = "",
        visit_date: str = "",
    ) -> AdapterCallResult:
        """按人员唯一标识（id_card/patient_id/insurance_card_no 三选一）+ 就诊日期定位结算单。

        visit_date 为 YYYY-MM-DD；住院结算落在入院-结算区间内即命中。

        返回 data 契约：
        {
            "match_status": "unique_match | multiple_candidates | no_match",
            "settlement_candidates": [
                {"settlement_id", "settlement_date", "total_amount", "service_type"}
            ],
            "resolve_note": "定位说明（含数据源可用性）",
        }

        多笔命中必须返回 multiple_candidates 候选供人工澄清选择，
        禁止自动选定执行（不确定不执行硬约束）；输出不得回显身份证原文。
        """
        ...
