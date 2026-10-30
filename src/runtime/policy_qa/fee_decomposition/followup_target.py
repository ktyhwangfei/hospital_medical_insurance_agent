"""会话级追问目标继承（阶段 D）：(session_id, settlement_id) → 上一问显式目标。

容量有界（LRU 淘汰最久未用，模式同 integration.py 的会话分解缓存）；
policy-qa 流在 executor 线程执行，读写加锁。键含 settlement_id：换单/换会话
天然隔离，锚点切换不串单。ambiguous/invalid/whole_settlement 不作为继承来源，
显式目标覆盖存储。
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict

from src.runtime.policy_qa.fee_decomposition.model_explanation import (
    QuestionTarget, resolve_question_target)
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic

_CAPACITY = 64
_store: OrderedDict[tuple[str, str], QuestionTarget] = OrderedDict()
_lock = threading.Lock()

#: 指代词：这/那/该/其 + 项/行/条/笔（“那这项为什么自费”“该行费用”“那个项目”）；
#: 不含裸“个”（“这个比例”是整单/字段追问，不触发继承）；
#: “这笔结算/这张单”是整单指代，不触发继承。
_REFERENT = re.compile(
    r"(?:这|那|该|其)(?:一|个)?(?:项|行|条|笔)(?!(?:结算|单子|张单))(?:费用|项目|明细)?")

#: 可继承的显式目标形态；整单/歧义/无效不覆盖存储也不被继承。
_INHERITABLE_KINDS = frozenset({"summary_fields", "fee_line", "multi_line", "comparison", "mixed"})


def has_followup_reference(question: str) -> bool:
    """问题是否含行/项指代词（“那这项”“该行费用”）。"""
    return bool(_REFERENT.search(question or ""))


def get_followup_target(session_id: str, settlement_id: str) -> QuestionTarget | None:
    """读上一问显式目标；命中即刷新为最近使用。"""
    key = (session_id, settlement_id)
    with _lock:
        target = _store.get(key)
        if target is not None:
            _store.move_to_end(key)
        return target


def remember_question_target(
    session_id: str, settlement_id: str, target: QuestionTarget
) -> None:
    """写入上一问显式目标（仅可继承形态）；超容量淘汰最久未用条目。"""
    if target.kind not in _INHERITABLE_KINDS:
        return
    key = (session_id, settlement_id)
    with _lock:
        _store[key] = target
        _store.move_to_end(key)
        while len(_store) > _CAPACITY:
            _store.popitem(last=False)


def clear_followup_targets() -> None:
    """清空存储（测试隔离用）。"""
    with _lock:
        _store.clear()


def resolve_session_question_target(
    public: FeeDecompositionPublic, question: str, session_id: str, settlement_id: str
) -> QuestionTarget:
    """本问先显式解析；指代词且无显式目标（whole_settlement）时继承上一问目标。

    显式可继承目标覆盖存储；ambiguous/invalid/whole 不覆盖（用户尚未给出新目标）。
    """
    explicit = resolve_question_target(public, question)
    if explicit.kind in _INHERITABLE_KINDS:
        remember_question_target(session_id, settlement_id, explicit)
        return explicit
    if explicit.kind == "whole_settlement" and has_followup_reference(question):
        inherited = get_followup_target(session_id, settlement_id)
        if inherited is not None:
            return inherited
    return explicit
