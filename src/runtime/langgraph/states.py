from typing import Any, TypedDict

from typing_extensions import NotRequired


class BaseAgentState(TypedDict):
    messages: list
    intent: str
    role: str
    workflow_id: str
    citations: list
    uncertainties: list
    requires_confirmation: bool
    human_confirmed: bool
    blocked_actions: NotRequired[list[str]]
    response: NotRequired[Any]
