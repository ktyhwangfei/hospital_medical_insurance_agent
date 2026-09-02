from pathlib import Path


def test_env_file_is_read_as_utf8() -> None:
    script = (Path(__file__).parents[3] / "start-servers.ps1").read_text(encoding="utf-8")

    assert "Get-Content -LiteralPath $envFile -Encoding UTF8" in script
