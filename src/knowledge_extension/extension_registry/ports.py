from typing import Protocol

from src.knowledge_extension.extension_registry.models import ExtensionSelectionRequest, ExtensionSelectionResult


class ExtensionRegistry(Protocol):
    def select(self, request: ExtensionSelectionRequest) -> ExtensionSelectionResult: ...
