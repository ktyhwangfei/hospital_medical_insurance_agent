import logging

from src.knowledge_extension.rag.models import (
    Citation,
    ContextPackage,
    RAGResult,
    RetrievalFilter,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResult,
)
from src.knowledge_extension.rag.pipeline import RAGPipeline
from src.knowledge_extension.rag.ports import ContextAssembler, RagReranker, RagRetriever

logger = logging.getLogger(__name__)

try:
    from src.knowledge_extension.rag.milvus import MilvusVectorStore
except ImportError:
    MilvusVectorStore = None  # type: ignore
    logger.warning("MilvusVectorStore not available, pymilvus not installed")

__all__ = [
    "RagRetriever",
    "RagReranker",
    "ContextAssembler",
    "RetrievalFilter",
    "RetrievalRequest",
    "RetrievalHit",
    "ContextPackage",
    "RetrievalResult",
    "Citation",
    "RAGResult",
    "RAGPipeline",
]

if MilvusVectorStore is not None:
    __all__.append("MilvusVectorStore")
