"""policy_facts 写入集成测试（P3 Task 1）。依赖 Milvus，不可用则 skip。"""
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


def test_upsert_facts_writes_and_readable():
    from pymilvus import connections, utility
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
        create_policy_facts_collection, upsert_facts,
    )

    connections.connect(alias="default", host="127.0.0.1", port="19530")
    tmp = "_test_facts_write"
    try:
        col = create_policy_facts_collection(collection_name=tmp, drop_existing=True)
        records = [
            {"fact_id": "f_smoke_1", "doc_id": "d_smoke",
             "fact_text": "起付标准1300元", "vector": [0.1] * 768, "created_at": "2026-07-24"},
            {"fact_id": "f_smoke_2", "doc_id": "d_smoke",
             "fact_text": "统筹支付85%", "vector": [0.2] * 768, "created_at": "2026-07-24"},
        ]
        n = upsert_facts(col, records)
        assert n == 2
        col.load()
        res = col.query(expr='doc_id == "d_smoke"',
                        output_fields=["fact_text"], limit=10)
        texts = {r["fact_text"] for r in res}
        assert "起付标准1300元" in texts and "统筹支付85%" in texts
    finally:
        if utility.has_collection(tmp):
            utility.drop_collection(tmp)
