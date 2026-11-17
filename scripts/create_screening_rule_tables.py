"""在 bjyb（SQL Server）上幂等创建筛查结果表 — issue #86。

问数读的是 dbo.ai_screen_*。本脚本只建表、补列，不写规则、不跑数。
连接沿用 MSSQL_*。密码未在环境里时，从 gitignore 的 deploy/docker/.env
读取 SA_PASSWORD，不打印口令。

用法：
    uv run python scripts/create_screening_rule_tables.py          # 建表/补列
    uv run python scripts/create_screening_rule_tables.py --check  # 只读检查
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_platform.storage.screening_rules.sqlserver import (  # noqa: E402
    SqlServerScreeningRuleStorage,
)


def _read_key(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip().strip('"').strip("'")
    return ""


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _docker_env_candidates() -> list[Path]:
    root = Path(__file__).resolve().parent.parent
    found = [root / "deploy" / "docker" / ".env"]
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        found.append(Path(result.stdout.strip()).parent / "deploy" / "docker" / ".env")
    return found


def prepare_mssql_env() -> None:
    """补齐 bjyb 连接变量。已有环境变量优先，不覆盖。"""
    _load_env_file(Path(__file__).resolve().parent.parent / ".env")
    os.environ.setdefault("MSSQL_HOST", "127.0.0.1")
    os.environ.setdefault("MSSQL_PORT", "1433")
    os.environ.setdefault("MSSQL_DATABASE", "bjybdb")
    os.environ.setdefault("MSSQL_USER", "sa")
    if not os.getenv("MSSQL_PASSWORD"):
        for candidate in _docker_env_candidates():
            password = _read_key(candidate, "SA_PASSWORD")
            if password:
                os.environ["MSSQL_PASSWORD"] = password
                break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只读检查结果表是否齐全")
    args = parser.parse_args(argv)
    prepare_mssql_env()
    if not os.getenv("MSSQL_PASSWORD"):
        print("MSSQL_PASSWORD 未配置，不能连接 bjyb。")
        return 2
    store = SqlServerScreeningRuleStorage(ensure=not args.check)
    missing = store.missing_tables()
    if missing:
        print("缺少结果表: " + ", ".join(missing))
        return 1
    print("screening rule tables: " + ("ready" if args.check else "initialized")
          + " (dbo.ai_screen_rule/ai_screen_run/ai_screen_run_rule/ai_screen_finding)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
