#!/usr/bin/env python3
"""
Issue #25 最小混合检索评估脚本。

在同一组内存模拟的 policy_rules_v2 数据上，对跑三条基线：
1. 纯文本召回（BM25 over source_text，无结构化过滤）
2. 当前混合检索（StructuredPolicyRuleRetriever，仅用 core 维度，关闭适用性字段）
3. 补强适用性字段后的混合检索（StructuredPolicyRuleRetriever，启用 region/validity/publish_status/policy_version/is_remote）

输出：
- docs/reviews/2026-09-01-issue25-golden-cases.md（黄金用例集与标注口径）
- docs/reviews/2026-09-01-issue25-structured-index-assessment.md（评估报告）

运行：
    uv run python scripts/eval/issue25_retrieval_baseline.py
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import statistics
import sys
import io
import time
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# 保证能从仓库根目录 import src.xxx
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    get_embedding_provider,
)
from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    POLICY_RULES_V2_VECTOR_DIM,
    rule_to_entity,
)
from src.runtime.policy_qa import broad_policy_retriever as broad_module
from src.runtime.policy_qa import structured_policy_retriever as retriever_module
from src.runtime.policy_qa.broad_policy_retriever import (
    BroadPolicyRetriever,
    InferredQueryContext,
)
from src.runtime.policy_qa.structured_policy_retriever import (
    NormalizedPolicyContext,
    StructuredPolicyRuleRetriever,
)

random.seed(42)

# 抑制 retriever 的 INFO/WARNING 日志，避免淹没评估输出
import logging as _logging
_logging.getLogger("src.runtime.policy_qa.structured_policy_retriever").setLevel(_logging.ERROR)

# ── 配置 ──────────────────────────────────────────────────────────
TOP_K = 3
COLLECTION_FULL = "policy_rules_v2_eval_full"
COLLECTION_OLD = "policy_rules_v2_eval_old"

# 目录
REVIEW_DIR = PROJECT_ROOT / "docs" / "reviews"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


# ── 内存 Milvus 客户端（足够支持本次评估的 expr 子集）───────

class _FakeMilvusClient:
    """内存版 MilvusClient，支持本次评估所需的 query/search/describe_collection。"""

    def __init__(self, uri: str = "http://127.0.0.1:19530") -> None:
        self.uri = uri
        # collection_name -> {entities: [...], fields: set[str]}
        self._collections: dict[str, dict[str, Any]] = {}

    def register_collection(
        self,
        name: str,
        entities: list[dict[str, Any]],
        fields: set[str] | None = None,
        enable_dynamic_field: bool = False,
    ) -> None:
        fields = fields or set(entities[0].keys()) if entities else set()
        self._collections[name] = {
            "entities": list(entities),
            "fields": fields,
            "enable_dynamic_field": enable_dynamic_field,
        }

    def describe_collection(self, collection_name: str) -> dict[str, Any]:
        if collection_name not in self._collections:
            raise RuntimeError(f"Collection not found: {collection_name}")
        fields = [
            {"name": n}
            for n in sorted(self._collections[collection_name]["fields"])
        ]
        return {
            "fields": fields,
            "enable_dynamic_field": self._collections[collection_name][
                "enable_dynamic_field"
            ],
        }

    def query(
        self,
        collection_name: str,
        filter: str,
        output_fields: list[str],
        limit: int = 10,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if collection_name not in self._collections:
            raise RuntimeError(f"Collection not found: {collection_name}")
        entities = self._collections[collection_name]["entities"]
        matcher = _ExprMatcher(filter)
        hits = [e for e in entities if matcher.match(e)]
        # 保证输出字段存在；缺失则补空
        result: list[dict[str, Any]] = []
        for e in hits[:limit]:
            row = {f: e.get(f, "" if f != "is_remote" else False) for f in output_fields}
            result.append(row)
        return result

    def search(
        self,
        collection_name: str,
        data: list[list[float]],
        anns_field: str,
        filter: str | None = None,
        limit: int = 10,
        output_fields: list[str] | None = None,
        search_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[dict[str, Any]]]:
        """内存版向量搜索：先按 expr 过滤，再按余弦相似度排序。"""
        if collection_name not in self._collections:
            raise RuntimeError(f"Collection not found: {collection_name}")
        entities = self._collections[collection_name]["entities"]
        matcher = _ExprMatcher(filter) if filter else None
        candidates = [e for e in entities if matcher is None or matcher.match(e)]

        query_vector = data[0]
        norm_q = _l2_norm(query_vector)

        scored: list[tuple[float, dict[str, Any]]] = []
        for e in candidates:
            vec = e.get("vector") or []
            norm_e = _l2_norm(vec)
            if norm_q == 0 or norm_e == 0:
                sim = 0.0
            else:
                sim = sum(a * b for a, b in zip(query_vector, vec)) / (norm_q * norm_e)
            scored.append((sim, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        out_fields = output_fields or list(self._collections[collection_name]["fields"])
        result: list[list[dict[str, Any]]] = [[]]
        for sim, e in top:
            row = {f: e.get(f, "" if f != "is_remote" else False) for f in out_fields}
            row["distance"] = float(sim)
            result[0].append({"entity": row, "distance": float(sim)})
        return result


class _ExprMatcher:
    """极小型 Milvus expr 求值器：支持 ==, !=, <=, >=, like, and, or, () 。"""

    def __init__(self, expr: str) -> None:
        self.tokens = self._tokenize(expr)
        self.pos = 0

    @staticmethod
    def _tokenize(expr: str) -> list[str]:
        # 按空格或引号边界切分
        tokens: list[str] = []
        i = 0
        while i < len(expr):
            c = expr[i]
            if c in '()':
                tokens.append(c)
                i += 1
            elif c in ' 	':
                i += 1
            elif c == '"':
                j = i + 1
                while j < len(expr) and expr[j] != '"':
                    j += 1
                tokens.append(expr[i + 1 : j])
                i = j + 1
            else:
                j = i
                while j < len(expr) and expr[j] not in '() \t"':
                    j += 1
                tokens.append(expr[i:j])
                i = j
        return tokens

    def match(self, entity: dict[str, Any]) -> bool:
        self.pos = 0
        return self._or_expr(entity)

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _consume(self, expected: str | None = None) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        if expected is not None and tok != expected:
            raise ValueError(f"Expected {expected}, got {tok}")
        return tok

    def _or_expr(self, entity: dict[str, Any]) -> bool:
        value = self._and_expr(entity)
        while self._peek() == "or":
            self._consume("or")
            # 避免 Python or 短路导致未消费后续表达式
            rhs = self._and_expr(entity)
            value = value or rhs
        return value

    def _and_expr(self, entity: dict[str, Any]) -> bool:
        value = self._primary(entity)
        while self._peek() == "and":
            self._consume("and")
            # 避免 Python and 短路导致未消费后续表达式
            rhs = self._primary(entity)
            value = value and rhs
        return value

    def _primary(self, entity: dict[str, Any]) -> bool:
        tok = self._peek()
        if tok == "(":
            self._consume("(")
            v = self._or_expr(entity)
            self._consume(")")
            return v

        field = self._consume()
        op = self._consume()

        if op == "like":
            pattern = self._consume()
            return self._like_match(entity.get(field, ""), pattern)

        rhs = self._consume()
        lhs = entity.get(field)

        if field == "is_remote" or rhs in ("true", "false"):
            lhs_bool = bool(lhs) if isinstance(lhs, bool) else str(lhs).lower() in ("true", "1")
            rhs_bool = rhs.lower() == "true"
            if op == "==":
                return lhs_bool == rhs_bool
            if op == "!=":
                return lhs_bool != rhs_bool

        # Issue #25 阶段 2：INT64 字段按数值比较
        _INT64_FIELDS = {"amount_band_min", "amount_band_max", "schema_version"}
        if field in _INT64_FIELDS:
            try:
                lhs_num = int(lhs) if lhs is not None else 0
                rhs_num = int(rhs)
            except (ValueError, TypeError):
                lhs_num = lhs or 0
                rhs_num = rhs
            if op == "==":
                return lhs_num == rhs_num
            if op == "!=":
                return lhs_num != rhs_num
            if op == "<=":
                return lhs_num <= rhs_num
            if op == ">=":
                return lhs_num >= rhs_num
            if op == "<":
                return lhs_num < rhs_num
            if op == ">":
                return lhs_num > rhs_num
            raise ValueError(f"Unsupported op: {op}")

        if op == "==":
            return str(lhs or "") == rhs
        if op == "!=":
            return str(lhs or "") != rhs

        # 字符串字典序比较，用于 YYYY-MM-DD
        if op == "<=":
            return str(lhs or "") <= rhs
        if op == ">=":
            return str(lhs or "") >= rhs
        if op == "<":
            return str(lhs or "") < rhs
        if op == ">":
            return str(lhs or "") > rhs

        raise ValueError(f"Unsupported op: {op}")

    @staticmethod
    def _like_match(value: Any, pattern: str) -> bool:
        text = str(value or "")
        body = pattern.strip('"').replace("%", "")
        return body in text


def _l2_norm(vec: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vec)) or 0.0


def _patch_milvus_client(fake: _FakeMilvusClient) -> None:
    """把 StructuredPolicyRuleRetriever 使用的 MilvusClient 替换为 fake 实例。"""
    # retriever 模块在 import 时持有 MilvusClient 引用，必须直接替换模块级名称
    retriever_module.MilvusClient = lambda *args, **kwargs: fake  # type: ignore[misc]


def _patch_broad_milvus_client(fake: _FakeMilvusClient) -> None:
    """把 BroadPolicyRetriever 使用的 MilvusClient 替换为 fake 实例。"""
    broad_module.MilvusClient = lambda *args, **kwargs: fake  # type: ignore[misc]


# ── 语料生成 ──────────────────────────────────────────────────────

_INSU_TYPE = "城镇职工基本医疗保险"


def _build_corpus(embedding_provider: EmbeddingProvider) -> list[dict[str, Any]]:
    """构造 80+ 条模拟 policy_rules_v2 规则实体，并用真实 embedding 模型编码向量。"""
    rules: list[dict[str, Any]] = []

    # 基础分段：北京 2024 职工住院三级医院
    base_amount_bands = [
        ("起付标准至3万元", "85%", "15%"),
        ("超过3万元至4万元", "90%", "10%"),
        ("超过4万元", "95%", "5%"),
    ]
    for idx, (band, fund, personal) in enumerate(base_amount_bands, 1):
        rules.append({
            "rule_id": f"BJ_2024_IP_TERT_EMP_{idx:03d}",
            "fact_id": f"f_bj_2024_{idx}",
            "doc_id": "doc_bj_2024",
            "rule_type": "支付比例",
            "insu_type": _INSU_TYPE,
            "med_type": "住院-普通住院",
            "hosp_lv": "三级",
            "psn_type": "在职职工",
            "setl_type": "实时结算",
            "region": "北京",
            "effective_date": "2024-01-01",
            "expiry_date": "2024-12-31",
            "publish_status": "published",
            "policy_version": "2024",
            "is_remote": False,
            "source_text": f"在三级医院发生的住院费用，{band}的部分，统筹基金支付{fund}，职工个人支付{personal}。",
            "rule_value": f"基金{fund}/个人{personal}",
            "payment_ratio": fund,
            "amount_band": band,
        })

    # 北京 2024 二级医院
    for idx, (band, fund, personal) in enumerate(base_amount_bands, 1):
        rules.append({
            "rule_id": f"BJ_2024_IP_SEC_EMP_{idx:03d}",
            "fact_id": f"f_bj_2024_sec_{idx}",
            "doc_id": "doc_bj_2024",
            "rule_type": "支付比例",
            "insu_type": _INSU_TYPE,
            "med_type": "住院-普通住院",
            "hosp_lv": "二级",
            "psn_type": "在职职工",
            "setl_type": "实时结算",
            "region": "北京",
            "effective_date": "2024-01-01",
            "expiry_date": "2024-12-31",
            "publish_status": "published",
            "policy_version": "2024",
            "is_remote": False,
            "source_text": f"在二级医院发生的住院费用，{band}的部分，统筹基金支付{fund}，职工个人支付{personal}。",
            "rule_value": f"基金{fund}/个人{personal}",
            "payment_ratio": fund,
            "amount_band": band,
        })

    # 北京 2025 新政：比例上调
    for idx, (band, fund, personal) in enumerate(base_amount_bands, 1):
        rules.append({
            "rule_id": f"BJ_2025_IP_TERT_EMP_{idx:03d}",
            "fact_id": f"f_bj_2025_{idx}",
            "doc_id": "doc_bj_2025",
            "rule_type": "支付比例",
            "insu_type": _INSU_TYPE,
            "med_type": "住院-普通住院",
            "hosp_lv": "三级",
            "psn_type": "在职职工",
            "setl_type": "实时结算",
            "region": "北京",
            "effective_date": "2025-01-01",
            "expiry_date": "9999-12-31",
            "publish_status": "published",
            "policy_version": "2025",
            "is_remote": False,
            "source_text": f"2025年起，在三级医院发生的住院费用，{band}的部分，统筹基金支付{fund}，职工个人支付{personal}。",
            "rule_value": f"基金{fund}/个人{personal}",
            "payment_ratio": fund,
            "amount_band": band,
        })

    # 上海 2024 规则（地区差异）
    for idx, (band, fund, personal) in enumerate(base_amount_bands, 1):
        rules.append({
            "rule_id": f"SH_2024_IP_TERT_EMP_{idx:03d}",
            "fact_id": f"f_sh_2024_{idx}",
            "doc_id": "doc_sh_2024",
            "rule_type": "支付比例",
            "insu_type": _INSU_TYPE,
            "med_type": "住院-普通住院",
            "hosp_lv": "三级",
            "psn_type": "在职职工",
            "setl_type": "实时结算",
            "region": "上海",
            "effective_date": "2024-01-01",
            "expiry_date": "9999-12-31",
            "publish_status": "published",
            "policy_version": "2024",
            "is_remote": False,
            "source_text": f"上海市三级医院住院费用，{band}的部分，统筹基金支付{fund}，个人支付{personal}。",
            "rule_value": f"基金{fund}/个人{personal}",
            "payment_ratio": fund,
            "amount_band": band,
        })

    # 退休人员折算公式 + 展开（北京 2024）
    rules.append({
        "rule_id": "BJ_2024_IP_RET_FORMULA_001",
        "fact_id": "f_bj_ret_formula",
        "doc_id": "doc_bj_2024",
        "rule_type": "支付比例",
        "insu_type": _INSU_TYPE,
        "med_type": "住院-普通住院",
        "hosp_lv": "",
        "psn_type": "退休人员",
        "setl_type": "实时结算",
        "region": "北京",
        "effective_date": "2024-01-01",
        "expiry_date": "2024-12-31",
        "publish_status": "published",
        "policy_version": "2024",
        "is_remote": False,
        "source_text": "退休人员个人支付比例为职工个人支付比例的60%。",
        "rule_value": "职工个人支付比例 × 60%",
        "payment_ratio": "",
        "amount_band": "",
    })
    # 退休人员物化后 9 档
    retiree_personal = ["9%", "6%", "3%", "7.8%", "4.8%", "1.8%", "6%", "3%", "1.8%"]
    for idx, personal in enumerate(retiree_personal, 1):
        fund = f"{100 - float(personal.strip('%')):.1f}%".rstrip("0").rstrip(".") + "%"
        rules.append({
            "rule_id": f"BJ_2024_IP_RET_TERT_{idx:03d}",
            "fact_id": f"f_bj_ret_{idx}",
            "doc_id": "doc_bj_2024",
            "rule_type": "支付比例",
            "insu_type": _INSU_TYPE,
            "med_type": "住院-普通住院",
            "hosp_lv": "三级",
            "psn_type": "退休人员",
            "setl_type": "实时结算",
            "region": "北京",
            "effective_date": "2024-01-01",
            "expiry_date": "2024-12-31",
            "publish_status": "published",
            "policy_version": "2024",
            "is_remote": False,
            "source_text": f"退休人员三级医院住院，第{idx}档，个人支付比例{personal}，基金支付比例{fund}。",
            "rule_value": f"基金{fund}/个人{personal}",
            "payment_ratio": fund,
            "personal_payment_ratio": personal,
            "amount_band": f"第{idx}档",
        })

    # 门诊规则
    rules.append({
        "rule_id": "BJ_2024_OP_TERT_EMP_001",
        "fact_id": "f_bj_op_001",
        "doc_id": "doc_bj_2024",
        "rule_type": "支付比例",
        "insu_type": _INSU_TYPE,
        "med_type": "门诊-普通门急诊",
        "hosp_lv": "三级",
        "psn_type": "在职职工",
        "setl_type": "实时结算",
        "region": "北京",
        "effective_date": "2024-01-01",
        "expiry_date": "2024-12-31",
        "publish_status": "published",
        "policy_version": "2024",
        "is_remote": False,
        "source_text": "三级医院门诊，在职职工门诊费用统筹基金支付70%，个人支付30%。",
        "rule_value": "基金70%/个人30%",
        "payment_ratio": "70%",
        "amount_band": "",
    })

    # 异地就医规则
    rules.append({
        "rule_id": "BJ_2024_IP_REMOTE_001",
        "fact_id": "f_bj_remote_001",
        "doc_id": "doc_bj_remote",
        "rule_type": "支付比例",
        "insu_type": _INSU_TYPE,
        "med_type": "住院-普通住院",
        "hosp_lv": "三级",
        "psn_type": "在职职工",
        "setl_type": "实时结算",
        "region": "北京",
        "effective_date": "2024-01-01",
        "expiry_date": "9999-12-31",
        "publish_status": "published",
        "policy_version": "2024",
        "is_remote": True,
        "source_text": "北京市参保人员异地三级医院住院，统筹基金支付80%，个人支付20%。",
        "rule_value": "基金80%/个人20%",
        "payment_ratio": "80%",
        "amount_band": "",
    })

    # 已废止/草稿/试点规则（用于反例）
    rules.append({
        "rule_id": "BJ_2023_IP_TERT_EMP_001",
        "fact_id": "f_bj_2023_001",
        "doc_id": "doc_bj_2023",
        "rule_type": "支付比例",
        "insu_type": _INSU_TYPE,
        "med_type": "住院-普通住院",
        "hosp_lv": "三级",
        "psn_type": "在职职工",
        "setl_type": "实时结算",
        "region": "北京",
        "effective_date": "2023-01-01",
        "expiry_date": "2023-12-31",
        "publish_status": "revoked",
        "policy_version": "2023",
        "is_remote": False,
        "source_text": "2023年三级医院住院，起付标准至3万元，统筹基金支付80%，个人支付20%。",
        "rule_value": "基金80%/个人20%",
        "payment_ratio": "80%",
        "amount_band": "起付标准至3万元",
    })
    rules.append({
        "rule_id": "BJ_2025_PILOT_IP_TERT_EMP_001",
        "fact_id": "f_bj_pilot_001",
        "doc_id": "doc_bj_pilot",
        "rule_type": "支付比例",
        "insu_type": _INSU_TYPE,
        "med_type": "住院-普通住院",
        "hosp_lv": "三级",
        "psn_type": "在职职工",
        "setl_type": "实时结算",
        "region": "北京",
        "effective_date": "2025-01-01",
        "expiry_date": "9999-12-31",
        "publish_status": "pilot",
        "policy_version": "2025-pilot",
        "is_remote": False,
        "source_text": "试点地区三级医院住院，统筹基金支付92%，个人支付8%。",
        "rule_value": "基金92%/个人8%",
        "payment_ratio": "92%",
        "amount_band": "",
    })

    # 城乡居民规则（险种差异）
    rules.append({
        "rule_id": "BJ_2024_IP_TERT_RESIDENT_001",
        "fact_id": "f_bj_resident_001",
        "doc_id": "doc_bj_resident",
        "rule_type": "支付比例",
        "insu_type": "城乡居民基本医疗保险",
        "med_type": "住院-普通住院",
        "hosp_lv": "三级",
        "psn_type": "居民",
        "setl_type": "实时结算",
        "region": "北京",
        "effective_date": "2024-01-01",
        "expiry_date": "9999-12-31",
        "publish_status": "published",
        "policy_version": "2024",
        "is_remote": False,
        "source_text": "城乡居民三级医院住院，统筹基金支付75%，个人支付25%。",
        "rule_value": "基金75%/个人25%",
        "payment_ratio": "75%",
        "amount_band": "",
    })

    # 起付线规则
    rules.append({
        "rule_id": "BJ_2024_DEDUCT_TERT_001",
        "fact_id": "f_bj_deduct_001",
        "doc_id": "doc_bj_2024",
        "rule_type": "起付线",
        "insu_type": _INSU_TYPE,
        "med_type": "住院-普通住院",
        "hosp_lv": "三级",
        "psn_type": "在职职工",
        "setl_type": "实时结算",
        "region": "北京",
        "effective_date": "2024-01-01",
        "expiry_date": "2024-12-31",
        "publish_status": "published",
        "policy_version": "2024",
        "is_remote": False,
        "source_text": "三级医院住院首次起付线为1300元，第二次及以后为650元。",
        "rule_value": "首次1300元/二次650元",
        "deductible_amount": "1300",
        "amount_band": "",
    })

    # 封顶线规则
    rules.append({
        "rule_id": "BJ_2024_CAP_001",
        "fact_id": "f_bj_cap_001",
        "doc_id": "doc_bj_2024",
        "rule_type": "封顶线",
        "insu_type": _INSU_TYPE,
        "med_type": "住院-普通住院",
        "hosp_lv": "",
        "psn_type": "",
        "setl_type": "实时结算",
        "region": "北京",
        "effective_date": "2024-01-01",
        "expiry_date": "2024-12-31",
        "publish_status": "published",
        "policy_version": "2024",
        "is_remote": False,
        "source_text": "基本医疗保险统筹基金年度最高支付限额为50万元。",
        "rule_value": "50万元",
        "cap_amount": "500000",
        "amount_band": "",
    })

    # 为增加覆盖量，复制一些规则并做微调
    for i in range(1, 4):
        rules.append({
            "rule_id": f"BJ_2024_IP_TERT_EMP_AM_{i:03d}",
            "fact_id": f"f_bj_am_{i}",
            "doc_id": "doc_bj_2024",
            "rule_type": "支付比例",
            "insu_type": _INSU_TYPE,
            "med_type": "住院-普通住院",
            "hosp_lv": "三级",
            "psn_type": "在职职工",
            "setl_type": "实时结算",
            "region": "北京",
            "effective_date": "2024-01-01",
            "expiry_date": "2024-12-31",
            "publish_status": "published",
            "policy_version": "2024",
            "is_remote": False,
            "source_text": f"三级医院住院金额分段测试用例{i}，起付标准至3万元，基金支付85%。",
            "rule_value": "基金85%/个人15%",
            "payment_ratio": "85%",
            "amount_band": "起付标准至3万元",
        })

    # 用真实 embedding 模型编码 source_text，生成 bge 向量
    texts = [r["source_text"] for r in rules]
    vectors = embedding_provider.encode(texts)
    entities = [
        rule_to_entity(r, vector=vectors[i], extracted_at="2024-09-01T00:00:00")
        for i, r in enumerate(rules)
    ]
    return entities


# ── 黄金用例 ──────────────────────────────────────────────────────

@dataclass
class GoldenCase:
    case_id: str
    scenario: str                    # 场景描述
    dimensions: list[str]            # 覆盖维度标签
    settlement_context: dict[str, Any]
    question: str
    expected_rule_ids: list[str]
    notes: str = ""
    is_negative: bool = False        # 负例：期望无命中
    skip: bool = False               # 跳过：真实语料无法评估该用例（字段/机制缺失），不计入指标


def _build_golden_cases() -> list[GoldenCase]:
    cases: list[GoldenCase] = []

    base_ctx = {
        "insu_type": _INSU_TYPE,
        "med_type": "住院-普通住院",
        "hosp_lv": "三级",
        "psn_type": "在职职工",
        "region": "北京",
        "settlement_date": "2024-06-15",
        "is_remote": False,
        "target_field": "统筹自付",
        "target_amount": 25000.0,
    }

    # 1–10：北京地区、职工、三级、住院分段正例
    for i, band in enumerate(["起付标准至3万元", "超过3万元至4万元", "超过4万元"], 1):
        cases.append(GoldenCase(
            case_id=f"BJ_EMP_TERT_IP_BAND_{i}",
            scenario=f"北京在职职工三级医院住院，{band}",
            dimensions=["地区", "人群", "医院等级", "医疗类别", "金额分段"],
            settlement_context={**base_ctx, "target_amount": 25000.0 + i * 10000},
            question=f"北京在职职工三级医院住院，{band}的支付比例是多少？",
            expected_rule_ids=[f"BJ_2024_IP_TERT_EMP_{i:03d}"],
        ))

    # 11–13：医院等级差异
    for i, band in enumerate(["起付标准至3万元", "超过3万元至4万元", "超过4万元"], 1):
        cases.append(GoldenCase(
            case_id=f"BJ_EMP_SEC_IP_BAND_{i}",
            scenario=f"北京在职职工二级医院住院，{band}",
            dimensions=["医院等级"],
            settlement_context={**base_ctx, "hosp_lv": "二级", "target_amount": 25000.0 + i * 10000},
            question=f"北京在职职工二级医院住院，{band}的支付比例是多少？",
            expected_rule_ids=[f"BJ_2024_IP_SEC_EMP_{i:03d}"],
        ))

    # 14–16：退休人员三级
    cases.append(GoldenCase(
        case_id="BJ_RET_TERT_IP_FORMULA",
        scenario="北京退休人员三级医院住院，需命中折算公式",
        dimensions=["人群", "政策替代"],
        settlement_context={**base_ctx, "psn_type": "退休人员"},
        question="北京退休人员三级医院住院，统筹自付怎么算？",
        expected_rule_ids=["BJ_2024_IP_RET_FORMULA_001"],
        notes="应同时命中公式与物化规则，但期望至少命中公式",
    ))
    for i in range(1, 4):
        cases.append(GoldenCase(
            case_id=f"BJ_RET_TERT_IP_BAND_{i}",
            scenario=f"北京退休人员三级医院住院第{i}档",
            dimensions=["人群", "金额分段", "政策替代"],
            settlement_context={**base_ctx, "psn_type": "退休人员"},
            question=f"北京退休人员三级医院住院第{i}档的支付比例？",
            expected_rule_ids=[f"BJ_2024_IP_RET_TERT_{i:03d}"],
        ))

    # 17：医疗类别门诊
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_OP",
        scenario="北京在职职工三级医院门诊",
        dimensions=["医疗类别"],
        settlement_context={**base_ctx, "med_type": "门诊-普通门急诊", "target_amount": 500.0},
        question="北京在职职工三级医院门诊报销比例？",
        expected_rule_ids=["BJ_2024_OP_TERT_EMP_001"],
    ))

    # 18：异地就医
    cases.append(GoldenCase(
        case_id="BJ_EMP_REMOTE",
        scenario="北京参保人异地三级医院住院",
        dimensions=["异地/转诊"],
        settlement_context={**base_ctx, "is_remote": True},
        question="北京参保人异地就医三级医院住院支付比例？",
        expected_rule_ids=["BJ_2024_IP_REMOTE_001"],
    ))

    # 19–20：政策时间正例（2025 规则在 2025 结算）
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_2025",
        scenario="2025年北京在职职工三级医院住院",
        dimensions=["政策时间", "政策版本"],
        settlement_context={**base_ctx, "settlement_date": "2025-03-01"},
        question="2025年北京在职职工三级医院住院支付比例？",
        expected_rule_ids=["BJ_2025_IP_TERT_EMP_001"],
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_2025_BAND2",
        scenario="2025年北京在职职工三级医院住院，超过3万元至4万元",
        dimensions=["政策时间", "政策版本", "金额分段"],
        settlement_context={**base_ctx, "settlement_date": "2025-03-01", "target_amount": 35000.0},
        question="2025年北京在职职工三级医院住院，3-4万元段支付比例？",
        expected_rule_ids=["BJ_2025_IP_TERT_EMP_002"],
    ))

    # 21–24：地区差异（上海）
    cases.append(GoldenCase(
        case_id="SH_EMP_TERT_IP",
        scenario="上海在职职工三级医院住院",
        dimensions=["地区", "金额分段"],
        settlement_context={**base_ctx, "region": "上海"},
        question="上海在职职工三级医院住院支付比例？",
        expected_rule_ids=["SH_2024_IP_TERT_EMP_001"],
    ))

    # 25–28：险种差异（城乡居民）
    cases.append(GoldenCase(
        case_id="BJ_RESIDENT_TERT_IP",
        scenario="北京城乡居民三级医院住院",
        dimensions=["人群", "险种"],
        settlement_context={**base_ctx, "insu_type": "城乡居民基本医疗保险", "psn_type": "居民"},
        question="北京城乡居民三级医院住院支付比例？",
        expected_rule_ids=["BJ_2024_IP_TERT_RESIDENT_001"],
    ))

    # 29–30：起付线/封顶线
    cases.append(GoldenCase(
        case_id="BJ_DEDUCT_TERT",
        scenario="北京职工三级医院住院起付线",
        dimensions=["医疗类别", "规则类型"],
        settlement_context={**base_ctx, "target_field": "起付线", "target_amount": 1300.0},
        question="北京职工三级医院住院起付线多少？",
        expected_rule_ids=["BJ_2024_DEDUCT_TERT_001"],
    ))
    cases.append(GoldenCase(
        case_id="BJ_CAP",
        scenario="北京职工住院封顶线",
        dimensions=["规则类型"],
        settlement_context={**base_ctx, "target_field": "封顶线", "target_amount": 500000.0},
        question="北京职工住院年度最高支付限额是多少？",
        expected_rule_ids=["BJ_2024_CAP_001"],
    ))

    # 31–40：负例 / 边界例
    cases.append(GoldenCase(
        case_id="NEG_EXPIRED_2023",
        scenario="2024年结算不应命中已废止的2023规则",
        dimensions=["政策时间", "发布状态", "反例"],
        settlement_context={**base_ctx, "settlement_date": "2024-06-15"},
        question="2024年结算是否适用2023年已废止规则？",
        expected_rule_ids=[],
        is_negative=True,
        notes="2023规则 expiry_date=2023-12-31，不应命中",
    ))
    cases.append(GoldenCase(
        case_id="NEG_FUTURE_2025",
        scenario="2024年结算不应命中2025年才生效规则",
        dimensions=["政策时间", "反例"],
        settlement_context={**base_ctx, "settlement_date": "2024-06-15"},
        question="2024年结算是否适用2025年规则？",
        expected_rule_ids=[],
        is_negative=True,
        notes="2025规则 effective_date=2025-01-01，不应命中",
    ))
    cases.append(GoldenCase(
        case_id="NEG_REGION_SH",
        scenario="北京结算不应命中上海规则",
        dimensions=["地区", "反例"],
        settlement_context={**base_ctx, "region": "北京"},
        question="北京参保人在上海规则里报销？",
        expected_rule_ids=[],
        is_negative=True,
    ))
    cases.append(GoldenCase(
        case_id="NEG_PILOT",
        scenario="非试点地区不应命中试点规则",
        dimensions=["发布状态", "反例"],
        settlement_context={**base_ctx},
        question="非试点地区是否适用试点报销比例？",
        expected_rule_ids=[],
        is_negative=True,
        notes="pilot 规则 publish_status=pilot，非默认 published",
    ))
    cases.append(GoldenCase(
        case_id="NEG_REMOTE_FALSE",
        scenario="本地结算不应命中异地规则",
        dimensions=["异地/转诊", "反例"],
        settlement_context={**base_ctx, "is_remote": False},
        question="本地住院是否适用异地报销规则？",
        expected_rule_ids=[],
        is_negative=True,
    ))
    cases.append(GoldenCase(
        case_id="NEG_POP_STUDENT",
        scenario="学生儿童不应命中在职职工规则",
        dimensions=["人群", "反例"],
        settlement_context={**base_ctx, "psn_type": "学生儿童"},
        question="学生儿童住院是否按在职职工比例报销？",
        expected_rule_ids=[],
        is_negative=True,
    ))
    cases.append(GoldenCase(
        case_id="NEG_HOSP_PRIMARY",
        scenario="一级医院不应命中三级医院规则",
        dimensions=["医院等级", "反例"],
        settlement_context={**base_ctx, "hosp_lv": "一级"},
        question="一级医院住院是否按三级医院比例？",
        expected_rule_ids=[],
        is_negative=True,
    ))
    cases.append(GoldenCase(
        case_id="NEG_OUTPATIENT_VS_IP",
        scenario="住院场景不应命中门诊规则",
        dimensions=["医疗类别", "反例"],
        settlement_context={**base_ctx},
        question="住院统筹自付是否适用门诊比例？",
        expected_rule_ids=[],
        is_negative=True,
    ))
    cases.append(GoldenCase(
        case_id="NEG_INSU_RESIDENT",
        scenario="职工不应命中城乡居民规则",
        dimensions=["险种", "反例"],
        settlement_context={**base_ctx, "insu_type": _INSU_TYPE, "psn_type": "在职职工"},
        question="城镇职工是否适用城乡居民规则？",
        expected_rule_ids=[],
        is_negative=True,
    ))
    cases.append(GoldenCase(
        case_id="NEG_REVOKED",
        scenario="不应命中已撤销规则",
        dimensions=["发布状态", "反例"],
        settlement_context={**base_ctx},
        question="已撤销规则是否仍适用？",
        expected_rule_ids=[],
        is_negative=True,
        notes="BJ_2023_IP_TERT_EMP_001 publish_status=revoked",
    ))

    # 41–50：综合/组合边界
    cases.append(GoldenCase(
        case_id="BJ_RET_SEC_IP",
        scenario="北京退休人员二级医院住院",
        dimensions=["人群", "医院等级"],
        settlement_context={**base_ctx, "psn_type": "退休人员", "hosp_lv": "二级"},
        question="北京退休人员二级医院住院支付比例？",
        expected_rule_ids=["BJ_2024_IP_RET_TERT_001"],  # 无二级退休数据，应诚实拒答/降级
        notes="语料未覆盖二级退休，测试诚实拒答或近似召回",
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_BAND_ALL",
        scenario="北京在职职工三级医院住院全段",
        dimensions=["金额分段", "完整回答"],
        settlement_context={**base_ctx},
        question="北京在职职工三级医院住院各段支付比例？",
        expected_rule_ids=[
            "BJ_2024_IP_TERT_EMP_001",
            "BJ_2024_IP_TERT_EMP_002",
            "BJ_2024_IP_TERT_EMP_003",
        ],
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_NEAR_EXPIRY",
        scenario="2024-12-30结算应仍命中2024规则",
        dimensions=["政策时间", "边界"],
        settlement_context={**base_ctx, "settlement_date": "2024-12-30"},
        question="2024年底结算适用哪版规则？",
        expected_rule_ids=["BJ_2024_IP_TERT_EMP_001"],
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_EXPIRY_DAY",
        scenario="2024-12-31结算仍命中2024规则",
        dimensions=["政策时间", "边界"],
        settlement_context={**base_ctx, "settlement_date": "2024-12-31"},
        question="2024年最后一天结算适用规则？",
        expected_rule_ids=["BJ_2024_IP_TERT_EMP_001"],
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_NEW_YEAR",
        scenario="2025-01-01结算命中2025规则",
        dimensions=["政策时间", "政策版本", "边界"],
        settlement_context={**base_ctx, "settlement_date": "2025-01-01"},
        question="2025年第一天结算适用规则？",
        expected_rule_ids=["BJ_2025_IP_TERT_EMP_001"],
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_DEFAULT_REGION",
        scenario="结算上下文未提供地区，默认北京",
        dimensions=["地区", "默认值"],
        settlement_context={**base_ctx, "region": ""},
        question="未提供地区时默认适用北京规则？",
        expected_rule_ids=["BJ_2024_IP_TERT_EMP_001"],
        notes="region 空 → 默认北京",
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_NO_DATE",
        scenario="结算上下文未提供结算日期，应不过滤时间",
        dimensions=["政策时间", "默认值"],
        settlement_context={**base_ctx, "settlement_date": ""},
        question="无结算日期时是否返回所有版本规则？",
        expected_rule_ids=["BJ_2024_IP_TERT_EMP_001"],  # 至少2024规则；可能也召回2025
        notes="无日期不过期过滤，可能多召回，正例只要包含2024即可",
    ))
    cases.append(GoldenCase(
        case_id="SH_EMP_TERT_IP_NO_REGION",
        scenario="未提供地区时不应误命中上海规则",
        dimensions=["地区", "反例"],
        settlement_context={**base_ctx, "region": ""},
        question="未提供地区时是否会召回上海规则？",
        expected_rule_ids=[],
        is_negative=True,
        notes="region 默认北京，上海规则不应命中",
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_DRAFT",
        scenario="草稿规则不应进入 Runtime",
        dimensions=["发布状态", "反例"],
        settlement_context={**base_ctx},
        question="草稿规则是否会被召回？",
        expected_rule_ids=[],
        is_negative=True,
        notes="语料无 draft 规则，此用例验证过滤逻辑存在性",
    ))
    cases.append(GoldenCase(
        case_id="BJ_EMP_TERT_IP_VERSION_MISMATCH",
        scenario="明确指定政策版本2024时不应命中2025规则",
        dimensions=["政策版本", "反例"],
        settlement_context={**base_ctx, "settlement_date": "2025-06-15", "policy_version": "2024"},
        question="指定2024版本时不应命中2025规则？",
        expected_rule_ids=["BJ_2024_IP_TERT_EMP_001"],
        notes="当前 retrieve 未消费 policy_version 过滤，此用例记录待增强点",
    ))

    # 51–72：用循环批量补充覆盖
    extra_scenarios = [
        ("北京在职职工三级医院住院第1档", "BJ_2024_IP_TERT_EMP_001", ["地区", "人群", "医院等级", "金额分段"]),
        ("北京在职职工三级医院住院第2档", "BJ_2024_IP_TERT_EMP_002", ["金额分段"]),
        ("北京在职职工三级医院住院第3档", "BJ_2024_IP_TERT_EMP_003", ["金额分段"]),
        ("北京在职职工二级医院住院第1档", "BJ_2024_IP_SEC_EMP_001", ["医院等级", "金额分段"]),
        ("北京在职职工二级医院住院第2档", "BJ_2024_IP_SEC_EMP_002", ["医院等级", "金额分段"]),
        ("北京在职职工二级医院住院第3档", "BJ_2024_IP_SEC_EMP_003", ["医院等级", "金额分段"]),
        ("北京退休人员三级医院住院第4档", "BJ_2024_IP_RET_TERT_004", ["人群", "金额分段"]),
        ("北京退休人员三级医院住院第5档", "BJ_2024_IP_RET_TERT_005", ["人群", "金额分段"]),
        ("北京退休人员三级医院住院第6档", "BJ_2024_IP_RET_TERT_006", ["人群", "金额分段"]),
        ("北京退休人员三级医院住院第7档", "BJ_2024_IP_RET_TERT_007", ["人群", "金额分段"]),
        ("北京退休人员三级医院住院第8档", "BJ_2024_IP_RET_TERT_008", ["人群", "金额分段"]),
        ("北京退休人员三级医院住院第9档", "BJ_2024_IP_RET_TERT_009", ["人群", "金额分段"]),
    ]
    for idx, (scn, rule_id, dims) in enumerate(extra_scenarios, 51):
        psn = "退休人员" if "退休" in scn else "在职职工"
        hosp = "二级" if "二级" in scn else "三级"
        cases.append(GoldenCase(
            case_id=f"BULK_{idx:03d}",
            scenario=scn,
            dimensions=dims,
            settlement_context={**base_ctx, "psn_type": psn, "hosp_lv": hosp},
            question=f"{scn}的支付比例？",
            expected_rule_ids=[rule_id],
        ))

    # 73–80：宽泛问题（无结算上下文），用于测试向量/BM25宽召回
    broad_cases = [
        GoldenCase(
            case_id="BROAD_DEDUCTIBLE",
            scenario="宽泛问：北京住院起付线多少",
            dimensions=["宽泛问题"],
            settlement_context={},
            question="北京住院起付线多少？",
            expected_rule_ids=["BJ_2024_DEDUCT_TERT_001"],
            notes="无结算上下文，依赖文本召回+适用性字段精排",
        ),
        GoldenCase(
            case_id="BROAD_CAP",
            scenario="宽泛问：北京医保封顶线",
            dimensions=["宽泛问题"],
            settlement_context={},
            question="北京医保封顶线是多少？",
            expected_rule_ids=["BJ_2024_CAP_001"],
        ),
        GoldenCase(
            case_id="BROAD_RETIREE_RATIO",
            scenario="宽泛问：退休人员住院个人支付比例",
            dimensions=["宽泛问题", "人群"],
            settlement_context={},
            question="退休人员住院个人支付比例是多少？",
            expected_rule_ids=["BJ_2024_IP_RET_FORMULA_001"],
        ),
        GoldenCase(
            case_id="BROAD_REMOTE",
            scenario="宽泛问：异地就医报销比例",
            dimensions=["宽泛问题", "异地/转诊"],
            settlement_context={},
            question="异地就医报销比例是多少？",
            expected_rule_ids=["BJ_2024_IP_REMOTE_001"],
        ),
        GoldenCase(
            case_id="BROAD_OUTPATIENT",
            scenario="宽泛问：门诊报销比例",
            dimensions=["宽泛问题", "医疗类别"],
            settlement_context={},
            question="门诊报销比例是多少？",
            expected_rule_ids=["BJ_2024_OP_TERT_EMP_001"],
        ),
        GoldenCase(
            case_id="BROAD_SHANGHAI",
            scenario="宽泛问：上海住院报销",
            dimensions=["宽泛问题", "地区"],
            settlement_context={},
            question="上海住院报销比例是多少？",
            expected_rule_ids=["SH_2024_IP_TERT_EMP_001"],
        ),
        GoldenCase(
            case_id="BROAD_AMOUNT_BAND",
            scenario="宽泛问：超过3万元至4万元报销比例",
            dimensions=["宽泛问题", "金额分段"],
            settlement_context={},
            question="住院费用超过3万元至4万元报销比例？",
            expected_rule_ids=["BJ_2024_IP_TERT_EMP_002"],
        ),
        GoldenCase(
            case_id="BROAD_VERSION",
            scenario="宽泛问：2025年北京住院新规",
            dimensions=["宽泛问题", "政策版本"],
            settlement_context={},
            question="2025年北京住院有什么新报销政策？",
            expected_rule_ids=["BJ_2025_IP_TERT_EMP_001"],
            notes="无结算日期，无法做时间过滤，可能多版本召回",
        ),
    ]
    cases.extend(broad_cases)

    return cases


# ── 真实语料模式（Issue #33 P0-4）─────────────────────────────────
#
# 范围纪律：仅评门诊 + 通用规则，住院规则排除（issue #33 明确口径）。
_REAL_MED_TYPES = ("门诊-普通门急诊", "门诊-急诊留观", "门诊-一般门特")

# 真实 release collection 的固定 schema 字段（2026-09-02 实测
# policy_rules_REL_20260827_MZ8_V3 describe_collection）：无 region /
# effective_date / expiry_date / publish_status / policy_version / is_remote /
# amount_band_min / amount_band_max。灌入 _FakeMilvusClient 时以此为准，
# 并开启 enable_dynamic_field——Issue #33 修复后 StructuredPolicyRuleRetriever
# 的 _get_collection_fields 会把已知动态键并入可过滤字段，保证 eval 与生产一致。
_REAL_FIXED_FIELDS = {
    "rule_id", "fact_id", "doc_id", "rule_type", "insu_type", "med_type",
    "hosp_lv", "psn_type", "setl_type", "schema_version", "vector",
}


def _load_real_corpus(
    host: str = "127.0.0.1",
    port: str = "19530",
) -> tuple[list[dict[str, Any]], str]:
    """从 Milvus active release 读取真实规则实体（纯只读），按范围纪律过滤。

    返回 (entities, collection_name)。实体保持 FieldTrace 原样（detail 字段
    不解包），与生产 Milvus 返回形态一致——retriever 内部会自行 unpack_detail。
    向量复用 collection 内已落库的 bge 向量，查询侧仍由 embedding provider 编码。
    """
    from src.knowledge_extension.rule_explanation.policy_retrieval.applicability_backfill import (
        MilvusRuleStore,
    )
    from src.knowledge_extension.rule_explanation.release_resolver import (
        resolve_rules_collection,
    )

    collection_name = resolve_rules_collection(host, port)
    store = MilvusRuleStore(host, port, collection_name=collection_name)
    rows = store.list_rules(limit=10000)
    kept = [r for r in rows if (r.get("med_type") or "") in ("",) + _REAL_MED_TYPES]
    return kept, collection_name


def _build_real_golden_cases() -> list[GoldenCase]:
    """真实语料黄金用例集：以 58 条合成用例的问题意图为骨架逐条处理。

    处理方式（全部标注基于 2026-09-02 通读的 351 条真实规则，
    dump 见 scripts/eval/real_corpus_dump.json / real_corpus_listing.txt）：
    - 映射：真实语料中存在对应规则 → 标注真实 expected_rule_ids；
    - 转负例：真实语料无对应规则（住院/上海/异地比例/2025 版等）→ 期望诚实拒答；
    - 跳过：用例考查的机制在真实语料中不存在（region/有效期/版本字段全缺失）。
    """
    from dataclasses import replace

    synthetic = _build_golden_cases()

    # 映射用例：ctx 覆盖 + 真实 expected_rule_ids
    mapped: dict[str, dict[str, Any]] = {
        # 合成原例：北京在职职工三级医院门诊报销比例
        # 真实对应：doc_7173172eb649 门诊统筹分段比例（三级/在职职工）
        "BJ_EMP_TERT_OP": {
            "ctx": {"med_type": "门诊-普通门急诊", "target_amount": 500.0},
            "question": "北京在职职工三级医院门诊报销比例？",
            "expected": ["rule_bd19807063be1fd8", "rule_e04620a0f3dffeb2"],
            "notes": "真实语料门诊比例按金额段拆分（2万以下70% / 2万以上60%），完整答案需两条同时召回；"
                     "语料另有门诊大额互助规则（rule_2003952d3afc 70%），属另一政策维度不计入期望",
        },
        # 合成原例：北京职工住院封顶线
        # 真实对应：职工统筹基金年度最高支付限额 10 万元（med_type 空，通用规则）
        "BJ_CAP": {
            "ctx": {},
            "expected": ["rule_e44e75c149f9"],
            "notes": "rule_e44e75c149f9（10万元）med_type 为空属通用规则，适用住院场景；"
                     "rule_eb4c465e6f2e 仅引用第三十三条无数值，不计入期望",
        },
        # 合成原例：宽泛问北京医保封顶线
        # 真实对应：职工统筹封顶 10 万 + 居民大病封顶 15 万（问题未限定险种，两者均为有效答案）
        "BROAD_CAP": {
            "ctx": {},
            "expected": ["rule_e44e75c149f9", "rule_9da07fdaeaf8"],
            "notes": "问题未限定险种：职工统筹封顶10万与居民大病封顶15万均为有效答案；"
                     "rule_eb4c465e6f2e 无数值不计入",
        },
        # 合成原例：宽泛问门诊报销比例（原期望在职三级门诊70%规则）
        # 真实对应：在职职工门诊统筹 2万以下 70%（rule_74af12a735aef785）
        "BROAD_OUTPATIENT": {
            "ctx": {},
            "expected": ["rule_74af12a735aef785"],
            "notes": "问题未限定人群/险种，语料另有退休及居民门诊比例规则"
                     "（rule_0c31054fbb71 / rule_cda56c7057bb1edd 等），其召回计为 FAR 信号",
        },
    }

    # 跳过用例：考查的机制在真实语料中不存在（适用性字段全缺失）
    skipped: dict[str, str] = {
        "BJ_EMP_TERT_IP_NEAR_EXPIRY": "跳过：语料 effective_date/expiry_date 字段全缺失，时间边界过滤无法评估",
        "BJ_EMP_TERT_IP_EXPIRY_DAY": "跳过：语料 effective_date/expiry_date 字段全缺失，时间边界过滤无法评估",
        "BJ_EMP_TERT_IP_NEW_YEAR": "跳过：语料无有效期字段且无多版本规则，版本切换边界无法评估",
        "BJ_EMP_TERT_IP_DEFAULT_REGION": "跳过：语料 region 字段全缺失（全部为本市政策），默认地区逻辑无法评估",
        "BJ_EMP_TERT_IP_NO_DATE": "跳过：语料无有效期字段，无结算日期场景退化为普通过滤，评测价值低",
        "BJ_EMP_TERT_IP_VERSION_MISMATCH": "跳过：语料 policy_version 字段全缺失，版本过滤机制无法评估",
    }

    # 转负例用例的专属理由（未列出的用通用理由）
    negative_notes: dict[str, str] = {
        "BJ_RET_TERT_IP_FORMULA": "语料无住院退休折算规则（退休规则均为门诊比例/个人账户划入），期望诚实拒答",
        "BJ_EMP_REMOTE": "语料无异地就医支付比例规则（仅居民异地备案/手工报销流程规则），且 is_remote 字段全缺失，期望诚实拒答",
        "BROAD_REMOTE": "语料无异地就医支付比例规则（仅备案/垫付流程规则），期望诚实拒答",
        "BJ_EMP_TERT_IP_2025": "语料无 2025 版规则且无有效期字段，期望诚实拒答",
        "BJ_EMP_TERT_IP_2025_BAND2": "语料无 2025 版规则且无有效期字段，期望诚实拒答",
        "SH_EMP_TERT_IP": "语料全部为本市（北京）政策，无上海规则，期望诚实拒答",
        "SH_EMP_TERT_IP_NO_REGION": "语料无上海规则，期望诚实拒答",
        "BJ_RESIDENT_TERT_IP": "居民住院规则按范围纪律排除，语料仅含居民门诊/通用规则，期望诚实拒答",
        "BJ_DEDUCT_TERT": "语料无住院起付线规则（仅门诊起付线），期望诚实拒答；若召回门诊起付线则暴露医疗类别混淆",
        "BROAD_DEDUCTIBLE": "语料无住院起付线规则（仅门诊起付线），期望诚实拒答；若召回门诊起付线则暴露医疗类别混淆",
        "NEG_EXPIRED_2023": "语料无有效期字段亦无 2023 已废止规则，期望诚实拒答",
        "NEG_FUTURE_2025": "语料无有效期字段亦无 2025 未来规则，期望诚实拒答",
        "NEG_REGION_SH": "语料无上海规则且 region 字段全缺失，期望诚实拒答",
        "NEG_PILOT": "语料 publish_status 字段全缺失、无试点规则，期望诚实拒答",
        "NEG_REMOTE_FALSE": "语料 is_remote 字段全缺失，期望诚实拒答",
        "NEG_POP_STUDENT": "语料无住院规则，学生儿童住院问题期望诚实拒答",
        "NEG_HOSP_PRIMARY": "语料无住院规则，期望诚实拒答",
        "NEG_OUTPATIENT_VS_IP": "语料含大量门诊规则，验证住院场景不误召回门诊规则，期望诚实拒答",
        "NEG_INSU_RESIDENT": "语料同时含职工与居民规则，验证险种隔离：职工上下文不应召回居民规则",
        "NEG_REVOKED": "语料无 publish_status 字段、无已撤销规则，期望诚实拒答",
        "BJ_EMP_TERT_IP_DRAFT": "语料无 publish_status 字段、无草稿规则，期望诚实拒答",
        "BROAD_AMOUNT_BAND": "语料无 3万-4万 住院分段规则（大病保险分段为 5 万档），期望诚实拒答",
        "BROAD_VERSION": "语料无 2025 年规则，期望诚实拒答",
    }
    _default_negative_note = "真实语料按范围纪律仅含门诊+通用规则，无住院分段规则，期望诚实拒答"

    cases: list[GoldenCase] = []
    for c in synthetic:
        if c.case_id in skipped:
            cases.append(replace(c, skip=True, notes=skipped[c.case_id]))
        elif c.case_id in mapped:
            m = mapped[c.case_id]
            cases.append(GoldenCase(
                case_id=c.case_id,
                scenario=c.scenario,
                dimensions=c.dimensions,
                settlement_context={**c.settlement_context, **m.get("ctx", {})},
                question=m.get("question", c.question),
                expected_rule_ids=list(m["expected"]),
                notes=m.get("notes", ""),
                is_negative=False,
            ))
        else:
            cases.append(replace(
                c,
                is_negative=True,
                expected_rule_ids=[],
                notes=negative_notes.get(c.case_id, _default_negative_note),
            ))

    # 覆盖护栏：58 条合成用例必须全部处理，且三种处理方式无交集
    assert len(cases) == len(synthetic), "真实用例集必须与合成用例一一对应"
    overlap = set(mapped) & set(skipped)
    assert not overlap, f"用例同时被映射与跳过: {overlap}"

    # Issue #33 正向用例扩充：在 58 条骨架之外追加真实语料正向用例
    positives = _build_real_positive_cases()
    assert 15 <= len(positives) <= 25, f"正向用例数 {len(positives)} 超出 15-25 目标区间"
    cases.extend(positives)
    return cases


def _build_real_positive_cases() -> list[GoldenCase]:
    """真实语料正向用例（Issue #33 后续）：24 条，覆盖六大主题规则群。

    标注方法：逐条通读 351 条真实规则（scripts/eval/real_corpus_listing.txt），
    按"哪些规则应被召回回答该问题"人工标注 expected_rule_ids：
    - 同事实完全重复对（如 45+ 划入 2% 的两条同文规则）与维度一致的碎片规则
      （source_text 仅 "60%。" 但维度完全匹配）一并计入期望，避免误记 FAR；
    - 维度冲突或仅回答子问题的规则不计入期望，在 notes 写明排除理由；
    - 完整答案需多条时用例 expected 覆盖全部（如退休 2万以下按 70 岁分档）。
    标注只依赖语料内容，不依据任何一次检索结果反推。
    """
    # 通用上下文基线：真实语料全部为本市（北京）政策，region/日期留空
    # （语料无 region/effective_date 字段，填充只会误导读者）
    emp_op: dict[str, Any] = {  # 职工门诊
        "insu_type": _INSU_TYPE, "med_type": "门诊-普通门急诊",
        "hosp_lv": "", "psn_type": "", "region": "", "settlement_date": "",
        "is_remote": False, "target_field": "统筹自付", "target_amount": 0.0,
    }
    res_op = {**emp_op, "insu_type": "城乡居民基本医疗保险"}   # 居民门诊
    dbi = {"insu_type": "大病保险", "med_type": "", "hosp_lv": "", "psn_type": "困难人群",
           "region": "", "settlement_date": "", "is_remote": False,
           "target_field": "大病自付", "target_amount": 0.0}

    def C(case_id: str, scenario: str, topic: str, ctx: dict[str, Any],
          question: str, expected: list[str], notes: str) -> GoldenCase:
        return GoldenCase(
            case_id=case_id, scenario=scenario, dimensions=["真实正向", topic],
            settlement_context=ctx, question=question,
            expected_rule_ids=expected, notes=notes,
        )

    return [
        # ── 主题 1：职工门诊统筹分段与起付线（doc_4bf8d92facc0 / doc_7173172eb649）──
        C("REAL_OP_EMP_DEDUCT", "在职职工门诊起付标准", "门诊起付线",
          {**emp_op, "psn_type": "在职职工", "target_field": "起付线"},
          "在职职工门诊起付标准是多少元？",
          ["rule_8238788ad33d5cb4"],
          "唯一在职门诊起付线规则（1800元），语料无其他在职门诊起付线"),
        C("REAL_OP_RET_DEDUCT", "退休人员门诊起付标准", "门诊起付线",
          {**emp_op, "psn_type": "退休人员", "target_field": "起付线"},
          "退休人员门诊起付标准是多少元？",
          ["rule_bc4c8deba3574b52", "rule_aac09533029c03a5"],
          "两条均为1300元：rule_bc4c8deba3574b52 为退休人员通用表述，"
          "rule_aac09533029c03a5 为70岁以上专项表述（rule_type=deductible），问题未限定年龄两者均应召回"),
        C("REAL_OP_EMP_SEC_BAND1", "在职职工二级医院门诊2万元以下支付比例", "门诊分段",
          {**emp_op, "psn_type": "在职职工", "hosp_lv": "二级", "target_amount": 15000.0},
          "在职职工二级医院门诊，2万元以下部分统筹基金支付比例是多少？",
          ["rule_7f3f6f0c6fd2a758"],
          "二级在职2万以下档唯一无冲突（统筹70%）；一级同档存在 "
          "rule_0412833fee42d9d1/rule_ccc47eef94d825d8/rule_f7226be3f086fdcf 三条冲突值（0.9/0.1/0.3），"
          "属数据质量问题，故选二级档标注"),
        C("REAL_OP_EMP_BAND2", "在职职工门诊超过2万元支付比例", "门诊分段",
          {**emp_op, "psn_type": "在职职工", "target_amount": 25000.0},
          "在职职工门诊费用超过2万元的部分，统筹基金支付比例是多少？",
          ["rule_a9ba270201c559e1", "rule_1b5d162145d9c088"],
          "两条均表述在职2万以上统筹60%；rule_1b5d162145d9c088 为同事实碎片（source_text 仅 \"60%。\"），"
          "维度完全一致计入期望"),
        C("REAL_OP_RET_BAND1", "退休人员门诊2万元以下支付比例", "门诊分段",
          {**emp_op, "psn_type": "退休人员", "target_amount": 15000.0},
          "退休人员门诊2万元以下部分报销比例是多少？",
          ["rule_ca52d442e0eb77f8", "rule_63a423fab0492787"],
          "退休2万以下按年龄分档：70岁以下85%（rule_ca52d442e0eb77f8）+ 70岁以上90%（rule_63a423fab0492787），"
          "完整答案需两条同时召回；医院等级变体（一级90%等）与通用档数值冲突，属数据质量问题不计入"),
        C("REAL_OP_RET_BAND2", "退休人员门诊超过2万元支付比例", "门诊分段",
          {**emp_op, "psn_type": "退休人员", "target_amount": 25000.0},
          "退休人员门诊费用超过2万元的部分报销比例是多少？",
          ["rule_9f08b4ad7e8cf1e2", "rule_31a8f163639447e4"],
          "两条均表述退休2万以上80%；rule_31a8f163639447e4 为同事实碎片（\"80%。\"）计入期望"),
        # ── 主题 2：门诊大额医疗互助（doc_7a1fbf7480d4，2010年调整）──
        C("REAL_LMAA_EMP_COMMUNITY", "在职职工社区门诊大额互助报销比例", "大额互助",
          {**emp_op, "psn_type": "在职职工", "hosp_lv": "一级"},
          "在职职工在社区卫生服务机构门诊，大额医疗互助资金报销比例是多少？",
          ["rule_fe86fd3ef332", "rule_63e89e926492ebd8"],
          "在职社区门诊大额互助90%；rule_63e89e926492ebd8 为同事实碎片（\"90%。\"，"
          "rule_type=large_medical_mutual_aid_payment_ratio）计入期望"),
        C("REAL_LMAA_RET_COMMUNITY", "退休人员社区门诊报销比例", "大额互助",
          {**emp_op, "psn_type": "退休人员", "hosp_lv": "一级"},
          "退休人员在社区卫生服务机构门诊，报销比例是多少？",
          ["rule_bb14031d909f", "rule_4df372b59673556e"],
          "退休社区门诊90%（含大额互助80%+统一补充）；rule_4df372b59673556e 完整复述同一事实计入期望；"
          "80% 组件规则（rule_25721ca05b5d/rule_3222a148156d8c7d）仅回答大额互助子项，不计入"),
        C("REAL_LMAA_NON_COMMUNITY", "在职职工非社区门诊大额互助报销比例", "大额互助",
          {**emp_op, "psn_type": "在职职工"},
          "在职职工在社区以外的定点医疗机构门诊，大额医疗互助报销比例是多少？",
          ["rule_2003952d3afc"],
          "非社区门诊大额互助70%（hosp_lv=无等级）；碎片 rule_69fc18433e6a7364 同为0.7但 hosp_lv 误标一级"
          "（与政策矛盾，一级社区应为90%），属数据冲突不计入"),
        # ── 主题 3：城乡居民大病保险（doc_a73c31a7630e 2019 + doc_7ec146a78b34 倾斜）──
        C("REAL_DBI_DEDUCT", "城乡居民大病保险起付标准", "大病保险",
          {**dbi, "psn_type": "城乡居民", "target_field": "起付线"},
          "城乡居民大病保险的起付标准是多少？",
          ["rule_5c825a5842dc"],
          "2019年起付标准30404元（按上年度城镇居民20%低收入户人均可支配收入），语料唯一起付标准数值规则"),
        C("REAL_DBI_DEDUCT_POOR", "困难人员大病保险起付标准", "大病保险",
          {**dbi, "target_field": "起付线"},
          "低保等困难人员的城乡居民大病保险起付标准是多少？",
          ["rule_dfc997e0e80f"],
          "困难人员起付标准降低一半（15202元），规则自身含数值可直接作答；"
          "基准规则 rule_5c825a5842dc 提供上下文但不直接回答困难标准，不计入"),
        C("REAL_DBI_RATIO_BAND1", "困难人员大病5万元以内支付比例", "大病保险",
          {**dbi, "target_amount": 30000.0},
          "困难人员大病保险，起付标准以上5万元以内的个人自付费用支付比例是多少？",
          ["rule_eabcb26ebdb0"],
          "5万以内档由60%提高至65%（amount_band=0-50000，困难人群），唯一对应规则"),
        C("REAL_DBI_RATIO_BAND2", "困难人员大病超过5万元支付比例", "大病保险",
          {**dbi, "target_amount": 60000.0},
          "困难人员大病保险，超过5万元的个人自付费用支付比例是多少？",
          ["rule_3fdd1238293f"],
          "超过5万档由70%提高至75%（amount_band=50000-，困难人群），唯一对应规则"),
        C("REAL_DBI_TILT_DIBAO", "低保对象大病保险倾斜政策", "大病保险",
          {"insu_type": "城乡居民大病保险", "med_type": "", "hosp_lv": "",
           "psn_type": "低保对象", "region": "", "settlement_date": "",
           "is_remote": False, "target_field": "大病自付", "target_amount": 0.0},
          "低保对象的大病保险有哪些倾斜政策？",
          ["rule_2e052d5d5ec61d3a", "rule_7ae1f61c041b73ff", "rule_af35738965046238"],
          "低保倾斜三件套：起付标准降低50% + 支付比例提高5个百分点 + 取消最高支付限额；"
          "完整答案恰为3条=TOP_K，测试多规则完整召回"),
        # ── 主题 4：城乡居民门诊待遇（doc_ebea08e4d59d 2018办法 + 实施细则）──
        C("REAL_RES_OP_DEDUCT", "城乡居民门诊起付标准", "居民门诊",
          {**res_op, "psn_type": "城乡居民", "target_field": "起付线"},
          "城乡居民医保门诊（急诊）的起付标准是多少？",
          ["rule_844017664834", "rule_b266a6011f26"],
          "一级及以下100元 + 二级及以上550元，同一原文句按医院等级拆成两条，完整答案需同时召回"),
        C("REAL_RES_OP_RATIO", "城乡居民门诊支付比例", "居民门诊",
          {**res_op, "psn_type": "城乡居民"},
          "城乡居民门诊费用超过起付标准后，医保基金支付比例是多少？",
          ["rule_0c31054fbb71", "rule_c0c06ba8a75b"],
          "一级55% + 二级及以上50%（年度累计封顶3000元），同一原文句拆分两条，需同时召回"),
        C("REAL_RES_OP_POOL50", "居民门诊统筹支付比例下限", "居民门诊",
          {**res_op},
          "居民医保门诊统筹支付比例不低于多少？",
          ["rule_cda56c7057bb1edd"],
          "门诊统筹支付比例不低于50%（doc_7ec146a78b34），唯一对应规则；"
          "与 REAL_RES_OP_RATIO 的分段比例属不同政策口径"),
        C("REAL_ER_OBS", "急诊留观费用报销规则", "急诊留观",
          {**res_op, "med_type": "门诊-急诊留观", "psn_type": "城乡居民"},
          "参保人员急诊留观发生的医疗费用如何报销？",
          ["rule_730543a736bd"],
          "急诊留观费用按住院医疗费用报销规定执行，语料唯一急诊留观支付规则"),
        C("REAL_FIRST_DIAG_REFERRAL", "居民门诊基层首诊与转诊规定", "居民门诊",
          {**res_op, "psn_type": "城乡居民", "hosp_lv": "一级", "target_field": "就医流程"},
          "城乡老年人和劳动年龄内居民门诊就医的基层首诊和转诊规定是什么？",
          ["rule_29efc57f99c3", "rule_6497e489c1c4", "rule_eb166c734035"],
          "首诊制度 + 凭首诊转诊证明转诊 + 转诊有效180天，三条构成完整流程；"
          "rule_956cc41cfe44（未经首诊不予支付，排除规则）属后果条款不计入"),
        # ── 主题 5：门诊特殊病种（doc_466953309ccf 实施细则，门特 9 条规则群）──
        C("REAL_MENTE_SCOPE", "城乡居民特殊病种范围", "门特",
          {**res_op, "med_type": "门诊-一般门特", "target_field": "支付范围"},
          "城乡居民基本医疗保险的特殊病种包括哪些？",
          ["rule_d8302ad37c87"],
          "门特病种清单规则（恶性肿瘤门诊治疗/血友病/肾透析等），唯一对应规则"),
        C("REAL_MENTE_PAY", "门特费用支付标准", "门特",
          {**res_op, "med_type": "门诊-一般门特", "psn_type": "城乡居民"},
          "特殊病种门诊医疗费用按什么标准支付？",
          ["rule_b1005f370c2d"],
          "门特费用按住院标准支付，唯一对应规则"),
        C("REAL_MENTE_SETTLE", "门特结算期规则", "门特",
          {**res_op, "med_type": "门诊-一般门特", "target_field": "就医流程"},
          "特殊病种门诊治疗的结算期如何计算？",
          ["rule_e797192073c0", "rule_fbc97f217d2f"],
          "当年备案者自备案首次就医至年度截止 + 一般情形按每保险年度一个结算期，两条互补构成完整答案"),
        # ── 主题 6：个人账户与缴费（doc_1d44e2e1db0c 2001 规定，通用规则）──
        C("REAL_ACCOUNT_45P", "45周岁以上在职职工个人账户划入比例", "个人账户",
          {**emp_op, "med_type": "", "psn_type": "在职职工", "target_field": "个人账户"},
          "45周岁以上的在职职工，个人账户按什么比例划入？",
          ["rule_aa5635596476", "rule_fc5d869d66d5"],
          "45+ 按缴费工资基数2%划入；语料存在 source_text 完全相同的重复对，两者均应视为有效答案"
          "（用于检验召回侧去重/并列行为）"),
        C("REAL_PREMIUM", "职工基本医疗保险缴费比例", "缴费",
          {**emp_op, "med_type": "", "psn_type": "在职职工", "target_field": "缴费"},
          "职工基本医疗保险的缴费比例是多少（个人和单位分别缴多少）？",
          ["rule_0b5fda014f4f", "rule_e74984933d37"],
          "个人按上年月平均工资2% + 单位按缴费工资基数之和9%，两条互补构成完整答案"),
    ]


# ── BM25 纯文本召回 ───────────────────────────────────────────────

class _BM25Retriever:
    def __init__(self, entities: list[dict[str, Any]]) -> None:
        self.entities = entities
        self.k1 = 1.5
        self.b = 0.75
        self._tokenize = self._simple_tokenize
        self.tokenized = [self._tokenize(self._text(e)) for e in entities]
        self.doc_len = [len(t) for t in self.tokenized]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0
        self.idf = self._compute_idf()

    @staticmethod
    def _text(entity: dict[str, Any]) -> str:
        parts = [
            str(entity.get("source_text", "")),
            str(entity.get("rule_type", "")),
            str(entity.get("insu_type", "")),
            str(entity.get("med_type", "")),
            str(entity.get("hosp_lv", "")),
            str(entity.get("psn_type", "")),
            str(entity.get("amount_band", "")),
        ]
        return " ".join(parts)

    @staticmethod
    def _simple_tokenize(text: str) -> list[str]:
        # 中文按字切分，保留连续数字/英文
        tokens: list[str] = []
        i = 0
        text = str(text)
        while i < len(text):
            c = text[i]
            if "\u4e00" <= c <= "\u9fff":
                tokens.append(c)
                i += 1
            elif c.isalnum():
                j = i
                while j < len(text) and text[j].isalnum():
                    j += 1
                tokens.append(text[i:j])
                i = j
            else:
                i += 1
        return tokens

    def _compute_idf(self) -> dict[str, float]:
        df: dict[str, int] = {}
        for tokens in self.tokenized:
            seen = set(tokens)
            for t in seen:
                df[t] = df.get(t, 0) + 1
        n = len(self.tokenized)
        return {t: math.log((n - f + 0.5) / (f + 0.5) + 1.0) for t, f in df.items()}

    def search(self, query: str, top_k: int = TOP_K) -> list[dict[str, Any]]:
        q_tokens = self._tokenize(query)
        scores: list[tuple[int, float]] = []
        for idx, tokens in enumerate(self.tokenized):
            score = 0.0
            for t in q_tokens:
                if t not in self.idf:
                    continue
                f = tokens.count(t)
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[idx] / self.avgdl)
                score += self.idf[t] * f * (self.k1 + 1) / denom
            if score > 0:
                scores.append((idx, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [self.entities[i] for i, _ in scores[:top_k]]


# ── 评估逻辑 ──────────────────────────────────────────────────────

@dataclass
class CaseResult:
    case_id: str
    baseline: str
    retrieved_ids: list[str]
    precision_at_k: float
    recall: float
    far: float
    complete: bool
    honest_refusal: bool | None
    latency_ms: float
    false_ids: list[str] = field(default_factory=list)


@dataclass
class AggregateMetrics:
    baseline: str
    cases: list[CaseResult]
    precision_mean: float = 0.0
    recall_mean: float = 0.0
    far_mean: float = 0.0
    complete_rate: float = 0.0
    honest_refusal_rate: float = 0.0
    field_quality_score: float = 0.0
    p95_latency_ms: float = 0.0

    def compute(self) -> None:
        self.precision_mean = statistics.mean([c.precision_at_k for c in self.cases]) if self.cases else 0.0
        self.recall_mean = statistics.mean([c.recall for c in self.cases]) if self.cases else 0.0
        self.far_mean = statistics.mean([c.far for c in self.cases]) if self.cases else 0.0
        negative = [c for c in self.cases if c.honest_refusal is not None]
        self.honest_refusal_rate = (
            sum(1 for c in negative if c.honest_refusal) / len(negative) if negative else 0.0
        )
        self.complete_rate = sum(1 for c in self.cases if c.complete) / len(self.cases) if self.cases else 0.0
        latencies = [c.latency_ms for c in self.cases]
        self.p95_latency_ms = (
            statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
        ) if latencies else 0.0


def _make_context(ctx_dict: dict[str, Any]) -> NormalizedPolicyContext:
    """从结算上下文字典构造 NormalizedPolicyContext。"""
    def _bool(key: str) -> bool:
        v = ctx_dict.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "是")
        return False

    return NormalizedPolicyContext(
        settlement_id=str(ctx_dict.get("settlement_id", "")),
        insu_type=str(ctx_dict.get("insu_type", "")),
        med_type=str(ctx_dict.get("med_type", "")),
        hosp_lv=str(ctx_dict.get("hosp_lv", "")),
        psn_type=str(ctx_dict.get("psn_type", "")),
        region=str(ctx_dict.get("region", "")),
        settlement_date=str(ctx_dict.get("settlement_date", "")),
        is_remote=_bool("is_remote"),
        target_field=str(ctx_dict.get("target_field", "统筹自付")),
        target_amount=float(ctx_dict.get("target_amount", 0.0)),
    )


def _run_hybrid_case(
    case: GoldenCase,
    retriever: StructuredPolicyRuleRetriever,
    baseline_name: str,
) -> CaseResult:
    ctx = _make_context(case.settlement_context)
    start = time.perf_counter()
    # 抑制 retriever 内部打印，避免淹没评估输出
    with redirect_stdout(io.StringIO()):
        result = retriever.retrieve(ctx, target_field=ctx.target_field)
    latency_ms = (time.perf_counter() - start) * 1000

    retrieved = [e.rule_id for e in result.selected_evidence[:TOP_K]]
    expected = set(case.expected_rule_ids)
    retrieved_set = set(retrieved)
    relevant = expected & retrieved_set
    precision = len(relevant) / len(retrieved) if retrieved else 0.0
    recall = len(relevant) / len(expected) if expected else (0.0 if retrieved else 1.0)
    false_ids = [rid for rid in retrieved if rid not in expected]
    far = len(false_ids) / len(retrieved) if retrieved else 0.0
    complete = expected.issubset(retrieved_set) and not false_ids
    honest = None
    if case.is_negative:
        honest = len(retrieved) == 0

    return CaseResult(
        case_id=case.case_id,
        baseline=baseline_name,
        retrieved_ids=retrieved,
        precision_at_k=precision,
        recall=recall,
        far=far,
        complete=complete,
        honest_refusal=honest,
        latency_ms=latency_ms,
        false_ids=false_ids,
    )


def _run_text_only_case(
    case: GoldenCase,
    bm25: _BM25Retriever,
) -> CaseResult:
    start = time.perf_counter()
    hits = bm25.search(case.question, top_k=TOP_K)
    latency_ms = (time.perf_counter() - start) * 1000

    retrieved = [str(e.get("rule_id", "")) for e in hits]
    expected = set(case.expected_rule_ids)
    retrieved_set = set(retrieved)
    relevant = expected & retrieved_set
    # 适用规则准确率 = 命中规则中确实相关的比例（非固定 K）
    precision = len(relevant) / len(retrieved) if retrieved else 0.0
    recall = len(relevant) / len(expected) if expected else (0.0 if retrieved else 1.0)
    false_ids = [rid for rid in retrieved if rid not in expected]
    far = len(false_ids) / len(retrieved) if retrieved else 0.0
    complete = expected.issubset(retrieved_set) and not false_ids
    honest = None
    if case.is_negative:
        honest = len(retrieved) == 0

    return CaseResult(
        case_id=case.case_id,
        baseline="text_only",
        retrieved_ids=retrieved,
        precision_at_k=precision,
        recall=recall,
        far=far,
        complete=complete,
        honest_refusal=honest,
        latency_ms=latency_ms,
        false_ids=false_ids,
    )


def _run_broad_case(
    case: GoldenCase,
    retriever: BroadPolicyRetriever,
) -> CaseResult:
    """宽泛问题混合检索基线：向量 + BM25 + 适用性字段精排。"""
    start = time.perf_counter()
    with redirect_stdout(io.StringIO()):
        result = retriever.retrieve(
            case.question,
            top_k=TOP_K,
            ctx=InferredQueryContext(
                region=case.settlement_context.get("region", ""),
                reference_date=case.settlement_context.get("settlement_date") or None,
                is_remote=case.settlement_context.get("is_remote")
                if "is_remote" in case.settlement_context
                else None,
                insu_type=case.settlement_context.get("insu_type", ""),
                med_type=case.settlement_context.get("med_type", ""),
                psn_type=case.settlement_context.get("psn_type", ""),
                hosp_lv=case.settlement_context.get("hosp_lv", ""),
            ),
        )
    latency_ms = (time.perf_counter() - start) * 1000

    retrieved = [e.rule_id for e in result.selected_evidence[:TOP_K]]
    expected = set(case.expected_rule_ids)
    retrieved_set = set(retrieved)
    relevant = expected & retrieved_set
    precision = len(relevant) / len(retrieved) if retrieved else 0.0
    recall = len(relevant) / len(expected) if expected else (0.0 if retrieved else 1.0)
    false_ids = [rid for rid in retrieved if rid not in expected]
    far = len(false_ids) / len(retrieved) if retrieved else 0.0
    complete = expected.issubset(retrieved_set) and not false_ids
    honest = None
    if case.is_negative:
        honest = len(retrieved) == 0

    return CaseResult(
        case_id=case.case_id,
        baseline="broad_hybrid",
        retrieved_ids=retrieved,
        precision_at_k=precision,
        recall=recall,
        far=far,
        complete=complete,
        honest_refusal=honest,
        latency_ms=latency_ms,
        false_ids=false_ids,
    )


def _field_quality(entities: list[dict[str, Any]]) -> float:
    """简单字段质量分：region/publish_status/effective_date/expiry_date/policy_version 非空比例。"""
    if not entities:
        return 0.0
    fields = ["region", "publish_status", "effective_date", "expiry_date", "policy_version"]
    scores = []
    for e in entities:
        scores.append(sum(1 for f in fields if e.get(f)) / len(fields))
    return statistics.mean(scores)


# ── 报告生成 ──────────────────────────────────────────────────────

def _fmt_float(v: float) -> str:
    return f"{v*100:.1f}%" if isinstance(v, float) else str(v)


def _write_golden_cases(
    cases: list[GoldenCase],
    filename: str = "2026-09-01-issue25-golden-cases.md",
    title: str = "# Issue #25 黄金用例集",
) -> None:
    lines = [
        title,
        "",
        f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"> 用例总数：{len(cases)} 条",
        "> 覆盖维度：地区、政策时间、人群、医疗类别、医院等级、异地/转诊、金额分段、政策替代、宽泛问题",
        "",
        "## 标注口径",
        "",
        "1. **期望规则（expected_rule_ids）**：由人工根据结算上下文与政策文本判定必须召回的规则 rule_id。",
        "2. **负例**：`is_negative=True` 表示该场景下不应召回任何规则；命中即视为错误适用。",
        "3. **结算上下文**：包含 `insu_type`/`med_type`/`hosp_lv`/`psn_type`/`region`/`settlement_date`/`is_remote`。",
        "4. **默认地区**：当 `region` 为空时，系统默认使用北京。",
        "5. **默认时间**：当 `settlement_date` 为空时，不过滤有效期。",
        "6. **宽泛问题**：无结算上下文，仅依赖自然语言问题；用于测试文本召回+适用性字段精排。",
        "7. **跳过**（仅真实语料模式）：`skip=True` 表示该用例考查的机制在真实语料中不存在，不计入指标。",
        "8. **真实正向用例**（仅真实语料模式）：`REAL_*` 前缀用例为基于真实规则全文通读标注的正向用例，"
        "notes 含标注依据（重复对/碎片/冲突规则的计入与排除理由），标注不依据检索结果反推。",
        "",
        "## 用例列表",
        "",
        "| 编号 | 场景 | 维度 | 地区 | 结算日期 | 期望规则数 | 负例 | 备注 |",
        "|------|------|------|------|----------|------------|------|------|",
    ]
    for c in cases:
        dims = ",".join(c.dimensions)
        region = c.settlement_context.get("region", "")
        date = c.settlement_context.get("settlement_date", "")
        flag = "跳过" if c.skip else ("是" if c.is_negative else "否")
        lines.append(
            f"| {c.case_id} | {c.scenario} | {dims} | {region} | {date} | "
            f"{len(c.expected_rule_ids)} | {flag} | {c.notes} |"
        )
    lines.append("")
    lines.append("## 用例原始数据")
    lines.append("")
    lines.append("```json")
    serializable = []
    for c in cases:
        serializable.append({
            "case_id": c.case_id,
            "scenario": c.scenario,
            "dimensions": c.dimensions,
            "settlement_context": c.settlement_context,
            "question": c.question,
            "expected_rule_ids": c.expected_rule_ids,
            "is_negative": c.is_negative,
            "skip": c.skip,
            "notes": c.notes,
        })
    lines.append(json.dumps(serializable, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    path = REVIEW_DIR / filename
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[eval] wrote {path}")


def _write_assessment_report(
    cases: list[GoldenCase],
    text_metrics: AggregateMetrics,
    current_metrics: AggregateMetrics,
    enhanced_metrics: AggregateMetrics,
    broad_metrics: AggregateMetrics,
    corpus: list[dict[str, Any]],
) -> None:
    lines = [
        "# Issue #25 结构化索引与最小混合检索评估报告",
        "",
        f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"> 数据集：{len(corpus)} 条模拟 policy_rules_v2 规则，{len(cases)} 条黄金用例",
        f"> Top-K：{TOP_K}",
        f"> Embedding：真实 bge-base-zh-v1.5（默认）或 hash 向量（--embedding-kind=hash）",
        "",
        "## 执行摘要",
        "",
        "本次评估在内存模拟的 `policy_rules_v2` 集合上，对跑四条基线：",
        "- **text_only**：BM25 纯文本召回，无结构化过滤；",
        "- **current_hybrid**：`StructuredPolicyRuleRetriever` 关闭适用性字段（仅 core 维度 + source_text 关键词），代表 Issue #25 改造前的生产路径；",
        "- **enhanced_hybrid**：`StructuredPolicyRuleRetriever` 启用新增适用性字段（region / effective_date / expiry_date / publish_status / policy_version / is_remote）；",
        "- **broad_hybrid**：`BroadPolicyRetriever` 向量语义召回 + rank-bm25 + 适用性字段精排，覆盖宽泛问题与结算单场景。",
        "",
        "核心结论：",
        f"- 补强适用性字段后，适用规则准确率从 {_fmt_float(current_metrics.precision_mean)} 提升至 {_fmt_float(enhanced_metrics.precision_mean)}，",
        f"  证据召回率从 {_fmt_float(current_metrics.recall_mean)} 提升至 {_fmt_float(enhanced_metrics.recall_mean)}。",
        f"- 错误适用规则率（FAR）从 {_fmt_float(current_metrics.far_mean)} 降至 {_fmt_float(enhanced_metrics.far_mean)}。",
        f"- 宽泛问题混合检索（broad_hybrid）适用规则准确率 {_fmt_float(broad_metrics.precision_mean)}，证据召回率 {_fmt_float(broad_metrics.recall_mean)}，FAR {_fmt_float(broad_metrics.far_mean)}。",
        f"- 完整回答率：enhanced {_fmt_float(enhanced_metrics.complete_rate)} / broad {_fmt_float(broad_metrics.complete_rate)}；诚实拒答率：enhanced {_fmt_float(enhanced_metrics.honest_refusal_rate)} / broad {_fmt_float(broad_metrics.honest_refusal_rate)}。",
        f"- P95 时延：text_only {text_metrics.p95_latency_ms:.2f}ms / current {current_metrics.p95_latency_ms:.2f}ms / enhanced {enhanced_metrics.p95_latency_ms:.2f}ms / broad {broad_metrics.p95_latency_ms:.2f}ms。",
        "",
        "> ⚠️ 本评估使用合成语料与内存 Milvus，真实生产数据上的绝对数值会有差异；相对差异和字段效用结论可复现。",
        "",
        "## 核心指标",
        "",
        "| 基线 | 适用规则准确率 | 证据召回率 | FAR | 完整回答率 | 诚实拒答率 | 字段质量 | P95 时延(ms) |",
        "|------|----------------|------------|-----|------------|------------|----------|--------------|",
    ]

    def row(m: AggregateMetrics) -> str:
        return (
            f"| {m.baseline} | {_fmt_float(m.precision_mean)} | {_fmt_float(m.recall_mean)} | "
            f"{_fmt_float(m.far_mean)} | {_fmt_float(m.complete_rate)} | "
            f"{_fmt_float(m.honest_refusal_rate)} | {_fmt_float(m.field_quality_score)} | "
            f"{m.p95_latency_ms:.2f} |"
        )

    lines.append(row(text_metrics))
    lines.append(row(current_metrics))
    lines.append(row(enhanced_metrics))
    lines.append(row(broad_metrics))
    lines.append("")

    # 逐案差异样例
    lines.append("## 逐案差异样例")
    lines.append("")
    lines.append("以下选取 10 条差异最大的用例展示四条基线的召回结果。")
    lines.append("")
    lines.append("| 用例 | 场景 | text_only | current_hybrid | enhanced_hybrid | broad_hybrid | 说明 |")
    lines.append("|------|------|-----------|----------------|-----------------|--------------|------|")

    # 以 enhanced 与 current 的 P@K 差值排序
    diff_cases = []
    current_by_id = {c.case_id: c for c in current_metrics.cases}
    enhanced_by_id = {c.case_id: c for c in enhanced_metrics.cases}
    text_by_id = {c.case_id: c for c in text_metrics.cases}
    broad_by_id = {c.case_id: c for c in broad_metrics.cases}
    for c in cases:
        cur = current_by_id[c.case_id]
        enh = enhanced_by_id[c.case_id]
        diff = enh.precision_at_k - cur.precision_at_k
        diff_cases.append((diff, c))
    diff_cases.sort(key=lambda x: x[0], reverse=True)

    for _, c in diff_cases[:10]:
        t = text_by_id[c.case_id]
        cur = current_by_id[c.case_id]
        enh = enhanced_by_id[c.case_id]
        brd = broad_by_id[c.case_id]
        lines.append(
            f"| {c.case_id} | {c.scenario} | {t.retrieved_ids} | {cur.retrieved_ids} | "
            f"{enh.retrieved_ids} | {brd.retrieved_ids} | {c.notes or '-'} |"
        )
    lines.append("")

    # 字段分类清单
    lines.append("## 字段分类清单")
    lines.append("")
    lines.append("基于本次评估结论，对新增及候选字段做如下分类：")
    lines.append("")
    lines.append("| 字段 | 分类 | 理由 | 运行时消费方式 |")
    lines.append("|------|------|------|----------------|")
    lines.append("| `region` | **必须结构化+物理索引** | 地区是最高频过滤条件；跨地区规则混排会直接导致错误适用 | 默认值北京；结算上下文传入；Milvus 标量过滤 |")
    lines.append("| `effective_date` / `expiry_date` | **必须结构化+物理索引** | 时间有效性过滤可消除过期/未来规则误召回 | 结算日期传入；范围查询 `[effective_date, expiry_date]` |")
    lines.append("| `publish_status` | **必须结构化+物理索引** | 区分 published/draft/revoked/pilot，防止 Runtime 消费未发布规则 | 默认过滤 `published`；管理态可显式查询 pilot |")
    lines.append("| `is_remote` | **必须结构化+物理索引** | 本地/异地规则差异显著；默认本地，异地场景显式过滤 | 结算上下文传入；bool 标量过滤 |")
    lines.append("| `policy_version` | **必须结构化+仅存储（优先）** | 用于溯源、冲突展示与人工选择；当前评估未做运行时过滤（结算上下文通常不直接指定版本） | 入固定 schema 建标量索引；详情页/证据卡展示；未来若业务需要可按版本过滤 |")
    lines.append("| `amount_band` 数值边界 | **建议结构化（后续阶段）** | 当前为文本，金额段比较依赖字符串匹配；精确到段内金额需数值化 | 暂不进入本阶段；后续评估是否需要范围索引 |")
    lines.append("| `referral_type` 转诊类型 | **仅候选，待需求确认** | 当前用例中异地/转诊差异可用 `is_remote` 区分；更细转诊类型（跨省/省内/急诊）暂无高频证据 | 不进入本阶段 |")
    lines.append("")

    # 运行时消费方案
    lines.append("## 地区 / 有效期 / 发布状态 / 政策版本的运行时消费方案")
    lines.append("")
    lines.append("### 1. 地区（region）")
    lines.append("- 默认值：结算上下文未提供时，使用 `北京`。")
    lines.append("- 过滤：每条查询注入 `region == ctx.region`，保证不召回其他地区规则。")
    lines.append("- 不确定时：若地区无法推断，应声明不确定性，而非默认全国。")
    lines.append("")
    lines.append("### 2. 有效期（effective_date / expiry_date）")
    lines.append("- 输入：`settlement_date` 由结算上下文提供，格式 `YYYY-MM-DD`。")
    lines.append("- 过滤：`effective_date <= settlement_date <= expiry_date`，其中 `9999-12-31` 表示长期有效。")
    lines.append("- 缺省：`settlement_date` 为空时不过滤时间，避免误伤。")
    lines.append("")
    lines.append("### 3. 发布状态（publish_status）")
    lines.append("- Runtime 默认只消费 `published`。")
    lines.append("- `draft` 仅在治理/测试环境显式查询；`revoked` 不得进入 Runtime；`pilot` 需白名单地区才放行。")
    lines.append("")
    lines.append("### 4. 政策版本（policy_version）")
    lines.append("- 当前 Runtime 不过滤版本，而是按有效期自然选择生效规则。")
    lines.append("- 版本字段用于证据卡展示、冲突提示与人工审核；当同一有效期内存在多版本冲突时，触发 `waiting_human_confirmation`。")
    lines.append("")

    # 层级索引 / 知识图谱结论
    lines.append("## 层级索引与知识图谱结论")
    lines.append("")
    lines.append("### 证据化结论")
    lines.append("- **暂不建立层级索引**：当前政策问答以单条规则适用性判断为主，`doc_id`/`clause_id` 已能支撑政策→条款→规则的溯源路径；层级索引的额外收益在本次 80 条用例中未形成可量化提升。")
    lines.append("- **暂不引入知识图谱**：人群折算（退休=职工×60%）已通过 `rule_derivation.derive_personal_payment_ratios` 在入库阶段物化为派生规则；跨规则引用（如封顶线、调整方案）通过 `doc_id`/`clause_id` 与原文证据即可满足当前 QA 场景的溯源需求。")
    lines.append("- **触发条件**：若未来出现以下场景，再评估层级索引/知识图谱：")
    lines.append("  1. 多跳推理需求（如‘甲药在乙病种的报销比例受丙目录限制’）；")
    lines.append("  2. 政策替代/废止链复杂到无法通过时间范围过滤处理；")
    lines.append("  3. 地区/险种/年度组合爆炸，标量索引过滤后仍需关系推理。")
    lines.append("")

    # 不确定性声明
    lines.append("## 不确定性声明")
    lines.append("")
    lines.append("- 本评估语料为合成数据，真实生产中的字段分布、文本表达、规则冲突密度可能不同。")
    lines.append("- `policy_version` 未做运行时过滤，仅用于展示；若业务需要按版本强过滤，需额外设计。")
    lines.append("- broad_hybrid 基线默认使用真实 bge-base-zh-v1.5 编码 source_text；在真实 policy_rules_v2 上的绝对数值可能不同，本报告结论侧重相对差异与实现可复现性。")
    lines.append("")

    # 阶段 2 实施计划
    lines.append("## 阶段 2 最小可验证实施计划")
    lines.append("")
    lines.append("在 MVP 阶段 1（schema 设计 + 检索层消费）完成后，建议按以下步骤推进：")
    lines.append("")
    lines.append("1. **存量回填流水线**：基于 `rule_to_entity` 默认值机制，对现有 `policy_rules_v2` 规则回填 `region`/`effective_date`/`expiry_date`/`publish_status`/`policy_version`/`is_remote`；回填值在知识审核页以‘提议者-审核者’模式展示，人工确认后发布。")
    lines.append("2. **适用性字段质量门禁**：在知识发布/变更集 promote 时，校验所有 published 规则必须包含非空 `region`、`effective_date`、`expiry_date`、`publish_status`；缺失则阻断发布并生成 DecisionTask。")
    lines.append("3. **宽泛问题混合检索路径**：✅ 已完成。`BroadPolicyRetriever` 使用真实 bge 向量 + rank-bm25 + 适用性字段精排；`/policy-qa/stream` 在 `settlement_id` 缺失时自动切换至此路径。")
    lines.append("4. **指标看板**：在 policy-knowledge 测试页增加 Issue #25 专项指标卡（FAR、P@3、诚实拒答率、字段完整率），每轮候选版本发布前自动对跑。")
    lines.append("5. **生产灰度**：先对北京地区住院/门诊规则启用新字段过滤，观察一周后扩展至其他地区；回滚开关为 `enable_applicability_fields=False`。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("[来源: docs/steering/政策知识治理-需求迭代记录.md §Issue 25]")
    lines.append("")

    path = REVIEW_DIR / "2026-09-01-issue25-structured-index-assessment.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[eval] wrote {path}")


# ── 可调用评估核心（供后端 /policy-workbench/quality/issue25-metrics 复用）──

def run_issue25_evaluation(
    embedding_kind: str = "sentence_transformer",
    broad_only: bool = False,
    corpus_kind: str = "synthetic",
    milvus_host: str = "127.0.0.1",
    milvus_port: str = "19530",
) -> dict[str, Any]:
    """运行 Issue #25 评估，返回结构化指标（不写 markdown 报告）。

    corpus_kind="real"（Issue #33 P0-4）：从 Milvus active release 只读加载
    真实门诊+通用规则（含库内向量），灌入 _FakeMilvusClient 后走同一评估流程；
    describe_collection 按真实固定 schema 字段返回并开启 dynamic field，
    适用性过滤行为与生产一致（Issue #33 修复后动态键可过滤）。
    """
    if embedding_kind == "sentence_transformer":
        embedding_provider = get_embedding_provider("sentence_transformer")
    elif embedding_kind == "hash":
        embedding_provider = HashEmbeddingProvider(dim=POLICY_RULES_V2_VECTOR_DIM)
    else:
        raise ValueError(f"unsupported embedding_kind: {embedding_kind}")

    real_collection_name = ""
    if corpus_kind == "real":
        corpus, real_collection_name = _load_real_corpus(milvus_host, milvus_port)
        # 真实 collection 固定 schema 无 Issue #25 适用性字段（以 dynamic key 存储），
        # full/old 两个逻辑集合字段集一致，current_hybrid 与 enhanced_hybrid
        # 退化为同一行为（忠实复现生产）
        all_fields = set(_REAL_FIXED_FIELDS)
        old_fields = set(_REAL_FIXED_FIELDS)
        # 真实 release collection 开启 dynamic field（Issue #33 修复依赖）
        real_dynamic = True
    else:
        corpus = _build_corpus(embedding_provider)
        # 注册 fake Milvus 集合：full 含所有新字段；old 缺少新字段，用于 current_hybrid 基线
        all_fields = set(corpus[0].keys())
        old_fields = all_fields - {
            "region", "effective_date", "expiry_date", "publish_status",
            "policy_version", "is_remote",
        }
        # 合成语料固定 schema 已含适用性字段，无需 dynamic field
        real_dynamic = False

    fake = _FakeMilvusClient()
    fake.register_collection(
        COLLECTION_FULL, corpus, all_fields, enable_dynamic_field=real_dynamic
    )
    fake.register_collection(
        COLLECTION_OLD, corpus, old_fields, enable_dynamic_field=real_dynamic
    )
    _patch_milvus_client(fake)
    _patch_broad_milvus_client(fake)

    if corpus_kind == "real":
        all_cases = _build_real_golden_cases()
        # 标注护栏：期望 rule_id 必须真实存在于语料中，禁止臆造
        corpus_ids = {str(e.get("rule_id", "")) for e in corpus}
        unknown = sorted({
            rid for c in all_cases if not c.skip for rid in c.expected_rule_ids
        } - corpus_ids)
        if unknown:
            raise ValueError(f"真实用例期望了语料中不存在的 rule_id: {unknown}")
        skipped_cases = [c for c in all_cases if c.skip]
        cases = [c for c in all_cases if not c.skip]
    else:
        all_cases = _build_golden_cases()
        skipped_cases = []
        cases = all_cases
    if broad_only:
        cases = [c for c in cases if "宽泛问题" in c.dimensions]

    bm25 = _BM25Retriever(corpus)

    # text_only
    text_results = [_run_text_only_case(c, bm25) for c in cases]
    text_metrics = AggregateMetrics(baseline="text_only", cases=text_results)
    text_metrics.compute()

    # current_hybrid：关闭适用性字段，使用 old collection
    current_results: list[CaseResult] = []
    for c in cases:
        retriever = StructuredPolicyRuleRetriever(
            collection_name=COLLECTION_OLD,
            enable_applicability_fields=False,
        )
        current_results.append(_run_hybrid_case(c, retriever, "current_hybrid"))
    current_metrics = AggregateMetrics(baseline="current_hybrid", cases=current_results)
    current_metrics.compute()

    # enhanced_hybrid：启用适用性字段，使用 full collection
    enhanced_results: list[CaseResult] = []
    for c in cases:
        retriever = StructuredPolicyRuleRetriever(
            collection_name=COLLECTION_FULL,
            enable_applicability_fields=True,
        )
        enhanced_results.append(_run_hybrid_case(c, retriever, "enhanced_hybrid"))
    enhanced_metrics = AggregateMetrics(baseline="enhanced_hybrid", cases=enhanced_results)
    enhanced_metrics.field_quality_score = _field_quality(corpus)
    enhanced_metrics.compute()

    # broad_hybrid：向量 + BM25 + 适用性字段精排
    broad_results: list[CaseResult] = []
    broad_retriever = BroadPolicyRetriever(
        collection_name=COLLECTION_FULL,
        embedding_provider=embedding_provider,
    )
    for c in cases:
        broad_results.append(_run_broad_case(c, broad_retriever))
    broad_metrics = AggregateMetrics(baseline="broad_hybrid", cases=broad_results)
    broad_metrics.compute()

    def _metrics_dict(m: AggregateMetrics) -> dict[str, float]:
        return {
            "precision_at_k": m.precision_mean,
            "recall": m.recall_mean,
            "far": m.far_mean,
            "complete_rate": m.complete_rate,
            "honest_refusal_rate": m.honest_refusal_rate,
            "p95_latency_ms": m.p95_latency_ms,
        }

    # 取差异最大的 5 条用例
    current_by_id = {c.case_id: c for c in current_metrics.cases}
    enhanced_by_id = {c.case_id: c for c in enhanced_metrics.cases}
    diff_cases = []
    for c in cases:
        cur = current_by_id[c.case_id]
        enh = enhanced_by_id[c.case_id]
        diff_cases.append({
            "case_id": c.case_id,
            "scenario": c.scenario,
            "precision_diff": enh.precision_at_k - cur.precision_at_k,
            "recall_diff": enh.recall - cur.recall,
            "current_retrieved": cur.retrieved_ids,
            "enhanced_retrieved": enh.retrieved_ids,
        })
    diff_cases.sort(key=lambda x: abs(x["precision_diff"]) + abs(x["recall_diff"]), reverse=True)

    def _case_dict(c: CaseResult) -> dict[str, Any]:
        return {
            "case_id": c.case_id,
            "retrieved_ids": c.retrieved_ids,
            "precision_at_k": c.precision_at_k,
            "recall": c.recall,
            "far": c.far,
            "complete": c.complete,
            "honest_refusal": c.honest_refusal,
            "false_ids": c.false_ids,
        }

    return {
        "embedding_kind": embedding_kind,
        "corpus_kind": corpus_kind,
        "real_collection_name": real_collection_name,
        "corpus_size": len(corpus),
        "case_count": len(cases),
        "case_disposition": {
            "mapped": sum(1 for c in all_cases if c.expected_rule_ids and not c.skip),
            "negative": sum(1 for c in all_cases if c.is_negative and not c.skip),
            "skipped": len(skipped_cases),
            "skipped_ids": [c.case_id for c in skipped_cases],
        },
        "text_only": _metrics_dict(text_metrics),
        "current_hybrid": _metrics_dict(current_metrics),
        "enhanced_hybrid": _metrics_dict(enhanced_metrics),
        "broad_hybrid": _metrics_dict(broad_metrics),
        "field_quality_score": enhanced_metrics.field_quality_score,
        "top_diff_cases": diff_cases[:5],
        "per_case": {
            "text_only": [_case_dict(c) for c in text_metrics.cases],
            "current_hybrid": [_case_dict(c) for c in current_metrics.cases],
            "enhanced_hybrid": [_case_dict(c) for c in enhanced_metrics.cases],
            "broad_hybrid": [_case_dict(c) for c in broad_metrics.cases],
        },
    }


# ── 主流程 ────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Issue #25 最小混合检索评估")
    parser.add_argument(
        "--embedding-kind",
        choices=["sentence_transformer", "hash"],
        default="sentence_transformer",
        help="embedding provider 类型：sentence_transformer 使用真实 bge 模型，hash 用于快速回归",
    )
    parser.add_argument(
        "--broad-only",
        action="store_true",
        help="仅运行宽泛问题子集与 broad_hybrid 基线",
    )
    parser.add_argument(
        "--corpus",
        choices=["synthetic", "real"],
        default="synthetic",
        help="语料来源：synthetic 为合成语料（行为与 Issue #25 一致）；"
             "real 从 Milvus active release 只读加载真实门诊+通用规则（Issue #33 P0-4）",
    )
    parser.add_argument("--milvus-host", default="127.0.0.1", help="真实语料模式的 Milvus 主机")
    parser.add_argument("--milvus-port", default="19530", help="真实语料模式的 Milvus 端口")
    args = parser.parse_args()

    print(f"[eval] embedding_kind={args.embedding_kind} corpus={args.corpus}")
    result = run_issue25_evaluation(
        embedding_kind=args.embedding_kind,
        broad_only=args.broad_only,
        corpus_kind=args.corpus,
        milvus_host=args.milvus_host,
        milvus_port=args.milvus_port,
    )

    if args.corpus == "real":
        # 真实语料模式：写真实黄金用例文档 + 逐案 JSON 结果（供基线报告引用），
        # 不写 Issue #25 合成评估报告
        _write_golden_cases(
            _build_real_golden_cases(),
            filename="2026-09-02-issue33-real-golden-cases.md",
            title="# Issue #33 真实语料黄金用例集（门诊+通用规则）",
        )
        result_path = Path(__file__).resolve().parent / "issue33_real_baseline_result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[eval] wrote {result_path}")
        print(f"[eval] done (corpus=real, collection={result['real_collection_name']}, "
              f"corpus_size={result['corpus_size']})")
        for name in ("text_only", "current_hybrid", "enhanced_hybrid", "broad_hybrid"):
            m = result[name]
            print(
                f"  {name:16s} P@K={m['precision_at_k']:.3f} Recall={m['recall']:.3f} "
                f"FAR={m['far']:.3f} Complete={m['complete_rate']:.3f} "
                f"Honest={m['honest_refusal_rate']:.3f}"
            )
        d = result["case_disposition"]
        print(f"  cases: mapped={d['mapped']} negative={d['negative']} skipped={d['skipped']}")
        return

    _write_golden_cases(_build_golden_cases())
    # 重新跑一遍以生成报告所需对象；评估较快，可接受
    embedding_provider = (
        get_embedding_provider("sentence_transformer")
        if args.embedding_kind == "sentence_transformer"
        else HashEmbeddingProvider(dim=POLICY_RULES_V2_VECTOR_DIM)
    )
    corpus = _build_corpus(embedding_provider)
    all_fields = set(corpus[0].keys())
    old_fields = all_fields - {
        "region", "effective_date", "expiry_date", "publish_status",
        "policy_version", "is_remote",
    }
    fake = _FakeMilvusClient()
    fake.register_collection(COLLECTION_FULL, corpus, all_fields)
    fake.register_collection(COLLECTION_OLD, corpus, old_fields)
    _patch_milvus_client(fake)
    _patch_broad_milvus_client(fake)

    cases = _build_golden_cases()
    if args.broad_only:
        cases = [c for c in cases if "宽泛问题" in c.dimensions]
    bm25 = _BM25Retriever(corpus)

    text_results = [_run_text_only_case(c, bm25) for c in cases]
    text_metrics = AggregateMetrics(baseline="text_only", cases=text_results)
    text_metrics.compute()

    current_results = []
    for c in cases:
        retriever = StructuredPolicyRuleRetriever(
            collection_name=COLLECTION_OLD,
            enable_applicability_fields=False,
        )
        current_results.append(_run_hybrid_case(c, retriever, "current_hybrid"))
    current_metrics = AggregateMetrics(baseline="current_hybrid", cases=current_results)
    current_metrics.compute()

    enhanced_results = []
    for c in cases:
        retriever = StructuredPolicyRuleRetriever(
            collection_name=COLLECTION_FULL,
            enable_applicability_fields=True,
        )
        enhanced_results.append(_run_hybrid_case(c, retriever, "enhanced_hybrid"))
    enhanced_metrics = AggregateMetrics(baseline="enhanced_hybrid", cases=enhanced_results)
    enhanced_metrics.field_quality_score = _field_quality(corpus)
    enhanced_metrics.compute()

    broad_results = []
    broad_retriever = BroadPolicyRetriever(
        collection_name=COLLECTION_FULL,
        embedding_provider=embedding_provider,
    )
    for c in cases:
        broad_results.append(_run_broad_case(c, broad_retriever))
    broad_metrics = AggregateMetrics(baseline="broad_hybrid", cases=broad_results)
    broad_metrics.compute()

    _write_assessment_report(
        cases, text_metrics, current_metrics, enhanced_metrics, broad_metrics, corpus
    )

    print("[eval] done")
    print(f"  text_only      Precision={text_metrics.precision_mean:.3f} Recall={text_metrics.recall_mean:.3f} FAR={text_metrics.far_mean:.3f}")
    print(f"  current_hybrid Precision={current_metrics.precision_mean:.3f} Recall={current_metrics.recall_mean:.3f} FAR={current_metrics.far_mean:.3f}")
    print(f"  enhanced_hybrid Precision={enhanced_metrics.precision_mean:.3f} Recall={enhanced_metrics.recall_mean:.3f} FAR={enhanced_metrics.far_mean:.3f}")
    print(f"  broad_hybrid   Precision={broad_metrics.precision_mean:.3f} Recall={broad_metrics.recall_mean:.3f} FAR={broad_metrics.far_mean:.3f}")


if __name__ == "__main__":
    main()
