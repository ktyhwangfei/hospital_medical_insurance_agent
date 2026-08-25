"""
结构化政策规则检索器（StructuredPolicyRuleRetriever）

不依赖向量检索，优先使用 Milvus scalar query（字段精准过滤）查询 policy_rules。
向量检索只作为排序兜底，不作为判断"有没有政策依据"的依据。

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
from dataclasses import dataclass, field
from typing import Any

from pymilvus import MilvusClient
from pymilvus.exceptions import MilvusException

from src.runtime.policy_qa.policy_rules_search import (
    COLLECTION_NAME,
    OUTPUT_FIELDS,
    unpack_detail,
)

logger = logging.getLogger(__name__)


class PolicyRetrievalUnavailableError(Exception):
    """政策数据源瞬时不可用，可由有界 Loop 重试。"""

    pass


# ── 标准化结算上下文 ──────────────────────────────────────────────

@dataclass
class NormalizedPolicyContext:
    """从真实结算数据标准化后的政策查询上下文。"""
    settlement_id: str = ""
    insu_type: str = ""       # 险种: "城镇职工基本医疗保险"
    med_type: str = ""        # 医疗类别: "住院-普通住院"
    hosp_lv: str = ""         # 医院等级: "三级医院"
    psn_type: str = ""        # 人员类别: "退休人员"
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
    normalized_context: dict[str, str] = field(default_factory=dict)
    planned_queries: list[dict[str, Any]] = field(default_factory=list)
    query_results: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    selected_evidence: list[StructuredPolicyEvidence] = field(default_factory=list)
    missing_required_rules: list[str] = field(default_factory=list)
    dedupe_info: dict[str, Any] = field(default_factory=dict)


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
    ):
        uri = f"http://{host}:{port}"
        self.client = MilvusClient(uri=uri)
        self.collection_name = collection_name or COLLECTION_NAME
        logger.info(f"StructuredPolicyRuleRetriever initialized: {uri}")

    # ── 查询规划 ─────────────────────────────────────────────────

    def plan_queries(self, ctx: NormalizedPolicyContext,
                     target_field: str = "统筹自付") -> list[StructuredPolicyQuery]:
        """
        根据结算上下文生成结构化查询计划。

        "统筹自付"需要两组必需规则：
        1. 三级医院职工住院分段支付比例
        2. 退休人员个人支付比例60%折算公式
        """
        queries: list[StructuredPolicyQuery] = []

        if target_field in ("统筹自付", "pooling_self_pay"):
            # 查询1: 三级医院职工住院分段支付比例
            # ★ psn_type 不限定为退休人员，基础分段比例对全部人群通用
            # ★ hosp_lv 必须包含，否则会混入其他等级医院的规则
            query1_filters = {
                "insu_type": ctx.insu_type,
                "med_type": ctx.med_type,
                "rule_type": "支付比例",
            }
            if ctx.hosp_lv:
                query1_filters["hosp_lv"] = ctx.hosp_lv

            queries.append(StructuredPolicyQuery(
                query_name="employee_inpatient_tertiary_segment_ratio",
                required=True,
                filters=query1_filters,
                psn_type_allow_all=True,
                text_must_include_any=[
                    "起付标准至3万元",
                    "超过3万元至4万元",
                    "超过4万元",
                ],
            ))

            # 查询2: 退休人员个人支付比例（折算物化后的绝对值规则 + 折算公式规则）
            # ★ U3：去掉硬编码 rule_type=计算公式（提取端不产出该类型），改 rule_type=支付比例；
            # ★ 命中 U3 折算展开的退休 personal_payment_ratio 规则（source_text 含「个人支付比例/60%」）
            query2_filters = {
                "insu_type": ctx.insu_type,
                "med_type": ctx.med_type,
                "psn_type": ctx.psn_type,
                "rule_type": "支付比例",
            }

            queries.append(StructuredPolicyQuery(
                query_name="retiree_personal_ratio",
                required=True,
                filters=query2_filters,
                text_must_include_any=[
                    "个人支付比例",
                    "60%",
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
        """
        results: list[dict[str, Any]] = []

        # 构建 Milvus expr 过滤条件
        expr_parts: list[str] = []

        # 字段相等/模糊过滤
        for field, value in query.filters.items():
            if value and field != "psn_type":
                # ★ insu_type 使用 LIKE 匹配，因为上下文可能返回简称
                if field == "insu_type":
                    expr_parts.append(f'{field} like "%{value}%"')
                else:
                    expr_parts.append(f'{field} == "{value}"')
            elif value and field == "psn_type":
                # psn_type 允许宽松匹配
                if not query.psn_type_allow_all:
                    expr_parts.append(f'psn_type == "{value}"')

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
            raw_results = self.client.query(
                collection_name=self.collection_name,
                filter=expr,
                output_fields=OUTPUT_FIELDS,
                limit=top_k,
            )
            print(f"[MILVUS-QUERY] Scalar query returned {len(raw_results)} raw records", flush=True)
        except (ConnectionError, TimeoutError, MilvusException) as e:
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

        # 后处理：文本关键词过滤
        skipped_keyword = 0
        for r in raw_results:
            combined_text = str(r.get("source_text", "") or "")

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

        if skipped_keyword > 0:
            print(f"[MILVUS-QUERY] Keyword filter: {skipped_keyword} records skipped", flush=True)

        # 降级：如果标量查询 + 关键词过滤无结果，尝试 LIKE 宽松查询
        if not results and query.text_must_include_any:
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
                    )
                    print(f"[MILVUS-QUERY]   LIKE fallback returned {len(fallback)} records", flush=True)
                    for r in fallback:
                        unpack_detail(r)
                        r["score"] = 1.0
                        r["_query_name"] = query.query_name
                        if r not in results:
                            results.append(r)
                except Exception as e:
                    print(f"[MILVUS-QUERY]   LIKE fallback FAILED: {e}", flush=True)

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
            "target_field": target_field,
            "target_amount": ctx.target_amount,
        }
        result.normalized_context = result.settlement_context

        # Step 1: 规划查询（支持外部传入的自定义查询计划）
        queries = custom_queries if custom_queries is not None else self.plan_queries(ctx, target_field)
        result.planned_queries = [
            {
                "query_name": q.query_name,
                "required": q.required,
                "filters": q.filters,
                "text_must_include_any": q.text_must_include_any,
                "text_must_include_all": q.text_must_include_all,
                "psn_type_allow_all": q.psn_type_allow_all,
            }
            for q in queries
        ]
        logger.info(f"[StructuredRetrieval] Planned {len(queries)} queries for '{target_field}'")

        # Step 2: 执行各组查询
        all_raw_hits: list[dict[str, Any]] = []
        for query in queries:
            hits = self.execute_query(query)
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
    ctx = NormalizedPolicyContext(
        settlement_id=str(settlement_context.get("settlement_id", "")),
        insu_type=str(settlement_context.get("insu_type", "")),
        med_type=str(settlement_context.get("med_type", "")),
        hosp_lv=str(settlement_context.get("hosp_lv", "")),
        psn_type=str(settlement_context.get("psn_type", "")),
        target_field=str(settlement_context.get("target_field", "统筹自付")),
        target_amount=float(settlement_context.get("target_amount", 0)),
    )

    retriever = StructuredPolicyRuleRetriever(host=host, port=port)
    return retriever.retrieve(ctx, target_field=ctx.target_field, custom_queries=custom_queries)
