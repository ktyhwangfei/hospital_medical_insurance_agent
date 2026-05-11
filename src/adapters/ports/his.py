from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult


@runtime_checkable
class HisPort(Protocol):
    """HIS 系统适配器端口。

    封装与医院信息系统（HIS）核心的交互职责。
    负责医嘱查询、就诊信息获取等 HIS 域业务能力。
    """

    def query_orders(self, patient_id: str, encounter_id: str) -> AdapterCallResult:
        """查询医嘱信息。

        Args:
            patient_id: 患者ID
            encounter_id: 就诊ID

        Returns:
            医嘱列表数据
        """
        ...
