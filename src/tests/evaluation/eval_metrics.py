"""
检索质量评估 — 指标计算（Recall@k, MRR, Hit@k, NDCG@k, RRF 融合）。

纯 Python 函数，无外部依赖（不需要 Milvus / FastAPI）。
供 test_retrieval_quality.py 和 test_retrieval_regression.py 使用。

基于：docs/research/知识召回质量评估方案.md §3
增强：支持向量+BM25 混合检索评估（RRF 融合算法）

[来源: docs/research/知识召回质量评估方案.md §1]
"""
from __future__ import annotations

import math
from typing import Any


# ── 相关性判断 ───────────────────────────────────────

def is_relevant(hit: Any, expected: dict) -> bool:
    """宽松标注：rule_type 匹配 + 至少 1 个维度字段匹配。

    基于 policy_rules_v2 实际字段名（insu_type, hosp_lv, psn_type,
    med_type, setl_type, rule_type）。

    Args:
        hit: EvalHit（或任何带 .entity 属性的对象）。
        expected: eval_queries.yaml 中的 expected 字段。

    Returns:
        True 如果该结果被认为与 query 相关。
    """
    entity = hit.entity if hasattr(hit, "entity") else (hit.get("entity") or {})

    # rule_type 必须匹配（如果指定）
    if expected.get("rule_types"):
        rule_type = entity.get("rule_type", "")
        if rule_type not in expected["rule_types"]:
            return False

    # 至少 1 个维度字段匹配
    dim_fields = [
        "insu_type", "hosp_lv", "psn_type",
        "med_type", "setl_type",
    ]
    any_dim_specified = any(f in expected for f in dim_fields)

    if not any_dim_specified:
        return True if expected.get("rule_types") else False

    for field in dim_fields:
        if field in expected and entity.get(field) == expected.get(field):
            return True

    return False


# ── 排序-aware 相关性评分（用于 NDCG）──────────────

def relevance_score(hit: Any, expected: dict) -> float:
    """返回命中的相关性分数（0.0 / 0.5 / 1.0）。

    用于 NDCG 计算，比 is_relevant() 更精细：
    - 1.0: rule_type + 维度都匹配
    - 0.5: rule_type 匹配但维度不匹配
    - 0.0: rule_type 不匹配
    """
    entity = hit.entity if hasattr(hit, "entity") else (hit.get("entity") or {})

    if expected.get("rule_types"):
        rule_type = entity.get("rule_type", "")
        if rule_type not in expected["rule_types"]:
            return 0.0

    dim_fields = ["insu_type", "hosp_lv", "psn_type", "med_type", "setl_type"]
    any_dim_specified = any(f in expected for f in dim_fields)

    if not any_dim_specified:
        return 1.0

    for field in dim_fields:
        if field in expected and entity.get(field) == expected.get(field):
            return 1.0

    return 0.5 if expected.get("rule_types") else 0.0


# ── 核心指标 ─────────────────────────────────────────

def recall_at_k(results: list[Any], expected: dict, k: int = 5) -> float:
    """Recall@k：前 k 个结果中命中相关文档的比例。

    recall = min(relevant_count_in_top_k / total_relevant_expected, 1.0)
    """
    total_relevant = expected.get("min_relevant_hits", 1)
    if total_relevant == 0:
        return 1.0
    relevant_count = sum(1 for hit in results[:k] if is_relevant(hit, expected))
    return min(relevant_count / total_relevant, 1.0)


def mrr(results: list[Any], expected: dict) -> float:
    """MRR (Mean Reciprocal Rank)：第一个相关结果的倒数排名。

    第一个相关结果排在位置 rank → 得分 = 1/rank。无相关结果 → 0。
    """
    for rank, hit in enumerate(results, start=1):
        if is_relevant(hit, expected):
            return 1.0 / rank
    return 0.0


def hit_at_k(results: list[Any], expected: dict, k: int = 1) -> float:
    """Hit@k：前 k 个结果中至少命中一个相关结果。返回 1.0 或 0.0。"""
    for hit in results[:k]:
        if is_relevant(hit, expected):
            return 1.0
    return 0.0


def precision_at_k(results: list[Any], expected: dict, k: int = 5) -> float:
    """Precision@k：前 k 个结果中相关结果的比例。"""
    if k == 0:
        return 0.0
    relevant_count = sum(1 for hit in results[:k] if is_relevant(hit, expected))
    return relevant_count / k


def ndcg_at_k(results: list[Any], expected: dict, k: int = 5) -> float:
    """NDCG@k：归一化折扣累积增益。

    使用 3 级相关性分数（relevance_score）计算 DCG，
    以理想排序（前 k 全为 1.0）计算 IDCG。

    DCG_k = Σ(r_i / log2(i+2)) for i=0..k-1
    IDCG_k = Σ(1.0 / log2(i+2)) for i=0..k-1
    """
    if k == 0:
        return 0.0

    dcg = 0.0
    for i, hit in enumerate(results[:k]):
        rel = relevance_score(hit, expected)
        dcg += rel / math.log2(i + 2)

    idcg = sum(1.0 / math.log2(i + 2) for i in range(k))
    return dcg / idcg if idcg > 0 else 0.0


def map_at_k(results: list[Any], expected: dict, k: int = 10) -> float:
    """MAP@k (Mean Average Precision)：平均精确率的均值。

    对每个相关结果位置 i，计算 Precision@i 并取平均。
    """
    relevant_count = 0
    precision_sum = 0.0
    for i, hit in enumerate(results[:k], start=1):
        if is_relevant(hit, expected):
            relevant_count += 1
            precision_sum += relevant_count / i
    total_relevant = expected.get("min_relevant_hits", 1)
    return precision_sum / max(total_relevant, 1)


# ── RRF (Reciprocal Rank Fusion) ────────────────────

def rrf_fusion(
    vector_results: list[Any],
    bm25_results: list[Any],
    k: int = 60,
    top_n: int = 10,
) -> list[dict]:
    """RRF 融合：合并向量检索和 BM25 检索的结果列表。

    RRF 公式：score(d) = Σ 1/(k + rank_i(d))

    对每个文档 d，从两个列表中取其出现的最小 rank，计算融合分数。
    返回按 RRF 分数降序排列的 top_n 结果。

    Args:
        vector_results: 向量检索结果（EvalHit 列表）。
        bm25_results: BM25 检索结果（EvalHit 列表）。
        k: RRF 平滑参数（默认 60，经典值）。
        top_n: 返回结果数。

    Returns:
        [{"id": ..., "score": RRF_score, "entity": ..., "sources": ["vector"/"bm25"]}, ...]
    """
    # 使用 id 作为文档标识
    score_map: dict[str, dict] = {}

    for rank, hit in enumerate(vector_results, start=1):
        doc_id = hit.id
        if doc_id not in score_map:
            score_map[doc_id] = {"hit": hit, "score": 0.0}
        score_map[doc_id]["score"] += 1.0 / (k + rank)
        score_map[doc_id].setdefault("sources", []).append("vector")

    for rank, hit in enumerate(bm25_results, start=1):
        doc_id = hit.id
        if doc_id not in score_map:
            score_map[doc_id] = {"hit": hit, "score": 0.0}
        score_map[doc_id]["score"] += 1.0 / (k + rank)
        score_map[doc_id].setdefault("sources", []).append("bm25")

    # 按 RRF 分数降序
    sorted_items = sorted(score_map.values(), key=lambda x: x["score"], reverse=True)
    return sorted_items[:top_n]


# ── 批量评估 ─────────────────────────────────────────

# 统一指标列表
_ALL_METRICS = [
    "recall@1", "recall@3", "recall@5", "recall@10",
    "mrr", "hit@1", "hit@3",
    "ndcg@5", "ndcg@10",
    "precision@5", "map@10",
]


def _compute_per_query(q: dict, results: list[Any]) -> dict:
    """对单个 query 计算全部指标。"""
    expected = q.get("expected", {})
    return {
        "id": q.get("id", "?"),
        "question": q.get("question", ""),
        "difficulty": q.get("difficulty", "unknown"),
        "rule_type": (expected.get("rule_types", ["unknown"]) or ["unknown"])[0],
        "recall@1": recall_at_k(results, expected, k=1),
        "recall@3": recall_at_k(results, expected, k=3),
        "recall@5": recall_at_k(results, expected, k=5),
        "recall@10": recall_at_k(results, expected, k=10),
        "mrr": mrr(results, expected),
        "hit@1": hit_at_k(results, expected, k=1),
        "hit@3": hit_at_k(results, expected, k=3),
        "ndcg@5": ndcg_at_k(results, expected, k=5),
        "ndcg@10": ndcg_at_k(results, expected, k=10),
        "precision@5": precision_at_k(results, expected, k=5),
        "map@10": map_at_k(results, expected, k=10),
        "result_count": len(results),
        # 额外诊断
        "relevant_in_top5": sum(1 for h in results[:5] if is_relevant(h, expected)),
        "relevant_in_top10": sum(1 for h in results[:10] if is_relevant(h, expected)),
    }


def _group_by(results: list[dict], key: str, metrics: list[str]) -> dict:
    """按指定 key 分组计算平均值。"""
    groups: dict[str, list[dict]] = {}
    for r in results:
        gk = r.get(key, "unknown")
        groups.setdefault(gk, []).append(r)
    out = {}
    for gk, items in groups.items():
        out[gk] = {
            "count": len(items),
            "metrics": {
                m: sum(it[m] for it in items) / len(items) if items else 0.0
                for m in metrics
            },
        }
    return out


def evaluate_all(
    queries: list[dict],
    retriever,
    top_k: int = 10,
    search_method: str = "search",
) -> dict:
    """对全部 query 计算评估指标并汇总。

    Args:
        queries: eval_queries.yaml 的 queries 数组。
        retriever: EvalRetriever 实例（支持 mode='vector'/'bm25'）。
        top_k: 每次搜索返回的结果数。
        search_method: retriever 的方法名（默认 "search"）。

    Returns:
        {
            "per_query": [...],     # 逐 query 明细
            "summary": {...},       # 汇总 + 按难度/rule_type 分组
            "retriever_mode": str,  # 检索模式
        }
    """
    search_fn = getattr(retriever, search_method, retriever.search)

    per_query = []
    for q in queries:
        results = search_fn(q["question"], top_k=top_k)
        per_query.append(_compute_per_query(q, results))

    # 全局汇总
    summary: dict[str, Any] = {
        "total_queries": len(per_query),
        "retriever_mode": getattr(retriever, "mode", "unknown"),
    }
    for m in _ALL_METRICS:
        vals = [r[m] for r in per_query]
        summary[m] = sum(vals) / len(vals) if vals else 0.0

    # 按难度分组
    summary["by_difficulty"] = _group_by(per_query, "difficulty", _ALL_METRICS)

    # 按 rule_type 分组
    summary["by_rule_type"] = _group_by(per_query, "rule_type", _ALL_METRICS)

    return {
        "per_query": per_query,
        "summary": summary,
        "retriever_mode": summary["retriever_mode"],
    }


def evaluate_hybrid(
    queries: list[dict],
    vector_retriever,
    bm25_retriever,
    top_k: int = 10,
    rrf_k: int = 60,
    fuse_top_n: int = 10,
) -> dict:
    """RRF 融合评估：向量 + BM25 → RRF 融合 → 指标。

    Args:
        queries: eval_queries.yaml 的 queries 数组。
        vector_retriever: EvalRetriever(mode="vector")。
        bm25_retriever: EvalRetriever(mode="bm25")。
        top_k: 单个检索的返回数。
        rrf_k: RRF 平滑参数（默认 60）。
        fuse_top_n: 融合后返回的结果数。

    Returns:
        与 evaluate_all 相同结构的 dict，retriever_mode="hybrid_rrf"。
    """
    per_query = []
    for q in queries:
        vec_hits = vector_retriever.search(q["question"], top_k=top_k)
        bm25_hits = bm25_retriever.search(q["question"], top_k=top_k)

        fused = rrf_fusion(vec_hits, bm25_hits, k=rrf_k, top_n=fuse_top_n)

        # 构造 EvalHit 兼容对象
        class _FusedHit:
            def __init__(self, item: dict):
                self.id = item["hit"].id
                self.score = item["score"]
                self.entity = item["hit"].entity
                self.fact_text = item["hit"].fact_text
                self._sources = item.get("sources", [])

        hits = [_FusedHit(f) for f in fused]
        per_query.append(_compute_per_query(q, hits))

    summary: dict[str, Any] = {
        "total_queries": len(per_query),
        "retriever_mode": "hybrid_rrf",
    }
    for m in _ALL_METRICS:
        vals = [r[m] for r in per_query]
        summary[m] = sum(vals) / len(vals) if vals else 0.0

    summary["by_difficulty"] = _group_by(per_query, "difficulty", _ALL_METRICS)
    summary["by_rule_type"] = _group_by(per_query, "rule_type", _ALL_METRICS)

    return {
        "per_query": per_query,
        "summary": summary,
        "retriever_mode": "hybrid_rrf",
    }
