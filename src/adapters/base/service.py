from datetime import UTC, datetime
from typing import Any

from src.adapters.base.models import AdapterCallContext, AdapterCallResult, DataQualityStatus


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def successful_result(context: AdapterCallContext, source_system: str, source_record_id: str, capability: str, data: dict[str, Any]) -> AdapterCallResult:
    return AdapterCallResult(
        status="success",
        source_system=source_system,
        source_record_id=source_record_id,
        capability=capability,
        data=data,
        data_quality=DataQualityStatus.COMPLETE,
        collected_at=_now(),
        workflow_id=context.workflow_id,
        step_id=context.step_id,
        input_summary=context.input_summary,
        output_summary={"keys": sorted(data.keys())},
    )


def failed_result(context: AdapterCallContext, source_system: str, capability: str, error_type: str, message: str) -> AdapterCallResult:
    return AdapterCallResult(
        status="failed",
        source_system=source_system,
        capability=capability,
        data_quality=DataQualityStatus.DEGRADED,
        collected_at=_now(),
        workflow_id=context.workflow_id,
        step_id=context.step_id,
        input_summary=context.input_summary,
        error_type=error_type,
        message=message,
    )


def adapter_citation(result: AdapterCallResult) -> dict[str, str]:
    return {
        "source_type": result.source_system,
        "source_id": result.source_record_id or result.capability,
        "summary": result.message or result.capability,
    }
