"""
comparison_context.py — 结算对比上下文（纯数据结构）。

baseline 为基准结算单，compared 为各对比单的差异与归因集合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .diff_engine import FieldDiff
from .strategies.compare.strategy import Attribution


@dataclass
class ComparedSettlement:
    """一张对比结算单相对基准的差异与归因。"""

    settlement_id: str
    context: Any
    diffs: list[FieldDiff]
    attributions: list[Attribution] = field(default_factory=list)


@dataclass
class ComparisonContext:
    """一次对比的完整上下文：基准 + 各对比单。"""

    baseline: Any
    compared: list[ComparedSettlement]
