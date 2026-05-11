import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

    PYMILVUS_AVAILABLE = True
except ImportError:
    PYMILVUS_AVAILABLE = False

    class _DummyCollection:  # type: ignore
        def __getattr__(self, name: str) -> Any:
            raise RuntimeError("pymilvus is not installed. Install it with: pip install pymilvus")

    Collection = _DummyCollection  # type: ignore
    utility = None  # type: ignore


class MilvusClient:
    """Manages connection lifecycle to a Milvus or Zilliz Cloud instance.

    Uses lazy connection — no network call is made until :meth:`connect` is
    explicitly called or the first operation triggers it automatically.
    """

    DEFAULT_URI = "localhost:19530"

    def __init__(self, uri: str | None = None, token: str | None = None) -> None:
        if not PYMILVUS_AVAILABLE:
            raise RuntimeError(
                "pymilvus is required for MilvusClient. Install it with: pip install pymilvus"
            )
        self._uri = uri or os.getenv("MILVUS_URI", self.DEFAULT_URI)
        self._token = token
        self._connected = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Establish a connection to the Milvus server.

        Safe to call multiple times — subsequent calls are no-ops when
        already connected.
        """
        if self._connected:
            return
        try:
            connections.connect(uri=self._uri, token=self._token)
            self._connected = True
            logger.info("Connected to Milvus at %s", self._uri)
        except Exception:
            logger.exception("Failed to connect to Milvus at %s", self._uri)
            raise

    def disconnect(self) -> None:
        """Close the current connection."""
        if not self._connected:
            return
        try:
            connections.disconnect(alias="default")
        except Exception:
            logger.warning("Error disconnecting from Milvus", exc_info=True)
        finally:
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Return a simple health-report dictionary."""
        result: dict[str, Any] = {"status": "ok", "uri": self._uri}
        if not self._connected:
            try:
                self.connect()
            except RuntimeError:
                return {"status": "unavailable", "uri": self._uri, "error": "pymilvus not installed"}
            except Exception as exc:
                return {"status": "unreachable", "uri": self._uri, "error": str(exc)}
        try:
            version = utility.get_server_version() if utility else "unknown"
            result["version"] = version
        except Exception as exc:
            result["status"] = "degraded"
            result["version_error"] = str(exc)
        return result

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def create_collection(
        self,
        collection_name: str,
        dimension: int = 768,
        description: str = "",
    ) -> None:
        """Create a collection suitable for storing document embeddings.

        Parameters
        ----------
        collection_name:
            Name of the collection to create.
        dimension:
            Embedding dimension (default 768, matching many sentence-transformers models).
        description:
            Optional human-readable description.
        """
        self.connect()
        if utility and utility.has_collection(collection_name):
            logger.info("Collection '%s' already exists, skipping creation", collection_name)
            return

        fields = [
            FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="asset_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="asset_type", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="section", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="page", dtype=DataType.INT64),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="metadata_json", dtype=DataType.VARCHAR, max_length=8192),
        ]
        schema = CollectionSchema(fields=fields, description=description)
        collection = Collection(name=collection_name, schema=schema)
        collection.create_index(
            field_name="embedding",
            index_params={"metric_type": "IP", "index_type": "IVF_FLAT", "params": {"nlist": 128}},
        )
        collection.load()
        logger.info("Created collection '%s' (dim=%d)", collection_name, dimension)

    def get_collection(self, collection_name: str) -> Any:
        """Return an existing collection by name (raises if not found)."""
        self.connect()
        return Collection(name=collection_name)

    def drop_collection(self, collection_name: str) -> None:
        """Delete a collection entirely."""
        self.connect()
        if utility:
            utility.drop_collection(collection_name)
        logger.info("Dropped collection '%s'", collection_name)

    def has_collection(self, collection_name: str) -> bool:
        """Check whether a collection exists."""
        self.connect()
        return bool(utility and utility.has_collection(collection_name))

    def list_collections(self) -> list[str]:
        """Return all collection names."""
        self.connect()
        return utility.list_collections() if utility else []
