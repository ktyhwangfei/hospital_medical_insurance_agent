import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

import hashlib
import base64

# 稳定 ID 的 keyed-hash 密钥：由环境变量注入，禁止硬编码（安全审计发现）。
# 默认值保留仅为兼容历史已入库 node_id；新部署应在首次提取前设置
# POLICY_NODE_ID_SECRET=<强随机值>（python -c "import secrets; print(secrets.token_hex(32))"）。
# 注意：修改密钥会改变生成结果，已入库的 node_id 将失效，需重新提取并重灌向量库。
ID_SECRET_KEY = os.getenv("POLICY_NODE_ID_SECRET", "sdgfxx")
CN_NUM = "一二三四五六七八九十百千万零〇两"


def short_secure_id(raw: str, prefix: str = "n", length: int = 12) -> str:
    """
    生成稳定、定长、较短、不可逆的安全ID。
    同一个 raw + secret 永远生成同一个 ID。
    """
    if not raw:
        return ""

    digest = hashlib.blake2s(
        raw.encode("utf-8"),
        key=ID_SECRET_KEY.encode("utf-8"),
        digest_size=10,
    ).digest()

    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{prefix}_{encoded[:length]}"


@dataclass
class ClauseNode:
    node_id: str
    level: str
    marker: str
    title: str
    text: str
    parent_id: Optional[str] = None
    children: List["ClauseNode"] = field(default_factory=list)
    path: List[str] = field(default_factory=list)
    full_context_text: str = ""
    order_no: int = 0
    policy_meta: dict = field(default_factory=dict)


LEVEL_ORDER = {
    "document": 0,
    "chapter": 1,
    "article": 2,
    "paragraph": 3,      # 一、二、三、
    "subparagraph": 4,   # （一）/(一)
    "item": 5,           # 1. / 1、
    "subitem": 6,        # （1）/(1)
    "proviso": 4,        # 条款直属无编号补充句（但书/本条…），与子项同级，不入栈
}

# 子项级叶子：句号收尾后，后续非编号直属补充句应独立成 proviso，不并入。
# 用结构性信号（句号收尾）判断，不靠「但/本条」关键词启发式（脆弱）。
_LEAF_LEVELS_FOR_PROVISO = frozenset({"subparagraph", "item", "subitem"})
_PROVISO_SENTENCE_END = re.compile(r"[。！？]\s*$")


def _clause_ancestor_in_stack(stack: List[ClauseNode]) -> Optional[ClauseNode]:
    """从栈顶往栈底找最近的条款级节点（article/paragraph），用于挂直属补充句。

    补充句逻辑上属于其所在「条」或「段」，不属于最后一个子项。
    找不到条款级祖先时返回 None（退化到原归入栈顶行为，保持安全）。
    """
    for node in reversed(stack):
        if node.level in {"article", "paragraph"}:
            return node
    return None

PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("chapter", re.compile(rf"^(第[{CN_NUM}]+章)\s*(.*)$")),
    ("article", re.compile(rf"^(第[{CN_NUM}]+条)\s*(.*)$")),
    ("paragraph", re.compile(rf"^([{CN_NUM}]+[、.．])\s*(.*)$")),
    # 关键修正：同时支持中文全角括号和英文半角括号
    ("subparagraph", re.compile(rf"^([（(][{CN_NUM}]+[）)])\s*(.*)$")),
    ("item", re.compile(r"^(\d+[、.．])\s*(.*)$")),
    ("subitem", re.compile(r"^([（(]\d+[）)])\s*(.*)$")),
]

CHAPTER_RE = PATTERNS[0][1]
ARTICLE_RE = PATTERNS[1][1]

# 用于把一行里粘连的层级标记拆开：
# 例如：3.超过4万元的部分...。(二)在二级医院发生的医疗费用：
INLINE_MARKER_RE = re.compile(
    rf"(?<!^)(?P<marker>[（(][{CN_NUM}]+[）)]|[（(]\d+[）)]|\d+[、.．])"
)

BREADCRUMB_OR_WEB_UI_LINES = {
    "政务公开",
    "政策公开",
    "政策文件",
    "其他文件",
    "收藏",
    "取消收藏",
    "相关解读",
    "相关政策",
    ">",
}

META_LINE_RE = re.compile(r"^\[(发文字号|发文机构|发布日期|有效性)\]$|^政府令$|^〔\d+〕$|^\d+号$")

# 政府网站页脚/导航 boilerplate：逐行丢弃，避免污染末尾条款（不破坏正文完整性）。
# [来源: 用户要求 req4 — 排除正文前后的无用内容]
WEB_BOILERPLATE_RE = re.compile(
    r"^("
    r"建议意见|法律声明|网站地图|关于我们|使用帮助|网站无障碍|无障碍阅读|无障碍|"
    r"移动版|简体版|繁体版|简体|繁体|简|繁|"
    r"官方微信|官方微博|官方抖音|官方客户端|官方APP|扫码|二维码|关注我们|"
    r"返回顶部|返回首页|打印|分享|收藏|取消收藏|字体大小|字体：|"
    r"北京政务服务网|访问我的专属空间|智能问答|首页|通知公告|要闻动态|"
    r"政务公开|政务服务|政民互动|本网站|一网通查|一网通办|高级搜索|"
    r"政策文件搜索|政策文件|搜索结果|包含以下全部的关键词|包含以下的完整关|"
    r"相关解读|相关政策|其他文件|政策公开|我要咨询|我要投诉|办事服务|"
    r"中共中央|国务院"
    r")$"
    r"|^(服务热线|咨询电话|联系电话|客服电话|传真|邮政编码|地址)[：:]"
    r"|^(主办|承办|协办|指导单位|技术支持)[：:]"
    r"|^(政府网站标识码|网站标识码)[：:]?"
    r"|^(京公网安备|公网安备|ICP备案|备案序号|京ICP|粤ICP|沪ICP)"
    r"|^(版权所有|Copyright|©|All Right)"
)
# 中文落款日期（如「二○一○年四月十五日」「2010年4月15日」），单独成行视为落款，丢弃
# 注意：网页常用 ○(U+25CB 圆圈) 代替 〇(U+3007)，用显式转义确保两者都在字符类里
SIGNATURE_DATE_RE = re.compile(
    r"^[\u4e00-\u9fff\u3007\u25cb0-9]{2,}年"
    r"[\u4e00-\u9fff\u3007\u25cb0-9]{1,3}月"
    r"[\u4e00-\u9fff\u3007\u25cb0-9]{1,4}日?$"
)
# 发文机构落款（单独成行的机构名，如「北京市人力资源和社会保障局」）。
# 保守判定：纯中文、4-20字、以机构后缀结尾；仅在末尾落款区出现，不破坏条款正文。
ORG_SIGNATURE_RE = re.compile(r"^[\u4e00-\u9fff]{4,20}(局|委员会|办公室|办公厅|厅|部|院|中心|管理局|监督管理局|管理中心)$")


def detect_clause_level(line: str):
    line = normalize_marker(line.strip())
    for level, pattern in PATTERNS:
        match = pattern.match(line)
        if match:
            marker = normalize_marker(match.group(1))
            content = match.group(2).strip()
            return level, marker, content
    return None, "", line


def normalize_marker(text: str) -> str:
    """统一括号形态，避免 (一) 和 （一） 被当成两类。"""
    return text.replace("(", "（").replace(")", "）")


def split_inline_clause_markers(line: str) -> List[str]:
    """
    将粘在同一行的下级编号拆成独立行。
    只在标记前面已有正文时拆分，不影响行首标记。
    """
    line = line.strip()
    if not line:
        return []

    parts: List[str] = []
    start = 0
    for match in INLINE_MARKER_RE.finditer(line):
        # 前一个字符如果是冒号/句号/分号/换行后的正文，通常说明新编号粘连了
        prev = line[match.start() - 1]
        if prev in "。；;：:\n" or match.group("marker").startswith(("（", "(")):
            before = line[start:match.start()].strip()
            if before:
                parts.append(before)
            start = match.start()
    tail = line[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def clean_and_split_lines(text: str, *, drop_catalog: bool = True) -> List[str]:
    raw_lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in BREADCRUMB_OR_WEB_UI_LINES:
            continue
        if META_LINE_RE.match(line):
            continue
        # 丢弃政府网站页脚/导航 boilerplate 与落款日期/机构签名（req4）
        if WEB_BOILERPLATE_RE.match(line):
            continue
        if SIGNATURE_DATE_RE.match(line):
            continue
        if ORG_SIGNATURE_RE.match(line):
            continue
        raw_lines.extend(split_inline_clause_markers(line))

    if drop_catalog:
        raw_lines = remove_catalog_lines(raw_lines)

    return raw_lines


def remove_catalog_lines(lines: List[str]) -> List[str]:
    """
    删除“目录”及其后面的章标题清单，只保留真正正文里的章节。

    典型结构：
    目录
    第一章 总则
    第二章 基本医疗保险基金
    ...
    第一章 总则
    第一条 ...

    判断正文起点：目录之后，第一个“章标题”且其后第一个有效行是“第X条”。
    """
    result: List[str] = []
    i = 0
    while i < len(lines):
        if lines[i] != "目录":
            result.append(lines[i])
            i += 1
            continue

        body_start = None
        j = i + 1
        while j < len(lines):
            if CHAPTER_RE.match(lines[j]):
                k = j + 1
                if k < len(lines) and ARTICLE_RE.match(lines[k]):
                    body_start = j
                    break
            j += 1

        if body_start is not None:
            # 跳过“目录”和目录清单，从真正正文章标题继续解析
            i = body_start
        else:
            # 兜底：跳过目录及连续章标题；遇到非章标题恢复
            i += 1
            while i < len(lines) and CHAPTER_RE.match(lines[i]):
                i += 1
    return result


def parse_policy_structure(
    text: str,
    document_title: str = "",
    policy_meta: Optional[dict] = None,
    *,
    drop_catalog: bool = True,
) -> ClauseNode:
    policy_meta = policy_meta or {}

    root = ClauseNode(
        node_id="root",
        level="document",
        marker="",
        title=document_title,
        text=document_title,
        parent_id=None,
        order_no=0,
        policy_meta=policy_meta,
    )

    stack = [root]
    counters = {level: 0 for level in LEVEL_ORDER if level != "document"}
    global_order = 0
    lines = clean_and_split_lines(text, drop_catalog=drop_catalog)

    for line in lines:
        level, marker, content = detect_clause_level(line)

        if level:
            global_order += 1
            counters[level] += 1

            current_order = LEVEL_ORDER[level]
            for k, v in LEVEL_ORDER.items():
                if v > current_order and k in counters:
                    counters[k] = 0

            while stack and LEVEL_ORDER[stack[-1].level] >= LEVEL_ORDER[level]:
                stack.pop()

            parent = stack[-1] if stack else root
            raw_node_id = build_node_id(parent, level, marker, counters[level], content)
            node_id = short_secure_id(raw_node_id)

            title = f"{marker} {content}".strip()
            node = ClauseNode(
                node_id=node_id,
                level=level,
                marker=marker,
                title=title,
                text=title,
                parent_id=parent.node_id,
                order_no=global_order,
                policy_meta=policy_meta,
            )

            parent.children.append(node)
            stack.append(node)
        else:
            # 非编号正文行。若当前是 root，丢弃（网页标题/通知元信息不并入正文）。
            if not stack or stack[-1] is root:
                continue
            top = stack[-1]
            top_text = (top.text or "").strip()
            # 子项级叶子句号收尾后，本行是条款直属补充（如「但…」「本条第一款…」），
            # 不并入该子项，独立成 proviso 叶子挂到所属条款 → 避免污染子项单元内容
            # （否则 leaf_match 子串包含会把补充句的提取记录误挂到该子项）。
            if (
                top.level in _LEAF_LEVELS_FOR_PROVISO
                and _PROVISO_SENTENCE_END.search(top_text)
            ):
                clause = _clause_ancestor_in_stack(stack)
                if clause is not None and clause is not root:
                    global_order += 1
                    raw_pid = f"{clause.node_id}|proviso||{global_order}|{line[:32]}"
                    proviso = ClauseNode(
                        node_id=short_secure_id(raw_pid),
                        level="proviso",
                        marker="",
                        title=line,
                        text=line,
                        parent_id=clause.node_id,
                        order_no=global_order,
                        policy_meta=policy_meta,
                    )
                    clause.children.append(proviso)
                    continue  # proviso 不入栈：后续直属补充句各自独立成叶
            # 续句（子项未收尾，或栈顶是条款级本身）：归入栈顶
            top.text = f"{top_text}\n{line}".strip()

    enrich_paths_and_context(root)
    return root


def build_node_id(parent: ClauseNode, level: str, marker: str, seq: int, content: str = "") -> str:
    """
    ID 原始串加入 parent_id + level + marker，避免同一父节点下 1. 2. 重复导致冲突。
    content 只取前 32 字，兼顾稳定性和去重。
    """
    safe_level = {
        "chapter": "ch",
        "article": "art",
        "paragraph": "p",
        "subparagraph": "sp",
        "item": "it",
        "subitem": "sit",
    }.get(level, level)
    return f"{parent.node_id}|{safe_level}|{marker}|{seq}|{content[:32]}"


def flatten_nodes(root: ClauseNode) -> List[ClauseNode]:
    result: List[ClauseNode] = []

    def walk(node: ClauseNode):
        result.append(node)
        for child in node.children:
            walk(child)

    walk(root)
    return result


def ancestors_of(node: ClauseNode, by_id: dict) -> List[ClauseNode]:
    ancestors = []
    parent_id = node.parent_id
    while parent_id and parent_id in by_id:
        parent = by_id[parent_id]
        if parent.level != "document":
            ancestors.append(parent)
        parent_id = parent.parent_id
    ancestors.reverse()
    return ancestors


def enrich_paths_and_context(root: ClauseNode) -> None:
    nodes = flatten_nodes(root)
    by_id = {n.node_id: n for n in nodes}

    for node in nodes:
        if node.level == "document":
            node.path = [node.title] if node.title else []
            node.full_context_text = node.text
            continue

        ancestors = ancestors_of(node, by_id)
        path_titles = [a.title for a in ancestors] + [node.title]
        node.path = path_titles

        context_lines = []
        if root.title:
            context_lines.append(f"【文件】{root.title}")
        context_lines.append(f"【结构路径】{' / '.join(path_titles)}")

        parent_context = [a.text for a in ancestors if a.text]
        if parent_context:
            context_lines.append("【上级语境】")
            context_lines.extend(parent_context)

        context_lines.append("【当前内容】")
        context_lines.append(node.text)
        node.full_context_text = "\n".join(context_lines).strip()


def is_structural_only_node(node: ClauseNode) -> bool:
    """
    纯结构节点不进入规则候选：
    - document/chapter；
    - 有子节点的父级节点，作为上下文，不作为原子规则；
    - 只有“第X条/第X章/（一）标题：”这类引导语且无实质谓词/数值/义务表达。
    """
    if node.level in {"document", "chapter"}:
        return True
    if node.children:
        return True

    text = re.sub(r"\s+", "", node.text or "")
    marker = re.escape(node.marker or "")
    title_without_marker = re.sub(rf"^{marker}", "", text).strip()
    if title_without_marker.endswith(("：", ":")) and len(title_without_marker) <= 40:
        return True
    return False


def is_rule_candidate_node(node: ClauseNode) -> bool:
    """
    第一阶段只做“候选过滤”，不做最终DSL语义判定。
    规则候选应当是叶子节点，且含有支付比例、金额、条件、不得/应当/可以等可执行约束。
    """
    if is_structural_only_node(node):
        return False

    text = node.text or ""
    rule_signal = re.search(
        r"(应当|不得|不予|可以|按照|支付|缴纳|享受|报销|负担|限额|起付|超过|不满|以上|以下|%|％|\d+元|\d+万元|\d+年|\d+%)",
        text,
    )
    return bool(rule_signal)


def infer_chunk_type(text: str, *, is_rule_candidate: bool) -> str:
    if not is_rule_candidate:
        return "context"
    if re.search(r"不予|不得|除外|不能|未造成|不符合", text):
        return "exception_rule"
    if re.search(r"最高支付限额|最高数额|累计最高|限额", text):
        return "cap_rule"
    if re.search(r"起付标准|起付", text):
        return "deductible_rule"
    if re.search(r"支付\d+%|支付\d+％|个人支付|职工支付|比例", text):
        return "ratio_rule"
    if re.search(r"人员范围|参加|享受|适用", text):
        return "eligibility_rule"
    return "general_policy"


def node_to_dict(node: ClauseNode) -> dict:
    is_rule = is_rule_candidate_node(node)
    return {
        "node_id": node.node_id,
        "level": node.level,
        "marker": node.marker,
        "title": node.title,
        "text": node.text,
        "parent_id": node.parent_id,
        "path": node.path,
        "path_text": " / ".join(node.path),
        "full_context_text": node.full_context_text,
        "order_no": node.order_no,
        "has_children": bool(node.children),
        "is_rule_candidate": is_rule,
        "chunk_type": infer_chunk_type(node.text, is_rule_candidate=is_rule),
        "content_size": len(node.full_context_text or node.text or ""),
        "policy_meta": node.policy_meta,
        "children": [node_to_dict(child) for child in node.children],
    }


if __name__ == "__main__":
    # 简单自测：验证半角括号、目录和粘连拆分
    demo = """
目录
第一章 总则
第二章 待遇
第一章 总则
第一条 测试。
第二章 待遇
第二条 按照以下比例支付：
(一)在三级医院发生的医疗费用：
1.起付标准至3万元的部分，统筹基金支付85%，职工支付15%；
2.超过3万元至4万元的部分，统筹基金支付90%，职工支付10%；
3.超过4万元的部分，统筹基金支付95%，职工支付5%。(二)在二级医院发生的医疗费用：
1.起付标准至3万元的部分，统筹基金支付87%，职工支付13%；
"""
    root = parse_policy_structure(demo, document_title="测试政策")
    for n in flatten_nodes(root):
        if n.level != "document":
            print(n.level, n.marker, n.title, "parent=", n.parent_id, "rule=", is_rule_candidate_node(n))
