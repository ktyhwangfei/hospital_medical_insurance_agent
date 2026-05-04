from typing import Any

from src.shared.schemas.contracts import ErrorDetail


def error_detail(error_code: str, message: str, audit_event: dict[str, Any] | None = None) -> dict[str, Any]:
    return ErrorDetail(error_code=error_code, message=message, audit_event=audit_event or {}).model_dump()
