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


# 详情字段集合：这些字段不进固定 schema，作为 FieldTrace 落 dynamic field。
# 核心维度（CORE_DIM_FIELDS）外的字段都视为详情字段。
DETAIL_FIELDS = (
    "payment_ratio", "deductible_amount", "cap_amount", "amount_band",
    "time_period", "admission_order", "priority", "rule_value", "source_text",
    "entities", "relations",
)


# ── 维度值标准化（政策原文值 → 业务标准值，对齐 semantic_layer/seed.py 字典）──
# hosp_lv: seed.py 标准 ["三级","二级","一级","无等级"]
_HOSP_LV_NORMALIZE = {
    "社区": "一级",      # 社区卫生服务中心 ≈ 一级
    "未定级": "无等级",
}
# med_type: seed.py 标准 ["住院-普通住院","住院-门特住院","门诊-普通门急诊","门诊-一般门特",...]
# 政策原文多用大类（"住院"），业务结算是细类（"住院-普通住院"）。
_MED_TYPE_NORMALIZE = {
    "住院": "住院-普通住院",
    "门诊": "门诊-普通门急诊",
    "门特": "门诊-一般门特",
    "急诊": "门诊-急诊留观",
    "购药": "门诊-普通门急诊",
}


def normalize_hosp_lv(value: str) -> str:
    """医院等级标准化到 seed.py 业务字典值。"""
    return _HOSP_LV_NORMALIZE.get(value, value)


def normalize_med_type(value: str) -> str:
    """医疗类别标准化：政策大类 → seed.py 业务细类。

    复合值（含分隔符，如"住院,门特"）取第一个可映射的大类。
    """
    if not value:
        return value
    if value in _MED_TYPE_NORMALIZE:
        return _MED_TYPE_NORMALIZE[value]
    for sep in (",", "，", ";", "；"):
        if sep in value:
            for part in value.split(sep):
                p = part.strip()
                if p in _MED_TYPE_NORMALIZE:
                    return _MED_TYPE_NORMALIZE[p]
    return value


def rule_to_entity(
    rule: dict[str, Any],
    vector: list[float],
    extracted_at: str = "",
    schema_version: int = 1,
    confidence: float = 0.0,
) -> dict[str, Any]:
    """把一条规则 dict 转为 Milvus entity。

    - 核心维度 → 固定 schema 字段（顶层标量）。
    - 详情字段 → FieldTrace dict（落 dynamic field，字段级溯源）。
    - vector → 由调用方提供（P2 占位；P3 由 fact 向量复用，§4.1）。

    Args:
        rule: 规则 dict，含核心维度 + 详情字段（详情字段为裸值）。
        vector: 规则向量（复用 fact 的事实向量）。
        extracted_at: 本次提取时间（ISO），用于所有详情字段的溯源。
        schema_version: 本次提取所用 schema 版本。
        confidence: 本次提取置信度。
    """
    entity: dict[str, Any] = {"vector": vector, "schema_version": schema_version}

    # 核心维度（rule_id/fact_id/doc_id/rule_type/insu_type/med_type/hosp_lv/psn_type/setl_type）
    # hosp_lv/med_type 标准化到业务字典值（对齐 semantic_layer/seed.py）
    for dim in CORE_DIM_FIELDS:
        if dim in ("vector", "schema_version"):
            continue
        val = str(rule.get(dim, ""))
        if dim == "hosp_lv":
            val = normalize_hosp_lv(val)
        elif dim == "med_type":
            val = normalize_med_type(val)
        entity[dim] = val

    # 详情字段 → FieldTrace（裸值包成溯源对象）
    for detail in DETAIL_FIELDS:
        if detail in rule and rule[detail] is not None:
            trace = FieldTrace(
                value=rule[detail],
                extracted_at=extracted_at,
                schema_version=schema_version,
                confidence=confidence,
            )
            entity[detail] = trace.model_dump()

    return entity


def upsert_rules(col: Collection, entities: list[dict[str, Any]]) -> int:
    """批量写入规则实体（rule_to_entity 产出）到 policy_rules_v2。

    Args:
        col: policy_rules_v2 Collection（已创建）。
        entities: 每条为 rule_to_entity 返回的 dict。
    Returns: 写入条数。
    """
    if not entities:
        return 0
    col.insert(entities)
    col.flush()
    return len(entities)


def query_rules_by_doc(
    doc_id: str,
    col: Collection | None = None,
    collection_name: str = POLICY_RULES_V2_COLLECTION,
    alias: str = "default",
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """按 doc_id 查询 policy_rules_v2 的所有规则（P5 执行器的 read 步骤）。

    col 可注入（测试用 fake collection）；生产时内部连接 Milvus。
    output_fields=['*'] 取全部字段（含 dynamic 详情字段的 FieldTrace dict）。

    [来源: 设计文档 §6.1 read-modify-write]
    """
    if col is None:
        _connect(alias)
        if not utility.has_collection(collection_name, using=alias):
            return []
        col = Collection(collection_name, using=alias)
        col.load()
    return col.query(
        expr=f'doc_id == "{doc_id}"',
        output_fields=["*"],
        limit=limit,
    )
