from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult


@runtime_checkable
class EmrPort(Protocol):
    """EMR 电子病历系统适配器端口。

    封装与电子病历系统（EMR）的交互职责。
    负责病历记录查询、病程摘要获取等 EMR 域业务能力。
    """

    def query_record_summary(self, patient_id: str, encounter_id: str) -> AdapterCallResult:
        """查询病历记录摘要。

        Args:
            patient_id: 患者ID
            encounter_id: 就诊ID

        Returns:
            病历记录摘要数据
        """
        ...
