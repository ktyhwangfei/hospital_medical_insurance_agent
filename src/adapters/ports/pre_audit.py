from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult


@runtime_checkable
class PreAuditPort(Protocol):
    """事前审核系统适配器端口。

    封装与医保事前审核/智能审核系统的交互职责。
    负责审核结果查询、违规风险识别等事前审核域业务能力。
    """

    def query_audit_result(self, patient_id: str, encounter_id: str) -> AdapterCallResult:
        """查询事前审核结果。

        Args:
            patient_id: 患者ID
            encounter_id: 就诊ID

        Returns:
            审核结果及风险信息
        """
        ...
