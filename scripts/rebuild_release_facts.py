"""一键修复当前 active release 的 fact 层数据。

两个目的：
1. fact_text 维度修复：按 fact_id 汇总 rules，用修复后的 _sentence 重新生成
   带医院等级/金额区间等区分字段的完整业务句，并重新向量化。
2. 段落级溯源回填：为 fact 补 unit_id / unit_source_text（dynamic field），
   映射来源：change set 的 rule_id → unit_id；兜底用 rule.source_text 片段
   在 policy_extractions 里反查所属单元。

用法（项目根目录）：
    uv run python scripts/rebuild_release_facts.py
"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 允许从项目根目录以 scripts/xxx.py 方式直接运行
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg
from pymilvus import MilvusClient

from src.config.production import DATABASE_URL, MILVUS_HOST, MILVUS_PORT
from src.knowledge_extension.rule_explanation.change_set_store import (
    PostgresChangeSetStore,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    _sentence,
)
from src.knowledge_extension.rule_explanation.release_resolver import get_active_release
from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
    get_embedding_provider,
)
from src.runtime.policy_qa.policy_rules_search import unpack_detail


def _collect_rules_by_fact(rules: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for r in rules:
        unpack_detail(r)
        fid = str(r.get("fact_id") or "")
        rid = str(r.get("rule_id") or "")
        if not fid or (fid, rid) in seen:
            continue
        seen.add((fid, rid))
        groups.setdefault(fid, []).append(r)
    return groups


def _rebuild_fact_text(fact: dict[str, Any], rules: list[dict[str, Any]]) -> str:
    if not rules:
        return str(fact.get("fact_text") or "")
    sentences: list[str] = []
    seen_texts: set[str] = set()
    for rule in rules:
        s = _sentence(rule).strip()
        if not s or s in seen_texts:
            continue
        seen_texts.add(s)
        sentences.append(s)
    if not sentences:
        return str(fact.get("fact_text") or "")
    return " ".join(sentences)


def _load_rule_unit_map() -> dict[str, tuple[str, str]]:
    """rule_id → (unit_id, unit_source_text)，来自全部 change set。"""
    mapping: dict[str, tuple[str, str]] = {}
    store = PostgresChangeSetStore()
    for change_set in store.list():
        for item in change_set.items:
            unit_id = str(item.unit_id or "")
            if not unit_id:
                continue
            after = item.after or {}
            source_text = str(after.get("source_text") or "")
            if not source_text:
                citations = after.get("citations") or []
                if citations and isinstance(citations[0], dict):
                    source_text = str(citations[0].get("evidence") or "")
            mapping[str(item.rule_id)] = (unit_id, source_text)
    return mapping


def _load_extractions() -> tuple[dict[tuple[str, str], str], dict[str, list[tuple[str, str]]]]:
    """(doc_id, unit_id) → source_text；以及 doc_id → [(unit_id, source_text)] 用于片段反查。"""
    by_key: dict[tuple[str, str], str] = {}
    by_doc: dict[str, list[tuple[str, str]]] = {}
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT doc_id, unit_id, source_text FROM policy_extractions "
            "WHERE status <> 'archived'"
        )
        for doc_id, unit_id, source_text in cur.fetchall():
            text = str(source_text or "")
            if not text:
                continue
            if unit_id:
                by_key[(str(doc_id), str(unit_id))] = text
            by_doc.setdefault(str(doc_id), []).append((str(unit_id or ""), text))
    return by_key, by_doc


def _resolve_unit(
    fact: dict[str, Any],
    rules: list[dict[str, Any]],
    rule_unit_map: dict[str, tuple[str, str]],
    ext_by_key: dict[tuple[str, str], str],
    ext_by_doc: dict[str, list[tuple[str, str]]],
) -> tuple[str, str]:
    """为 fact 定位所属提取单元，返回 (unit_id, unit_source_text)。"""
    doc_id = str(fact.get("doc_id") or "")
    for rule in rules:
        hit = rule_unit_map.get(str(rule.get("rule_id") or ""))
        if hit:
            unit_id, source_text = hit
            if not source_text:
                source_text = ext_by_key.get((doc_id, unit_id), "")
            return unit_id, source_text
    # 兜底：用规则 source_text 片段在本文档提取记录里反查
    for rule in rules:
        fragment = str(rule.get("source_text") or "").strip()
        if len(fragment) < 8:
            continue
        for unit_id, source_text in ext_by_doc.get(doc_id, []):
            if fragment in source_text:
                return unit_id, source_text
    return "", ""


def main() -> int:
    release = get_active_release()
    if release is None:
        print("当前没有 active release")
        return 1

    print(f"active release: {release.release_id}")
    print(f"facts: {release.facts_collection}")
    print(f"rules: {release.rules_collection}")

    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    provider = get_embedding_provider()

    def _fetch_all(collection: str, fields: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        iterator = client.query_iterator(
            collection_name=collection,
            filter="",
            output_fields=fields,
            batch_size=2000,
        )
        while True:
            batch = iterator.next()
            if not batch:
                break
            rows.extend(batch)
        return rows

    facts = _fetch_all(
        release.facts_collection,
        ["fact_id", "doc_id", "fact_text", "created_at", "vector", "unit_id", "unit_source_text"],
    )
    print(f"loaded {len(facts)} facts")

    rules = _fetch_all(
        release.rules_collection,
        [
            "rule_id", "fact_id", "rule_type", "psn_type", "med_type",
            "hosp_lv", "amount_band", "payment_ratio", "deductible_amount",
            "cap_amount", "jjgs", "rule_value", "source_text",
        ],
    )
    print(f"loaded {len(rules)} rules")

    rule_unit_map = _load_rule_unit_map()
    print(f"loaded {len(rule_unit_map)} rule→unit 映射（change sets）")
    ext_by_key, ext_by_doc = _load_extractions()
    print(f"loaded {len(ext_by_key)} 提取单元（policy_extractions）")

    rules_by_fact = _collect_rules_by_fact(rules)

    updated: list[dict[str, Any]] = []
    unchanged = 0
    for fact in facts:
        fid = fact["fact_id"]
        fact_rules = rules_by_fact.get(fid, [])
        new_text = _rebuild_fact_text(fact, fact_rules)
        unit_id, unit_source_text = _resolve_unit(
            fact, fact_rules, rule_unit_map, ext_by_key, ext_by_doc
        )
        text_changed = bool(new_text) and new_text != str(fact.get("fact_text") or "")
        unit_changed = (
            unit_id != str(fact.get("unit_id") or "")
            or unit_source_text != str(fact.get("unit_source_text") or "")
        )
        if not text_changed and not unit_changed:
            unchanged += 1
            continue
        record = dict(fact)
        record["fact_text"] = new_text or str(fact.get("fact_text") or "")
        record["unit_id"] = unit_id
        record["unit_source_text"] = unit_source_text
        if text_changed:
            record["vector"] = provider.encode([record["fact_text"]])[0]
        updated.append(record)

    if not updated:
        print(f"没有需要更新的 fact（{unchanged} 条未变）")
        return 0

    print(f"updating {len(updated)} facts, {unchanged} unchanged")
    batch_size = 500
    for i in range(0, len(updated), batch_size):
        batch = updated[i:i + 500]
        client.upsert(collection_name=release.facts_collection, data=batch)
        print(f"  upserted {len(batch)}")

    client.load_collection(release.facts_collection)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
