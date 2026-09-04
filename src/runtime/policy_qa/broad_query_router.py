"""
宽泛政策问题路由层（Issue #33 路由/拒答最小实现）

把无结算单上下文的宽泛 query 在入口分流为三类落点（docs/issue33-router-dispatch.md）：
- A 具体政策可定位（险种+医疗类别+行为齐备）→ structured 精确路径
- B 宽泛但语义在本语料域内（门诊/通用）→ 路由 structured 取域内最可能意图
- C 语料外或无对应事实（时间/版本、地域、范围三判据）→ 确定性拒答
- broad 自由检索兜底第一版**默认关闭**（架构条件1）：不产出答案，只落 audit 记录

误路由兜底：结构化候选为空或最高置信 < 拒答阈 → 回落确定性拒答（诚实），
绝不回落 broad 自由检索。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from src.runtime.policy_qa.broad_policy_retriever import (
    BroadPolicyRetriever,
    InferredQueryContext,
)
from src.runtime.policy_qa.structured_policy_retriever import (
    StructuredPolicyQuery,
    StructuredPolicyEvidence,
    _DEFAULT_REGION,
)

logger = logging.getLogger(__name__)


# ── 拒答文案（确定性拒答，携带"未收录/不适用"语义）────────────────────

TIME_VERSION_REFUSAL_MESSAGE = (
    "本市现行政策未收录该年度或版本的政策（现行有效政策均为已发布版本），无法回答该问题。"
)
REGION_REFUSAL_MESSAGE = "该问题涉及异地或其他统筹区政策，本市现行政策不适用。"
SCOPE_REFUSAL_MESSAGE = "该问题涉及的住院范围暂未收录，当前仅覆盖门诊及通用政策。"
STRUCTURED_MISS_REFUSAL_MESSAGE = (
    "现有政策知识库中未检索到足以回答该问题的政策依据，建议咨询医保办或查阅最新政策文件。"
)
EMPTY_QUESTION_REFUSAL_MESSAGE = "当前信息不足，无法可靠回答该问题。"

# 路由拒答阈：结构化候选最高置信低于该值即回落确定性拒答（宁可多拒、不让 broad 误导）
ROUTING_MIN_CONFIDENCE = 0.5


# ── 三判据守卫（白名单规则表，逐项可用 "off"/"闭" 关闭）────────────────

# 时间/版本判据：语料现全 published+expiry=9999，不存在其他"时间档实体"，
# 问"已废止/当年旧规/草案/未来年度/新规"直接拒（不做 date 事后判，与加固②互补）
_TIME_VERSION_KEYWORDS: dict[str, bool] = {
    "已废止": True,
    "废止": True,
    "不再执行": True,
    "草案": True,
    "征求意见稿": True,
    "新规": True,
    "新政策": True,
    "即将实施": True,
    "未来": True,
    "明年": True,
    "后年": True,
    "去年": True,
    "往年": True,
    "旧规": True,
    "旧政策": True,
    "老政策": True,
}
# 边界守卫词："今年/现行"等时间锚在当年时不拒
_TIME_GUARD_KEYWORDS = ("今年", "本年度", "现行", "目前", "当前")

# 地域判据：明确非本统筹区 → 拒；"异地+比例/待遇" → 拒；"异地+备案/流程"可答不拒
_OTHER_REGION_KEYWORDS: dict[str, bool] = {
    "上海": True, "沪": True, "广州": True, "穗": True, "深圳": True,
    "天津": True, "津": True, "杭州": True, "南京": True, "苏州": True,
    "成都": True, "重庆": True, "武汉": True, "西安": True,
}
_REMOTE_BENEFIT_KEYWORDS = ("比例", "待遇", "报多少", "报销多少", "支付标准")
_REMOTE_PROCESS_KEYWORDS = ("备案", "流程", "手续", "怎么办", "怎么办理", "如何办理", "转诊")

# 范围判据：住院术语在 #33（门诊+通用）范围纪律之外 → 拒，不落 broad
_SCOPE_INPATIENT_KEYWORDS: dict[str, bool] = {"住院": True}

# 门诊域内信号（B 判的准入）：无门诊/门特信号的问题不猜、走 broad-kept-closed
_OUTPATIENT_SIGNAL_KEYWORDS = ("门诊", "门急诊", "门特", "急诊留观", "购药", "药店")

# 动作 → 规则类型映射（按优先级，先长后短避免"最高限额"被"比例"抢走）
_ACTION_RULE_TYPE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("起付线", ("起付线", "起付标准")),
    ("封顶线", ("最高限额", "最高支付", "封顶线", "限额", "上限")),
    ("支付比例", ("报销比例", "支付比例", "比例", "报多少", "报销多少")),
]

_YEAR_PATTERN = re.compile(r"(19|20)\d{2}")


def _enabled(table: dict[str, bool], keyword: str) -> bool:
    """白名单开关：值为 "off"/"闭"（或 False）即关闭该关键词判据。"""
    return table.get(keyword) is True


def check_time_version_criterion(question: str | None, current_year: int | None = None) -> str | None:
    """时间/版本判据：显式非当年年份或版本类词汇命中 → 拒（返回 reason code）。"""
    q = (question or "").strip()
    if not q:
        return None
    year = current_year if current_year is not None else date.today().year

    # 显式年份：与当年不符即拒（"2026年的政策"可答，"2025年"拒）
    for match in _YEAR_PATTERN.finditer(q):
        if int(match.group(0)) != year:
            return "time_version"

    # 相对/版本词汇："去年"拒、"今年"不拒（阈值边缘在此裁决）
    for keyword in _TIME_VERSION_KEYWORDS:
        if not _enabled(_TIME_VERSION_KEYWORDS, keyword):
            continue
        if keyword in q:
            # 守卫词仅豁免非强版本词（已废止/草案不因"现行"而豁免）
            if keyword not in ("已废止", "废止", "草案", "征求意见稿", "新规", "新政策"):
                if any(guard in q for guard in _TIME_GUARD_KEYWORDS):
                    continue
            return "time_version"
    return None


def check_region_criterion(question: str | None) -> str | None:
    """地域判据：明确非本统筹区拒；异地仅"比例/待遇"类拒，"备案流程"类可答。"""
    q = (question or "").strip()
    if not q:
        return None

    for keyword in _OTHER_REGION_KEYWORDS:
        if _enabled(_OTHER_REGION_KEYWORDS, keyword) and keyword in q:
            return "region_out_of_scope"

    if "异地" in q or "跨省" in q:
        # 备案/流程类问题语料可答，不属于拒答对象
        if any(token in q for token in _REMOTE_PROCESS_KEYWORDS) and not any(
            token in q for token in _REMOTE_BENEFIT_KEYWORDS
        ):
            return None
        if any(token in q for token in _REMOTE_BENEFIT_KEYWORDS):
            return "region_out_of_scope"
    return None


def check_scope_criterion(question: str | None) -> str | None:
    """范围判据：住院术语在 #33（门诊+通用）范围纪律之外 → 拒。"""
    q = (question or "").strip()
    if not q:
        return None
    for keyword in _SCOPE_INPATIENT_KEYWORDS:
        if _enabled(_SCOPE_INPATIENT_KEYWORDS, keyword) and keyword in q:
            return "scope_inpatient"
    return None


# ── 路由决策 ────────────────────────────────────────────────────────

@dataclass
class BroadRouteDecision:
    """宽泛问题路由决策。

    landing: A（具体可定位）/ B（域内宽泛）/ C（确定性拒答）/ broad-kept-closed（兜底关闭）
    route: structured / refuse / broad_kept_closed
    """

    landing: str
    route: str
    refusal_reason: str = ""
    refusal_message: str = ""
    structured_queries: list[StructuredPolicyQuery] = field(default_factory=list)
    evidence: list[StructuredPolicyEvidence] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


def _infer_action_rule_type(question: str) -> str:
    """从问题推断规则类型（支付比例/起付线/封顶线）。"""
    for rule_type, keywords in _ACTION_RULE_TYPE_KEYWORDS:
        if any(kw in question for kw in keywords):
            return rule_type
    return ""


def build_structured_queries(
    inferred: InferredQueryContext,
    action_rule_type: str,
    question: str = "",
) -> list[StructuredPolicyQuery]:
    """按路由推断维度构建结构化查询（B 缺险种时不过滤 = 职工/居民 all）。

    发布状态/有效期与 structured 共用同一语义（published + 默认结算日哨兵不裁日期）。
    search_text 挂原问题：激活 execute_query 内置 BM25 重排，避免候选退化为 Milvus 插入序。
    """
    filters: dict[str, str] = {
        "region": _DEFAULT_REGION,
        "publish_status": "published",
        "is_remote": "false",
    }
    if inferred.insu_type:
        filters["insu_type"] = inferred.insu_type
    if inferred.med_type:
        filters["med_type"] = inferred.med_type
    # B 无明确动作时取域内最可能意图：支付比例
    filters["rule_type"] = action_rule_type or "支付比例"

    query_name = "router_outpatient_" + filters["rule_type"]
    return [
        StructuredPolicyQuery(
            query_name=query_name,
            required=True,
            filters=filters,
            psn_type_allow_all=True,
            search_text=question,
        )
    ]


# 证据消费上限：答案生成只消费 top N，超出部分只会稀释相关性
_EVIDENCE_TOP_N = 5
# 相关性过滤带：保留综合相对分 >= 该比例的证据（低于带宽的视为噪声）
_RELEVANCE_BAND = 0.25
# 语义地板：问题与候选文本的向量最高余弦低于该值 → 候选池整体不相关，
# 按"宁可多拒"原则诚实拒答（标量过滤无法区分的跨主题词面巧合在此拦截）
_EVIDENCE_MIN_COSINE = 0.62


def _cosine_similarities(question: str, texts: list[str]) -> list[float] | None:
    """问题与候选文本的向量余弦相似度；embedding 不可用返回 None（降级 BM25-only）。"""
    try:
        import numpy as np

        from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
            get_embedding_provider,
        )

        provider = get_embedding_provider("sentence_transformer")
        query_vector = np.asarray(provider.encode([question or ""])[0], dtype=float)
        text_vectors = np.asarray(provider.encode(list(texts)), dtype=float)
        query_norm = float(np.linalg.norm(query_vector))
        text_norms = np.linalg.norm(text_vectors, axis=1)
        if query_norm == 0.0 or bool((text_norms == 0.0).all()):
            return None
        return [
            float(score)
            for score in (text_vectors @ query_vector) / (text_norms * query_norm + 1e-9)
        ]
    except Exception as exc:  # embedding 模型缺失/加载失败 → 降级，不阻塞路由
        logger.warning("[QUERY-ROUTER] embedding 不可用，证据排序降级为 BM25-only: %s", exc)
        return None


def _evidence_score_text(evidence: StructuredPolicyEvidence) -> str:
    """参与相关性打分的富文本：source_text + 适用维度字段。

    短文本规则（如"统筹基金支付85%"）词面信息少，把险种/医疗类别/医院等级/人群
    等维度并入打分文本，"三级医院"这类问题词才能命中对应规则。
    """
    return " ".join(
        str(part or "")
        for part in (
            getattr(evidence, "source_text", ""),
            getattr(evidence, "insu_type", ""),
            getattr(evidence, "med_type", ""),
            getattr(evidence, "hosp_lv", ""),
            getattr(evidence, "psn_type", ""),
            getattr(evidence, "rule_value", ""),
            getattr(evidence, "payment_ratio", ""),
        )
    )


def _rerank_evidence_by_relevance(
    question: str,
    evidence: list[StructuredPolicyEvidence],
) -> tuple[list[StructuredPolicyEvidence], float | None]:
    """按问题相关性对证据重排/过滤/截断（BM25 维度富文本 + 向量语义融合）。

    Returns:
        (保留证据, 语义地板裁决)：语义地板未通过时返回 ([], best_cosine)，
        调用方应回落确定性拒答；embedding 不可用时地板裁决为 None（BM25-only）。
    """
    if not evidence:
        return [], None
    from src.runtime.policy_qa.structured_policy_retriever import _bm25_scores

    bm25 = _bm25_scores(question or "", [_evidence_score_text(ev) for ev in evidence])
    # 向量只对非空文本打分（无文本证据不参与语义裁决）
    cosine_indexed: dict[int, float] = {}
    scored = [
        (idx, str(getattr(ev, "source_text", "") or "").strip())
        for idx, ev in enumerate(evidence)
    ]
    non_empty = [(idx, text) for idx, text in scored if text]
    cosine = (
        _cosine_similarities(question or "", [text for _, text in non_empty])
        if non_empty
        else None
    )

    cosine_norm: list[float] | None = None
    if cosine is not None:
        best_cosine = max(cosine)
        if best_cosine < _EVIDENCE_MIN_COSINE:
            # 候选池整体语义不相关（如问备案而池里只有报销比例）→ 诚实拒答
            return [], best_cosine
        cosine_norm = [0.0] * len(evidence)
        for (idx, _text), score in zip(non_empty, cosine):
            cosine_norm[idx] = score / best_cosine

    bm25_best = max(bm25, default=0.0)
    bm25_norm = [score / bm25_best if bm25_best > 0 else 0.0 for score in bm25]

    if cosine_norm is not None:
        # 几何平均融合：BM25 与向量任一维度归零即归零（词面/语义双重把关），
        # 划入类噪声（BM25 近零）与跨主题词面巧合（向量近零）都被过滤
        combined = [
            math.sqrt(bm * cs) if bm > 0 and cs > 0 else 0.0
            for bm, cs in zip(bm25_norm, cosine_norm)
        ]
    else:
        combined = bm25_norm

    best_combined = max(combined, default=0.0)
    if best_combined <= 0.0:
        # 零词面信号（embedding 不可用时）：不做相关性裁决，保持检索原序
        return list(evidence[:_EVIDENCE_TOP_N]), None

    ranked = sorted(zip(combined, evidence), key=lambda pair: pair[0], reverse=True)
    return [ev for rel, ev in ranked if rel >= best_combined * _RELEVANCE_BAND][:_EVIDENCE_TOP_N], None


def _default_audit_sink(record: dict[str, Any]) -> None:
    """默认 audit 出口：结构化日志（第一版不落库，后续可替换为持久化 sink）。"""
    import json

    logger.info("[QUERY-ROUTER] %s", json.dumps(record, ensure_ascii=False))


def route_broad_question(
    question: str | None,
    *,
    structured_retrieve: Callable[[BroadRouteDecision], Any] | None = None,
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
    current_year: int | None = None,
) -> BroadRouteDecision:
    """宽泛问题入口路由：C 判拦截 → A/B 路由 structured → broad 兜底默认关闭。

    Args:
        question: 用户原始问题（无结算单上下文的宽泛政策问题）。
        structured_retrieve: 结构化检索注入点（接收决策、返回带 selected_evidence 的结果）；
            None 时只做路由判定不检索（单元测试/预检可用）。
        audit_sink: 路由落点记录出口；None 时走默认日志 sink。
        current_year: 时间判据的当年锚（测试可固定）。

    Returns:
        BroadRouteDecision：landing/route/拒答文案/结构化查询计划/证据/audit 记录。
    """
    sink = audit_sink or _default_audit_sink
    q = (question or "").strip()

    def _decision(landing: str, route: str, reason: str = "", message: str = "") -> BroadRouteDecision:
        decision = BroadRouteDecision(
            landing=landing,
            route=route,
            refusal_reason=reason,
            refusal_message=message,
        )
        decision.audit = {
            "question": q,
            "landing": landing,
            "route": route,
            "refusal_reason": reason,
            "evidence_count": 0,
        }
        sink(decision.audit)
        return decision

    # 空输入：确定性拒答（校验层之外的防御）
    if not q:
        return _decision("C", "refuse", "empty_question", EMPTY_QUESTION_REFUSAL_MESSAGE)

    # 1. C 判：时间/版本 → 地域 → 范围（在检索之前拦截，不触碰数据源）
    criterion_reason = (
        check_time_version_criterion(q, current_year=current_year)
        or check_region_criterion(q)
        or check_scope_criterion(q)
    )
    if criterion_reason == "time_version":
        return _decision("C", "refuse", criterion_reason, TIME_VERSION_REFUSAL_MESSAGE)
    if criterion_reason == "region_out_of_scope":
        return _decision("C", "refuse", criterion_reason, REGION_REFUSAL_MESSAGE)
    if criterion_reason == "scope_inpatient":
        return _decision("C", "refuse", criterion_reason, SCOPE_REFUSAL_MESSAGE)

    # 2. A/B 判别：语义是否落在本语料域（门诊/通用）
    inferred = BroadPolicyRetriever._infer_context_from_question(q)
    # 补充简称推断：broad 推断只认"职工医保/城镇职工"，路由补认"职工/居民"裸词
    if not inferred.insu_type:
        if "职工" in q:
            inferred.insu_type = "城镇职工基本医疗保险"
        elif "居民" in q:
            inferred.insu_type = "城乡居民基本医疗保险"
    action_rule_type = _infer_action_rule_type(q)
    in_domain = any(signal in q for signal in _OUTPATIENT_SIGNAL_KEYWORDS) or (
        ("异地" in q or "跨省" in q) and any(k in q for k in _REMOTE_PROCESS_KEYWORDS)
    )
    if not in_domain:
        # 条件1：罕见 broad 兜底默认关闭——不产出答案，只落 audit 记录
        return _decision(
            "broad-kept-closed",
            "broad_kept_closed",
            "broad_fallback_closed",
            STRUCTURED_MISS_REFUSAL_MESSAGE,
        )

    action_rule_type = _infer_action_rule_type(q)
    landing = "A" if (inferred.insu_type and inferred.med_type and action_rule_type) else "B"

    decision = BroadRouteDecision(
        landing=landing,
        route="structured",
        structured_queries=build_structured_queries(inferred, action_rule_type, q),
    )

    # 3. 结构化检索与误路由兜底（候选空/低置信 → 确定性拒答，绝不回落 broad）
    if structured_retrieve is not None:
        retrieval_result = structured_retrieve(decision)
        raw_evidence = list(getattr(retrieval_result, "selected_evidence", []) or [])
        best_confidence = max((float(getattr(e, "score", 0.0) or 0.0) for e in raw_evidence), default=0.0)
        if not raw_evidence or best_confidence < ROUTING_MIN_CONFIDENCE:
            decision.route = "refuse"
            decision.refusal_reason = "structured_miss"
            decision.refusal_message = STRUCTURED_MISS_REFUSAL_MESSAGE
        else:
            # 相关性重排后再消费：缴费/划入类噪声不进答案；候选池整体不相关则诚实拒答
            reranked, low_cosine = _rerank_evidence_by_relevance(q, raw_evidence)
            if low_cosine is not None:
                decision.route = "refuse"
                decision.refusal_reason = "low_relevance"
                decision.refusal_message = STRUCTURED_MISS_REFUSAL_MESSAGE
            else:
                decision.evidence = reranked

    decision.audit = {
        "question": q,
        "landing": decision.landing,
        "route": decision.route,
        "refusal_reason": decision.refusal_reason,
        "evidence_count": len(decision.evidence),
    }
    sink(decision.audit)
    return decision
