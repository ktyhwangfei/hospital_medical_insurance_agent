"""清理错位的可信问题冷启动草稿（Issue #37 修复）。

早期 seed_trusted_questions.py 从政策问答历史（policy_qa_trajectories，
结算单解释类问题）挖掘入库的 tq_seed_* 草稿全部无 query_plan，
与受控问数场景双重错位（问题类型错 + 无执行能力），且 approve 闸门
上线后它们永远无法通过审核。本脚本物理删除这批存量草稿。

用法：
    uv run python scripts/cleanup_trusted_question_seeds.py            # 只打印（默认）
    uv run python scripts/cleanup_trusted_question_seeds.py --apply    # 实际删除
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="清理 tq_seed_* 无 query_plan 的错位草稿")
    parser.add_argument("--apply", action="store_true", help="实际删除（默认 dry-run）")
    args = parser.parse_args()

    from src.config.production import DATABASE_URL
    from src.data_platform.storage.postgresql.client import PostgreSQLClient

    client = PostgreSQLClient(DATABASE_URL)
    # LIKE 模式走参数绑定：避免 '%' 被 psycopg 误认为占位符
    rows = client.execute(
        "SELECT question_id, standard_question, status FROM trusted_questions "
        "WHERE question_id LIKE %s AND query_plan IS NULL",
        ("tq_seed_%",),
    )
    print(f"命中错位草稿: {len(rows)} 条")
    for row in rows:
        print(f"  [{row['status']}] {row['question_id']} {row['standard_question']}")

    if not args.apply:
        print("dry-run 结束；加 --apply 实际删除。")
        return

    deleted = client.execute(
        "DELETE FROM trusted_questions "
        "WHERE question_id LIKE %s AND query_plan IS NULL "
        "RETURNING question_id",
        ("tq_seed_%",),
    )
    print(f"删除完成: {len(deleted)} 条。")


if __name__ == "__main__":
    main()
