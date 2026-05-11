from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult


@runtime_checkable
class MedicalRecordPort(Protocol):
    """病案系统适配器端口。

    封装与病案管理系统的交互职责。
    负责病案首页查询、病案质控等病案域业务能力。
    """

    def query_homepage(self, patient_id: str, encounter_id: str) -> AdapterCallResult:
        """查询病案首页信息。

        Args:
            patient_id: 患者ID
            encounter_id: 就诊ID

        Returns:
            病案首页数据
        """
        ...
