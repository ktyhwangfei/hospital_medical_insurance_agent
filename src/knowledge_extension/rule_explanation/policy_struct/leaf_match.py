"""
叶子匹配工具（后端版，复刻前端 src/apps/portal/.../units/page.tsx 的逻辑）。

用途：计算 policy_documents 列表的 pending_count，使其与前端「单元」页 stats.draft
口径完全一致——以「去重后的叶子单元」为计数单位，排除匹配不到叶子的孤儿提取记录。

[来源: 排障 doc_466953309ccf/doc_ebea08e4d59d 的孤儿 draft 记录导致前后端待处理数不一致]
"""
from __future__ import annotations

import re
from typing import Any

from src.knowledge_extension.rule_explanation.policy_struct.structure_parser import (
    parse_policy_structure,
)

# 与前端 normText 一致：剥除空白与标点
_WS = re.compile(r"[\s，。、；：“”‘’（）()【】\[\]「」.,;:％%]")


def norm_text(s: str) -> str:
    return _WS.sub("", s or "")


def _leaf_body(node: Any) -> str:
    """剥除叶子文本的结构标记前缀（marker 不属于正文）。"""
    body = node.text or ""
    mk = node.marker or ""
    if mk and body.startswith(mk):
        body = body[len(mk):]
    return body.lstrip()


def _lcs_len(a: str, b: str) -> int:
    """最长公共子串长度（DP）。"""
    m, n = len(a), len(b)
    if not m or not n:
        return 0
    prev = [0] * (n + 1)
    best = 0
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        ai = a[i - 1]
        for j in range(1, n + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def collect_leaves(node: Any, out: list | None = None) -> list:
    if out is None:
        out = []
    ch = getattr(node, "children", []) or []
    if not getattr(node, "has_children", True) or not ch:
        if getattr(node, "level", "") != "document":
            out.append(node)
        return out
    for c in ch:
        collect_leaves(c, out)
    return out


def flatten_by_id(node: Any, m: dict | None = None) -> dict:
    if m is None:
        m = {}
    m[node.node_id] = node
    for c in (getattr(node, "children", []) or []):
        flatten_by_id(c, m)
    return m


def _path_text_parts(leaf: Any, by_id: dict) -> list[str]:
    parts: list[str] = []
    cur = by_id.get(leaf.parent_id) if leaf.parent_id else None
    while cur:
        if cur.level != "document":
            parts.insert(0, norm_text(cur.text or ""))
        cur = by_id.get(cur.parent_id) if cur.parent_id else None
    parts.append(norm_text(leaf.text or ""))
    return parts


def _fnv1a(s: str) -> str:
    """FNV-1a 32-bit，按 Unicode 码点（与前端 charCodeAt 在 BMP 内一致）。"""
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, "08x")


def _path_hash(leaf: Any, by_id: dict) -> str:
    return _fnv1a("|".join(_path_text_parts(leaf, by_id)))


def _is_main_text_path(parts: list[str]) -> bool:
    """path 是否为「正文」段（而非「修改决定」段）。

    正文章节形如「第四章 基本医疗保险待遇」「第三十六条 …」；
    修改决定段形如「二、第三十六条修改为」「一、第X条修改为」等。
    以 path 中是否出现「第X章」作为正文标志（修改决定通常不引入新章）。
    """
    return any("第" in p and "章" in p for p in parts)


def parse_kept_leaves(content_text: str, title: str):
    """解析结构 → (root, by_id, all_leaves, kept_leaves)。

    kept_leaves 为 pathHash 去重后的叶子，与前端 derived 单元口径一致。

    迭代 19 反思修复：额外做 body 级去重——政策文档常含「修改决定 + 修改后
    正文」两段逐字重复文本（如《关于修改…的决定》正文末尾附修改后全文），
    两个不同 path 的叶子 body 完全相同，导致 match_leaves 对同一 fact 返回
    多个 node_id → unit_id 留空。此处相同 body 只保留一个，优先保留正文段
    （path 含「第X章」）而非修改决定段。
    """
    root = parse_policy_structure(content_text or "", document_title=title or "")
    by_id = flatten_by_id(root)
    all_leaves = collect_leaves(root)
    all_leaves.sort(key=lambda n: getattr(n, "order_no", 0) or 0)
    seen: set[str] = set()
    kept: list = []
    kept_body: dict[str, int] = {}  # body → kept 索引，用于 body 级去重
    for lf in all_leaves:
        h = _path_hash(lf, by_id)
        body = norm_text(_leaf_body(lf))
        if h in seen:
            continue
        seen.add(h)
        if body in kept_body:
            existing_idx = kept_body[body]
            existing = kept[existing_idx]
            existing_main = _is_main_text_path(_path_text_parts(existing, by_id))
            current_main = _is_main_text_path(_path_text_parts(lf, by_id))
            if existing_main and current_main:
                # 两个都是正文段（如不同医院等级下相同比例文本）：合法内容，不去重。
                # kept_body 更新指向本版，后续修改决定段仍能正确判定为「跳过」。
                kept_body[body] = len(kept)
                kept.append(lf)
                continue
            if existing_main:
                continue  # 已保留正文版，跳过本（可能是修改决定）版
            # 本版更可能是正文 → 用本版替换（修改决定版让位）
            kept[existing_idx] = lf
            continue
        kept_body[body] = len(kept)
        kept.append(lf)
    return root, by_id, all_leaves, kept


def match_leaves(src: str, leaves: list) -> list[str]:
    """提取记录 source_text → 叶子定位（复刻前端 matchLeaves）。

    ① 双向全包含（取最长）；② 回退最长公共子串（≥较短文本50%且≥10字）。
    """
    s = norm_text(src)
    if not s or len(s) < 6:
        return []
    contained: list[tuple[str, int]] = []
    for lf in leaves:
        lt = norm_text(_leaf_body(lf))
        if len(lt) < 6:
            continue
        if lt in s:
            contained.append((lf.node_id, len(lt)))
        elif s in lt:
            contained.append((lf.node_id, len(s)))
    if contained:
        mx = max(c[1] for c in contained)
        return [c[0] for c in contained if c[1] == mx]
    scored: list[tuple[str, int]] = []
    for lf in leaves:
        lt = norm_text(_leaf_body(lf))
        if len(lt) < 6:
            continue
        lcs = _lcs_len(lt, s)
        if lcs >= 10 and lcs >= min(len(lt), len(s)) * 0.5:
            scored.append((lf.node_id, lcs))
    if scored:
        mx = max(c[1] for c in scored)
        return [c[0] for c in scored if c[1] == mx]
    return []
