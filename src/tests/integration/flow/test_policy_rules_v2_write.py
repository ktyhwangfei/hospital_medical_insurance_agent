"""policy_rules_v2 写入集成测试（P3 Task 2）。依赖 Milvus，不可用则 skip。"""
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


pytestmark = pytest.mark.skipif(not _milvus_ready(), reason="Milvus 不可用")


def test_upsert_rules_writes_entities():
    from pymilvus import connections, utility
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection, rule_to_entity, upsert_rules,
    )

    connections.connect(alias="default", host="127.0.0.1", port="19530")
    tmp = "_test_rules_v2_write"
    try:
        col = create_policy_rules_v2_collection(collection_name=tmp, drop_existing=True)
        rule = {
            "rule_id": "r_smoke_p3", "rule_type": "起付线",
            "insu_type": "城镇职工基本医疗保险", "hosp_lv": "三级医院",
            "deductible_amount": "1300元",
        }
        entity = rule_to_entity(rule, vector=[0.1] * 768,
                                extracted_at="2026-07-24", confidence=0.9)
        n = upsert_rules(col, [entity])
        assert n == 1
        col.load()
        res = col.query(expr='insu_type == "城镇职工基本医疗保险"',
                        output_fields=["rule_type", "deductible_amount"], limit=5)
        assert len(res) == 1
        assert res[0]["rule_type"] == "起付线"
        da = res[0]["deductible_amount"]
        assert isinstance(da, dict) and da["value"] == "1300元" and da["confidence"] == 0.9
    finally:
        if utility.has_collection(tmp):
            utility.drop_collection(tmp)
