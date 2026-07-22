import os
import json
import traceback
import pandas as pd

from .normalizer import normalize_policy_text
from .structure_parser import (
    parse_policy_structure,
    flatten_nodes,
    node_to_dict,
)
from .context_builder import build_context_for_tree
from .semantic_chunker import generate_semantic_chunks

POLICY_META_COLUMNS = [
    "主题分类",
    "标题",
    "发布日期",
    "废止日期",
    "有效性",
    "成文日期",
    "实施日期",
    "发文机构",
    "发文字号",
    "文件来源",
    "详情页URL",
    "附件名称",
    "附件URL",
    "附件本地路径",
    "爬取时间",
    "爬取状态",
    "内容大小",
]


INPUT_XLSX = "./raw/北京市医保局政策文件-3.xlsx"

OUTPUT_DIR = "./raw"

STRUCTURE_JSON_DIR = os.path.join(OUTPUT_DIR, "structure_json")
os.makedirs(STRUCTURE_JSON_DIR, exist_ok=True)

NODES_EXCEL = os.path.join(
    OUTPUT_DIR,
    "policy_structure_nodes.xlsx"
)

CHUNKS_EXCEL = os.path.join(
    OUTPUT_DIR,
    "policy_semantic_chunks.xlsx"
)

ERROR_EXCEL = os.path.join(
    OUTPUT_DIR,
    "policy_parse_errors.xlsx"
)


def safe_filename(name: str) -> str:
    invalid = r'\/:*?"<>|'
    for c in invalid:
        name = name.replace(c, "_")
    return name[:150]

def build_policy_meta(row) -> dict:
    meta = {}

    for col in POLICY_META_COLUMNS:
        value = row.get(col, "")

        if pd.isna(value):
            value = ""

        meta[col] = str(value).strip()

    return meta

def parse_single_policy(row_index: int, title: str, content: str, policy_meta: dict):
    clean_text = normalize_policy_text(content)

    root = parse_policy_structure(
        text=clean_text,
        document_title=title,
        policy_meta=policy_meta,
    )

    build_context_for_tree(
        root,
        document_title=title,
    )

    nodes = flatten_nodes(root)
    semantic_chunks = generate_semantic_chunks(root)

    return root, nodes, semantic_chunks


def export_structure_json(title: str, root):
    filename = safe_filename(title) + ".json"

    path = os.path.join(
        STRUCTURE_JSON_DIR,
        filename
    )

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            node_to_dict(root),
            f,
            ensure_ascii=False,
            indent=2
        )


def main():
    print("=" * 80)
    print("开始读取政策 Excel")
    print("=" * 80)

    if not os.path.exists(INPUT_XLSX):
        raise FileNotFoundError(
            f"未找到输入文件：{INPUT_XLSX}"
        )

    df = pd.read_excel(INPUT_XLSX)

    print(f"共读取 {len(df)} 条政策数据")

    required_columns = [
        "标题",
        "正文内容"
    ]

    for col in required_columns:
        if col not in df.columns:
            raise Exception(
                f"Excel 缺少字段：{col}"
            )

    all_node_rows = []
    all_chunk_rows = []
    error_rows = []

    total = len(df)

    for idx, row in df.iterrows():

        title = str(row.get("标题", "")).strip()
        content = str(row.get("正文内容", "")).strip()

        print("\n" + "-" * 80)
        print(f"[{idx + 1}/{total}] 正在解析：{title}")

        if not content:
            print("正文为空，跳过")
            continue

        try:
            policy_meta = build_policy_meta(row)

            root, nodes, chunks = parse_single_policy(
                row_index=idx,
                title=title,
                content=content,
                policy_meta=policy_meta,
            )

            # 导出结构树 JSON
            export_structure_json(title, root)

            # 节点表
            for node in nodes:

                meta_cols = {f"meta_{k}": v for k, v in node.policy_meta.items()}

                all_node_rows.append({
                    "policy_index": idx,
                    "policy_title": title,
                    **meta_cols,

                    "node_id": node.node_id,
                    "parent_id": node.parent_id,

                    "level": node.level,
                    "marker": node.marker,

                    "title": node.title,
                    "text": node.text,

                    "path_text": " / ".join(node.path),

                    "full_context_text": node.full_context_text,

                    "children_count": len(node.children),

                    "order_no": node.order_no,
                })

            # semantic chunks
            for chunk in chunks:

                meta_cols = {f"meta_{k}": v for k, v in policy_meta.items()}

                chunk["policy_index"] = idx
                chunk["policy_title"] = title
                chunk.update(meta_cols)

                all_chunk_rows.append(chunk)

            print(
                f"完成：节点数={len(nodes)}，语义块={len(chunks)}"
            )

        except Exception as e:

            error_msg = str(e)

            print(f"解析失败：{error_msg}")
            traceback.print_exc()

            error_rows.append({
                "policy_index": idx,
                "policy_title": title,
                "error_msg": error_msg,
            })

    print("\n")
    print("=" * 80)
    print("开始导出结果")
    print("=" * 80)

    # 导出节点
    node_df = pd.DataFrame(all_node_rows)

    node_df.to_excel(
        NODES_EXCEL,
        index=False
    )

    print(f"已导出：{NODES_EXCEL}")

    # 导出 semantic chunk
    chunk_df = pd.DataFrame(all_chunk_rows)

    chunk_df.to_excel(
        CHUNKS_EXCEL,
        index=False
    )

    print(f"已导出：{CHUNKS_EXCEL}")

    # 导出错误
    if error_rows:
        error_df = pd.DataFrame(error_rows)

        error_df.to_excel(
            ERROR_EXCEL,
            index=False
        )

        print(f"已导出错误文件：{ERROR_EXCEL}")

    print("\n")
    print("=" * 80)
    print("全部完成")
    print("=" * 80)

    print(f"政策总数：{total}")
    print(f"结构节点数：{len(all_node_rows)}")
    print(f"语义块数：{len(all_chunk_rows)}")
    print(f"错误数：{len(error_rows)}")


if __name__ == "__main__":
    main()