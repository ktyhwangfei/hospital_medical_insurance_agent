from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult


@runtime_checkable
class DrgDipPort(Protocol):
    """DRG/DIP 分组系统适配器端口。

    封装与 DRG/DIP 分组付费系统的交互职责。
    负责分组结果查询、付费标准获取等 DRG/DIP 域业务能力。
    """

    def query_group_result(self, patient_id: str, encounter_id: str) -> AdapterCallResult:
        """查询 DRG/DIP 分组结果。

        Args:
            patient_id: 患者ID
            encounter_id: 就诊ID

        Returns:
            分组结果及支付风险信息
        """
        ...
