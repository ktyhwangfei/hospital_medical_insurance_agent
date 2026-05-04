import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f'event: {event}\ndata: {payload}\n\n'


def ensure_knowledge_fields(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("citations", [])
    payload.setdefault("uncertainties", ["流式响应未获得额外知识依据"] if not payload.get("citations") else [])
    return payload
