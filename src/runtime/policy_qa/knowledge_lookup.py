"""知识检索编排：结构化可信问题库 + 向量政策证据 + 综合两级来源。

真实检索逻辑归 policy_qa（与结算 provider 同层），tool_registry 只做薄包装。
综合检索的优先级是硬约束：确定性可信问题库命中优先于向量检索，
未命中才降级到向量证据，并把澄清候选一并返回供上层追问。
"""

from __future__ import annotations

import asyncio
from typing import Any


async def retrieve_policy_evidence_for_fact(settlement_fact: dict[str, Any]) -> dict[str, Any]:
    """按结算事实的适用性维度做 Milvus 结构化政策检索。

    输出携带 rule_id/原文/支付比例/金额分段，供下游对比计算与引用组装复用。
    """
    from src.config.production import MILVUS_HOST, MILVUS_PORT
    from src.runtime.policy_qa.structured_policy_retriever import retrieve_policy_evidence

    normalized_ctx = {
        "settlement_id": settlement_fact.get("settlement_id") or "",
        "insu_type": settlement_fact.get("insurance_type") or "城镇职工",
        "med_type": settlement_fact.get("service_type") or "普通住院",
        "hosp_lv": settlement_fact.get("hospital_level") or "三级医院",
        "psn_type": settlement_fact.get("person_type") or "退休人员",
        "target_field": "统筹自付",
        "target_amount": float(settlement_fact.get("total_amount") or 0),
    }
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: retrieve_policy_evidence(
            settlement_context=normalized_ctx,
            host=MILVUS_HOST,
            port=str(MILVUS_PORT),
        ),
    )
    evidence = [
        {
            "rule_id": ev.rule_id,
            "source_text": ev.source_text,
            "doc_id": ev.doc_id,
            "payment_ratio": ev.payment_ratio,
            "amount_band": ev.amount_band,
            "rule_value": ev.rule_value,
            "applied_reason": ev.applied_reason,
            "effective_date": ev.effective_date,
            "expiry_date": ev.expiry_date,
            "score": ev.score,
        }
        for ev in result.selected_evidence
    ]
    if result.missing_required_rules:
        policy_status = "partial_policy_matched"
    elif len(evidence) >= 2:
        policy_status = "full_policy_matched"
    else:
        policy_status = "no_policy_matched"
    return {
        "policy_status": policy_status,
        "evidence": evidence,
        "evidence_count": len(evidence),
        "missing_required_rules": list(result.missing_required_rules),
    }


def match_trusted_question(question: str) -> dict[str, Any]:
    """可信问题库匹配：归一化精确命中即返回标准问题，否则返回澄清候选。

    不确定不执行是硬约束——本函数只做匹配，不触发查询计划。
    """
    from src.data_platform.storage.question_library.question_factory import (
        get_trusted_question_storage,
    )
    from src.runtime.question_library.service import QuestionLibraryService

    service = QuestionLibraryService(get_trusted_question_storage())
    outcome = service.match(question)
    if outcome.kind == "hit" and outcome.question is not None:
        return {
            "kind": "hit",
            "question_id": outcome.question.question_id,
            "standard_question": outcome.question.standard_question,
            "matched_text": outcome.matched_text,
            "candidates": [],
        }
    return {
        "kind": "clarify",
        "question_id": None,
        "standard_question": None,
        "matched_text": None,
        "candidates": [
            {
                "question_id": candidate.question_id,
                "standard_question": candidate.standard_question,
                "score": candidate.score,
                "matched_text": candidate.matched_text,
            }
            for candidate in outcome.candidates
        ],
    }


async def comprehensive_knowledge_lookup(
    question: str, settlement_fact: dict[str, Any] | None = None
) -> dict[str, Any]:
    """综合知识检索：先结构化（可信问题库）后向量（政策证据），融合两级来源。

    可信问题库命中 → 直接返回标准问题（answer_source=trusted_question_library）；
    未命中 → 向量政策证据 + 澄清候选一并返回，供上层解释或追问复用。
    """
    structured = match_trusted_question(question)
    if structured["kind"] == "hit":
        return {
            "lookup_kind": "structured_hit",
            "answer_source": "trusted_question_library",
            "question_id": structured["question_id"],
            "standard_question": structured["standard_question"],
            "evidence": [],
            "evidence_count": 0,
            "clarify_candidates": [],
        }

    vector = await retrieve_policy_evidence_for_fact(settlement_fact or {})
    return {
        "lookup_kind": "vector_evidence",
        "answer_source": "structured_policy_retriever",
        "question_id": None,
        "standard_question": None,
        "evidence": vector["evidence"],
        "evidence_count": vector["evidence_count"],
        "policy_status": vector["policy_status"],
        "clarify_candidates": structured["candidates"],
    }
