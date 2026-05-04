from typing import Protocol

from src.knowledge_extension.rag.models import ContextPackage, RetrievalHit, RetrievalRequest, RetrievalResult


class RagRetriever(Protocol):
    def retrieve(self, request: RetrievalRequest) -> RetrievalResult: ...


class RagReranker(Protocol):
    def rerank(self, hits: list[RetrievalHit]) -> list[RetrievalHit]: ...


class ContextAssembler(Protocol):
    def assemble(self, hits: list[RetrievalHit], budget: int) -> ContextPackage: ...
