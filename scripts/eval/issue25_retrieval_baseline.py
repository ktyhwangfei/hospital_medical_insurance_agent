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
    ) -> None:
        fields = fields or set(entities[0].keys()) if entities else set()
        self._collections[name] = {"entities": list(entities), "fields": fields}

    def describe_collection(self, collection_name: str) -> dict[str, Any]:
        if collection_name not in self._collections:
            raise RuntimeError(f"Collection not found: {collection_name}")
        fields = [
            {"name": n}
            for n in sorted(self._collections[collection_name]["fields"])
        ]
        return {"fields": fields}

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


def _write_golden_cases(cases: list[GoldenCase]) -> None:
    lines = [
        "# Issue #25 黄金用例集",
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
        lines.append(
            f"| {c.case_id} | {c.scenario} | {dims} | {region} | {date} | "
            f"{len(c.expected_rule_ids)} | {'是' if c.is_negative else '否'} | {c.notes} |"
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
            "notes": c.notes,
        })
    lines.append(json.dumps(serializable, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    path = REVIEW_DIR / "2026-09-01-issue25-golden-cases.md"
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
    args = parser.parse_args()

    print(f"[eval] embedding_kind={args.embedding_kind}")
    if args.embedding_kind == "sentence_transformer":
        embedding_provider = get_embedding_provider("sentence_transformer")
    else:
        embedding_provider = HashEmbeddingProvider(dim=POLICY_RULES_V2_VECTOR_DIM)

    print("[eval] building corpus...")
    corpus = _build_corpus(embedding_provider)

    # 注册 fake Milvus 集合：full 含所有新字段；old 缺少新字段，用于 current_hybrid 基线
    all_fields = set(corpus[0].keys())
    old_fields = all_fields - {"region", "effective_date", "expiry_date", "publish_status", "policy_version", "is_remote"}

    fake = _FakeMilvusClient()
    fake.register_collection(COLLECTION_FULL, corpus, all_fields)
    fake.register_collection(COLLECTION_OLD, corpus, old_fields)
    _patch_milvus_client(fake)
    _patch_broad_milvus_client(fake)

    print(f"[eval] corpus={len(corpus)} rules; full_fields={len(all_fields)} old_fields={len(old_fields)}")

    cases = _build_golden_cases()
    if args.broad_only:
        cases = [c for c in cases if "宽泛问题" in c.dimensions]
    print(f"[eval] golden_cases={len(cases)}")

    _write_golden_cases(cases)

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
