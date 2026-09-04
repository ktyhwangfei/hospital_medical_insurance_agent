"""
结构化政策规则检索器（StructuredPolicyRuleRetriever）

优先使用 Milvus scalar query（字段精准过滤）查询 policy_rules。
结构化候选不相关时，使用稠密向量召回并在本地做 BM25 重排；混合检索
不能绕过险种、医疗类别等严格适用条件。

设计原则：
1. 基于真实结算上下文生成标准化查询条件
2. 针对"统筹自付"拆成两组必需规则查询：
   a. 三级医院职工住院分段支付比例（psn_type 不限制为退休人员）
   b. 退休人员个人支付比例60%折算公式（psn_type=退休人员, rule_type=计算公式）
3. 使用 rule_instance_key（非 rule_id）去重，避免分段规则被覆盖
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

import grpc
from pymilvus import MilvusClient
from pymilvus.exceptions import (
    ConnectError,
    ConnectionNotExistException,
    ErrorCode,
    MilvusException,
    MilvusUnavailableException,
)

from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    normalize_hosp_lv,
)
from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
    get_embedding_provider,
)
from src.runtime.policy_qa.policy_rules_search import (
    COLLECTION_NAME,
    OUTPUT_FIELDS,
    unpack_detail,
)
from src.runtime.policy_qa.policy_validity import build_validity_date_expr

logger = logging.getLogger(__name__)

_TRANSIENT_MILVUS_ERROR_TYPES = (
    ConnectionError,
    TimeoutError,
    ConnectError,
    ConnectionNotExistException,
    MilvusUnavailableException,
)
_TRANSIENT_GRPC_CODES = {
    grpc.StatusCode.ABORTED,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.UNKNOWN,
}


def _is_transient_milvus_error(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_MILVUS_ERROR_TYPES):
        return True
    if isinstance(exc, grpc.RpcError):
        return exc.code() in _TRANSIENT_GRPC_CODES
    if isinstance(exc, MilvusException):
        return (
            exc.code in _TRANSIENT_GRPC_CODES
            or exc.code == ErrorCode.RATE_LIMIT
            or "Retry run out" in exc.message
            or "Retry timeout" in exc.message
        )
    return False


class PolicyRetrievalUnavailableError(Exception):
    """政策数据源瞬时不可用，可由有界 Loop 重试。"""

    pass


def _searchable_text(rule: dict[str, Any]) -> str:
    return " ".join(
        str(rule.get(field, "") or "")
        for field in ("source_text", "rule_value")
    )


def _bm25_tokens(text: str) -> list[str]:
    """无需额外分词依赖的中英文 BM25 词元。"""
    tokens: list[str] = []
    for chunk in re.findall(r"[a-z0-9_.%+-]+|[\u4e00-\u9fff]+", text.lower()):
        if not re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            tokens.append(chunk)
            continue
        if len(chunk) == 1:
            tokens.append(chunk)
            continue
        for size in range(2, min(4, len(chunk)) + 1):
            tokens.extend(chunk[index:index + size] for index in range(len(chunk) - size + 1))
    return tokens


def _bm25_scores(query_text: str, documents: list[str]) -> list[float]:
    query_tokens = set(_bm25_tokens(query_text))
    document_tokens = [_bm25_tokens(item) for item in documents]
    if not query_tokens or not document_tokens:
        return [0.0] * len(documents)
    average_length = sum(map(len, document_tokens)) / len(document_tokens) or 1.0
    document_frequency = {
        token: sum(token in document for document in document_tokens)
        for token in query_tokens
    }
    scores: list[float] = []
    for document in document_tokens:
        score = 0.0
        for token in query_tokens:
            frequency = document.count(token)
            if not frequency:
                continue
            inverse_frequency = math.log(
                1 + (len(document_tokens) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            score += inverse_frequency * frequency * 2.5 / (
                frequency + 1.5 * (0.25 + 0.75 * len(document) / average_length)
            )
        scores.append(score)
    maximum = max(scores, default=0.0)
    return [score / maximum if maximum else 0.0 for score in scores]


def resolve_rules_collection(
    host: str = "127.0.0.1", port: str = "19530"
) -> str:
    """委托统一 release resolver（Issue #33 P0-1）；保留本函数名兼容既有调用方。"""
    from src.knowledge_extension.rule_explanation.release_resolver import (
        resolve_rules_collection as _resolve,
    )

    return _resolve(host, port)


# ── 标准化结算上下文 ──────────────────────────────────────────────

# Issue #25 新增适用性字段默认值
_DEFAULT_REGION = "北京"
_DEFAULT_SETTLEMENT_DATE = "9999-12-31"

# Issue #33：dynamic field 开启时可过滤的已知动态键（适用性字段 + 金额段数值，
# 见 policy_rules_schema_v2.CORE_DIM_FIELDS 中未进固定 schema 的 Issue #25 字段）
_KNOWN_DYNAMIC_FILTERABLE_FIELDS = frozenset({
    "region", "effective_date", "expiry_date", "publish_status",
    "policy_version", "is_remote", "amount_band_min", "amount_band_max",
})


@dataclass
class NormalizedPolicyContext:
    """从真实结算数据标准化后的政策查询上下文。"""
    settlement_id: str = ""
    insu_type: str = ""       # 险种: "城镇职工基本医疗保险"
    med_type: str = ""        # 医疗类别: "住院-普通住院"
    hosp_lv: str = ""         # 医院等级: "三级医院"
    psn_type: str = ""        # 人员类别: "退休人员"
    region: str = _DEFAULT_REGION  # 适用地区（Issue #25）
    settlement_date: str = _DEFAULT_SETTLEMENT_DATE  # 结算日期 YYYY-MM-DD（Issue #25）
    is_remote: bool = False   # 是否异地就医（Issue #25）
    target_field: str = ""    # 目标字段: "统筹自付"
    target_amount: float = 0.0  # 目标金额


# ── 结构化查询定义 ────────────────────────────────────────────────

@dataclass
class StructuredPolicyQuery:
    """一组结构化查询定义。"""
    query_name: str                           # 查询名称
    required: bool = True                     # 是否必须查到
    filters: dict[str, str] = field(default_factory=dict)  # 字段相等过滤
    text_must_include_any: list[str] = field(default_factory=list)  # source_text 至少包含一个
    text_must_include_all: list[str] = field(default_factory=list)  # source_text 全部包含
    psn_type_allow_all: bool = False          # 是否允许 psn_type 宽松匹配（不限定为指定值）
    settlement_date: str = _DEFAULT_SETTLEMENT_DATE  # 结算日期 YYYY-MM-DD（Issue #25 时间过滤）
    amount_range: tuple[int, int] | None = None  # 金额段范围 (min, max)（Issue #25 阶段 2）
    search_text: str = ""                    # 结构化不足时的向量/BM25 查询文本
    exact_match_fields: list[str] = field(default_factory=list)  # 不允许空维度兜底
    top_k: int = 20                          # 候选池上限（路由层放大喂下游重排）


# ── 结构化检索结果 ────────────────────────────────────────────────

@dataclass
class StructuredPolicyEvidence:
    """单条政策证据。"""
    evidence_id: str = ""
    source: str = "structured_policy_rule"
    query_name: str = ""
    policy_id: str = ""
    clause_id: str = ""
    rule_type: str = ""
    insu_type: str = ""
    med_type: str = ""
    hosp_lv: str = ""
    psn_type: str = ""
    region: str = _DEFAULT_REGION  # 适用地区（Issue #25）
    effective_date: str = ""      # 生效日期（Issue #25）
    expiry_date: str = ""         # 失效日期（Issue #25）
    publish_status: str = ""      # 发布状态（Issue #25）
    policy_version: str = ""      # 政策版本（Issue #25）
    is_remote: bool = False       # 是否异地规则（Issue #25）
    source_text: str = ""
    rule_value: str = ""
    payment_ratio: str = ""
    amount_band: str = ""
    rule_id: str = ""
    rule_instance_key: str = ""
    applied_reason: str = ""
    score: float = 1.0  # 结构化匹配默认满分


@dataclass
class StructuredRetrievalResult:
    """完整的结构化检索结果。"""
    settlement_context: dict[str, Any] = field(default_factory=dict)
    normalized_context: dict[str, Any] = field(default_factory=dict)
    planned_queries: list[dict[str, Any]] = field(default_factory=list)
    query_results: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    selected_evidence: list[StructuredPolicyEvidence] = field(default_factory=list)
    missing_required_rules: list[str] = field(default_factory=list)
    dedupe_info: dict[str, Any] = field(default_factory=dict)
    # Issue #33 加固：拒答原因与面向用户的拒答文案（空串表示正常完成）。
    # 下游零证据应走既有诚实拒答通道（answer_status=unavailable），不得编造兜底答案。
    refusal_reason: str = ""
    refusal_message: str = ""


# Issue #33 加固①空 ctx 拒答：拒答码与面向用户文案
EMPTY_CONTEXT_REFUSAL_REASON = "empty_context"
EMPTY_CONTEXT_REFUSAL_MESSAGE = (
    "缺少可依据的政策上下文（无险种/医疗类别/人群/医院等级/结算单号），无法回答该问题。"
)


def _is_empty_policy_context(ctx: NormalizedPolicyContext) -> bool:
    """Issue #33 加固：上下文是否没有任何区分性维度。

    险种/医疗类别/人群/医院等级/结算单号全部为空时，所有维度过滤退化为
    "空值保留"，泛化规则会被当作确定答案召回（真实语料基线实测 6 条 BROAD_*
    负例全部误召同 3 条门诊支付比例规则）——此时必须拒答而非放行。
    """
    return not any([
        str(ctx.insu_type or "").strip(),
        str(ctx.med_type or "").strip(),
        str(ctx.psn_type or "").strip(),
        str(ctx.hosp_lv or "").strip(),
        str(ctx.settlement_id or "").strip(),
    ])


# ── 结构化检索器 ──────────────────────────────────────────────────

class StructuredPolicyRuleRetriever:
    """
    结构化政策规则检索器。

    使用 Milvus scalar query（非向量 search）精准查询 policy_rules_v2。
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: str = "19530",
        collection_name: str | None = None,
        enable_applicability_fields: bool = True,
    ):
        uri = f"http://{host}:{port}"
        try:
            self.client = MilvusClient(uri=uri)
        except Exception as e:
            if not _is_transient_milvus_error(e):
                raise
            raise PolicyRetrievalUnavailableError(str(e)) from e
        self.collection_name = collection_name or COLLECTION_NAME
        # Issue #25：缓存 collection 的固定 schema 字段名，用于旧 collection 兼容
        self._collection_fields: set[str] | None = None
        # Issue #25 评估：是否启用新增适用性字段（region/validity/publish_status/policy_version/is_remote）
        self._enable_applicability_fields = enable_applicability_fields
        logger.info(
            f"StructuredPolicyRuleRetriever initialized: {uri} "
            f"(applicability_fields={enable_applicability_fields})"
        )

    def _get_collection_fields(self) -> set[str]:
        """获取当前 collection 的字段名集合（含固定 schema + dynamic field 键）。

        用于 Issue #25 新增字段的向后兼容：若旧 collection 缺少某字段，
        则跳过该字段的 Milvus expr 过滤，避免查询报错。

        注：单元测试可能直接构造实例而不调用 __init__，使用 getattr 防御。
        """
        cached = getattr(self, "_collection_fields", None)
        if cached is not None:
            return cached
        try:
            desc = self.client.describe_collection(collection_name=self.collection_name)
        except Exception as e:
            logger.warning(f"[StructuredRetrieval] describe_collection failed: {e}")
            self._collection_fields: set[str] = set()
            return self._collection_fields
        fields: set[str] = set()
        for f in desc.get("fields", []):
            fields.add(str(f.get("name", "")))
        # Issue #33：dynamic field 开启的 collection（含 release 产物）中，适用性/金额段
        # 字段以 dynamic key 存储、不出现在 describe 固定字段里，但可正常过滤
        # （缺失该 key 的实体不匹配而非报错）。显式并入已知可过滤动态键。
        if desc.get("enable_dynamic_field"):
            fields |= _KNOWN_DYNAMIC_FILTERABLE_FIELDS
        self._collection_fields = fields
        logger.info(f"[StructuredRetrieval] collection fields: {sorted(fields)}")
        return self._collection_fields

    # ── 查询规划 ─────────────────────────────────────────────────

    def plan_queries(self, ctx: NormalizedPolicyContext,
                     target_field: str = "统筹自付") -> list[StructuredPolicyQuery]:
        """
        根据结算上下文生成结构化查询计划。

        "统筹自付"需要两组必需规则：
        1. 三级医院职工住院分段支付比例
        2. 退休人员个人支付比例60%折算公式

        Issue #25：所有查询默认注入 region / publish_status / is_remote 适用性过滤。
        """
        # Issue #33 加固：空上下文（无险种/医疗类别/人群/医院等级/结算单号）拒绝规划，
        # 防止泛化规则被当作确定答案召回
        if _is_empty_policy_context(ctx):
            logger.warning(
                "[StructuredRetrieval] 空上下文拒答：无险种/医疗类别/人群/医院等级/结算单号，"
                "拒绝规划查询"
            )
            return []

        queries: list[StructuredPolicyQuery] = []

        # Issue #25 全局适用性过滤（会注入到每个查询中）
        base_filters: dict[str, str] = {}
        if getattr(self, "_enable_applicability_fields", True):
            base_filters["region"] = ctx.region or _DEFAULT_REGION
            base_filters["publish_status"] = "published"
            if ctx.is_remote:
                base_filters["is_remote"] = "true"
            else:
                # 本地结算：同时匹配本地规则（is_remote=false）和未标记规则（兼容旧数据）
                base_filters["is_remote"] = "false"

        if target_field in ("统筹自付", "pooling_self_pay"):
            # 查询1: 分段支付比例（Issue #33：按医疗类别分化）
            # ★ psn_type 不限定为退休人员，基础分段比例对全部人群通用
            # ★ hosp_lv 必须包含，否则会混入其他等级医院的规则
            query1_filters = {
                **base_filters,
                "insu_type": ctx.insu_type,
                "med_type": ctx.med_type,
                "rule_type": "支付比例",
            }
            if ctx.hosp_lv:
                query1_filters["hosp_lv"] = ctx.hosp_lv

            if ctx.med_type.startswith("门诊"):
                # 门诊：分段文本不在 source_text 而在 amount_band 字段（实测），
                # 分段选择交给金额段数值过滤（P0-2 已回填），不再用住院特化关键词
                query1 = StructuredPolicyQuery(
                    query_name="employee_outpatient_segment_ratio",
                    required=True,
                    filters=query1_filters,
                    psn_type_allow_all=True,
                )
            else:
                query1 = StructuredPolicyQuery(
                    query_name="employee_inpatient_tertiary_segment_ratio",
                    required=True,
                    filters=query1_filters,
                    psn_type_allow_all=True,
                    text_must_include_any=[
                        "起付标准至3万元",
                        "超过3万元至4万元",
                        "超过4万元",
                    ],
                )
            # Issue #25 阶段 2：金额段范围过滤
            if ctx.target_amount > 0:
                query1.amount_range = (int(ctx.target_amount), int(ctx.target_amount))
            queries.append(query1)

            # 查询2: 退休人员个人支付比例（折算物化后的绝对值规则 + 折算公式规则）
            # ★ U3：去掉硬编码 rule_type=计算公式（提取端不产出该类型），改 rule_type=支付比例；
            # ★ 命中 U3 折算展开的退休 personal_payment_ratio 规则（source_text 含「个人支付比例/60%」）
            query2_filters = {
                **base_filters,
                "insu_type": ctx.insu_type,
                "med_type": ctx.med_type,
                "psn_type": ctx.psn_type,
                "rule_type": "支付比例",
            }

            queries.append(StructuredPolicyQuery(
                query_name="retiree_personal_ratio",
                required=True,
                filters=query2_filters,
                # Issue #33：去掉万金油关键词 "60%"（实测误召回大量无关分段规则，
                # 是负例 FAR 的全部来源）；"个人支付"同时覆盖折算公式规则
                # （"个人支付比例为职工…60%"）与门诊分段规则（"个人支付15%。"）
                text_must_include_any=[
                    "个人支付",
                ],
            ))

        return queries

    # ── 结构化检索执行 ────────────────────────────────────────────

    def execute_query(self, query: StructuredPolicyQuery,
                      top_k: int = 20) -> list[dict[str, Any]]:
        """
        执行单一结构化查询。

        优先使用 Milvus scalar query（字段过滤 + source_text LIKE），
        不依赖向量相似度。

        Issue #25：新增 region / effective_date / expiry_date / publish_status /
        policy_version / is_remote 过滤；对旧 collection 缺少的字段做兼容跳过。
        """
        results: list[dict[str, Any]] = []

        # Issue #25：检测当前 collection 实际存在的字段（旧 collection 兼容）
        available_fields = self._get_collection_fields()

        # 构建 Milvus expr 过滤条件
        expr_parts: list[str] = []
        skipped_fields: list[str] = []

        # 字段相等/模糊过滤
        for field, value in query.filters.items():
            # Issue #25：字段不存在时跳过，避免旧 collection 查询报错
            if available_fields and field not in available_fields:
                skipped_fields.append(field)
                continue

            if field == "is_remote":
                # is_remote 是 BOOL 类型
                bool_val = str(value).lower() in ("true", "1", "yes", "是")
                expr_parts.append(f'is_remote == {str(bool_val).lower()}')
                continue

            safe_value = str(value).replace("\\", "\\\\").replace('"', '\\"')
            exact = field in query.exact_match_fields
            if value and field != "psn_type":
                # ★ insu_type 使用 LIKE 匹配，因为上下文可能返回简称
                if field == "insu_type":
                    match = f'{field} like "%{safe_value}%"'
                    expr_parts.append(match if exact else f'({match} or {field} == "")')
                elif field == "rule_type":
                    expr_parts.append(f'{field} == "{safe_value}"')
                else:
                    match = f'{field} == "{safe_value}"'
                    expr_parts.append(match if exact else f'({match} or {field} == "")')
            elif value and field == "psn_type":
                # psn_type 允许宽松匹配
                if exact:
                    expr_parts.append(f'psn_type == "{safe_value}"')
                elif not query.psn_type_allow_all:
                    expr_parts.append(f'(psn_type == "{safe_value}" or psn_type == "")')

        # Issue #25：时间范围过滤（ settlement_date 在 [effective_date, expiry_date] 内）
        # Issue #33 加固②：与 broad 共用 policy_validity helper，两读路径同一有效期语义
        settlement_date = query.settlement_date
        if (
            getattr(self, "_enable_applicability_fields", True)
            and settlement_date
            and settlement_date != _DEFAULT_SETTLEMENT_DATE
        ):
            expr_parts.extend(build_validity_date_expr(settlement_date, available_fields))

        # Issue #25 阶段 2：金额段范围过滤
        # Issue #33：(0,0) 视为"无法解析"，不参与范围过滤、保留召回（不漏规则优先）
        if (
            query.amount_range
            and "amount_band_min" in available_fields
            and "amount_band_max" in available_fields
        ):
            amount = query.amount_range[0]
            expr_parts.append(
                f'((amount_band_min == 0 and amount_band_max == 0) or '
                f'(amount_band_min <= {amount} and '
                f'(amount_band_max >= {amount} or amount_band_max == -1)))'
            )

        if skipped_fields:
            logger.warning(
                f"[StructuredRetrieval] Query '{query.query_name}' skipped fields not in collection: "
                f"{skipped_fields}"
            )

        # ★ 如果没有其他过滤条件，加一个保底条件
        if not expr_parts:
            expr_parts.append('rule_id != ""')

        expr = " and ".join(expr_parts)

        # ── 详细日志：打印完整的 Milvus 查询 ──
        print(f"\n[MILVUS-QUERY] ====== 结构化政策查询 ======", flush=True)
        print(f"[MILVUS-QUERY] Query: {query.query_name}", flush=True)
        print(f"[MILVUS-QUERY] Collection: {self.collection_name}", flush=True)
        print(f"[MILVUS-QUERY] Filters: {json.dumps(query.filters, ensure_ascii=False)}", flush=True)
        print(f"[MILVUS-QUERY] Expr: {expr}", flush=True)
        print(f"[MILVUS-QUERY] Text must include ANY: {query.text_must_include_any}", flush=True)
        print(f"[MILVUS-QUERY] Text must include ALL: {query.text_must_include_all}", flush=True)
        print(f"[MILVUS-QUERY] Output fields: {OUTPUT_FIELDS}", flush=True)
        print(f"[MILVUS-QUERY] Top K: {top_k}", flush=True)

        try:
            # 优先：纯标量查询（不依赖向量）
            # Issue #33：带关键词过滤时先取足候选再过滤——此前 limit=top_k 在关键词
            # 过滤之前截断，候选超过 top_k 时期望规则会被截掉（基线实测第 22 位被截）
            candidate_limit = (
                max(top_k, 200)
                if (query.text_must_include_any or query.text_must_include_all)
                else top_k
            )
            raw_results = self.client.query(
                collection_name=self.collection_name,
                filter=expr,
                output_fields=OUTPUT_FIELDS,
                limit=candidate_limit,
                retry_times=0,
            )
            print(f"[MILVUS-QUERY] Scalar query returned {len(raw_results)} raw records", flush=True)
        except Exception as e:
            if not _is_transient_milvus_error(e):
                raise
            print(f"[MILVUS-QUERY] Scalar query FAILED: {e}", flush=True)
            logger.warning(f"[StructuredRetrieval] scalar query failed: {e}")
            raise PolicyRetrievalUnavailableError(str(e)) from e

        # 打印每条原始结果的关键字段
        if raw_results:
            print(f"[MILVUS-QUERY] Raw results sample (first 5):", flush=True)
            for i, r in enumerate(raw_results[:5]):
                src = (str(r.get("source_text", "") or ""))[:100]
                print(f"[MILVUS-QUERY]   [{i}] id={r.get('rule_id','')} insu={r.get('insu_type','')} "
                      f"med={r.get('med_type','')} hosp={r.get('hosp_lv','')} "
                      f"psn={r.get('psn_type','')} type={r.get('rule_type','')}", flush=True)
                print(f"[MILVUS-QUERY]        src: {src}", flush=True)

        # detail 字段归一化（FieldTrace dict → 裸值）
        for r in raw_results:
            unpack_detail(r)

        # 后处理：严格适用维度与文本关键词过滤
        skipped_keyword = 0
        for r in raw_results:
            if any(
                not str(r.get(field, "") or "")
                or not (
                    str(query.filters.get(field, "")) in str(r.get(field, ""))
                    or str(r.get(field, "")) in str(query.filters.get(field, ""))
                )
                for field in query.exact_match_fields
                if query.filters.get(field)
            ):
                skipped_keyword += 1
                continue
            combined_text = _searchable_text(r)

            # 检查 text_must_include_any
            if query.text_must_include_any:
                if not any(kw in combined_text for kw in query.text_must_include_any):
                    skipped_keyword += 1
                    continue

            # 检查 text_must_include_all
            if query.text_must_include_all:
                if not all(kw in combined_text for kw in query.text_must_include_all):
                    skipped_keyword += 1
                    continue

            r["score"] = 1.0  # 结构化匹配
            r["_query_name"] = query.query_name
            results.append(r)

        if results and query.search_text:
            scores = _bm25_scores(query.search_text, [_searchable_text(r) for r in results])
            for item, score in zip(results, scores):
                item["score"] = 0.7 + 0.3 * score
            results.sort(key=lambda item: item["score"], reverse=True)
        elif results:
            # Issue #33：无语义文本时按适用特异性确定性排序（此前为 Milvus 插入序，
            # top_k 截断后期望规则能否进入前列纯属运气）：
            # 精确人群/医院等级匹配 + 已解析金额段优先
            want_psn = str(query.filters.get("psn_type", "") or "")
            want_hosp = str(query.filters.get("hosp_lv", "") or "")

            def _specificity(item: dict[str, Any]) -> float:
                score = 1.0
                if want_psn and str(item.get("psn_type", "") or "") == want_psn:
                    score += 0.2
                if want_hosp and str(item.get("hosp_lv", "") or "") == want_hosp:
                    score += 0.1
                if query.amount_range and (
                    int(item.get("amount_band_min") or 0),
                    int(item.get("amount_band_max") or 0),
                ) != (0, 0):
                    score += 0.1
                return score

            for item in results:
                item["score"] = _specificity(item)
            results.sort(key=lambda item: item["score"], reverse=True)

        # Issue #33：候选放大（candidate_limit）后截回 top_k，保持既有返回上界
        results = results[:top_k]

        if skipped_keyword > 0:
            print(f"[MILVUS-QUERY] Keyword filter: {skipped_keyword} records skipped", flush=True)

        # 结构化候选存在但不相关时，保持适用条件做向量召回 + BM25 重排。
        if not results and raw_results and query.search_text:
            try:
                vector = get_embedding_provider().encode([query.search_text])[0]
                search_results = self.client.search(
                    collection_name=self.collection_name,
                    data=[vector],
                    anns_field="vector",
                    search_params={"metric_type": "COSINE", "params": {"ef": 64}},
                    filter=expr,
                    limit=top_k * 3,
                    output_fields=OUTPUT_FIELDS,
                )
                candidates: list[dict[str, Any]] = []
                dense_scores: list[float] = []
                for hit in search_results[0] if search_results else []:
                    item = dict(hit["entity"])
                    unpack_detail(item)
                    combined_text = _searchable_text(item)
                    if query.text_must_include_any and not any(
                        keyword in combined_text for keyword in query.text_must_include_any
                    ):
                        continue
                    if query.text_must_include_all and not all(
                        keyword in combined_text for keyword in query.text_must_include_all
                    ):
                        continue
                    candidates.append(item)
                    dense_scores.append(max(0.0, min(1.0, float(hit["distance"]))))
                bm25_scores = _bm25_scores(
                    query.search_text, [_searchable_text(item) for item in candidates]
                )
                for item, dense_score, bm25_score in zip(
                    candidates, dense_scores, bm25_scores
                ):
                    keyword_score = sum(
                        keyword in _searchable_text(item)
                        for keyword in query.text_must_include_any
                    ) / max(1, len(query.text_must_include_any))
                    item["score"] = (
                        0.55 * dense_score + 0.25 * bm25_score + 0.20 * keyword_score
                    )
                    item["_query_name"] = query.query_name
                results = sorted(
                    candidates, key=lambda item: item["score"], reverse=True
                )[:top_k]
            except Exception as e:
                if _is_transient_milvus_error(e):
                    raise PolicyRetrievalUnavailableError(str(e)) from e
                logger.warning("[StructuredRetrieval] hybrid fallback failed: %s", e)

        # 兼容旧查询计划：无语义检索文本时继续使用 LIKE 宽松查询。
        if not results and not query.search_text and query.text_must_include_any:
            print(f"[MILVUS-QUERY] No results after keyword filter, trying LIKE fallback...", flush=True)
            for kw in query.text_must_include_any[:3]:
                try:
                    like_expr = expr + f' and source_text like "%{kw}%"'
                    print(f"[MILVUS-QUERY]   LIKE fallback expr: {like_expr}", flush=True)
                    fallback = self.client.query(
                        collection_name=self.collection_name,
                        filter=like_expr,
                        output_fields=OUTPUT_FIELDS,
                        limit=top_k,
                        retry_times=0,
                    )
                    print(f"[MILVUS-QUERY]   LIKE fallback returned {len(fallback)} records", flush=True)
                    for r in fallback:
                        unpack_detail(r)
                        r["score"] = 1.0
                        r["_query_name"] = query.query_name
                        if r not in results:
                            results.append(r)
                except Exception as e:
                    if not _is_transient_milvus_error(e):
                        raise
                    print(f"[MILVUS-QUERY]   LIKE fallback FAILED: {e}", flush=True)
                    raise PolicyRetrievalUnavailableError(str(e)) from e

        print(f"[MILVUS-QUERY] Final: {len(results)} records (after all filters)", flush=True)
        print(f"[MILVUS-QUERY] ====== 查询结束 ======\n", flush=True)
        return results

    # ── 完整检索流程 ──────────────────────────────────────────────

    def retrieve(self, ctx: NormalizedPolicyContext,
                 target_field: str = "统筹自付",
                 custom_queries: list[StructuredPolicyQuery] | None = None) -> StructuredRetrievalResult:
        """
        完整结构化检索流程：
        1. 规划查询
        2. 执行各组查询
        3. 组装 evidence
        4. 去重
        5. 标记缺失必需规则
        """
        result = StructuredRetrievalResult()
        result.settlement_context = {
            "settlement_id": ctx.settlement_id,
            "insu_type": ctx.insu_type,
            "med_type": ctx.med_type,
            "hosp_lv": ctx.hosp_lv,
            "psn_type": ctx.psn_type,
            "region": ctx.region or _DEFAULT_REGION,
            "settlement_date": ctx.settlement_date or _DEFAULT_SETTLEMENT_DATE,
            "is_remote": ctx.is_remote,
            "target_field": target_field,
            "target_amount": ctx.target_amount,
        }
        result.normalized_context = result.settlement_context

        # Issue #33 加固：空上下文（无区分性维度）直接拒答，返回空证据。
        # 显式传入 custom_queries 的调用方自负规划责任，不受此限。
        if custom_queries is None and _is_empty_policy_context(ctx):
            result.refusal_reason = EMPTY_CONTEXT_REFUSAL_REASON
            result.refusal_message = EMPTY_CONTEXT_REFUSAL_MESSAGE
            logger.warning(
                "[StructuredRetrieval] 空上下文拒答：无险种/医疗类别/人群/医院等级/结算单号，"
                "返回空证据"
            )
            return result

        # Step 1: 规划查询（支持外部传入的自定义查询计划）
        queries = custom_queries if custom_queries is not None else self.plan_queries(ctx, target_field)
        # 注入结算日期到每个查询（Issue #25 时间过滤）
        for q in queries:
            q.settlement_date = ctx.settlement_date or _DEFAULT_SETTLEMENT_DATE
        result.planned_queries = [
            {
                "query_name": q.query_name,
                "required": q.required,
                "filters": q.filters,
                "text_must_include_any": q.text_must_include_any,
                "text_must_include_all": q.text_must_include_all,
                "psn_type_allow_all": q.psn_type_allow_all,
                "settlement_date": q.settlement_date,
                "search_text": q.search_text,
                "exact_match_fields": q.exact_match_fields,
            }
            for q in queries
        ]
        logger.info(f"[StructuredRetrieval] Planned {len(queries)} queries for '{target_field}'")

        # Step 2: 执行各组查询
        all_raw_hits: list[dict[str, Any]] = []
        for query in queries:
            hits = self.execute_query(query, top_k=query.top_k)
            result.query_results[query.query_name] = hits
            all_raw_hits.extend(hits)

            if query.required and not hits:
                result.missing_required_rules.append(query.query_name)
                logger.warning(
                    f"[StructuredRetrieval] MISSING required rule: {query.query_name}"
                )

        # Step 3: 去重（使用 rule_instance_key）
        before_dedupe = len(all_raw_hits)
        seen_keys: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for hit in all_raw_hits:
            key = self._build_rule_instance_key(hit)
            if key and key not in seen_keys:
                seen_keys.add(key)
                deduped.append(hit)
            elif not key:
                deduped.append(hit)  # 无法生成 key 的保留

        result.dedupe_info = {
            "before_count": before_dedupe,
            "after_count": len(deduped),
            "dedupe_key": "rule_instance_key",
            "removed_count": before_dedupe - len(deduped),
        }
        logger.info(
            f"[StructuredRetrieval] Dedup: {before_dedupe} -> {len(deduped)} "
            f"(removed {before_dedupe - len(deduped)})"
        )

        # Step 4: 组装 StructuredPolicyEvidence
        for hit in deduped:
            evidence = self._assemble_evidence(hit)
            result.selected_evidence.append(evidence)

        logger.info(
            f"[StructuredRetrieval] Final evidence: {len(result.selected_evidence)} items, "
            f"missing: {result.missing_required_rules}"
        )
        return result

    # ── 辅助方法 ──────────────────────────────────────────────────

    @staticmethod
    def _build_rule_instance_key(entity: dict[str, Any]) -> str:
        """
        构建 rule_instance_key（非 rule_id）。

        使用多个字段组合 hash，避免共用 rule_id 的分段规则被覆盖。
        """
        key_parts = [
            str(entity.get("policy_id", "") or ""),
            str(entity.get("clause_id", "") or ""),
            str(entity.get("source_text", "") or "")[:200],
            str(entity.get("insu_type", "") or ""),
            str(entity.get("med_type", "") or ""),
            str(entity.get("hosp_lv", "") or ""),
            str(entity.get("psn_type", "") or ""),
            str(entity.get("rule_type", "") or ""),
            str(entity.get("region", "") or ""),
            str(entity.get("policy_version", "") or ""),
            str(entity.get("payment_ratio", "") or ""),
            str(entity.get("amount_band", "") or ""),
            str(entity.get("rule_value", "") or "")[:200],
        ]
        combined = "|||".join(key_parts)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:32]

    def _assemble_evidence(self, entity: dict[str, Any]) -> StructuredPolicyEvidence:
        """从 Milvus 实体组装 StructuredPolicyEvidence。"""
        rule_type = str(entity.get("rule_type", "") or "")
        query_name = str(entity.get("_query_name", "") or "")

        # 构建 applied_reason
        applied_reason = self._build_applied_reason(entity, query_name)

        # Issue #25：从 entity 读取适用性字段，缺失时填默认值
        def _bool_val(key: str) -> bool:
            v = entity.get(key)
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes", "是")
            return False

        return StructuredPolicyEvidence(
            evidence_id=str(entity.get("rule_id", "") or ""),
            source="structured_policy_rule",
            query_name=query_name,
            policy_id=str(entity.get("policy_id", "") or ""),
            clause_id=str(entity.get("clause_id", "") or ""),
            rule_type=rule_type,
            insu_type=str(entity.get("insu_type", "") or ""),
            med_type=str(entity.get("med_type", "") or ""),
            hosp_lv=str(entity.get("hosp_lv", "") or ""),
            psn_type=str(entity.get("psn_type", "") or ""),
            region=str(entity.get("region", "") or _DEFAULT_REGION),
            effective_date=str(entity.get("effective_date", "") or ""),
            expiry_date=str(entity.get("expiry_date", "") or ""),
            publish_status=str(entity.get("publish_status", "") or ""),
            policy_version=str(entity.get("policy_version", "") or ""),
            is_remote=_bool_val("is_remote"),
            source_text=str(entity.get("source_text", "") or ""),
            rule_value=str(entity.get("rule_value", "") or ""),
            payment_ratio=str(entity.get("payment_ratio", "") or ""),
            amount_band=str(entity.get("amount_band", "") or ""),
            rule_id=str(entity.get("rule_id", "") or ""),
            rule_instance_key=self._build_rule_instance_key(entity),
            applied_reason=applied_reason,
            score=float(entity.get("score", 1.0)),
        )

    @staticmethod
    def _build_applied_reason(entity: dict[str, Any], query_name: str) -> str:
        """构建人性化匹配原因。"""
        if query_name == "employee_inpatient_tertiary_segment_ratio":
            return "本次为城镇职工退休人员三级医院普通住院，统筹自付需先取得三级医院职工住院分段支付比例。"
        elif query_name == "retiree_personal_ratio":
            return "本次结算人员为退休人员，退休人员个人支付比例为职工个人支付比例的60%。"
        # 通用 fallback
        parts = []
        if entity.get("insu_type"):
            parts.append(f"险种={entity['insu_type']}")
        if entity.get("psn_type"):
            parts.append(f"人群={entity['psn_type']}")
        if entity.get("rule_type"):
            parts.append(f"类型={entity['rule_type']}")
        return "、".join(parts) if parts else "结构化政策规则匹配"


# ── 快速检索函数 ──────────────────────────────────────────────────

def retrieve_policy_evidence(
    settlement_context: dict[str, Any],
    host: str = "127.0.0.1",
    port: str = "19530",
    custom_queries: list[StructuredPolicyQuery] | None = None,
    collection_name: str | None = None,
) -> StructuredRetrievalResult:
    """
    从结算上下文快速检索政策证据。

    Args:
        settlement_context: 标准化结算上下文字典，包含 insu_type/med_type/hosp_lv/psn_type
        host: Milvus host
        port: Milvus port

    Returns:
        StructuredRetrievalResult
    """
    # PDSC 适用关系过滤（§10.3）：已发布关系存在时，业务事实值转换为
    # 政策标量过滤并覆盖同名上下文字段；无关系时为空，行为不变。
    from src.runtime.policy_qa.pdsc_filter_bridge import build_pdsc_filters

    pdsc_filters = build_pdsc_filters(settlement_context)
    effective_context = dict(settlement_context)
    effective_context.update(pdsc_filters)

    # Issue #25：读取新增适用性字段
    def _bool_from_ctx(key: str) -> bool:
        v = effective_context.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "是")
        return False

    ctx = NormalizedPolicyContext(
        settlement_id=str(effective_context.get("settlement_id", "")),
        insu_type=str(effective_context.get("insu_type", "")),
        med_type=str(effective_context.get("med_type", "")),
        hosp_lv=normalize_hosp_lv(str(effective_context.get("hosp_lv", ""))),
        psn_type=str(effective_context.get("psn_type", "")),
        region=str(effective_context.get("region", _DEFAULT_REGION) or _DEFAULT_REGION),
        settlement_date=str(effective_context.get("settlement_date", _DEFAULT_SETTLEMENT_DATE) or _DEFAULT_SETTLEMENT_DATE),
        is_remote=_bool_from_ctx("is_remote"),
        target_field=str(effective_context.get("target_field", "统筹自付")),
        target_amount=float(effective_context.get("target_amount", 0)),
    )

    retriever = StructuredPolicyRuleRetriever(
        host=host,
        port=port,
        collection_name=collection_name or resolve_rules_collection(host, port),
    )
    return retriever.retrieve(ctx, target_field=ctx.target_field, custom_queries=custom_queries)
