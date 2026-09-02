"""为本地数据治理控制面幂等配置持久主密钥。"""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from cryptography.fernet import Fernet


KEY_NAME = "DATA_GOVERNANCE_MASTER_KEY"


def configure_project(project_root: Path, env_path: Path | None = None) -> bool:
    """确保项目根 .env 含有效主密钥；新增返回 True，已存在返回 False。"""
    root = project_root.resolve(strict=True)
    env_file = env_path or root / ".env"
    if env_file.parent.resolve(strict=True) != root or env_file.name != ".env":
        raise ValueError("只允许配置项目根目录的 .env")
    if env_file.is_symlink():
        raise ValueError("拒绝配置符号链接 .env")

    existing = env_file.read_bytes() if env_file.exists() else b""
    for raw_line in existing.decode("utf-8").splitlines():
        if not raw_line.startswith(f"{KEY_NAME}="):
            continue
        value = raw_line.split("=", 1)[1].strip().strip('"\'')
        Fernet(value.encode("ascii"))
        print("数据治理主密钥已存在")
        return False

    separator = b"" if not existing or existing.endswith((b"\n", b"\r")) else b"\n"
    content = existing + separator + KEY_NAME.encode("ascii") + b"=" + Fernet.generate_key() + b"\n"
    with NamedTemporaryFile(dir=root, prefix=".env.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, env_file)
    finally:
        temporary.unlink(missing_ok=True)
    print("数据治理主密钥已配置")
    return True


def main() -> int:
    configure_project(Path(__file__).resolve().parent.parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
