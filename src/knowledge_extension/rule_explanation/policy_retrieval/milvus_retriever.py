from __future__ import annotations

from pymilvus import Collection

from .embedding_provider import get_embedding_provider, EmbeddingProvider
from .milvus_schema import FACT_COLLECTION, NODE_COLLECTION, connect_milvus
from .models import SearchHit, SearchQuery
from .query_understanding import understand_query


NODE_OUTPUT_FIELDS = [
    "node_id",
    "policy_id",
    "policy_title",
    "path_text",
    "current_text",
    "full_context_text",
    "chunk_type",
    "keywords_json",
    "metadata_json",
    "embedding_text",
]

FACT_OUTPUT_FIELDS = [
    "fact_id",
    "source_node_id",
    "policy_id",
    "policy_title",
    "fact_type",
    "population",
    "service_type",
    "insurance_type",
    "hospital_level",
    "admission_order",
    "amount",
    "ratio",
    "unit",
    "derived",
    "inferred",
    "knowledge_group_id",
    "knowledge_group_type",
    "subject_json",
    "conditions_json",
    "value_json",
    "value_map_json",
    "formula_json",
    "keywords_json",
    "dimensions_json",
    "depends_on_json",
    "evidence_text",
    "embedding_text",
]


class MilvusPolicyRetriever:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: str = "19530",
        embedding_provider: EmbeddingProvider | None = None,
        embedding_kind: str = "sentence_transformer",
    ):
        connect_milvus(host=host, port=port)

        self.embedding_provider = embedding_provider or get_embedding_provider(embedding_kind)

        self.node_col = Collection(NODE_COLLECTION)
        self.fact_col = Collection(FACT_COLLECTION)

        self.node_col.load()
        self.fact_col.load()

        self.search_params = {
            "metric_type": "COSINE",
            "params": {
                "ef": 64,
            },
        }

    def search_nodes(
        self,
        query: str,
        top_k: int = 10,
        expr: str | None = None,
    ) -> list[SearchHit]:
        vector = self.embedding_provider.encode([query])[0]

        result = self.node_col.search(
            data=[vector],
            anns_field="embedding",
            param=self.search_params,
            limit=top_k,
            expr=expr,
            output_fields=NODE_OUTPUT_FIELDS,
        )

        return self._to_hits(
            result=result,
            collection=NODE_COLLECTION,
            id_field="node_id",
            output_fields=NODE_OUTPUT_FIELDS,
        )

    def search_facts(
        self,
        query: str,
        top_k: int = 10,
        expr: str | None = None,
    ) -> list[SearchHit]:
        vector = self.embedding_provider.encode([query])[0]

        result = self.fact_col.search(
            data=[vector],
            anns_field="embedding",
            param=self.search_params,
            limit=top_k,
            expr=expr,
            output_fields=FACT_OUTPUT_FIELDS,
        )

        return self._to_hits(
            result=result,
            collection=FACT_COLLECTION,
            id_field="fact_id",
            output_fields=FACT_OUTPUT_FIELDS,
        )

    def query_facts_by_expr(
        self,
        expr: str,
        limit: int = 50,
    ) -> list[SearchHit]:
        rows = self.fact_col.query(
            expr=expr,
            limit=limit,
            output_fields=FACT_OUTPUT_FIELDS,
        )

        return [
            SearchHit(
                collection=FACT_COLLECTION,
                id=r.get("fact_id", ""),
                score=None,
                entity=r,
            )
            for r in rows
        ]

    def hybrid_search(
        self,
        question: str,
        top_k: int = 10,
    ) -> dict[str, list[SearchHit]]:
        sq = understand_query(question)
        sq.top_k = top_k

        fact_expr = self._build_fact_expr(sq)

        nodes = self.search_nodes(
            query=question,
            top_k=top_k,
        )

        fact_vector_hits = self.search_facts(
            query=question,
            top_k=top_k,
            expr=fact_expr or None,
        )

        fact_filter_hits = (
            self.query_facts_by_expr(
                expr=fact_expr,
                limit=top_k * 3,
            )
            if fact_expr
            else []
        )

        merged_facts = self._merge_hits(fact_vector_hits + fact_filter_hits)

        expanded = self.expand_by_knowledge_group(
            hits=merged_facts,
            limit=top_k * 3,
        )

        merged_facts = self._merge_hits(merged_facts + expanded)

        return {
            "nodes": nodes,
            "facts": merged_facts[: top_k * 3],
        }

    def expand_by_knowledge_group(
        self,
        hits: list[SearchHit],
        limit: int = 50,
    ) -> list[SearchHit]:
        group_ids: list[str] = []

        for h in hits:
            entity = h.entity or {}
            gid = entity.get("knowledge_group_id")

            if gid and gid not in group_ids:
                group_ids.append(gid)

        if not group_ids:
            return []

        quoted = ", ".join([f'"{x}"' for x in group_ids])
        expr = f"knowledge_group_id in [{quoted}] and derived == false"

        return self.query_facts_by_expr(expr=expr, limit=limit)

    def _build_fact_expr(self, sq: SearchQuery) -> str:
        parts = ["derived == false"]

        if sq.fact_types:
            quoted = ", ".join([f'"{x}"' for x in sq.fact_types])
            parts.append(f"fact_type in [{quoted}]")

        if sq.service_type:
            parts.append(f'service_type == "{sq.service_type}"')

        if sq.population:
            parts.append(f'(population == "{sq.population}" or population == "all")')

        if sq.hospital_level:
            parts.append(
                f'(hospital_level == "{sq.hospital_level}" or hospital_level == "unknown")'
            )

        if sq.admission_order:
            parts.append(
                f'(admission_order == "{sq.admission_order}" or admission_order == "unknown")'
            )

        return " and ".join(parts)

    def _to_hits(
        self,
        result,
        collection: str,
        id_field: str,
        output_fields: list[str],
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []

        for batch in result:
            for h in batch:
                entity = self._hit_to_dict(h, output_fields)
                item_id = entity.get(id_field) or str(h.id)

                hits.append(
                    SearchHit(
                        collection=collection,
                        id=item_id,
                        score=float(h.score) if h.score is not None else None,
                        entity=entity,
                    )
                )

        return hits

    def _hit_to_dict(
        self,
        hit,
        output_fields: list[str],
    ) -> dict:
        entity = {}

        for field in output_fields:
            try:
                entity[field] = hit.entity.get(field)
            except Exception:
                entity[field] = None

        return entity

    def _merge_hits(
        self,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        seen: dict[tuple[str, str], SearchHit] = {}

        for h in hits:
            key = (h.collection, h.id)

            if key not in seen:
                seen[key] = h
                continue

            old = seen[key]

            if old.score is None:
                seen[key] = h
            elif h.score is not None and h.score > old.score:
                seen[key] = h

        return list(seen.values())