"""表格感知 HTML→文本提取测试 — #39 吸并 #24。

爬虫 extract_content 原先用 get_text 把 <table> 拍平成逐单元格孤立行，
行列结构全丢；html_text.extract_text_with_tables 应把 <table> 渲染为
「单元格 | 单元格」行文本，表格外内容保持 get_text 语义。
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from src.knowledge_extension.rule_explanation.crawl.html_text import (
    extract_text_with_tables,
    render_table_rows,
)

HTML = """
<html><body>
<div class="content">
  <p>第十条 门诊起付标准按下列标准执行：</p>
  <table>
    <tr><th>医疗机构等级</th><th>起付标准（元）</th><th>支付比例</th></tr>
    <tr><td>一级及以下定点医疗机构</td><td>100</td><td>55%</td></tr>
    <tr><td>二级及以上定点医疗机构</td><td>550</td><td>50%</td></tr>
  </table>
  <p>第十一条 本通知自发布之日起执行。</p>
</div>
</body></html>
"""


def _content_div(html: str = HTML):
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("div", class_="content")


def test_table_renders_as_pipe_rows_preserving_order() -> None:
    text = extract_text_with_tables(_content_div())
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    assert "医疗机构等级 | 起付标准（元） | 支付比例" in lines
    assert "一级及以下定点医疗机构 | 100 | 55%" in lines
    assert "二级及以上定点医疗机构 | 550 | 50%" in lines
    # 表格前后正文保留、顺序不变
    assert lines.index("第十条 门诊起付标准按下列标准执行：") < lines.index("医疗机构等级 | 起付标准（元） | 支付比例")
    assert lines.index("第十一条 本通知自发布之日起执行。") > lines.index("二级及以上定点医疗机构 | 550 | 50%")


def test_prose_without_table_unchanged_semantics() -> None:
    html = '<div class="content"><p>第一条 起付标准为300元。</p><p>第二条 支付比例为90%。</p></div>'
    text = extract_text_with_tables(BeautifulSoup(html, "html.parser").find("div"))
    assert "第一条 起付标准为300元。" in text
    assert "|" not in text


def test_render_table_rows_skips_empty_rows() -> None:
    html = "<table><tr><td>a</td><td>b</td></tr><tr></tr><tr><td></td><td></td></tr></table>"
    rendered = render_table_rows(BeautifulSoup(html, "html.parser").find("table"))
    assert rendered == "a | b"


def test_multiple_tables_all_rendered() -> None:
    html = (
        '<div><table><tr><td>t1a</td><td>t1b</td></tr></table>'
        "<p>中间正文</p>"
        '<table><tr><td>t2a</td><td>t2b</td></tr></table></div>'
    )
    text = extract_text_with_tables(BeautifulSoup(html, "html.parser").find("div"))
    assert "t1a | t1b" in text
    assert "t2a | t2b" in text
    assert "中间正文" in text


def test_nested_table_flattens_into_host_cell_without_duplication() -> None:
    # 嵌套表格随宿主单元格展开，不再作为独立行重复渲染
    html = (
        '<div><table><tr><td>外1</td><td><table><tr><td>内1</td><td>内2</td></tr></table></td></tr>'
        '<tr><td>外2</td><td>外3</td></tr></table></div>'
    )
    text = extract_text_with_tables(BeautifulSoup(html, "html.parser").find("div"))
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    assert lines == ["外1 | 内1 内2", "外2 | 外3"]
