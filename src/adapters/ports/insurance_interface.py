from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult


@runtime_checkable
class InsuranceInterfacePort(Protocol):
    """医保接口适配器端口。

    封装与医保核心结算系统（医保局端接口）的交互职责。
    负责医保交易查询、结算状态确认等医保核心业务能力。
    """

    def query_transaction(self, patient_id: str, encounter_id: str) -> AdapterCallResult:
        """查询医保交易记录。

        Args:
            patient_id: 患者ID
            encounter_id: 就诊ID

        Returns:
            医保交易记录数据
        """
        ...
