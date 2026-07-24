"""policy_rules 新版 collection（设计文档 §3.3）。

与旧 policy_rules_schema.py（21 字段扁平）的区别：
- 核心检索维度进固定 schema + 标量索引（高频过滤性能）。
- 详情字段走 dynamic field，值是字段级溯源对象 FieldTrace
  （{value, extracted_at, schema_version, confidence}）。
- 向量字段名统一为 vector（复用 policy_facts 的事实向量，见 §4.1；实际复用逻辑在 P3）。

[来源: docs/steering/政策知识管线设计文档.md §3.3 / §4.1]
"""
from __future__ import annotations

from typing import Any

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
from pydantic import BaseModel, Field

POLICY_RULES_V2_COLLECTION = "policy_rules_v2"
POLICY_RULES_V2_VECTOR_DIM = 768  # bge-base-zh-v1.5，与 policy_facts 一致

# 核心检索维度（进固定 schema + 标量索引）。设计文档 §3.3 固定 schema。
CORE_DIM_FIELDS = (
    "rule_id",      # PK
    "fact_id",      # 关联 policy_facts
    "doc_id",       # 关联 policy_documents
    "rule_type",    # 规则业务类别（起付线/报销比例/封顶线…）
    "insu_type",    # 险种
    "med_type",     # 医疗类别
    "hosp_lv",      # 医院等级
    "psn_type",     # 人群标签
    "setl_type",    # 结算方式
    "schema_version",
    "vector",
)


# ── 字段级溯源对象（设计文档 §3.3 D3）──────────────────────────

class FieldTrace(BaseModel):
    """字段级溯源：每个详情字段值携带提取元信息，而非裸值。

    落 Milvus dynamic field 时序列化为 dict（Milvus 原生支持嵌套 dict）。
    """
    value: Any = Field(description="字段值（可能是 str/float/list[dict] 等）")
    extracted_at: str = Field(description="提取时间 ISO 字符串")
    schema_version: int = Field(default=1, description="提取时所用 schema 版本")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="提取置信度")


def _connect(alias: str = "default", host: str = "127.0.0.1", port: str = "19530") -> None:
    if not connections.has_connection(alias):
        connections.connect(alias=alias, host=host, port=port)


def create_policy_rules_v2_collection(
    collection_name: str = POLICY_RULES_V2_COLLECTION,
    dim: int = POLICY_RULES_V2_VECTOR_DIM,
    drop_existing: bool = False,
    alias: str = "default",
) -> Collection:
    """创建新版 policy_rules collection（核心维度固定 schema + 标量索引 + dynamic field）。

    已存在则返回（除非 drop_existing）。
    """
    _connect(alias=alias)
    if utility.has_collection(collection_name, using=alias):
        if drop_existing:
            utility.drop_collection(collection_name, using=alias)
        else:
            return Collection(collection_name, using=alias)

    fields = [
        FieldSchema("rule_id", DataType.VARCHAR, is_primary=True, max_length=64,
                    description="规则ID（PK）"),
        FieldSchema("fact_id", DataType.VARCHAR, max_length=64,
                    description="关联 policy_facts.fact_id"),
        FieldSchema("doc_id", DataType.VARCHAR, max_length=64,
                    description="关联 policy_documents.doc_id"),
        FieldSchema("rule_type", DataType.VARCHAR, max_length=64, description="规则业务类别"),
        FieldSchema("insu_type", DataType.VARCHAR, max_length=64, description="险种"),
        FieldSchema("med_type", DataType.VARCHAR, max_length=64, description="医疗类别"),
        FieldSchema("hosp_lv", DataType.VARCHAR, max_length=64, description="医疗机构等级"),
        FieldSchema("psn_type", DataType.VARCHAR, max_length=64, description="人群标签"),
        FieldSchema("setl_type", DataType.VARCHAR, max_length=64, description="结算方式"),
        FieldSchema("schema_version", DataType.INT64, description="提取时 schema 版本"),
        FieldSchema("vector", DataType.FLOAT_VECTOR, dim=dim,
                    description="复用对应 fact 的事实向量（§4.1）"),
    ]
    schema = CollectionSchema(
        fields,
        description="政策结构化规则（核心维度固定 schema + 详情 dynamic field + 字段级溯源）",
        enable_dynamic_field=True,
    )
    col = Collection(collection_name, schema, using=alias)
    _create_indexes(col)
    return col


def _create_indexes(col: Collection) -> None:
    # 向量索引：HNSW + COSINE（与 policy_facts 一致）
    col.create_index(
        field_name="vector",
        index_params={
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200},
        },
    )
    # 核心维度标量索引（高频过滤）
    for dim in ("fact_id", "doc_id", "rule_type", "insu_type",
                "med_type", "hosp_lv", "psn_type", "setl_type"):
        col.create_index(field_name=dim, index_params={})


def drop_policy_rules_v2_collection(
    collection_name: str = POLICY_RULES_V2_COLLECTION, alias: str = "default"
) -> None:
    _connect(alias=alias)
    if utility.has_collection(collection_name, using=alias):
        utility.drop_collection(collection_name, using=alias)
