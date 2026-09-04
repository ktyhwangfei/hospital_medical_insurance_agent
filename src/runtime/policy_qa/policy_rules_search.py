"""
医保政策问答 RAG - policy_rules_v2 搜索引擎

搜索 Milvus policy_rules_v2 集合（schema-driven 提取的结构化政策规则，
向量复用 policy_facts）。返回的 detail 字段已解包为裸值，下游消费者无感。
"""

from __future__ import annotations

from typing import Any

# policy_rules_v2 collection（schema-driven 提取）
COLLECTION_NAME = "policy_rules_v2"
# 向量字段名（复用 policy_facts 的向量）
VECTOR_FIELD = "vector"

# 核心维度字段（固定列，裸值）
# amount_band_min/max 在 release 产物集合中是 dynamic key（可按名取回），
# 在新建 v2 schema 中是固定列（Issue #25 阶段 2）
CORE_FIELDS = (
    "rule_id", "fact_id", "doc_id",
    "rule_type", "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
    "region", "effective_date", "expiry_date", "publish_status",
    "policy_version", "is_remote", "amount_band_min", "amount_band_max",
)

# 详情字段（落 dynamic field，值是 FieldTrace dict，需解包 .value）
DETAIL_FIELDS = (
    "payment_ratio", "deductible_amount", "cap_amount", "amount_band",
    "time_period", "admission_order", "priority", "rule_value", "source_text",
)

# 检索输出字段
OUTPUT_FIELDS = list(CORE_FIELDS) + list(DETAIL_FIELDS)


def unpack_detail(entity: dict[str, Any]) -> dict[str, Any]:
    """detail 字段落 dynamic field，值是 FieldTrace dict，解包为裸 value。

    并将 doc_id 复制到 policy_id，兼容下游依赖 policy_id 的消费者。
    """
    for f in DETAIL_FIELDS:
        v = entity.get(f)
        if isinstance(v, dict) and "value" in v:
            entity[f] = v["value"]
    if "policy_id" not in entity:
        entity["policy_id"] = entity.get("doc_id", "")
    return entity
