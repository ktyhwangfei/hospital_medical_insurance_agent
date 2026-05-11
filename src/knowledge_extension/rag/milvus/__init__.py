try:
    from src.knowledge_extension.rag.milvus.vector_store import MilvusVectorStore

    __all__ = ["MilvusVectorStore"]
except ImportError:
    MilvusVectorStore = None  # type: ignore

    __all__: list[str] = []
