"""P8.2 迁移脚本转换单元测试（§9.2：一条 extraction = 一条 fact + 一条/多条 rule）。

仅测纯函数 to_ingest_input（不依赖 PG/Milvus），覆盖 93 条扁平 + 12 条 rules 两种形态。
"""
from src.knowledge_extension.rule_explanation.policy_retrieval.migrate_extractions_to_v2 import (
    to_ingest_input,
)


def test_flat_extraction_becomes_single_rule():
    """93 条扁平：extracted_fields 本身作为一条 rule，补确定性 rule_id。"""
    ext = {
        "extraction_id": "ext_abc123def456",
        "source_text": "原文",
        "extracted_fields": {
            "rule_type": "封顶线",
            "cap_amount": "100000",
            "path": "统筹基金最高支付限额10万元",
            "insu_type": "",
        },
    }
    out = to_ingest_input(ext)
    assert out["fact_text"] == "统筹基金最高支付限额10万元"  # path 优先于 source_text
    assert len(out["rules"]) == 1
    r = out["rules"][0]
    assert r["rule_type"] == "封顶线"
    assert r["cap_amount"] == "100000"
    assert r["rule_id"] == "rule_abc123def456"  # extraction_id 后 12 位派生（确定性、幂等）


def test_rules_form_passthrough():
    """12 条 rules 形式：直接用 fields.rules，每条补 rule_id（若无）。"""
    ext = {
        "extraction_id": "ext_aaabbbcccddd",
        "source_text": "原文",
        "extracted_fields": {
            "fact_text": "事实文本",
            "rules": [
                {"rule_type": "起付线", "rule_id": "rule_keep_me"},
                {"rule_type": "报销比例"},
            ],
        },
    }
    out = to_ingest_input(ext)
    assert out["fact_text"] == "事实文本"  # fact_text 优先
    assert len(out["rules"]) == 2
    # 已有 rule_id 保留
    assert out["rules"][0]["rule_id"] == "rule_keep_me"
    # 缺 rule_id 的补确定性 id
    assert out["rules"][1]["rule_id"] == "rule_aaabbbcccddd_1"
    assert all(r.get("rule_id") for r in out["rules"])


def test_fact_text_fallback_chain():
    """fact_text 回退链：fact_text → path → source_text → ''。"""
    # 无 fact_text/path，回退 source_text
    ext1 = {"extraction_id": "ext_1", "source_text": "原文fallback",
            "extracted_fields": {"rule_type": "X"}}
    assert to_ingest_input(ext1)["fact_text"] == "原文fallback"
    # 全空
    ext2 = {"extraction_id": "ext_2", "source_text": "", "extracted_fields": {}}
    assert to_ingest_input(ext2)["fact_text"] == ""


def test_extracted_fields_json_string():
    """extracted_fields 可能是 jsonb 字符串，应能解析。"""
    import json
    ext = {
        "extraction_id": "ext_json_test001",
        "source_text": "原文",
        "extracted_fields": json.dumps({"rule_type": "封顶线", "path": "片段"}),
    }
    out = to_ingest_input(ext)
    assert out["rules"][0]["rule_type"] == "封顶线"
    assert out["fact_text"] == "片段"
