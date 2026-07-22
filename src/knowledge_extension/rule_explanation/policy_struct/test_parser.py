import json
import pandas as pd

from .normalizer import normalize_policy_text
from .structure_parser import parse_policy_structure, node_to_dict, flatten_nodes
from .context_builder import build_context_for_tree
from .semantic_chunker import generate_semantic_chunks


SAMPLE_TEXT = """
北京市城乡居民基本医疗保险办法实施细则

第一条 根据《北京市城乡居民基本医疗保险办法》及国家和本市有关规定，结合本市实际，制定本实施细则。

第二条 参加本市城乡居民基本医疗保险的人员范围：

（一）男年满60周岁和女年满50周岁，且无其它基本医疗保障的本市户籍城乡居民；

（二）男年满16周岁不满60周岁、女年满16周岁不满50周岁，且无其它基本医疗保障的本市户籍城乡居民：
1. 参照本市城乡社会救助对象医疗救助政策享受医疗待遇的退养人员；
2. 参照本市城乡社会救助对象医疗救助政策享受医疗待遇的退离居委会老积极分子；
3. 在外埠办理退休手续且无基本医疗保障，来京取得本市户籍的人员；

第三条 普通高等院校，是指按照国家规定批准设立的全日制普通高等学校。

第四条 本细则第二条规定的参保人员在办理参保缴费手续时，应当分别提交相关证明材料。
（一）在外埠办理退休手续且无基本医疗保障，来京取得本市户籍的人员，提交本人户口簿；
（二）具有本市户籍在外省市、国外或港澳台地区就读且无基本医疗保障的学生，提交本人学生证明；
"""


def run_demo():
    document_title = "北京市城乡居民基本医疗保险办法实施细则"

    clean_text = normalize_policy_text(SAMPLE_TEXT)

    root = parse_policy_structure(
        text=clean_text,
        document_title=document_title,
    )

    build_context_for_tree(root, document_title=document_title)

    nodes = flatten_nodes(root)
    chunks = generate_semantic_chunks(root)

    print("\n========== 结构树 JSON ==========\n")
    print(json.dumps(node_to_dict(root), ensure_ascii=False, indent=2))

    print("\n========== 语义 Chunk ==========\n")
    for chunk in chunks:
        print("\n---")
        print("node_id:", chunk["node_id"])
        print("level:", chunk["level"])
        print("path:", chunk["path_text"])
        print("chunk_type:", chunk["chunk_type"])
        print("is_rule_candidate:", chunk["is_rule_candidate"])
        print(chunk["full_context_text"])

    export_debug_excel(nodes, chunks)


def export_debug_excel(nodes, chunks):
    node_rows = []
    for node in nodes:
        node_rows.append({
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "level": node.level,
            "marker": node.marker,
            "title": node.title,
            "text": node.text,
            "path_text": " / ".join(node.path),
            "full_context_text": node.full_context_text,
            "order_no": node.order_no,
            "children_count": len(node.children),
        })

    with pd.ExcelWriter("./policy_structure_debug.xlsx", engine="openpyxl") as writer:
        pd.DataFrame(node_rows).to_excel(writer, sheet_name="structure_nodes", index=False)
        pd.DataFrame(chunks).to_excel(writer, sheet_name="semantic_chunks", index=False)

    print("\n已导出调试文件：./policy_structure_debug.xlsx")


if __name__ == "__main__":
    run_demo()