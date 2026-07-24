"""policy_rules 新版 collection schema 验证（P2）。

验证设计文档 §3.3：核心检索维度进固定 schema + 标量索引，
详情字段走 dynamic field（字段级溯源对象）。

依赖 Milvus @ 127.0.0.1:19530；不可用则 skip。测试用独立临时 collection 名，不碰生产。
"""
import pytest

MILVUS_URI = "http://127.0.0.1:19530"


def _milvus_ready() -> bool:
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI, timeout=2)
        c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _milvus_ready(), reason="Milvus 不可用（需 127.0.0.1:19530）")


def test_create_v2_collection_has_core_dims_and_dynamic():
    """新 collection 固定 schema 含全部核心维度，标量索引齐全，dynamic field 启用。"""
    from pymilvus import connections, utility, Collection
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection,
        CORE_DIM_FIELDS,
    )

    connections.connect(alias="default", host="127.0.0.1", port="19530")
    tmp_name = "_test_pr_v2_schema"
    try:
        col = create_policy_rules_v2_collection(collection_name=tmp_name, drop_existing=True)
        # 固定 schema 含全部核心维度
        field_names = {f.name for f in col.schema.fields}
        for dim in CORE_DIM_FIELDS:
            assert dim in field_names, f"核心维度 {dim} 应在固定 schema 中"
        # rule_id 是主键
        pk = next(f for f in col.schema.fields if f.name == "rule_id")
        assert pk.is_primary is True
        # vector 字段存在（768 维浮点向量）
        vec = next(f for f in col.schema.fields if f.name == "vector")
        assert vec.dtype.name == "FLOAT_VECTOR"
        # dynamic field 启用
        assert col.schema.enable_dynamic_field is True
        # 核心维度已建标量索引（rule_id 为主键、vector 走向量索引）
        indexed = {idx.field_name for idx in col.indexes}
        for dim in ("insu_type", "med_type", "hosp_lv", "psn_type", "setl_type", "fact_id", "doc_id"):
            assert dim in indexed, f"{dim} 应建标量索引，实际 indexed={indexed}"
    finally:
        if utility.has_collection(tmp_name):
            utility.drop_collection(tmp_name)
