"""清单条目分类与候选规则生成 — issue #86 规则管理。

确定性分类（首轮不依赖 LLM，保证可测试、可复核）：

- ``not_executable``：条件依赖就诊材料中经常缺失的信息（突变/基因检测、
  用药线数、前置治疗等），首轮不生成待办规则（issue #86 明确排除）；
- ``needs_mapping``：条目可执行性差一层映射（如项目需先与国家目录/院内
  收费项目字典对齐、限机构等级或支付标准上限等首轮不做主功能的形态），
  ``mapping_gap`` 必须写清缺什么，且不得悄悄执行；
- ``executable``：能落成「同一次结算内的项目组合」条件（重复收取/同时收取
  类），生成带原条款的候选规则（condition_spec 为结构化条件）。

候选规则必须携带原条款（source_clause）；引不出原条款的不生成。
"""
from __future__ import annotations

import re
from datetime import datetime

from src.domain.screening_rules.models import (
    ChecklistItem,
    RuleClass,
    ScreeningRule,
    new_rule_id,
)

# 就诊材料经常缺失的条件关键词（首轮不自动生成待办规则）
_MISSING_MATERIAL_KEYWORDS = (
    "突变", "基因", "用药线数", "线数", "一线", "二线", "三线",
    "前置治疗", "既往治疗", "新辅助", "辅助治疗史", "病理报告", "免疫组化",
)

# 差一层映射的形态关键词：执行前还缺一层字典/目录对齐
_NEEDS_MAPPING_KEYWORDS = (
    "限二级", "限三级", "限机构", "限特定医院", "支付标准", "支付上限",
    "限额", "限定支付", "目录内", "医保目录", "超限定",
)

# 可执行形态：同单项目组合（比较相关项目内涵，而非单条备注）
_COCHARGE_PATTERN = re.compile(
    r"开展(?P<anchor>.+?)[，,].*?重复收[取费](?P<conflicts>.+?)费用"
)
_CONFLICT_SPLIT = re.compile(r"和[（(]或[)）]|和|或|、|及")

# 上传清单条目序号：行首的 1. / 1、/ （1）/ 一、等
_ITEM_REF_PATTERN = re.compile(r"^\s*(?:[（(]?\d+[)）]?|[一二三四五六七八九十]+)[.、]\s*|^\s*\d+\s+")


def split_checklist_items(text: str) -> list[tuple[str, str]]:
    """把上传清单文本拆成 (条目序号, 条款原文) 列表。

    按行切分；行首序号（如有）作为 source_item_ref，否则用行号。
    """
    items: list[tuple[str, str]] = []
    for index, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        ref = str(index)
        match = _ITEM_REF_PATTERN.match(line)
        if match:
            ref = match.group(0).strip().strip("（）().、")
            line = line[match.end():].strip()
        if line:
            items.append((ref, line))
    return items


def classify_clause(clause: str) -> tuple[RuleClass, str | None]:
    """逐条分类，返回 (分类, mapping_gap)。

    顺序：材料缺失 → not_executable；差一层映射 → needs_mapping（写清缺什么）；
    可落成同单项目组合 → executable；其余默认 needs_mapping（缺执行条件
    结构化），绝不悄悄执行。
    """
    for keyword in _MISSING_MATERIAL_KEYWORDS:
        if keyword in clause:
            return (
                RuleClass.NOT_EXECUTABLE,
                f"条件依赖「{keyword}」等就诊材料，该材料在历史诊次中经常缺失，首轮不生成待办规则",
            )
    cocharge = _parse_cocharge(clause)
    if cocharge is not None:
        return (RuleClass.EXECUTABLE, None)
    for keyword in _NEEDS_MAPPING_KEYWORDS:
        if keyword in clause:
            return (
                RuleClass.NEEDS_MAPPING,
                f"条目含「{keyword}」：需先完成与国家目录/院内收费项目字典及支付标准的映射后才能执行",
            )
    return (
        RuleClass.NEEDS_MAPPING,
        "未能结构化为可执行条件（非同单项目组合形态），需人工确认条件并补充项目映射",
    )


def _cocharge_title(anchor: str, conflicts: list[str]) -> str:
    return f"{anchor}重复收取{'/'.join(conflicts)}"


def _cocharge_condition_text(anchor: str, conflicts: list[str]) -> str:
    return (
        f"同一次结算中同时收取「{anchor}」与「{'、'.join(conflicts)}」"
        "中任一项目时，后者列入疑点"
    )


def _parse_cocharge(clause: str) -> tuple[str, list[str]] | None:
    """解析「开展X，重复收取Y和（或）Z费用」形态，返回 (anchor, conflicts)。"""
    match = _COCHARGE_PATTERN.search(clause)
    if not match:
        return None
    anchor = match.group("anchor").strip("，,。；; ")
    conflicts = [
        part.strip("，,。；; （）()")
        for part in _CONFLICT_SPLIT.split(match.group("conflicts"))
        if part.strip("，,。；; （）()")
    ]
    if not anchor or not conflicts:
        return None
    return (anchor, conflicts)


def build_candidate_rule(
    clause: str,
    *,
    source_doc: str,
    source_item_ref: str,
    now: datetime,
) -> ScreeningRule | None:
    """为可执行条目生成带原条款的候选规则；不可执行条目返回 None。"""
    rule_class, mapping_gap = classify_clause(clause)
    if rule_class is not RuleClass.EXECUTABLE:
        return None
    parsed = _parse_cocharge(clause)
    if parsed is None:
        return None
    anchor, conflicts = parsed
    return ScreeningRule(
        rule_id=new_rule_id(),
        source_doc=source_doc,
        source_clause=clause,  # 必填：原条款
        title=_cocharge_title(anchor, conflicts),
        condition_text=_cocharge_condition_text(anchor, conflicts),
        rule_class=RuleClass.EXECUTABLE,
        mapping_gap=mapping_gap,
        condition_spec={
            "kind": "cocharge",
            "anchor_item_contains": anchor,
            "conflict_items_contain": conflicts,
        },
        source_item_ref=source_item_ref,
        created_at=now,
        updated_at=now,
    )


def classify_checklist(
    text: str,
    *,
    source_doc: str,
    now: datetime,
) -> tuple[list[ChecklistItem], list[ScreeningRule]]:
    """上传清单 → 逐条分类 + 可执行条目的候选规则（带原条款）。"""
    items: list[ChecklistItem] = []
    rules: list[ScreeningRule] = []
    for item_ref, clause in split_checklist_items(text):
        rule_class, mapping_gap = classify_clause(clause)
        candidate: ScreeningRule | None = None
        if rule_class is RuleClass.EXECUTABLE:
            candidate = build_candidate_rule(
                clause, source_doc=source_doc, source_item_ref=item_ref, now=now
            )
        if candidate is not None:
            rules.append(candidate)
        items.append(
            ChecklistItem(
                item_ref=item_ref,
                clause=clause,
                rule_class=rule_class,
                mapping_gap=mapping_gap,
                candidate_rule_id=candidate.rule_id if candidate else None,
            )
        )
    return items, rules
