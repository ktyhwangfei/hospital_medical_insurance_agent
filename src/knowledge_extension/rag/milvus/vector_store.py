import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from pymilvus import Collection, utility

    PYMILVUS_AVAILABLE = True
except ImportError:
    PYMILVUS_AVAILABLE = False


class MilvusVectorStore:
    """Vector store backed by Milvus for document embedding storage and
    semantic search.

    This class is a *protocol-level implementation* — it is ready to use
    when ``pymilvus`` is installed and a Milvus server is reachable, but
    degrades gracefully when the dependency is absent so that imports and
    instantiation never fail.

    Usage::

        store = MilvusVectorStore(collection_name="my_docs")
        store.insert_documents([
            {"chunk_id": "c1", "text": "hello world", "embedding": [0.1, ...], ...},
        ])
        results = store.search(query_embedding=[0.1, ...], top_k=3)

    Connection is lazy — the first operation triggers ``connect()``.
    """

    def __init__(
        self,
        collection_name: str = "knowledge_chunks",
        uri: str | None = None,
        token: str | None = None,
    ) -> None:
        self.collection_name = collection_name
        self._uri = uri
        self._token = token
        self._client: Any = None
        self._collection: Any = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> None:
        """Lazy-init the Milvus client and collection handle."""
        if self._client is not None:
            return
        if not PYMILVUS_AVAILABLE:
            raise RuntimeError(
                "pymilvus is required for MilvusVectorStore. "
                "Install it with: pip install pymilvus"
            )
        from src.knowledge_extension.rag.milvus.client import MilvusClient

        self._client = MilvusClient(uri=self._uri, token=self._token)
        self._client.connect()
        if not self._client.has_collection(self.collection_name):
            self._client.create_collection(self.collection_name)
        self._collection = self._client.get_collection(self.collection_name)

    def _collection_ref(self) -> Any:
        self._ensure_client()
        return self._collection

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def insert_documents(self, documents: list[dict[str, Any]]) -> int:
        """Insert a batch of documents into the collection.

        Each document *must* include an ``"embedding"`` key
        (list[float]).  Optional metadata fields:

        - ``chunk_id``, ``asset_id``, ``asset_type``
        - ``title``, ``section``, ``source``, ``page``
        - ``text`` — the original text content
        - any extra keys → serialised into ``metadata_json``

        Returns the number of rows inserted.
        """
        if not documents:
            return 0
        coll = self._collection_ref()
        rows = []
        for doc in documents:
            row: dict[str, Any] = {
                "embedding": doc.get("embedding", []),
                "chunk_id": doc.get("chunk_id", ""),
                "asset_id": doc.get("asset_id", ""),
                "asset_type": doc.get("asset_type", ""),
                "title": doc.get("title", ""),
                "section": doc.get("section", ""),
                "source": doc.get("source", ""),
                "page": doc.get("page", 0),
                "text": doc.get("text", ""),
            }
            # Pack any extra fields into metadata_json
            known = {"embedding", "chunk_id", "asset_id", "asset_type", "title", "section", "source", "page", "text"}
            extra = {k: v for k, v in doc.items() if k not in known}
            row["metadata_json"] = json.dumps(extra, ensure_ascii=False) if extra else "{}"
            rows.append(row)

        try:
            mr = coll.insert(rows)
            coll.flush()
            count = len(rows)
            logger.info("Inserted %d document(s) into '%s'", count, self.collection_name)
            return count
        except Exception:
            logger.exception("Failed to insert documents into Milvus")
            raise

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """Perform a vector similarity search.

        Parameters
        ----------
        query_embedding:
            The embedding vector to search with.
        top_k:
            Maximum number of results to return.
        expr:
            Optional boolean expression for scalar filtering (e.g.
            ``asset_type == "policy"``).

        Returns a list of dicts with keys matching the collection schema
        plus a ``distance`` score.
        """
        coll = self._collection_ref()
        coll.load()

        search_params = {"metric_type": "IP", "params": {"nprobe": 10}}
        try:
            results = coll.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=expr,
                output_fields=[
                    "chunk_id", "asset_id", "asset_type", "title",
                    "section", "source", "page", "text", "metadata_json",
                ],
            )
        except Exception:
            logger.exception("Milvus search failed")
            return []

        hits: list[dict[str, Any]] = []
        for hits_group in results:
            for hit in hits_group:
                record = {
                    "chunk_id": hit.entity.get("chunk_id"),
                    "asset_id": hit.entity.get("asset_id"),
                    "asset_type": hit.entity.get("asset_type"),
                    "title": hit.entity.get("title"),
                    "section": hit.entity.get("section"),
                    "source": hit.entity.get("source"),
                    "page": hit.entity.get("page"),
                    "text": hit.entity.get("text"),
                    "distance": hit.score,
                }
                meta_raw = hit.entity.get("metadata_json")
                if meta_raw and meta_raw != "{}":
                    try:
                        record["metadata"] = json.loads(meta_raw)
                    except (json.JSONDecodeError, TypeError):
                        record["metadata"] = {}
                hits.append(record)
        return hits

    def delete_collection(self) -> None:
        """Remove the entire Milvus collection and reset local state."""
        self._ensure_client()
        try:
            self._client.drop_collection(self.collection_name)
        except Exception:
            logger.exception("Failed to delete collection '%s'", self.collection_name)
            raise
        finally:
            self._client = None
            self._collection = None

    def count(self) -> int:
        """Return approximate entity count in the collection."""
        coll = self._collection_ref()
        coll.flush()
        return coll.num_entities
