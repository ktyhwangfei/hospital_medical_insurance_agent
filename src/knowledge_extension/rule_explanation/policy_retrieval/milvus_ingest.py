from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from pymilvus import Collection

from .embedding_provider import get_embedding_provider
from .excel_loader import load_policy_facts_from_excel, load_policy_nodes_from_excel
from .milvus_schema import FACT_COLLECTION, NODE_COLLECTION, connect_milvus, create_policy_collections
from .utils import dumps_json


def none_to_default(value: Any, default: Any) -> Any:
    return default if value is None else value


def nodes_to_entities(nodes, vectors):
    entities = []
    for node, vector in zip(nodes, vectors):
        entities.append({
            "node_id": node.node_id,
            "policy_id": node.policy_id or "",
            "policy_title": node.policy_title or "",
            "parent_id": node.parent_id or "",
            "level": node.level or 0,
            "path_text": node.path_text or "",
            "current_text": node.current_text or "",
            "full_context_text": node.full_context_text or "",
            "chunk_type": node.chunk_type or "",
            "keywords_json": dumps_json(node.keywords),
            "metadata_json": dumps_json(node.metadata),
            "embedding_text": node.embedding_text or "",
            "embedding": vector,
        })
    return entities


def facts_to_entities(facts, vectors):
    entities = []
    for fact, vector in zip(facts, vectors):
        entities.append({
            "fact_id": fact.fact_id,
            "source_node_id": fact.source_node_id or "",
            "policy_id": fact.policy_id or "",
            "policy_title": fact.policy_title or "",
            "fact_type": fact.fact_type or "",
            "population": fact.population or "unknown",
            "service_type": fact.service_type or "unknown",
            "insurance_type": fact.insurance_type or "unknown",
            "hospital_level": fact.hospital_level or "unknown",
            "admission_order": fact.admission_order or "unknown",
            "amount": fact.amount if fact.amount is not None else -1.0,
            "ratio": fact.ratio if fact.ratio is not None else -1.0,
            "unit": fact.unit or "unknown",
            "derived": bool(fact.derived),
            "inferred": bool(fact.inferred),
            "knowledge_group_id": fact.knowledge_group_id or "",
            "knowledge_group_type": fact.knowledge_group_type or "",
            "subject_json": dumps_json(fact.subject),
            "conditions_json": dumps_json(fact.conditions),
            "value_json": dumps_json(fact.value),
            "value_map_json": dumps_json(fact.value_map),
            "formula_json": dumps_json(fact.formula),
            "keywords_json": dumps_json(fact.keywords),
            "dimensions_json": dumps_json(fact.dimensions),
            "depends_on_json": dumps_json(fact.depends_on),
            "evidence_text": fact.evidence_text or "",
            "embedding_text": fact.embedding_text or "",
            "embedding": vector,
        })
    return entities


def batch_insert(collection: Collection, entities: list[dict[str, Any]], batch_size: int = 512) -> None:
    if not entities:
        return
    for i in range(0, len(entities), batch_size):
        collection.insert(entities[i:i + batch_size])
    collection.flush()
    collection.load()


def ingest_from_excel(
    *,
    nodes_excel: str | Path,
    facts_excel: str | Path,
    host: str = "127.0.0.1",
    port: str = "19530",
    embedding_kind: str = "sentence_transformer",
    drop_existing: bool = False,
) -> None:
    provider = get_embedding_provider(embedding_kind)
    connect_milvus(host=host, port=port)
    create_policy_collections(dim=provider.dim, drop_existing=drop_existing)

    nodes = load_policy_nodes_from_excel(nodes_excel)
    facts = load_policy_facts_from_excel(facts_excel)

    print(f"loaded nodes={len(nodes)}, facts={len(facts)}")

    node_vectors = provider.encode([x.embedding_text or "" for x in nodes])
    fact_vectors = provider.encode([x.embedding_text or "" for x in facts])

    node_col = Collection(NODE_COLLECTION)
    fact_col = Collection(FACT_COLLECTION)

    batch_insert(node_col, nodes_to_entities(nodes, node_vectors))
    batch_insert(fact_col, facts_to_entities(facts, fact_vectors))

    print("ingest done")
    print(f"{NODE_COLLECTION}: {node_col.num_entities}")
    print(f"{FACT_COLLECTION}: {fact_col.num_entities}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes-excel", required=True)
    parser.add_argument("--facts-excel", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="19530")
    parser.add_argument("--embedding-kind", default="sentence_transformer", choices=["sentence_transformer", "hash"])
    parser.add_argument("--drop-existing", action="store_true")
    args = parser.parse_args()

    ingest_from_excel(
        nodes_excel=args.nodes_excel,
        facts_excel=args.facts_excel,
        host=args.host,
        port=args.port,
        embedding_kind=args.embedding_kind,
        drop_existing=args.drop_existing,
    )


if __name__ == "__main__":
    main()
