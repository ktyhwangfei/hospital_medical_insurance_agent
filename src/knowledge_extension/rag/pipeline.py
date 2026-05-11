import hashlib
import logging
from typing import Any, Callable

from src.knowledge_extension.rag.models import Citation, RAGResult

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Complete RAG pipeline with citation tracking.

    Integrates with a vector store (e.g. ``MilvusVectorStore``) for
    document retrieval and produces structured answers with cited
    sources and confidence scores.

    Usage::

        # With real Milvus
        store = MilvusVectorStore(collection_name="my_docs")
        pipeline = RAGPipeline(vector_store=store)

        result = pipeline.query("医保结算错误码E001的含义是什么？")
        print(result.answer)
        for c in result.citations:
            print(f"  [{c.source}] {c.text[:80]}...")

        # Index a document
        pipeline.index_document(
            doc_id="policy-001",
            content="...全文...",
            metadata={"source": "医保政策文件", "title": "结算异常处理"},
        )
    """

    def __init__(
        self,
        vector_store: Any,
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        """Initialize the pipeline.

        Parameters
        ----------
        vector_store:
            A vector store instance supporting ``search(query_embedding,
            top_k)`` and ``insert_documents(documents)``.  Typically a
            ``MilvusVectorStore``.
        embed_fn:
            Optional callable that converts a text string into an
            embedding vector (list[float]).  If omitted, a simple
            deterministic hash-based embedding is used — this is **not**
            semantically meaningful and is only suitable for development
            / testing.
        """
        self.vector_store = vector_store
        self.embed_fn = embed_fn or self._default_embed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, question: str, context: dict | None = None) -> RAGResult:
        """Run the full RAG pipeline: embed → retrieve → answer.

        Parameters
        ----------
        question:
            The user's natural-language question.
        context:
            Optional extra context dict (reserved for future use).

        Returns
        -------
        RAGResult with answer, citations, confidence, and sources.
        """
        # 1. Embed the question
        embedding = self.embed_fn(question)

        # 2. Retrieve relevant documents from vector store
        results = self._retrieve(embedding)

        # 3. Handle empty results gracefully
        if not results:
            return RAGResult(
                answer="未检索到相关知识，请人工确认。",
                citations=[],
                confidence=0.0,
                sources=[],
            )

        # 4. Build citations from retrieved documents
        citations = []
        sources_seen: set[str] = set()
        for r in results:
            source = r.get("source") or r.get("title", "")
            if source:
                sources_seen.add(source)
            citations.append(
                Citation(
                    source=source,
                    page=r.get("page"),
                    text=(r.get("text", "") or "")[:300],
                    relevance_score=float(r.get("distance", 0.0)),
                )
            )

        # 5. Generate template-based answer with citations
        answer = self._generate_answer(question, results)

        # 6. Calculate confidence from retrieval scores
        confidence = self._calculate_confidence(results)

        return RAGResult(
            answer=answer,
            citations=citations,
            confidence=confidence,
            sources=list(sources_seen),
        )

    def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> int:
        """Index a document into the vector store for future retrieval.

        Parameters
        ----------
        doc_id:
            Unique identifier for the document (used as ``chunk_id``).
        content:
            Full text content of the document.
        metadata:
            Optional dict of metadata fields (e.g. ``source``, ``page``,
            ``title``, ``asset_type``).  These are passed through to the
            vector store's schema.

        Returns
        -------
        Number of documents inserted (0 if the store is unavailable).
        """
        metadata = metadata or {}
        embedding = self.embed_fn(content)

        doc: dict[str, Any] = {
            "chunk_id": doc_id,
            "text": content,
            "embedding": embedding,
        }
        # Merge metadata — do not override the three core fields
        for k, v in metadata.items():
            if k not in ("chunk_id", "text", "embedding"):
                doc[k] = v

        try:
            return self.vector_store.insert_documents([doc])
        except RuntimeError:
            logger.warning("Vector store unavailable (pymilvus not installed)")
            return 0
        except Exception:
            logger.exception("Failed to index document '%s'", doc_id)
            return 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _default_embed(self, text: str) -> list[float]:
        """Simple fallback embedding based on text hashing.

        Produces a deterministic 128-dimensional vector.  This exists
        only to enable development / testing **without** requiring an
        external embedding model — it is **not** semantically meaningful.
        """
        dim = 128
        vec = [0.0] * dim
        for i, char in enumerate(text):
            h = hashlib.md5(f"{char}{i}".encode()).digest()
            for j in range(min(16, dim)):
                vec[(i + j) % dim] += h[j % 16] / 255.0
        magnitude = sum(v * v for v in vec) ** 0.5
        if magnitude > 0:
            vec = [v / magnitude for v in vec]
        return vec

    def _retrieve(self, embedding: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """Search the vector store, returning empty list on failure."""
        try:
            return self.vector_store.search(query_embedding=embedding, top_k=top_k)
        except RuntimeError:
            logger.warning("Vector store unavailable (pymilvus not installed)")
            return []
        except Exception:
            logger.exception("Vector store search failed")
            return []

    def _generate_answer(self, question: str, results: list[dict[str, Any]]) -> str:
        """Template-based answer generation (no external LLM required).

        Produces a structured answer that lists every piece of evidence
        retrieved for the user to review.
        """
        parts = [
            f"根据以下 {len(results)} 条检索结果，为您提供参考信息：",
            "",
        ]
        for i, r in enumerate(results, 1):
            source = r.get("source") or r.get("title", "未知来源")
            text = r.get("text", "") or ""
            display = text[:200]
            suffix = "…" if len(text) > 200 else ""
            parts.append(f"{i}. 【{source}】{display}{suffix}")
        parts.append("")
        parts.append(f"您的问题：{question}")
        parts.append("")
        parts.append("以上信息仅供参考，具体业务办理请以当地医保政策为准。")
        return "\n".join(parts)

    def _calculate_confidence(self, results: list[dict[str, Any]]) -> float:
        """Map average retrieval distance to a [0, 1] confidence score.

        Uses a sigmoid centered at 0.5, suitable for IP (inner product)
        distance metric where higher values indicate better matches.
        """
        if not results:
            return 0.0
        import math

        avg_distance = sum(r.get("distance", 0.0) for r in results) / len(results)
        return 1.0 / (1.0 + math.exp(-5.0 * (avg_distance - 0.5)))
