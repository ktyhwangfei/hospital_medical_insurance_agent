"""清理 dummy 提取脏数据（设计 §4.3 附：运维手动执行）。

删除 source_text 为「示例提取结果（dummy 模式…）」且 status='archived' 的行。
用法：python scripts/purge_dummy_extractions.py [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    client = PostgreSQLClient(DATABASE_URL)
    rows = client.execute(
        "SELECT extraction_id, doc_id FROM policy_extractions "
        "WHERE source_text LIKE '示例提取结果%' AND status='archived'"
    )
    print(f"dummy archived 行数: {len(rows or [])}")
    if not rows or dry_run:
        return
    for r in rows:
        client.execute("DELETE FROM policy_extractions WHERE extraction_id=%s",
                       (r["extraction_id"],))
    print(f"已删除 {len(rows)} 行。")


if __name__ == "__main__":
    main()
