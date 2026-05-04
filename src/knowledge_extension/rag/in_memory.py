import re

from src.knowledge_extension.assets.models import AssetQuery, KnowledgeChunk
from src.knowledge_extension.assets.ports import KnowledgeChunkRepository
from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus
from src.knowledge_extension.rag.models import ContextPackage, RetrievalHit, RetrievalRequest, RetrievalResult


class InMemoryHybridRetriever:
    def __init__(self, chunk_repository: KnowledgeChunkRepository):
        self.chunk_repository = chunk_repository

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        chunks = self.chunk_repository.list_chunks(self._to_asset_query(request))
        hits = self._match_chunks(request.query, chunks)
        reranked = self._rerank(hits)[: request.max_results]
        if not reranked:
            return RetrievalResult(
                status=KnowledgeExtensionStatus.NO_HIT,
                uncertainties=["未检索到可用知识依据，建议人工复核"],
                audit_events=[AuditSummary(event_type="rag_no_hit", summary={"query": request.query})],
            )
        context = self._assemble(reranked, request.context_budget)
        return RetrievalResult(
            status=KnowledgeExtensionStatus.SUCCESS,
            hits=reranked,
            context=context,
            citations=context.citations,
            audit_events=[AuditSummary(event_type="rag_retrieved", summary={"hits": len(reranked)})],
        )

    def _to_asset_query(self, request: RetrievalRequest) -> AssetQuery:
        return AssetQuery(
            role=request.filters.role,
            tenant_id=request.filters.tenant_id,
            campus_id=request.filters.campus_id,
            scenario=request.filters.scenario,
            asset_types=request.filters.asset_types,
        )

    def _match_chunks(self, query: str, chunks: list[KnowledgeChunk]) -> list[RetrievalHit]:
        query_terms = self._query_terms(query)
        hits = []
        for chunk in chunks:
            searchable = self._searchable_text(chunk)
            matched_terms = [term for term in query_terms if term in searchable]
            if matched_terms:
                hits.append(RetrievalHit(chunk=chunk, score=float(len(matched_terms)), matched_terms=matched_terms))
        return hits

    def _query_terms(self, query: str) -> list[str]:
        lowered = query.lower().replace("/", " ")
        terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", lowered)
        known_tokens = ["医保", "结算", "异常", "错误码", "出院", "审核", "drg", "dip", "病案", "政策"]
        terms.extend(token for token in known_tokens if token in lowered)
        seen = set()
        return [term for term in terms if not (term in seen or seen.add(term))]

    def _searchable_text(self, chunk: KnowledgeChunk) -> str:
        return " ".join([chunk.text, chunk.summary, " ".join(chunk.tags), " ".join(chunk.scenario_tags)]).lower()

    def _rerank(self, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        return sorted(hits, key=lambda hit: (-hit.score, hit.chunk.asset_type.value, hit.chunk.chunk_id))

    def _assemble(self, hits: list[RetrievalHit], budget: int) -> ContextPackage:
        context_parts = []
        citations = []
        used = 0
        truncated = 0
        for hit in hits:
            remaining = budget - used
            if remaining <= 0:
                truncated += 1
                continue
            selected = hit.chunk.text[:remaining]
            used += len(selected)
            if len(selected) < len(hit.chunk.text):
                truncated += 1
            context_parts.append(selected)
            citations.append(
                Citation(
                    source_id=hit.chunk.asset_id,
                    source_type=hit.chunk.asset_type.value,
                    title=hit.chunk.title,
                    version=hit.chunk.asset_version,
                    section=hit.chunk.section,
                    chunk_id=hit.chunk.chunk_id,
                    evidence=hit.chunk.summary,
                    score=hit.score,
                    internal_locator=hit.chunk.locator,
                )
            )
        return ContextPackage(hits=hits, citations=citations, context_text="\n".join(context_parts), truncated_count=truncated)
