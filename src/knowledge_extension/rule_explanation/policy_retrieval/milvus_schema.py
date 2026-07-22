from __future__ import annotations

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility


NODE_COLLECTION = "policy_nodes"
FACT_COLLECTION = "policy_facts"


def connect_milvus(host: str = "127.0.0.1", port: str = "19530", alias: str = "default") -> None:
    connections.connect(alias=alias, host=host, port=port)


def create_policy_collections(dim: int, drop_existing: bool = False) -> None:
    create_policy_nodes_collection(dim, drop_existing=drop_existing)
    create_policy_facts_collection(dim, drop_existing=drop_existing)


def create_policy_nodes_collection(dim: int, drop_existing: bool = False) -> Collection:
    if utility.has_collection(NODE_COLLECTION):
        if drop_existing:
            utility.drop_collection(NODE_COLLECTION)
        else:
            return Collection(NODE_COLLECTION)

    fields = [
        FieldSchema("node_id", DataType.VARCHAR, is_primary=True, max_length=256),
        FieldSchema("policy_id", DataType.VARCHAR, max_length=256),
        FieldSchema("policy_title", DataType.VARCHAR, max_length=1024),
        FieldSchema("parent_id", DataType.VARCHAR, max_length=256),
        FieldSchema("level", DataType.INT64),
        FieldSchema("path_text", DataType.VARCHAR, max_length=4096),
        FieldSchema("current_text", DataType.VARCHAR, max_length=8192),
        FieldSchema("full_context_text", DataType.VARCHAR, max_length=16384),
        FieldSchema("chunk_type", DataType.VARCHAR, max_length=256),
        FieldSchema("keywords_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("metadata_json", DataType.VARCHAR, max_length=8192),
        FieldSchema("embedding_text", DataType.VARCHAR, max_length=16384),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=dim),
    ]
    schema = CollectionSchema(fields, description="医保政策语义节点", enable_dynamic_field=True)
    col = Collection(NODE_COLLECTION, schema)
    _create_vector_index(col)
    return col


def create_policy_facts_collection(dim: int, drop_existing: bool = False) -> Collection:
    if utility.has_collection(FACT_COLLECTION):
        if drop_existing:
            utility.drop_collection(FACT_COLLECTION)
        else:
            return Collection(FACT_COLLECTION)

    fields = [
        FieldSchema("fact_id", DataType.VARCHAR, is_primary=True, max_length=256),
        FieldSchema("source_node_id", DataType.VARCHAR, max_length=256),
        FieldSchema("policy_id", DataType.VARCHAR, max_length=256),
        FieldSchema("policy_title", DataType.VARCHAR, max_length=1024),
        FieldSchema("fact_type", DataType.VARCHAR, max_length=128),
        FieldSchema("population", DataType.VARCHAR, max_length=128),
        FieldSchema("service_type", DataType.VARCHAR, max_length=128),
        FieldSchema("insurance_type", DataType.VARCHAR, max_length=128),
        FieldSchema("hospital_level", DataType.VARCHAR, max_length=128),
        FieldSchema("admission_order", DataType.VARCHAR, max_length=128),
        FieldSchema("amount", DataType.DOUBLE),
        FieldSchema("ratio", DataType.DOUBLE),
        FieldSchema("unit", DataType.VARCHAR, max_length=64),
        FieldSchema("derived", DataType.BOOL),
        FieldSchema("inferred", DataType.BOOL),
        FieldSchema("knowledge_group_id", DataType.VARCHAR, max_length=512),
        FieldSchema("knowledge_group_type", DataType.VARCHAR, max_length=256),
        FieldSchema("subject_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("conditions_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("value_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("value_map_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("formula_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("keywords_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("dimensions_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("depends_on_json", DataType.VARCHAR, max_length=4096),
        FieldSchema("evidence_text", DataType.VARCHAR, max_length=8192),
        FieldSchema("embedding_text", DataType.VARCHAR, max_length=16384),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=dim),
    ]
    schema = CollectionSchema(fields, description="医保政策结构化事实", enable_dynamic_field=True)
    col = Collection(FACT_COLLECTION, schema)
    _create_vector_index(col)
    return col


def _create_vector_index(col: Collection) -> None:
    index_params = {
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "params": {"M": 16, "efConstruction": 200},
    }
    col.create_index(field_name="embedding", index_params=index_params)
