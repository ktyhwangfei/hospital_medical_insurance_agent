from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from scripts.configure_data_governance_local import configure_project


def test_configure_project_adds_one_persistent_key_without_exposing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"MODEL_BASE_URL=https://model.example\n")

    configure_project(tmp_path)
    first_bytes = env_file.read_bytes()
    key_line = next(
        line for line in first_bytes.decode("utf-8").splitlines()
        if line.startswith("DATA_GOVERNANCE_MASTER_KEY=")
    )
    key = key_line.split("=", 1)[1]
    Fernet(key.encode("ascii"))
    assert first_bytes.count(b"DATA_GOVERNANCE_MASTER_KEY=") == 1
    assert key not in capsys.readouterr().out

    configure_project(tmp_path)

    assert env_file.read_bytes() == first_bytes
    assert key not in capsys.readouterr().out


def test_configure_project_rejects_outside_env_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(ValueError, match="项目根目录"):
        configure_project(project_root, tmp_path / "outside.env")


def test_configure_project_rejects_symlink_env(tmp_path: Path) -> None:
    target = tmp_path / "target.env"
    target.write_text("", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    env_file = project_root / ".env"
    try:
        env_file.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"当前环境不能创建符号链接: {exc}")

    with pytest.raises(ValueError, match="符号链接"):
        configure_project(project_root)


def test_server_scripts_manage_only_the_scoped_worker() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    start_script = (repository_root / "start-servers.ps1").read_text(encoding="utf-8")
    stop_script = (repository_root / "stop-servers.ps1").read_text(encoding="utf-8")

    assert "run_outpatient_sync_worker.py" in start_script
    assert "-WindowStyle Hidden" in start_script
    assert "worker_pid" in start_script
    assert "run_outpatient_sync_worker.py" in stop_script
    assert "$WORKDIR" in stop_script
    assert "worker_pid" in stop_script
    assert "Get-Process python" not in stop_script
