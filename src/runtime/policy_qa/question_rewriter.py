"""
医保政策问答RAG系统 - 问题重写

基于SQL结果+意图上下文，将用户口语化问题改写为精准的政策检索查询。
核心目标：让向量搜索能命中正确的政策条文，而不是简单的上下文拼接。

示例：
  用户: "为什么我这次统筹自付这么多？"
  SQL补充: 城镇职工 + 住院 + 退休 + 三级医院
  改写: "城镇职工退休人员在三级医院住院的统筹分段自付比例"
"""

from __future__ import annotations

import re
import logging
from typing import Any

from src.runtime.policy_qa.models import RewrittenQuestion, SQLQueryResult, PolicyQAIntent
from src.runtime.policy_qa.dictionary_normalizer import get_normalizer

logger = logging.getLogger(__name__)

# 费用类型关键词映射
FEE_TYPE_KEYWORDS = {
    "统筹自付": "bdtczf",
    "统筹支付": "bdtczfje",
    "大额支付": "bddegwyzfje",
    "大额自付": "bddegwyzf",
    "个人应负": "bdgryf",
    "起付线": "bcqfje",
    "医保内": "bdybnzje",
    "医保外": "ybwje",
    "总费用": "bdfyzje",
}

# 意图→检索关键词映射：根据用户意图生成精准的检索查询
INTENT_SEARCH_KEYWORDS = {
    PolicyQAIntent.FEE_DECOMPOSITION: "费用分解 医保报销比例 分段计算",
    PolicyQAIntent.TREATMENT_DECOMPOSITION: "待遇分解 统筹支付 大额支付",
    PolicyQAIntent.DEDUCTIBLE: "起付线 住院起付标准",
    PolicyQAIntent.PAYMENT_RATIO: "统筹分段 支付比例 自付比例 报销比例",
    PolicyQAIntent.CAP_AMOUNT: "封顶线 年度最高支付限额",
    PolicyQAIntent.GENERAL: "医保支付",
}


class QuestionRewriter:
    """
    问题重写器

    将用户口语化问题 + SQL上下文 → 精准的政策检索查询。
    输出两部分：
    1. search_query: 用于 Milvus 向量检索的精准查询
    2. context_prefix: 业务上下文（注入到解释 Prompt 中）
    """

    def __init__(self):
        self.normalizer = get_normalizer()

    async def rewrite(
        self, question: str, sql_result: SQLQueryResult,
        intent: PolicyQAIntent | None = None,
        target_fee_item: str | None = None,
    ) -> RewrittenQuestion:
        """
        重写问题

        Args:
            question: 原始问题
            sql_result: SQL查询结果
            intent: 识别出的意图（可选）
            target_fee_item: 结构化目标费用项（可选）

        Returns:
            RewrittenQuestion: 重写后的问题
        """
        try:
            semantic_mappings: dict[str, str] = {}

            # 提取 SQL 上下文（标准化后的值）
            fund_type = sql_result.yb_brdjxx.get("fund_type", "")
            per_type = sql_result.yb_brdjxx.get("PER_TYPE", "")
            yllb = sql_result.yb_brdjxx.get("yllb", "")
            zqxh = sql_result.yb_dyxxzy.get("zqxh", "")

            if fund_type:
                semantic_mappings["fund_type"] = fund_type
            if per_type:
                semantic_mappings["per_type"] = per_type
            if yllb:
                semantic_mappings["yllb"] = yllb

            if target_fee_item == "pooling_self_pay":
                search_query = self._build_pooling_self_pay_search_query(sql_result)
                explanation_context = self._build_pooling_self_pay_context(sql_result)
                return RewrittenQuestion(
                    original=question,
                    rewritten=search_query,
                    search_query=search_query,
                    explanation_context=explanation_context,
                    semantic_mappings={
                        **semantic_mappings,
                        "target_fee_item": "pooling_self_pay",
                        "fund_type": fund_type,
                        "per_type": explanation_context["person_type"],
                        "yllb": yllb,
                        "统筹自付": "pooling_self_pay",
                    },
                )

            # 住院次数描述
            admission_desc = ""
            if zqxh:
                try:
                    zqxh_int = int(zqxh)
                    admission_desc = "首次" if zqxh_int == 1 else f"第{zqxh_int}次"
                    semantic_mappings["admission_order"] = str(zqxh_int)
                except ValueError:
                    pass

            # === 核心改写逻辑 ===
            # 1. 构建精准的检索查询：险种+人员类别+医疗类别+意图关键词
            search_parts = []
            if fund_type:
                search_parts.append(fund_type)
            if per_type:
                search_parts.append(per_type)
            if yllb:
                search_parts.append(yllb)
            if admission_desc:
                search_parts.append(f"{admission_desc}住院")

            # 根据意图补充检索关键词
            intent_keywords = INTENT_SEARCH_KEYWORDS.get(
                intent or PolicyQAIntent.GENERAL, "医保支付"
            )
            search_parts.append(intent_keywords)

            # 从用户问题中提取费用类型，补充到检索查询
            mentioned_fees = self._extract_mentioned_fees(question)
            for fee_label in mentioned_fees:
                search_parts.append(fee_label)

            search_query = " ".join(search_parts)

            # 2. 构建业务上下文前缀（供解释生成使用）
            context_parts = []
            if fund_type:
                context_parts.append(f"险种: {fund_type}")
            if per_type:
                context_parts.append(f"人员类别: {per_type}")
            if yllb:
                context_parts.append(f"医疗类别: {yllb}")
            if admission_desc:
                context_parts.append(f"住院次数: {admission_desc}")
            fynd = sql_result.yb_dyxxnd.get("fynd", "")
            if fynd:
                context_parts.append(f"费用年度: {fynd}")

            # 关键金额
            key_amounts = self._extract_key_amounts(sql_result)
            for label, value in key_amounts.items():
                context_parts.append(f"{label}: {value}元")

            # 提及的费用类型补充金额
            for fee_label in mentioned_fees:
                if fee_label in FEE_TYPE_KEYWORDS:
                    field_name = FEE_TYPE_KEYWORDS[fee_label]
                    value = self._get_field_value(sql_result, field_name)
                    if value is not None and f"{fee_label}:" not in " ".join(context_parts):
                        context_parts.append(f"{fee_label}: {value}元")

            # 3. 组装最终输出
            context_str = ""
            if context_parts:
                context_str = "，".join(context_parts)
                rewritten = f"【业务上下文】{context_str}\n\n【检索查询】{search_query}\n\n【用户问题】{question}"
            else:
                rewritten = question

            return RewrittenQuestion(
                original=question,
                rewritten=rewritten,
                search_query=search_query,
                explanation_context={"context_text": context_str},
                semantic_mappings=semantic_mappings,
            )

        except Exception as e:
            logger.exception("Failed to rewrite question")
            return RewrittenQuestion(
                original=question,
                rewritten=question,
                search_query=question,
                explanation_context={"context_text": ""},
            )

    def _is_retired(self, per_type: str | None, per_type_raw: str | None) -> bool:
        """判断人员类别是否为退休人员。"""
        candidates = [str(value).strip() for value in (per_type, per_type_raw) if value]
        return any(
            "退休" in value or "退职" in value or value in {"2", "02"}
            for value in candidates
        )

    def _build_pooling_self_pay_search_query(self, sql_result: SQLQueryResult) -> str:
        """构建统筹自付解释专用短检索查询，避免向向量检索注入大段业务上下文。"""
        brdjxx = sql_result.yb_brdjxx
        fund_type = brdjxx.get("fund_type") or brdjxx.get("fund_type_raw") or ""
        per_type = brdjxx.get("PER_TYPE") or ""
        per_type_raw = brdjxx.get("PER_TYPE_raw") or ""
        yllb = brdjxx.get("yllb") or ""
        yllb_raw = brdjxx.get("yllb_raw") or ""

        person_label = "退休人员" if self._is_retired(per_type, per_type_raw) else (per_type_raw or per_type)
        medical_label = "住院" if "住院" in (yllb_raw or yllb) else (yllb_raw or yllb)

        search_parts = [
            str(part)
            for part in [
                fund_type,
                person_label,
                medical_label,
                "统筹基金",
                "起付线以上",
                "分段",
                "自付比例",
                "退休人员个人负担比例",
            ]
            if part
        ]
        return " ".join(search_parts)

    def _build_pooling_self_pay_context(self, sql_result: SQLQueryResult) -> dict[str, Any]:
        """构建统筹自付解释所需的结构化上下文。"""
        brdjxx = sql_result.yb_brdjxx
        dyxxnd = sql_result.yb_dyxxnd
        per_type = brdjxx.get("PER_TYPE") or ""
        per_type_raw = brdjxx.get("PER_TYPE_raw") or ""

        context: dict[str, Any] = {
            "target_fee_item": "pooling_self_pay",
            "target_fee_label": "统筹自付",
            "fund_type": brdjxx.get("fund_type") or "",
            "fund_type_raw": brdjxx.get("fund_type_raw") or "",
            "person_type": per_type,
            "person_type_raw": per_type_raw,
            "is_retired": self._is_retired(per_type, per_type_raw),
            "medical_type": brdjxx.get("yllb") or "",
            "medical_type_raw": brdjxx.get("yllb_raw") or "",
            "year": dyxxnd.get("fynd") or "",
        }

        amount_fields = {
            "deductible": "bcqfje",
            "in_scope_amount": "bcybnje",
            "total_fee": "bdfyzje",
            "pooling_self_pay": "bdtczf",
            "pooling_payment": "bdtczfje",
            "major_self_pay": "bddegwyzf",
            "major_payment": "bddegwyzfje",
        }
        for context_key, field_name in amount_fields.items():
            value = self._get_field_value(sql_result, field_name)
            if value is not None:
                context[context_key] = value

        return context

    def _extract_key_amounts(self, sql_result: SQLQueryResult) -> dict[str, float]:
        """从SQL结果中提取关键金额"""
        amounts = {}

        # 起付线
        bcqfje = sql_result.yb_dyxxzy.get("bcqfje", 0)
        if bcqfje:
            amounts["起付线"] = float(bcqfje)

        # 医保内金额
        bcybnje = sql_result.yb_dyxxzy.get("bcybnje", 0)
        if bcybnje:
            amounts["医保内金额"] = float(bcybnje)

        # 统筹支付
        bdtczfje = sql_result.yb_zyfdxx.get("bdtczfje", 0)
        if bdtczfje:
            amounts["统筹支付"] = float(bdtczfje)

        # 统筹自付
        bdtczf = sql_result.yb_zyfdxx.get("bdtczf", 0)
        if bdtczf:
            amounts["统筹自付"] = float(bdtczf)

        return amounts

    def _extract_mentioned_fees(self, question: str) -> list[str]:
        """从用户问题中提取提及的费用类型"""
        mentioned = []
        for fee_label in FEE_TYPE_KEYWORDS:
            if fee_label in question:
                mentioned.append(fee_label)
        return mentioned

    def _get_field_value(self, sql_result: SQLQueryResult, field_name: str) -> float | None:
        """从SQL结果中获取字段值"""
        # 按优先级查找不同表
        for table in [sql_result.yb_zyfdxx, sql_result.yb_dyxxzy, sql_result.yb_dyxxnd]:
            if field_name in table:
                return float(table[field_name])
        return None
