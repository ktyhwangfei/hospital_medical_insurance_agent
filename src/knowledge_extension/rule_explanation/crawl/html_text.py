"""HTML→政策正文文本的表格感知提取（#39 吸并 #24）。

背景：爬虫原先用 ``soup.get_text("\\n")`` 抽正文，HTML <table> 被拍平成
逐单元格的孤立行，行列结构全部丢失——政策里的待遇标准表（医院等级×
起付线/支付比例）无法作为表格被下游解析，事实引用也无法定位到单元格。

本模块把 <table> 渲染为「单元格 | 单元格」的行文本（一行 <tr> 一行文本），
其余内容保持 get_text 语义不变。下游 policy_struct/table_parser 识别这种
行文本并产出单元格级定位。
"""
from __future__ import annotations

from bs4 import NavigableString, Tag

# 单元格分隔符：与 policy_struct/table_parser 的 CELL_SEP 保持一致，
# 选「 | 」因为中文政策正文里几乎不出现竖线。
CELL_SEP = " | "


def render_table_rows(table: Tag) -> str:
    """把 <table> 渲染为逐行文本：一行 <tr> → 「单元格 | 单元格 | ...」。

    只取 <tr> 的直接 <td>/<th> 子单元格（find_all 递归会把嵌套表格的
    行/格并进当前行造成重复）；嵌套表格整体随宿主单元格 get_text 拍平。
    """
    lines: list[str] = []
    for tr in table.find_all("tr"):
        if tr.find_parent("tr") is not None:
            continue  # 嵌套表格自身的行：随宿主单元格文本展开
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            cells = tr.find_all(["td", "th"])
        values = [c.get_text(" ", strip=True) for c in cells]
        if any(values):
            lines.append(CELL_SEP.join(values))
    return "\n".join(lines)


def extract_text_with_tables(node: Tag) -> str:
    """表格感知版 get_text("\\n", strip=True)。

    先把树内所有顶层 <table> 原位替换为渲染好的行文本，再整体 get_text，
    保证表格外内容的行为与旧提取完全一致。嵌套表格不单独渲染——其文本
    已随外层单元格 get_text 展开，单独再渲会重复。
    """
    # 先在完整树上判定嵌套关系（替换后内层表游离，祖先链断裂判不出），
    # 再统一替换，避免嵌套表重复渲染
    top_level_tables = [
        t for t in node.find_all("table") if t.find_parent("table") is None
    ]
    for table in top_level_tables:
        rendered = render_table_rows(table)
        table.replace_with(NavigableString("\n" + rendered + "\n"))
    return node.get_text("\n", strip=True)
