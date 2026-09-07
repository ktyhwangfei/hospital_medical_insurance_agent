"""可信问题库冷启动挖掘（Issue #37 Slice 4）。

从政策问答历史（policy_qa_trajectories.question）挖掘高频问题，
归一化分组后产出 draft 状态可信问题候选——一律待人工审核，禁止直接 active。
"""

from __future__ import annotations

import hashlib
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from src.domain.trusted_qa.models import TrustedQuestion, TrustedQuestionSynonym
from src.runtime.trusted_qa.matcher import normalize_question


class MinedQuestion(BaseModel):
    """挖掘出的高频问题候选（DTO）。

    standard_question 取组内最高频原文写法；variants 为归一化相同的
    其他原文写法，作为同义表达候选进入草稿。
    """

    model_config = ConfigDict(frozen=True)

    standard_question: str
    frequency: int = Field(ge=1)
    variants: list[str] = Field(default_factory=list)


def mine_frequent_questions(
    questions: list[str],
    *,
    limit: int = 50,
    min_frequency: int = 1,
) -> list[MinedQuestion]:
    """高频问题挖掘：归一化分组 → 频次排序 → Top N。

    - 归一化（NFKC/标点剥离）相同的写法归为一组
    - 组内代表形取最高频原文；并列时取字典序最小者保证确定性
    - 频次低于 min_frequency 的组剔除
    """
    groups: dict[str, Counter[str]] = {}
    for raw in questions:
        normalized = normalize_question(raw)
        if not normalized:
            continue
        groups.setdefault(normalized, Counter())[raw.strip()] += 1

    mined: list[MinedQuestion] = []
    for variants_counter in groups.values():
        total = sum(variants_counter.values())
        if total < min_frequency:
            continue
        # 代表形：频次最高；并列取更短、再字典序最小，保证跨运行稳定且形态自然
        representative = min(
            variants_counter.items(), key=lambda item: (-item[1], len(item[0]), item[0])
        )[0]
        variants = sorted(v for v in variants_counter if v != representative)
        mined.append(
            MinedQuestion(
                standard_question=representative,
                frequency=total,
                variants=variants,
            )
        )

    # 频次倒序，standard_question 升序兜底
    mined.sort(key=lambda m: (-m.frequency, m.standard_question))
    return mined[:limit]


def build_draft_questions(
    mined: list[MinedQuestion],
    *,
    created_by: str = "cold-start",
) -> list[TrustedQuestion]:
    """挖掘结果 → draft 状态可信问题候选。

    question_id 取归一化文本的 sha256 前 12 位，幂等：重复执行
    对同一问题产生同一 ID，由存储层 ConflictError 实现跳过。
    """
    drafts: list[TrustedQuestion] = []
    for item in mined:
        digest = hashlib.sha256(
            normalize_question(item.standard_question).encode("utf-8")
        ).hexdigest()[:12]
        drafts.append(
            TrustedQuestion(
                question_id=f"tq_seed_{digest}",
                standard_question=item.standard_question,
                synonyms=[
                    TrustedQuestionSynonym(expression=v, added_by=created_by)
                    for v in item.variants
                ],
                created_by=created_by,
            )
        )
    return drafts
