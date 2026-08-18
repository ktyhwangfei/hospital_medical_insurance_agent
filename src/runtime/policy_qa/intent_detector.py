"""
医保政策问答RAG系统 - 意图识别

使用LLM识别用户意图
"""

from __future__ import annotations

import logging
from typing import Any

from src.model_service.gateway import ModelGateway
from src.model_service.governance_runtime import (
    GovernanceRuntimeError,
    render_governed_prompt,
)
from src.model_service.models import Message
from src.runtime.policy_qa.models import PolicyQAIntent, PolicyQAIntentResult

logger = logging.getLogger(__name__)

# 意图识别Prompt
INTENT_DETECTION_PROMPT = """你是一个医保政策问答系统的意图识别模块。

用户问题: {question}

请识别用户意图，返回JSON格式:
{{
  "intent": "意图类型",
  "need_patient_data": true/false,
  "query_type": "查询类型",
  "target_fee_item": "目标费用项或null",
  "target_fee_label": "目标费用项中文名或null",
  "confidence": 0.0-1.0
}}

意图类型说明:
- fee_decomposition: 费用分解（用户想了解费用构成）
- treatment_decomposition: 待遇分解（用户想了解待遇计算）
- deductible: 起付线（用户想了解起付线相关）
- payment_ratio: 报销比例（用户想了解报销比例）
- cap_amount: 封顶线（用户想了解封顶线）
- general: 通用问答

目标费用项说明:
- pooling_self_pay: 统筹自付、统筹自费、统筹个人自付
- null: 用户未询问具体费用项

查询类型说明:
- 统筹自付解释: 解释本次统筹自付金额为什么这么多、怎么算
- 费用分解: 了解费用构成
- 待遇分解: 了解待遇计算
- 起付线: 了解起付线规则
- 报销比例: 了解报销比例
- 封顶线: 了解封顶线规则
- 其他: 其他问题

请只返回JSON，不要有其他内容。"""


class IntentDetector:
    """
    意图识别器

    使用LLM识别用户意图
    """

    def __init__(self, model_gateway: ModelGateway | None = None):
        self.model_gateway = model_gateway

    async def detect(self, question: str) -> PolicyQAIntentResult:
        """
        检测用户意图 — 关键词优先，LLM 兜底。

        策略：先用关键词匹配，confidence ≥ 0.9 直接返回（省一次 LLM 调用）；
        仅当关键词匹配失败或不确信时才调用 LLM。
        """
        try:
            # 如果没有模型网关，使用关键词匹配
            if self.model_gateway is None:
                return self._keyword_based_detection(question)

            # ★ 优化：关键词优先 — 高置信度命中直接返回，跳过 LLM
            keyword_result = self._keyword_based_detection(question)
            if keyword_result.confidence >= 0.9:
                logger.info(
                    "Intent detected via keyword (confidence=%.2f), skipping LLM",
                    keyword_result.confidence,
                )
                return keyword_result

            # 关键词不确信，调用 LLM
            rendered = render_governed_prompt(
                "policy_qa.intent_detect",
                variables={"question": question},
                fallback_system="",
                fallback_user=INTENT_DETECTION_PROMPT,
            )
            messages = []
            if rendered.rendered_system_prompt:
                messages.append(Message(role="system", content=rendered.rendered_system_prompt))
            messages.append(Message(role="user", content=rendered.rendered_user_prompt or ""))
            response = await self.model_gateway.generate(
                messages=messages,
                model_type="llm",
                scene="policy_qa",
            )

            # 解析响应
            result = self._parse_llm_response(response.content, question)
            return result

        except GovernanceRuntimeError:
            raise
        except Exception as e:
            logger.exception("Intent detection failed")
            # 降级到关键词匹配
            return self._keyword_based_detection(question)

    def _keyword_based_detection(self, question: str) -> PolicyQAIntentResult:
        """
        基于关键词的意图识别

        Args:
            question: 用户问题

        Returns:
            PolicyQAIntentResult: 意图识别结果
        """
        question_lower = question.lower()

        # 统筹自付解释需要优先识别目标费用项，避免被泛化费用或待遇规则吞掉。
        if any(kw in question_lower for kw in ["统筹自付", "统筹自费", "统筹个人自付"]):
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="",
                need_patient_data=True,
                query_type="统筹自付解释",
                confidence=0.9,
                target_fee_item="pooling_self_pay",
                target_fee_label="统筹自付",
            )

        # 大额自付（在报销比例之前，因为"大额"也包含比例概念）
        if any(kw in question_lower for kw in ["大额自付", "大额个人负担", "大额互助"]):
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.PAYMENT_RATIO,
                settlement_id="",
                need_patient_data=True,
                query_type="大额自付",
                confidence=0.85,
                target_fee_item="large_amount_self_pay",
                target_fee_label="大额自付",
            )

        # 报销比例（必须在待遇分解之前，因为"报销"也匹配待遇分解）
        if any(kw in question_lower for kw in ["比例", "报销比例", "支付比例"]):
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.PAYMENT_RATIO,
                settlement_id="",
                need_patient_data=True,
                query_type="报销比例",
                confidence=0.8,
                target_fee_item="payment_ratio",
                target_fee_label="报销比例",
            )

        # 封顶线（必须在待遇分解之前）
        if any(kw in question_lower for kw in ["封顶", "最高", "限额"]):
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.CAP_AMOUNT,
                settlement_id="",
                need_patient_data=True,
                query_type="封顶线",
                confidence=0.8,
                target_fee_item="cap_amount",
                target_fee_label="封顶线",
            )

        # 起付线
        if any(kw in question_lower for kw in ["起付线", "起付", "门槛", "免赔"]):
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.DEDUCTIBLE,
                settlement_id="",
                need_patient_data=True,
                query_type="起付线",
                confidence=0.8,
                target_fee_item="deductible",
                target_fee_label="起付线",
            )

        # 费用分解
        if any(kw in question_lower for kw in ["费用", "多少钱", "花了", "收费", "账单"]):
            # 检测是否包含具体费用项关键词
            if any(kw in question_lower for kw in ["统筹自付", "统筹自费", "起付线"]):
                return PolicyQAIntentResult(
                    intent=PolicyQAIntent.FEE_DECOMPOSITION,
                    settlement_id="",
                    need_patient_data=True,
                    query_type="费用分解",
                    confidence=0.85,
                    target_fee_item="pooling_self_pay",
                    target_fee_label="统筹自付",
                )
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.FEE_DECOMPOSITION,
                settlement_id="",
                need_patient_data=True,
                query_type="费用分解",
                confidence=0.8,
            )

        # 待遇分解（放在后面，因为"报销"可能也匹配其他意图）
        if any(kw in question_lower for kw in ["待遇", "统筹", "大额"]):
            # 检测是否包含大额互助关键词
            if "大额" in question_lower:
                return PolicyQAIntentResult(
                    intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                    settlement_id="",
                    need_patient_data=True,
                    query_type="待遇分解",
                    confidence=0.8,
                    target_fee_item="large_amount_self_pay",
                    target_fee_label="大额自付",
                )
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="",
                need_patient_data=True,
                query_type="待遇分解",
                confidence=0.8,
            )

        # 默认为费用分解
        return PolicyQAIntentResult(
            intent=PolicyQAIntent.FEE_DECOMPOSITION,
            settlement_id="",
            need_patient_data=True,
            query_type="费用分解",
            confidence=0.6,
        )

    def _parse_llm_response(self, response: str, question: str = "") -> PolicyQAIntentResult:
        """
        解析LLM响应

        Args:
            response: LLM响应

        Returns:
            PolicyQAIntentResult: 意图识别结果
        """
        try:
            import json

            # 尝试解析JSON
            data = json.loads(response)

            # 映射意图类型
            intent_mapping = {
                "fee_decomposition": PolicyQAIntent.FEE_DECOMPOSITION,
                "treatment_decomposition": PolicyQAIntent.TREATMENT_DECOMPOSITION,
                "deductible": PolicyQAIntent.DEDUCTIBLE,
                "payment_ratio": PolicyQAIntent.PAYMENT_RATIO,
                "cap_amount": PolicyQAIntent.CAP_AMOUNT,
                "general": PolicyQAIntent.GENERAL,
            }

            intent_str = data.get("intent", "general")
            intent = intent_mapping.get(intent_str, PolicyQAIntent.GENERAL)

            return PolicyQAIntentResult(
                intent=intent,
                settlement_id="",
                need_patient_data=data.get("need_patient_data", True),
                query_type=data.get("query_type", ""),
                confidence=data.get("confidence", 0.8),
                target_fee_item=data.get("target_fee_item"),
                target_fee_label=data.get("target_fee_label"),
            )

        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            # 降级到关键词匹配（使用原始问题而非 LLM 响应）
            return self._keyword_based_detection(question) if question else self._keyword_based_detection(response)
