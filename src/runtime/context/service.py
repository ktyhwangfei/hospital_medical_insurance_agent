from datetime import UTC, datetime
from hashlib import md5

from src.runtime.api.schemas import ChatRequest
from src.runtime.context.models import RuntimeContext
from src.runtime.intent.models import IntentResult


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_runtime_context(request: ChatRequest, intent_result: IntentResult) -> RuntimeContext:
    requested_at = _now()
    key = f"{request.user_id}:{request.patient_id}:{request.encounter_id}:{request.message}:{requested_at}"
    suffix = md5(key.encode()).hexdigest()[:8]
    return RuntimeContext(
        request_id=f"req-{suffix}",
        workflow_id=f"wf-{suffix}",
        user_id=request.user_id,
        role=request.role,
        message=request.message,
        patient_id=request.patient_id,
        encounter_id=request.encounter_id,
        intent=intent_result.intent,
        intent_confidence=intent_result.confidence,
        intent_entities=intent_result.entities,
        intent_citations=intent_result.citations,
        requested_at=requested_at,
        mentioned_skill_ids=request.mentioned_skill_ids,
    )
