import os
import pandas as pd

from .rule_candidate_detector import (
    detect_rule_candidates
)


INPUT_FILE = "./raw/policy_semantic_chunks.xlsx"

OUTPUT_FILE = "./raw/policy_nodes1.xlsx"

SUMMARY_FILE = "./raw/policy_rule_statistics.xlsx"


def export_statistics(df):

    stats = []

    # 类型统计
    type_counter = {}

    for _, row in df.iterrows():

        if not row["is_rule_candidate"]:
            continue

        types = str(
            row.get("candidate_types", "")
        ).split(",")

        for t in types:

            t = t.strip()

            if not t:
                continue

            type_counter[t] = (
                type_counter.get(t, 0) + 1
            )

    for k, v in sorted(
        type_counter.items(),
        key=lambda x: x[1],
        reverse=True
    ):
        stats.append({
            "rule_type": k,
            "count": v
        })

    stats_df = pd.DataFrame(stats)

    stats_df.to_excel(
        SUMMARY_FILE,
        index=False
    )

    print(f"统计结果已导出：{SUMMARY_FILE}")


def main():

    print("=" * 80)
    print("开始规则候选识别")
    print("=" * 80)

    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(
            f"未找到文件：{INPUT_FILE}"
        )

    df = pd.read_excel(INPUT_FILE)

    print(f"读取 chunk 数量：{len(df)}")

    result_rows = detect_rule_candidates(df)

    result_df = pd.DataFrame(result_rows)

    # 排序
    result_df = result_df.sort_values(
        by=[
            "is_rule_candidate",
            "rule_score",
        ],
        ascending=[False, False]
    )

    result_df.to_excel(
        OUTPUT_FILE,
        index=False
    )

    print(f"规则候选已导出：{OUTPUT_FILE}")

    export_statistics(result_df)

    # 输出统计
    total = len(result_df)

    candidate_count = (
        result_df["is_rule_candidate"]
        .fillna(False)
        .sum()
    )

    strong_count = (
        result_df["candidate_level"] == "strong"
    ).sum()

    medium_count = (
        result_df["candidate_level"] == "medium"
    ).sum()

    weak_count = (
        result_df["candidate_level"] == "weak"
    ).sum()

    print("\n")
    print("=" * 80)
    print("规则候选识别完成")
    print("=" * 80)

    print(f"总 chunk 数：{total}")
    print(f"规则候选数：{candidate_count}")

    print(f"强规则：{strong_count}")
    print(f"中规则：{medium_count}")
    print(f"弱规则：{weak_count}")


if __name__ == "__main__":
    main()