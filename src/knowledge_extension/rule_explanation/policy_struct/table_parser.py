"""政策表格条款解析（#39 吸并 #24，借鉴 RagFlow 表格切片策略）。

上游事实：爬虫侧（crawl/html_text.py）已把 HTML <table> 渲染为
「单元格 | 单元格」的行文本；本模块在结构解析层识别这类表格块：

1. **块识别**：正文中连续 ≥2 行、每行含 ≥2 个「|」分隔单元格 → 表格块；
2. **网格解析**：首行为表头（数字占比低的行），其余为数据行；
3. **RagFlow 风格行组切片**：每片携带表头上下文重复，保证检索命中后
   脱离表格也能读懂（"一级及以下 | 100元" 单看不知 100 元是什么）；
4. **单元格级定位**：每个非空数据单元格产出定位单元
   ``{node_id}#r{row}c{col}``（r/c 为数据行/列下标，从 0 起），
   事实引用据此可定位到表格单元格（match_leaves 的 unit_id 沿用该串）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CELL_SEP = "|"
_MIN_TABLE_LINES = 2  # 少于 2 行不成表格


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.split(CELL_SEP)]


def is_table_line(line: str) -> bool:
    """行含 ≥2 个分隔单元格且至少一个非空。"""
    parts = line.split(CELL_SEP)
    return len(parts) >= 2 and any(p.strip() for p in parts)


def find_table_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """返回表格块的 [start, end) 行号区间列表。"""
    blocks: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        if is_table_line(lines[i]):
            j = i
            while j < len(lines) and is_table_line(lines[j]):
                j += 1
            if j - i >= _MIN_TABLE_LINES:
                blocks.append((i, j))
            i = j
        else:
            i += 1
    return blocks


def _looks_like_header(row: list[str]) -> bool:
    """表头启发：整行合起来数字字符占比低（金额/比例表头几乎全是汉字）。"""
    text = "".join(cell for cell in row if cell)
    if not text:
        return False
    digits = sum(ch.isdigit() for ch in text)
    return digits / len(text) < 0.2


@dataclass(frozen=True)
class TableCellUnit:
    """表格单元格定位单元——事实引用的最小落点。"""

    node_id: str  # 所属条款叶子的 node_id（表格挂在哪个条款下）
    locator: str  # f"{node_id}#r{row}c{col}"
    value: str  # 单元格文本
    column_header: str  # 列表头（同列表头行文本）
    row_header: str  # 行表头（同行首列文本；无首列表头时为空）
    row_text: str  # 整行原文（匹配回退用）


@dataclass(frozen=True)
class ParsedTable:
    header: list[str]  # 表头行（无表头时空列表）
    data_rows: list[list[str]]  # 数据行网格
    start_line: int  # 块首行号（含表头）
    end_line: int  # 块尾行号（开区间）


def parse_table_block(lines: list[str], start: int, end: int) -> ParsedTable:
    rows = [split_row(lines[i]) for i in range(start, end)]
    n_cols = max(len(r) for r in rows)
    # 列数对齐：参差行（合并单元格）右侧补空
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    if _looks_like_header(rows[0]):
        header, data_rows = rows[0], rows[1:]
    else:
        header, data_rows = [], rows
    return ParsedTable(header=header, data_rows=data_rows, start_line=start, end_line=end)


def build_cell_units(node_id: str, lines: list[str]) -> list[TableCellUnit]:
    """把 node 文本行中的表格块解析为单元格定位单元。

    同一单元格文本在多行重复（如分类维度列）时全部保留——由调用方按
    匹配优先级裁决，解析层不丢信息。
    """
    units: list[TableCellUnit] = []
    for start, end in find_table_blocks(lines):
        table = parse_table_block(lines, start, end)
        for r, row in enumerate(table.data_rows):
            row_header = row[0] if table.header else ""
            for c, value in enumerate(row):
                if not value:
                    continue
                units.append(TableCellUnit(
                    node_id=node_id,
                    locator=f"{node_id}#r{r}c{c}",
                    value=value,
                    column_header=table.header[c] if c < len(table.header) else "",
                    row_header=row_header,
                    row_text=f" {CELL_SEP} ".join(row),
                ))
    return units


def slice_table_for_retrieval(lines: list[str], *, rows_per_slice: int = 6) -> list[dict]:
    """RagFlow 风格表格切片：数据行按行组切片，每片重复表头上下文。

    返回切片列表，每片含 header（列表头）/ rows（数据行网格）/ row_range
    （数据行区间）/ line_range（原文行号区间），供检索与展示复用。
    """
    slices: list[dict] = []
    for start, end in find_table_blocks(lines):
        table = parse_table_block(lines, start, end)
        for a in range(0, len(table.data_rows), rows_per_slice):
            b = min(a + rows_per_slice, len(table.data_rows))
            slices.append({
                "header": list(table.header),
                "rows": [list(row) for row in table.data_rows[a:b]],
                "row_range": [a, b],
                "line_range": [table.start_line, table.end_line],
            })
    return slices
