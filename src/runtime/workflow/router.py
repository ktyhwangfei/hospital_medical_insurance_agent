"""WorkflowRouter：一次性关键词分类，选中 Workflow 或不选中（不做自由规划）。"""

from __future__ import annotations

from src.domain.workflow.models import WorkflowDefinition


class WorkflowRouter:
    def __init__(self, definitions: list[WorkflowDefinition]) -> None:
        self._definitions = definitions

    def route(self, question: str) -> WorkflowDefinition | None:
        best_match: WorkflowDefinition | None = None
        best_score = 0
        for definition in self._definitions:
            score = sum(1 for keyword in definition.intent_keywords if keyword in question)
            if score > best_score:
                best_score = score
                best_match = definition
        return best_match if best_score > 0 else None
