"""提取单元去重存量迁移（设计 docs/superpowers/specs/2026-08-25-extraction-unit-dedup-design.md §4.3）。

规则：同 doc+hash 组内保留带 unit 的行（updated_at 最新者优先），NULL 行置 archived。
幂等：重复执行无新增变更。--rollback 按同样分组逆向恢复（仅恢复本次脚本写入的行，
依赖迁移记录表 migrate_dedup_log）。
用法：python scripts/migrate_dedup_extractions.py [--dry-run|--rollback]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

LOG_DDL = """
CREATE TABLE IF NOT EXISTS migrate_dedup_log (
    run_id VARCHAR(64) PRIMARY KEY,
    archived_ids TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def find_groups(client: PostgreSQLClient) -> list[dict]:
    rows = client.execute(
        """SELECT doc_id, source_text_hash,
                  array_agg(extraction_id ORDER BY (unit_id IS NULL), updated_at DESC) AS ids,
                  count(*) FILTER (WHERE status <> 'archived') AS active_cnt,
                  count(*) FILTER (WHERE unit_id IS NOT NULL AND status <> 'archived') AS active_with_unit
           FROM policy_extractions
           GROUP BY doc_id, source_text_hash
           HAVING count(*) FILTER (WHERE status <> 'archived') > 1"""
    )
    return rows or []


def run(dry_run: bool = False) -> None:
    client = PostgreSQLClient(DATABASE_URL)
    client.execute(LOG_DDL)
    groups = find_groups(client)
    if not groups:
        print("无活跃重复组，无需迁移。")
        return
    total = 0
    archived_ids: list[str] = []
    for g in groups:
        ids = list(g["ids"])
        # 保留：带 unit 的活跃行中最新的 1 条（ids 已按 unit 非空优先、updated_at 降序）
        keep = None
        for eid in ids:
            row = client.execute(
                "SELECT unit_id, status FROM policy_extractions WHERE extraction_id=%s", (eid,),
            )[0]
            if row["unit_id"] is not None and row["status"] != "archived":
                keep = eid
                break
        if keep is None:
            # 全 NULL 组：保留最新 1 条
            keep = ids[0]
        victims = [e for e in ids if e != keep and
                   (client.execute("SELECT status FROM policy_extractions WHERE extraction_id=%s",
                                   (e,))[0]["status"]) != "archived"]
        for vid in victims:
            print(f"archive {vid} (doc={g['doc_id'][:16]} keep={keep})")
            archived_ids.append(vid)
            total += 1
            if not dry_run:
                client.execute(
                    "UPDATE policy_extractions SET status='archived', updated_at=now() "
                    "WHERE extraction_id=%s", (vid,),
                )
    if dry_run:
        print(f"[dry-run] 将归档 {total} 行，未写入。")
        return
    if archived_ids:
        import uuid
        client.execute(
            "INSERT INTO migrate_dedup_log (run_id, archived_ids) VALUES (%s, %s)",
            (f"dd_{uuid.uuid4().hex[:12]}", archived_ids),
        )
    print(f"已归档 {total} 行。")


def rollback() -> None:
    client = PostgreSQLClient(DATABASE_URL)
    rows = client.execute(
        "SELECT run_id, archived_ids FROM migrate_dedup_log ORDER BY created_at DESC LIMIT 1"
    )
    if not rows:
        print("无迁移记录，无需回滚。")
        return
    ids = rows[0]["archived_ids"]
    for eid in ids:
        client.execute(
            "UPDATE policy_extractions SET status='draft', updated_at=now() WHERE extraction_id=%s",
            (eid,),
        )
    client.execute("DELETE FROM migrate_dedup_log WHERE run_id=%s", (rows[0]["run_id"],))
    print(f"已回滚 {len(ids)} 行。")


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        run(dry_run="--dry-run" in sys.argv)
