from .milvus_retriever import MilvusPolicyRetriever


def main():
    retriever = MilvusPolicyRetriever(embedding_kind="sentence_transformer")  # 本地打通流程用 hash；生产改 sentence_transformer
    for q in ["三级医院成人首次住院起付线是多少", "三级医院成人跨周期住院起付线为什么是1950元"]:
        print("=" * 80)
        print("Q:", q)
        result = retriever.hybrid_search(q, top_k=5)
        print("\nFACTS")
        for h in result["facts"]:
            e = h.entity or {}
            print(
                h.score,
                e.get("fact_id"),
                e.get("fact_type"),
                e.get("population"),
                e.get("service_type"),
                e.get("hospital_level"),
                e.get("admission_order"),
                e.get("amount"),
                e.get("ratio"),
                e.get("evidence_text"),
            )
        print("\nNODES")
        for h in result["nodes"]:
            e = h.entity or {}
            current_text = e.get("current_text") or ""
            print(h.score, e.get("node_id"), e.get("path_text"), current_text[:80])


if __name__ == "__main__":
    main()
