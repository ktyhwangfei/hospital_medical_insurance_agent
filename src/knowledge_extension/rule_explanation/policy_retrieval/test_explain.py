from __future__ import annotations

from dataclasses import asdict

from .milvus_retriever import MilvusPolicyRetriever
from .query_understanding import understand_query
from .reranker import RuleBasedReranker
from .explanation_planner import ExplanationPlanner


def run_one(question: str):
    retriever = MilvusPolicyRetriever(
        host="127.0.0.1",
        port="19530",
        embedding_kind="sentence_transformer",
    )

    sq = understand_query(question)
    raw = retriever.hybrid_search(question, top_k=10)

    reranker = RuleBasedReranker()
    facts = reranker.rerank_facts(raw["facts"], sq)
    nodes = reranker.rerank_nodes(raw["nodes"], sq)
    evidence = reranker.pick_evidence(sq, facts, nodes)

    planner = ExplanationPlanner()
    trace = planner.build(evidence)

    print("=" * 80)
    print("Q:", question)

    print("\nSELECTED FACTS")
    for h in evidence.facts:
        e = h.entity or {}
        print(
            h.rerank_score,
            e.get("fact_id"),
            e.get("fact_type"),
            e.get("population"),
            e.get("service_type"),
            e.get("hospital_level"),
            e.get("admission_order"),
            e.get("amount"),
            e.get("ratio"),
        )
        print("  debug:", " | ".join(h.rerank_debug))

    print("\nANSWER")
    print(trace.final_explanation)

    print("\nTRACE")
    print(asdict(trace))


def main():
    questions = [
        "三级医院成人首次住院起付线是多少",
        "三级医院成人跨周期住院起付线为什么是1950元",
    ]

    for q in questions:
        run_one(q)


if __name__ == "__main__":
    main()
