"""诊疗/价格项目内涵的收费边界解释（Issue #85）。

窗口只讲两件事：「这项含什么」「为什么同单还有那几行」。
- 「不含 / 除外内容 / 另收」→ 同单匹配到的费用行是单独计费；
- 「包含」→ 本行收费已包含该项，不再另收（同单确有该项收费行时保持沉默）；
- 加收规则属医保办核对内容，不进入患者话术；药品目录备注（适应症/用药条件）不参与。
解释必须同时锚定费用行与目录内涵原文；对不上的不讲；同一被解释行只产出一处解释。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation

#: 患者话术禁词：符合性/违规/超收判断与加收规则一律不进入窗口解释。
_BANNED_WORDS = ("符合", "不符合", "违规", "超收", "加收")

#: 目录来源白名单：药品目录备注是支付条件，不在本模块处理。
_CATALOG_SOURCES = ("诊疗目录", "材料目录")

#: 类别词的归一别名：目录内涵写类别名，费用行写具体项目名。
#: 键为内涵原文 token，值为可匹配费用行名称的关键词（任一命中即算对上）。
_CLUE_ALIASES: dict[str, tuple[str, ...]] = {
    "实验室检验": ("测定", "检测", "计数", "分析"),
    "病理学检查": ("病理",),
    "消化内镜检查": ("胃镜", "肠镜", "内镜"),
    "内镜检查": ("胃镜", "肠镜", "内镜"),
    # 「套扎器（圈）」是目录对同一耗材的别名标注，费用行常写「圈套器」。
    "套扎器（圈）": ("圈套器", "套扎器"),
    "套扎器(圈)": ("圈套器", "套扎器"),
}

#: 「不含…」清单指向的是服务/操作，耗材行不匹配（如「活检」不配活检钳）；
#: 「除外内容/另收」清单指向另行收取的内容物（多为耗材），不限行类别。
_SERVICE_ITEM_TYPES = ("诊疗项目", "服务设施")

_EXCLUDE_RE = re.compile(r"除外内容[：:]([^。；\n]+)")
_NOT_INCLUDE_RE = re.compile(r"不含([^。；\n]+)")
_SEPARATE_RE = re.compile(r"([一-鿿（）()]{1,20}?)(?:按实际消耗)?另收")
_INCLUDE_RE = re.compile(r"包含([^。；\n]+)")
_SPLIT_RE = re.compile(r"[、，,]")
_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")


@dataclass(frozen=True)
class _Clue:
    kind: Literal["separate_charge", "included"]
    fragment: str            # 目录内涵原文片段（引用口径）
    keywords: tuple[str, ...]
    material_hint: bool      # True=除外内容/另收（不限行类别）；False=不含（仅服务行）


class BoundaryCitation(BaseModel):
    """一处目录内涵引用：内涵所在行 + 原文片段。"""
    model_config = ConfigDict(extra="forbid")
    display_no: int
    item_name: str
    fragment: str


class BoundaryTarget(BaseModel):
    """被内涵解释的同单费用行。"""
    model_config = ConfigDict(extra="forbid")
    display_no: int
    item_name: str


class LineBoundaryExplanation(BaseModel):
    """回看：本行（如耗材/操作）为何单独计费，合并全部来源引用。"""
    model_config = ConfigDict(extra="forbid")
    display_no: int
    item_name: str
    total_fee: str | None = None
    citations: list[BoundaryCitation]
    sentence: str


class SourceClueMatch(BaseModel):
    """一条「不含/除外/另收」内涵与它解释的同单费用行。"""
    model_config = ConfigDict(extra="forbid")
    fragment: str
    targets: list[BoundaryTarget]
    sentence: str


class SourceBoundaryExplanation(BaseModel):
    """前看：本行含什么（包含项）、本行内涵解释了同单哪些行。"""
    model_config = ConfigDict(extra="forbid")
    display_no: int
    item_name: str
    matches: list[SourceClueMatch]
    included_fragments: list[str]
    sentences: list[str]


class BillingBoundaryPayload(BaseModel):
    """交给解释链路与确定性正文的收费边界事实。"""
    model_config = ConfigDict(extra="forbid")
    line_explanations: list[LineBoundaryExplanation]
    source_explanations: list[SourceBoundaryExplanation]


def _keywords(raw: str) -> tuple[str, ...]:
    words = []
    for part in _SPLIT_RE.split(raw):
        word = part.strip().strip("。")
        if word:
            words.append(word)
    return tuple(words)


def _extract_clues(bz: str) -> list[_Clue]:
    """从目录内涵原文提取收费边界线索；加收句与无法成句的内容不取。"""
    clues: list[_Clue] = []
    for match in _EXCLUDE_RE.finditer(bz):
        fragment = f"除外内容：{match.group(1).strip()}"
        clues.append(_Clue("separate_charge", fragment, _keywords(match.group(1)), True))
    for match in _NOT_INCLUDE_RE.finditer(bz):
        fragment = f"不含{match.group(1).strip()}"
        clues.append(_Clue("separate_charge", fragment, _keywords(match.group(1)), False))
    for sentence in re.split(r"[。；\n]", bz):
        match = _SEPARATE_RE.search(sentence)
        if match and "除外内容" not in sentence:
            fragment = sentence.strip()
            if fragment:
                clues.append(_Clue("separate_charge", fragment, _keywords(match.group(1)), True))
    for match in _INCLUDE_RE.finditer(bz):
        fragment = f"包含{match.group(1).strip()}"
        clues.append(_Clue("included", fragment, _keywords(match.group(1)), True))
    return [clue for clue in clues if clue.keywords
            and not any(word in clue.fragment for word in _BANNED_WORDS)]


def _match_keywords(keyword: str) -> tuple[str, ...]:
    """类别词归一：命中别名表用别名，否则用词本身（去掉括号注释）。"""
    if keyword in _CLUE_ALIASES:
        return _CLUE_ALIASES[keyword]
    bare = _PAREN_RE.sub("", keyword).strip()
    return (bare,) if bare else ()


@dataclass
class _Match:
    source_index: int
    clue: _Clue
    target_indexes: list[int] = field(default_factory=list)


def _gather(items: list[FeeItemExplanation]) -> tuple[list[_Match], dict[int, list[str]]]:
    """逐行解析内涵并匹配同单费用行；返回（分开计费匹配，内涵行→包含项原文）。"""
    matches: list[_Match] = []
    included: dict[int, list[str]] = {}
    for index, item in enumerate(items):
        context = item.payment_condition_context
        if context is None or context.catalog_status != "unique":
            continue
        if context.catalog_source not in _CATALOG_SOURCES or not context.bz:
            continue
        for clue in _extract_clues(context.bz):
            keywords = tuple(word for key in clue.keywords for word in _match_keywords(key))
            if clue.kind == "included":
                # 同单确有该项收费行时不能讲「不再另收」。
                conflict = any(
                    other_index != index and any(word in (other.item_name or "") for word in keywords)
                    for other_index, other in enumerate(items))
                if not conflict:
                    included.setdefault(index, []).append(clue.fragment)
                continue
            targets = []
            for other_index, other in enumerate(items):
                if other_index == index or not other.item_name:
                    continue
                if other.item_type == "药品":
                    continue
                if not clue.material_hint and other.item_type not in _SERVICE_ITEM_TYPES:
                    continue
                if any(word in other.item_name for word in keywords):
                    targets.append(other_index)
            if targets:
                matches.append(_Match(index, clue, targets))
    return matches, included


def _compress_numbers(display_nos: list[int]) -> str:
    """连续展示序号压缩为区间：第18至31行 / 第9、11、12行。"""
    ordered = sorted(display_nos)
    parts: list[str] = []
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        parts.append(f"第{start}至{prev}行" if start != prev else f"第{start}行")
        start = prev = value
    parts.append(f"第{start}至{prev}行" if start != prev else f"第{start}行")
    return "、".join(parts)


def _target_desc(items: list[FeeItemExplanation], indexes: list[int]) -> str:
    """多个目标行的紧凑描述：序号区间 + 最多 3 个项目名示例。"""
    if len(indexes) == 1:
        item = items[indexes[0]]
        return f"第{indexes[0] + 1}行{item.item_name}"
    numbers = _compress_numbers([index + 1 for index in indexes])
    names = [items[index].item_name or "" for index in indexes[:3]]
    preview = "、".join(names) + ("等" if len(indexes) > 3 else "")
    return f"{numbers}（共{len(indexes)}项，如{preview}）"


def build_billing_boundary_payload(
    items: list[FeeItemExplanation], focus: set[int] | None,
) -> BillingBoundaryPayload | None:
    """组装收费边界解释。focus 为问题涉及行的展示序号集合；None 表示整单。

    回看（line_explanations）只收 focus 命中的被解释行；前看（source_explanations）
    只收 focus 命中的内涵所在行。同一被解释行合并全部来源引用，只讲一次。
    """
    matches, included = _gather(items)

    by_target: dict[int, list[tuple[int, _Clue]]] = {}
    for match in matches:
        for target in match.target_indexes:
            by_target.setdefault(target, []).append((match.source_index, match.clue))

    line_explanations: list[LineBoundaryExplanation] = []
    for target_index in sorted(by_target):
        display_no = target_index + 1
        if focus is not None and display_no not in focus:
            continue
        item = items[target_index]
        citations = [
            BoundaryCitation(display_no=source_index + 1,
                             item_name=items[source_index].item_name or "",
                             fragment=clue.fragment)
            for source_index, clue in sorted(by_target[target_index])
        ]
        basis = "；".join(f"第{c.display_no}行{c.item_name}的目录内涵注明「{c.fragment}」"
                          for c in citations)
        fee = ""
        if item.total_fee:
            try:
                from decimal import Decimal as _Decimal
                fee = f"（{_Decimal(item.total_fee).quantize(_Decimal('0.01'))}元）"
            except Exception:  # noqa: BLE001 — 金额原文不可解析时按原文展示
                fee = f"（{item.total_fee}元）"
        sentence = f"第{display_no}行{item.item_name}{fee}为单独计费项目，目录内涵依据：{basis}。"
        line_explanations.append(LineBoundaryExplanation(
            display_no=display_no, item_name=item.item_name or "",
            total_fee=item.total_fee, citations=citations, sentence=sentence))

    source_explanations: list[SourceBoundaryExplanation] = []
    by_source: dict[int, list[_Match]] = {}
    for match in matches:
        by_source.setdefault(match.source_index, []).append(match)
    for source_index in sorted(set(by_source) | set(included)):
        display_no = source_index + 1
        if focus is not None and display_no not in focus:
            continue
        item = items[source_index]
        name = item.item_name or ""
        clue_matches: list[SourceClueMatch] = []
        sentences: list[str] = []
        for match in by_source.get(source_index, []):
            desc = _target_desc(items, match.target_indexes)
            sentence = f"第{display_no}行{name}的目录内涵注明「{match.clue.fragment}」，同单{desc}为单独计费项目。"
            clue_matches.append(SourceClueMatch(
                fragment=match.clue.fragment,
                targets=[BoundaryTarget(display_no=i + 1, item_name=items[i].item_name or "")
                         for i in match.target_indexes],
                sentence=sentence))
            sentences.append(sentence)
        fragments = included.get(source_index, [])
        for fragment in fragments:
            topic = fragment[len("包含"):]
            sentences.append(f"第{display_no}行{name}的目录内涵注明「{fragment}」，"
                             f"本行收费已包含{topic}，不再另收此项费用。")
        source_explanations.append(SourceBoundaryExplanation(
            display_no=display_no, item_name=name, matches=clue_matches,
            included_fragments=fragments, sentences=sentences))

    if not line_explanations and not source_explanations:
        return None
    payload = BillingBoundaryPayload(
        line_explanations=line_explanations, source_explanations=source_explanations)
    for sentence in [line.sentence for line in payload.line_explanations] + [
            text for source in payload.source_explanations for text in source.sentences]:
        assert not any(word in sentence for word in _BANNED_WORDS), sentence
    return payload
