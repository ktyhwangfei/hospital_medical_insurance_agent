"""初始化或只读检查门诊 PostgreSQL 存储。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_platform.storage.postgresql.outpatient_store import OutpatientPostgresStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只读检查表和视图是否齐全")
    args = parser.parse_args(argv)
    store = OutpatientPostgresStore()
    if args.check:
        ready = store.check_schema()
        print("outpatient store: ready" if ready else "outpatient store: incomplete")
        return 0 if ready else 1
    store.ensure_schema()
    print("outpatient store: initialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
