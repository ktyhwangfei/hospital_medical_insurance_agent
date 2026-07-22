from typing import List
from .structure_parser import ClauseNode


def build_context_for_tree(root: ClauseNode, document_title: str = "") -> ClauseNode:
    """
    为每个节点生成：
    - path
    - full_context_text
    """

    def walk(node: ClauseNode, ancestors: List[ClauseNode]):
        titles = []

        if document_title:
            titles.append(document_title)

        for ancestor in ancestors:
            if ancestor.level != "document" and ancestor.title:
                titles.append(ancestor.title)

        if node.level != "document" and node.title:
            titles.append(node.title)

        node.path = titles

        if node.level == "document":
            node.full_context_text = node.text or document_title
        else:
            node.full_context_text = build_full_context_text(
                document_title=document_title,
                ancestors=ancestors,
                node=node,
            )

        for child in node.children:
            walk(child, ancestors + [node])

    walk(root, [])
    return root


def build_full_context_text(
    document_title: str,
    ancestors: List[ClauseNode],
    node: ClauseNode,
    max_ancestor_count: int = 4,
) -> str:
    context_parts = []

    if document_title:
        context_parts.append(f"【文件】{document_title}")

    path_parts = []
    for ancestor in ancestors:
        if ancestor.level != "document" and ancestor.title:
            path_parts.append(ancestor.title)

    if node.title:
        path_parts.append(node.title)

    if path_parts:
        context_parts.append(f"【结构路径】{' / '.join(path_parts)}")

    parent_context = []

    useful_ancestors = [
        a for a in ancestors
        if a.level != "document" and a.text
    ][-max_ancestor_count:]

    for ancestor in useful_ancestors:
        parent_context.append(ancestor.text)

    if parent_context:
        context_parts.append("【上级语境】")
        context_parts.append("\n".join(deduplicate_keep_order(parent_context)))

    context_parts.append("【当前内容】")
    context_parts.append(node.text)

    return "\n".join(context_parts).strip()


def deduplicate_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []

    for item in items:
        normalized = item.strip()
        if not normalized:
            continue

        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result