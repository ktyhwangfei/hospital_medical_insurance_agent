import re
from typing import List, Dict
from .structure_parser import ClauseNode, flatten_nodes


RULE_KEYWORDS = [
    "起付", "起付线", "起付标准",
    "报销比例", "支付比例", "基金支付", "医保基金", "统筹基金支付",
    "封顶线", "最高支付限额",
    "90天", "九十天", "周期", "年度", "自然年度",
    "第一次", "第二次", "以后", "减半",
    "应当", "按照", "标准", "范围", "条件",
    "参保", "缴费", "待遇", "报销", "支付",
    "住院", "门诊", "门特", "特殊病",
]

STRUCTURE_ONLY_LEVELS = {"document", "chapter"}
PARENT_CONTEXT_LEVELS = {"article", "paragraph", "subparagraph"}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def is_structure_only_node(node: ClauseNode) -> bool:
    """
    纯结构节点不作为规则：
    - 章
    - 目录项
    - 只有标题、没有实质正文的父节点
    """
    text = normalize_text(node.text)
    title = normalize_text(node.title)

    if node.level in STRUCTURE_ONLY_LEVELS:
        return True

    if text in {"目录", "相关解读", "相关政策"}:
        return True

    if node.level == "article" and node.children and text == title:
        return True

    return False


def is_rule_candidate_node(node: ClauseNode) -> bool:
    """
    规则候选只看当前节点自身，不直接用 full_context_text。
    否则父级上下文里有“支付比例”，会污染子节点/结构节点判断。
    """
    if is_structure_only_node(node):
        return False

    text = node.text or ""

    if not text.strip():
        return False

    return any(keyword in text for keyword in RULE_KEYWORDS)


def classify_chunk_type(text: str) -> str:
    if not text:
        return "unknown"

    if any(k in text for k in ["起付", "起付线", "起付标准"]):
        return "deductible_rule"

    if any(k in text for k in ["报销比例", "支付比例", "基金支付", "统筹基金支付"]):
        return "ratio_rule"

    if any(k in text for k in ["封顶线", "最高支付限额"]):
        return "cap_rule"

    if any(k in text for k in ["90天", "九十天", "周期", "自然年度", "年度"]):
        return "period_rule"

    if any(k in text for k in ["参保", "人员范围", "适用范围", "条件"]):
        return "eligibility_rule"

    if any(k in text for k in ["除外", "不包括", "另有规定", "不予支付"]):
        return "exception_rule"

    return "general_policy"


def should_output_node(node: ClauseNode) -> bool:
    """
    输出原则：
    1. document/chapter 永不输出
    2. 叶子节点输出
    3. 有子节点的父节点，只有在自身包含实质规则文本时才输出
    4. 纯结构父节点不输出
    """
    if node.level == "document":
        return False

    if is_structure_only_node(node):
        return False

    has_children = bool(node.children)

    if not has_children:
        return True

    # 父节点本身有独立规则语义时才输出
    return is_rule_candidate_node(node)


def generate_semantic_chunks(root: ClauseNode) -> List[Dict]:
    chunks = []

    for node in flatten_nodes(root):
        if not should_output_node(node):
            continue

        has_children = bool(node.children)
        is_rule = is_rule_candidate_node(node)

        chunks.append({
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "level": node.level,
            "marker": node.marker,
            "path_text": " / ".join(node.path),
            "current_text": node.text,
            "full_context_text": node.full_context_text,
            "has_children": has_children,
            "is_rule_candidate": is_rule,
            "chunk_type": classify_chunk_type(node.full_context_text if is_rule else node.text),
            "content_size": len(node.full_context_text or node.text or ""),
        })

    return chunks