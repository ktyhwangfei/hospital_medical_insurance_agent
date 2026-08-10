"""leaf_match body 级去重边界测试（问题2根因）。

迭代 19 的 body 去重设计意图：政策文档含「修改决定 + 修改后正文」两段逐字重复，
相同 body 只保留一个（正文优先）。但去重未区分父路径——一级/二级医院不同档位
文本恰好相同（如「3. 超过4万元的部分，统筹基金支付97%，职工支付3%；」）也被
误删，导致合法叶子消失、其 knowledge 无处挂靠（n_1lOz1yAQLbM4 案例）。

修复原则：两个叶子**都是正文段**（path 含第X章）时不去重；仅当一个是修改决定段、
一个是正文段时才按「正文优先」去重。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
    parse_kept_leaves,
)


def _leaf_bodies(kept) -> list[str]:
    return [getattr(lf, "text", "") or "" for lf in kept]


def test_same_body_across_different_hosp_levels_both_kept():
    """一级3档与二级3档文本相同（正文段）：两个叶子都应保留。"""
    content = """第四章 基本医疗保险待遇
第三十六条 在一个结算期内职工和退休人员发生的医疗费用，按医院等级和费用数额采取分段计算、累加支付的办法，由基本医疗保险统筹基金和个人按照以下比例分担：
（一） 在三级医院发生的医疗费用：
1. 起付标准至3万元的部分，统筹基金支付85%，职工支付15%；
（二） 在二级医院发生的医疗费用：
3. 超过4万元的部分，统筹基金支付97%，职工支付3%；
（三） 在一级医院以及家庭病床发生的医疗费用：
3. 超过4万元的部分，统筹基金支付97%，职工支付3%；
（四） 退休人员个人支付比例为职工支付比例的60%。
"""
    _root, _by_id, _all_leaves, kept = parse_kept_leaves(content, "测试文档")
    bodies = _leaf_bodies(kept)
    # 两个 97%/3% 叶子都要在（二级3档 + 一级3档）
    same = [b for b in bodies if "统筹基金支付97%" in b]
    assert len(same) == 2, f"应保留两个正文段叶子，实际 {len(same)}: {same}"


def test_amendment_duplicate_still_dropped():
    """修改决定段 vs 正文段 body 相同：只保留正文段（原去重意图保持）。"""
    content = """二、第三十六条修改为：
在一个结算期内职工和退休人员发生的医疗费用，按医院等级和费用数额采取分段计算、累加支付的办法，由基本医疗保险统筹基金和个人按照以下比例分担：
（一） 在三级医院发生的医疗费用：
1. 起付标准至3万元的部分，统筹基金支付85%，职工支付15%；
第四章 基本医疗保险待遇
第三十六条 在一个结算期内职工和退休人员发生的医疗费用，按医院等级和费用数额采取分段计算、累加支付的办法，由基本医疗保险统筹基金和个人按照以下比例分担：
（一） 在三级医院发生的医疗费用：
1. 起付标准至3万元的部分，统筹基金支付85%，职工支付15%；
"""
    _root, _by_id, _all_leaves, kept = parse_kept_leaves(content, "测试文档")
    bodies = _leaf_bodies(kept)
    main = [b for b in bodies if "统筹基金支付85%" in b]
    # 正文段优先：该 body 只保留 1 个（修改决定版被丢弃）
    assert len(main) == 1, f"修改决定重复应只保留 1 个正文版，实际 {len(main)}"
