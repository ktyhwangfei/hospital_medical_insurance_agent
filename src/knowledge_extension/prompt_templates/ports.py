from typing import Any, Protocol

from src.knowledge_extension.prompt_templates.models import TemplateRenderResult, TemplateSelectionRequest, TemplateSelectionResult


class PromptTemplateRepository(Protocol):
    def select(self, request: TemplateSelectionRequest) -> TemplateSelectionResult: ...
    def render(self, template_id: str, variables: dict[str, Any]) -> TemplateRenderResult: ...
