"""可信问题库冷启动脚本（Issue #37）。

从政策问答历史（policy_qa_trajectories.question）挖掘高频问题，
生成 draft 状态可信问题候选入库，等待人工审核（审核流见
/trusted-questions API）。

用法：
    uv run python scripts/seed_trusted_questions.py --dry-run          # 只打印（默认）
    uv run python scripts/seed_trusted_questions.py --apply            # 实际入库
    uv run python scripts/seed_trusted_questions.py --apply --limit 100 --min-frequency 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_platform.storage.trusted_question.trusted_question_ports import (
    TrustedQuestionConflictError,
    TrustedQuestionStorage,
)
from src.runtime.trusted_qa.cold_start import build_draft_questions, mine_frequent_questions


def _load_history_questions() -> list[str]:
    """从 QA 轨迹表读取全部问题原文（真实 PostgreSQL）。"""
    from src.config.production import DATABASE_URL
    from src.data_platform.storage.postgresql.client import PostgreSQLClient

    client = PostgreSQLClient(DATABASE_URL)
    rows = client.execute("SELECT question FROM policy_qa_trajectories")
    return [str(row["question"]) for row in rows if row.get("question")]


def _existing_normalized_questions(storage: TrustedQuestionStorage) -> set[str]:
    from src.runtime.trusted_qa.matcher import normalize_question

    existing = storage.list_questions(limit=1000)
    return {normalize_question(q.standard_question) for q in existing}


def main() -> None:
    parser = argparse.ArgumentParser(description="可信问题库冷启动：QA 历史高频问题挖掘")
    parser.add_argument("--apply", action="store_true", help="实际入库（默认 dry-run）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不入库（默认行为）")
    parser.add_argument("--limit", type=int, default=50, help="候选条数上限（50~100）")
    parser.add_argument("--min-frequency", type=int, default=1, help="最低出现频次")
    args = parser.parse_args()

    questions = _load_history_questions()
    print(f"QA 历史问题总数: {len(questions)}")

    mined = mine_frequent_questions(
        questions, limit=args.limit, min_frequency=args.min_frequency
    )
    print(f"归一化分组后候选: {len(mined)} 条（limit={args.limit}, min_frequency={args.min_frequency}）")

    for rank, item in enumerate(mined, start=1):
        print(f"  {rank:>3}. [{item.frequency:>4} 次] {item.standard_question}")

    if not args.apply:
        print("dry-run 结束；加 --apply 入库为 draft 候选。")
        return

    from src.data_platform.storage.trusted_question.trusted_question_factory import (
        get_trusted_question_storage,
    )

    storage = get_trusted_question_storage()
    existing = _existing_normalized_questions(storage)

    from src.runtime.trusted_qa.matcher import normalize_question

    created, skipped_dup, skipped_existing = 0, 0, 0
    for draft in build_draft_questions(mined):
        if normalize_question(draft.standard_question) in existing:
            skipped_existing += 1
            continue
        try:
            storage.save_question(draft)
            created += 1
        except TrustedQuestionConflictError:
            # question_id 幂等冲突：同一问题重复执行
            skipped_dup += 1
    print(
        f"入库完成: 新建 {created} 条 draft 候选；"
        f"幂等跳过 {skipped_dup}；已存在跳过 {skipped_existing}。"
        "候选一律 draft，需在 /trusted-questions 审核后生效。"
    )


if __name__ == "__main__":
    main()
