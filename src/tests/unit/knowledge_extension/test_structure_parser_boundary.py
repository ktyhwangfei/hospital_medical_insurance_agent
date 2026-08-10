"""单元边界修复测试（问题1）：子项句号收尾后的直属补充句不并入该子项。

复现缺陷：
- 第三十六条（四）"退休人员60%"之后紧跟的「但…最高支付限额」「本条第一款…调整方案」
  是第三十六条的直属补充，不属于（四）子项。
- 修复前 parse 把它们 append 进（四）body（3 句拼接），导致 leaf_match.match_leaves
  用子串包含（s in lt）把这两句的提取记录也挂到（四）单元 → 审核页混入。

修复目标：
- 子项级叶子（subparagraph/item/subitem）句号收尾后，后续非编号直属补充句
  独立成 proviso 叶子，挂到所属条款（article/paragraph），不并入该子项。
- 用结构性信号（句号收尾）判断，不用「但/本条」关键词启发式。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.policy_struct.structure_parser import (
    flatten_nodes,
    parse_policy_structure,
)

SAMPLE = (
    "第四章 基本医疗保险待遇\n"
    "第三十六条 在一个结算期内职工和退休人员发生的医疗费用，由基本医疗保险统筹基金"
    "和个人按照以下比例分担：\n"
    "（一）在三级医院发生的医疗费用：\n"
    "1.起付标准至3万元的部分，统筹基金支付85%，职工支付15%；\n"
    "2.超过3万元至4万元的部分，统筹基金支付90%，职工支付10%。\n"
    "（四）退休人员个人支付比例为职工支付比例的60%。\n"
    "但基本医疗保险统筹基金按照比例支付的最高数额不得超过本规定第三十三条规定的最高支付限额。\n"
    "本条第一款所列基本医疗保险统筹基金支付比例需要调整时，由市劳动保障行政部门会同市财政部门提出调整方案。\n"
)


def _find_by_marker(nodes, marker):
    return [n for n in nodes if n.marker == marker]


def test_subparagraph_does_not_absorb_trailing_proviso_sentences():
    """（四）子项句号收尾后的直属补充句不应并入（四）body。"""
    root = parse_policy_structure(SAMPLE, document_title="测试")
    nodes = flatten_nodes(root)

    si = _find_by_marker(nodes, "（四）")
    assert si and len(si) == 1, "未找到（四）子项"
    text = si[0].text
    assert "退休人员个人支付比例为职工支付比例的60%" in text
    assert "最高支付限额" not in text, f"（四）不应包含封顶线补充句：{text!r}"
    assert "调整方案" not in text, f"（四）不应包含调整程序补充句：{text!r}"


def test_proviso_sentences_become_independent_leaves_under_clause():
    """直属补充句应独立成 proviso 叶子，挂到所属条款（第三十六条）。"""
    root = parse_policy_structure(SAMPLE, document_title="测试")
    nodes = flatten_nodes(root)

    provisos = [n for n in nodes if n.level == "proviso"]
    assert len(provisos) == 2, f"应有2个 proviso 叶子，实际 {len(provisos)}"

    proviso_texts = "".join(n.text for n in provisos)
    assert "最高支付限额" in proviso_texts
    assert "调整方案" in proviso_texts

    article = _find_by_marker(nodes, "第三十六条")
    assert article and len(article) == 1
    for p in provisos:
        assert p.parent_id == article[0].node_id, "proviso 应挂到第三十六条 article"


def test_item_continuation_inside_subparagraph_not_broken():
    """回归：子项内部的编号 item（分号续句）仍正常，不被误判为 proviso。"""
    root = parse_policy_structure(SAMPLE, document_title="测试")
    nodes = flatten_nodes(root)

    items = [n for n in nodes if n.level == "item"]
    assert len(items) == 2, f"应有2个 item，实际 {len(items)}"
    joined = " ".join(n.text for n in items)
    assert "统筹基金支付85%" in joined
    assert "统筹基金支付90%" in joined
    # item 内容不应被拆成 proviso
    assert not any(n.level == "proviso" and "85%" in n.text for n in nodes)
