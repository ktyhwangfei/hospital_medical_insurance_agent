"""P8.2 数据迁移：PG policy_extractions → Milvus policy_facts + policy_rules_v2。

[来源: docs/steering/政策知识管线开发计划.md §9.2 / Phase 8]

规则：一条 extraction = 一条 fact + 一条/多条 rule。
- 93 条扁平（extracted_fields 无 rules）：扁平字段包成单条 rule，补确定性 rule_id。
- 12 条 rules 形式（fields.rules）：直接用，每条补 rule_id（若无）。

幂等：--drop 先 drop + recreate 两个新 collection（新 collection 独立于生产读的旧
policy_rules，灰度安全；§9 策略：建新→迁+校验→切换→下旧）。

用法：
    python -m src.knowledge_extension.rule_explanation.policy_retrieval.migrate_extractions_to_v2 --dry-run
    python -m src.knowledge_extension.rule_explanation.policy_retrieval.migrate_extractions_to_v2 --drop --verify
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def to_ingest_input(ext: dict) -> dict:
    """单条 extraction → build_ingest_records 输入 {fact_text, rules}。

    - fact_text 优先级：fields.fact_text → fields.path → source_text → ''
    - rules：有 fields.rules 用之（补 rule_id）；否则扁平 fields 包成单 rule。
    - rule_id 从 extraction_id 后 12 位派生（确定性，幂等重跑同 id）。
    """
    fields = ext.get("extracted_fields") or {}
    if isinstance(fields, str):
        fields = json.loads(fields)

    fact_text = (
        fields.get("fact_text")
        or fields.get("path")
        or ext.get("source_text")
        or ""
    )

    ext_id = ext.get("extraction_id", "")
    suffix = ext_id[-12:] if ext_id else uuid.uuid4().hex[:12]

    rules_raw = fields.get("rules")
    if rules_raw:
        # 12 条 rules 形式：直传，补缺失的 rule_id
        rules: list[dict[str, Any]] = []
        for i, r in enumerate(rules_raw):
            r = dict(r)
            if not r.get("rule_id"):
                r["rule_id"] = f"rule_{suffix}_{i}"
            rules.append(r)
    else:
        # 93 条扁平：fields 本身作为一条 rule（剔除 rules 键防污染）
        rule = {k: v for k, v in fields.items() if k != "rules"}
        rule["rule_id"] = f"rule_{suffix}"
        rules = [rule]

    return {"fact_text": fact_text, "rules": rules}


def read_extractions() -> list[dict]:
    """读 PG policy_extractions（有 extracted_fields 的全部）。"""
    import psycopg

    from src.config.production import DATABASE_URL

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT extraction_id, doc_id, source_text, extracted_fields, status "
                "FROM policy_extractions WHERE extracted_fields IS NOT NULL"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def migrate(drop: bool = False, dry_run: bool = False) -> dict:
    """执行迁移，返回统计 {extractions, facts, rules}。

    dry_run=True 只构造不写入。drop=True 先 drop+recreate 新 collection。
    """
    from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
        get_embedding_provider,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
        create_policy_facts_collection,
        drop_policy_facts_collection,
        upsert_facts,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_ingestion import (
        build_ingest_records,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection,
        drop_policy_rules_v2_collection,
        upsert_rules,
    )

    exts = read_extractions()
    inputs = [to_ingest_input(e) for e in exts]

    provider = get_embedding_provider()
    extracted_at = datetime.now(timezone.utc).isoformat()

    all_facts: list[dict] = []
    all_rules: list[dict] = []
    # 每条 extraction 一条 fact（build_ingest_records 按 doc_id 分组；同 doc 多 extraction → 多 fact）
    for ext, inp in zip(exts, inputs):
        fact_records, rule_entities = build_ingest_records(
            [inp], doc_id=ext["doc_id"], provider=provider, extracted_at=extracted_at,
        )
        all_facts += fact_records
        all_rules += rule_entities

    # U3 折算展开：退休人员个人支付比例 = 职工个人支付比例 × 系数，物化多条退休绝对值规则
    # （跨 extraction：折算规则与基数规则同 doc，故在全量累积后展开）
    from src.knowledge_extension.rule_explanation.policy_retrieval.rule_derivation import (
        derive_personal_payment_ratios,
    )
    derived_rules = derive_personal_payment_ratios(all_rules)
    all_rules += derived_rules

    stats = {
        "extractions": len(exts),
        "facts": len(all_facts),
        "rules": len(all_rules),
        "derived_rules": len(derived_rules),
    }

    if dry_run:
        stats["dry_run"] = True
        logger.warning("[dry-run] 未写入 Milvus。stats=%s", stats)
        return stats

    if drop:
        # drop_policy_facts_collection 不自动建连，需先连 Milvus（读 production.MILVUS_HOST/PORT）
        from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import connect_milvus
        connect_milvus()
        logger.warning("[drop] 重建 policy_facts + policy_rules_v2 collection")
        drop_policy_facts_collection()
        drop_policy_rules_v2_collection()

    facts_col = create_policy_facts_collection()
    rules_col = create_policy_rules_v2_collection()
    upsert_facts(facts_col, all_facts)
    upsert_rules(rules_col, all_rules)
    logger.warning("[done] 写入完成。stats=%s", stats)
    return stats


def verify(stats: dict) -> dict:
    """count 对账：Milvus 实际 entities vs migrate 统计。"""
    from pymilvus import Collection, connections

    if not connections.has_connection("default"):
        connections.connect(host="127.0.0.1", port="19530")
    facts_col = Collection("policy_facts")
    rules_col = Collection("policy_rules_v2")
    facts_col.flush()
    rules_col.flush()
    actual = {
        "policy_facts": facts_col.num_entities,
        "policy_rules_v2": rules_col.num_entities,
    }
    expected = {"policy_facts": stats["facts"], "policy_rules_v2": stats["rules"]}
    ok = actual["policy_facts"] == expected["policy_facts"] and \
        actual["policy_rules_v2"] == expected["policy_rules_v2"]
    return {"actual": actual, "expected": expected, "match": ok}


def main() -> None:
    import argparse

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    p = argparse.ArgumentParser(description="P8.2 迁移 policy_extractions → facts+rules_v2")
    p.add_argument("--drop", action="store_true", help="迁移前 drop+recreate 新 collection")
    p.add_argument("--dry-run", action="store_true", help="只构造不写入")
    p.add_argument("--verify", action="store_true", help="迁移后 count 对账")
    args = p.parse_args()

    stats = migrate(drop=args.drop, dry_run=args.dry_run)
    print("migrate stats:", stats)
    if args.verify and not args.dry_run:
        print("verify:", verify(stats))


if __name__ == "__main__":
    main()
