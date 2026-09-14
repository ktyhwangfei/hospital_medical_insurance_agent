"""综合知识检索（knowledge_lookup）单元测试：先结构化后向量的两级融合。"""

import os

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest

from src.runtime.policy_qa import knowledge_lookup
from src.runtime.policy_qa.knowledge_lookup import comprehensive_knowledge_lookup


def _patch(monkeypatch, *, structured: dict, vector: dict):
    async def _fake_retrieve(settlement_fact):
        return vector

    monkeypatch.setattr(knowledge_lookup, "match_trusted_question", lambda question: structured)
    monkeypatch.setattr(knowledge_lookup, "retrieve_policy_evidence_for_fact", _fake_retrieve)


@pytest.mark.asyncio
async def test_structured_hit_wins_over_vector(monkeypatch) -> None:
    _patch(
        monkeypatch,
        structured={
            "kind": "hit",
            "question_id": "q-001",
            "standard_question": "无痛肠胃镜退费政策是什么",
            "matched_text": "无痛肠胃镜退费",
            "candidates": [],
        },
        vector={
            "policy_status": "full_policy_matched",
            "evidence": [{"rule_id": "R-1"}],
            "evidence_count": 1,
            "missing_required_rules": [],
        },
    )

    result = await comprehensive_knowledge_lookup("无痛肠胃镜能不能退", {"settlement_id": "S001"})

    assert result["lookup_kind"] == "structured_hit"
    assert result["answer_source"] == "trusted_question_library"
    assert result["standard_question"] == "无痛肠胃镜退费政策是什么"
    assert result["evidence"] == []


@pytest.mark.asyncio
async def test_vector_fallback_carries_evidence_and_clarify_candidates(monkeypatch) -> None:
    _patch(
        monkeypatch,
        structured={
            "kind": "clarify",
            "question_id": None,
            "standard_question": None,
            "matched_text": None,
            "candidates": [{"question_id": "q-009", "standard_question": "候选问题", "score": 0.6}],
        },
        vector={
            "policy_status": "full_policy_matched",
            "evidence": [{"rule_id": "R-1", "source_text": "政策原文"}],
            "evidence_count": 1,
            "missing_required_rules": [],
        },
    )

    result = await comprehensive_knowledge_lookup("这个问题库里没有", {"settlement_id": "S001"})

    assert result["lookup_kind"] == "vector_evidence"
    assert result["answer_source"] == "structured_policy_retriever"
    assert result["evidence_count"] == 1
    assert result["policy_status"] == "full_policy_matched"
    assert result["clarify_candidates"][0]["question_id"] == "q-009"
