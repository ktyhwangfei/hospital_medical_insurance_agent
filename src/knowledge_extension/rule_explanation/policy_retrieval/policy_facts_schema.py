"""policy_facts Milvus 集合定义（政策知识管线·事实层）。

事实 = 政策的最小语义单元 + 向量入口。结构化规则（policy_rules）通过 fact_id 关联回此集合。

设计要点：
- 事实全文向量化（embedding=sentence_transformer/bge-base-zh-v1.5, dim=768）
- 语义检索的主入口；policy_rules 的 vector 复用此处的 fact 向量
- doc_id 建标量索引，支持按政策文档过滤

[来源: docs/steering/政策知识管线设计.md §3.2 / §4.1]
"""
from __future__ import annotations

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

FACT_COLLECTION = "policy_facts"
FACT_VECTOR_DIM = 768  # bge-base-zh-v1.5


def connect_milvus(host: str | None = None, port: str | None = None, alias: str = "default") -> None:
    """连接 Milvus（默认读 src.config.production）。"""
    if host is None or port is None:
        from src.config.production import MILVUS_HOST, MILVUS_PORT
        host = host or MILVUS_HOST
        port = port or str(MILVUS_PORT)
    connections.connect(alias=alias, host=host, port=port)


def create_policy_facts_collection(
    dim: int = FACT_VECTOR_DIM, drop_existing: bool = False, alias: str = "default",
    collection_name: str = FACT_COLLECTION,
) -> Collection:
    """创建 policy_facts 集合。collection_name 可参数化（测试用临时名隔离）。"""
    if not connections.has_connection(alias):
        connect_milvus(alias=alias)
    if utility.has_collection(collection_name, using=alias):
        if drop_existing:
            utility.drop_collection(collection_name, using=alias)
        else:
            return Collection(collection_name, using=alias)

    fields = [
        FieldSchema("fact_id", DataType.VARCHAR, is_primary=True, max_length=64,
                    description="事实ID，关联 policy_rules.fact_id"),
        FieldSchema("doc_id", DataType.VARCHAR, max_length=64,
                    description="来源政策文档ID，关联 PG policy_documents"),
        FieldSchema("fact_text", DataType.VARCHAR, max_length=16384,
                    description="事实全文（最小语义单元）"),
        FieldSchema("vector", DataType.FLOAT_VECTOR, dim=dim,
                    description="事实全文向量（语义检索主入口）"),
        FieldSchema("created_at", DataType.VARCHAR, max_length=32,
                    description="创建时间 ISO 字符串"),
    ]
    schema = CollectionSchema(
        fields,
        description="政策事实（语义单元 + 向量入口）",
        enable_dynamic_field=True,
    )
    col = Collection(collection_name, schema, using=alias)
    _create_indexes(col)
    return col


def _create_indexes(col: Collection) -> None:
    # 向量索引：HNSW + COSINE（与 policy_rules 一致）
    col.create_index(
        field_name="vector",
        index_params={
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200},
        },
    )
    # 标量索引：doc_id（按文档过滤）
    col.create_index(field_name="doc_id", index_params={})


def drop_policy_facts_collection(alias: str = "default") -> None:
    if utility.has_collection(FACT_COLLECTION, using=alias):
        utility.drop_collection(FACT_COLLECTION, using=alias)


def upsert_facts(col: Collection, fact_records: list[dict]) -> int:
    """批量写入事实到 policy_facts。

    Args:
        col: policy_facts Collection（已创建）。
        fact_records: 每条 {fact_id, doc_id, fact_text, vector, created_at}。
    Returns: 写入条数。
    """
    if not fact_records:
        return 0
    col.insert(fact_records)
    col.flush()
    return len(fact_records)
