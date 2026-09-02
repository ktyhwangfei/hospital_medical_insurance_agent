"""policy_rules_v2 搜索引擎的纯函数测试。

测 unpack_detail（FieldTrace dict → 裸值）与 collection 常量，
不依赖 Milvus / 嵌入模型（纯函数）。
"""
from __future__ import annotations

from src.runtime.policy_qa.policy_rules_search import (
    COLLECTION_NAME,
    DETAIL_FIELDS,
    OUTPUT_FIELDS,
    VECTOR_FIELD,
    unpack_detail,
)


def test_collection_constants():
    """v2 collection 名与向量字段名稳定。"""
    assert COLLECTION_NAME == "policy_rules_v2"
    assert VECTOR_FIELD == "vector"


def test_unpack_detail_dict_unwrapped_to_value():
    """detail 字段是 FieldTrace dict，解包为裸 value（下游无感）。"""
    entity = {
        "payment_ratio": {"value": "85%", "extracted_at": "t", "confidence": 0.9},
        "source_text": {"value": "原文", "extracted_at": "t"},
        "rule_type": "支付比例",  # 核心维度（裸值）不变
        "insu_type": "城镇职工基本医疗保险",
    }
    r = unpack_detail(entity)
    assert r["payment_ratio"] == "85%"
    assert r["source_text"] == "原文"
    assert r["rule_type"] == "支付比例"
    assert r["insu_type"] == "城镇职工基本医疗保险"


def test_unpack_detail_core_fields_untouched():
    """核心维度字段（裸值）不被改动；无 doc_id 时 policy_id 为空。"""
    entity = {"rule_type": "支付比例", "insu_type": "城镇职工", "rule_id": "r1"}
    r = unpack_detail(entity)
    assert r["rule_type"] == "支付比例"
    assert r["insu_type"] == "城镇职工"
    assert r["rule_id"] == "r1"
    assert r["policy_id"] == ""


def test_unpack_detail_doc_id_copied_to_policy_id():
    """doc_id 复制到 policy_id，兼容下游依赖 policy_id 的消费者。"""
    entity = {"doc_id": "doc_abc"}
    r = unpack_detail(entity)
    assert r["policy_id"] == "doc_abc"
    assert r["doc_id"] == "doc_abc"


def test_unpack_detail_dict_without_value_kept():
    """dict 无 value 键时保持原样（防御异常数据）。"""
    entity = {"payment_ratio": {"foo": "bar"}}
    r = unpack_detail(entity)
    assert r["payment_ratio"] == {"foo": "bar"}


def test_output_fields_is_core_plus_detail():
    """输出字段 = 核心维度 + 详情字段。"""
    assert set(OUTPUT_FIELDS) == set(
        ["rule_id", "fact_id", "doc_id", "rule_type", "insu_type", "med_type",
         "hosp_lv", "psn_type", "setl_type",
         "region", "effective_date", "expiry_date", "publish_status",
         "policy_version", "is_remote"]
    ) | set(DETAIL_FIELDS)
