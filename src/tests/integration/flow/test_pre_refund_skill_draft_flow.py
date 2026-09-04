"""退费候选包必须先进入草稿治理，不得直接进入运行时目录。"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from src.data_platform.storage.skill.draft_in_memory import InMemorySkillDraftStorage
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import get_skill_draft_service
from src.runtime.skill_management.draft_service import SkillDraftService


PREFIX = "/api/v1/medical-insurance-ai-agent"
SKILL_ID = "outpatient_pre_refund_analysis_skill"


def _control_token() -> str:
    payload = {
        "sub": "information-admin",
        "roles": ["information_department"],
        "permissions": ["skill:release:test"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"test.{encoded}.signature"


def _candidate_zip() -> bytes:
    repo_root = Path(__file__).resolve().parents[4]
    candidate = repo_root / "skill_drafts" / SKILL_ID
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in candidate.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, f"{SKILL_ID}/{path.relative_to(candidate).as_posix()}")
    return buffer.getvalue()


def test_pre_refund_candidate_is_visible_only_as_editing_draft(monkeypatch):
    monkeypatch.setenv("SKILL_CONTROL_DEV_MODE", "1")
    draft_service = SkillDraftService(storage=InMemorySkillDraftStorage())
    app = create_app()
    app.dependency_overrides[get_skill_draft_service] = lambda: draft_service
    client = TestClient(app)

    formal = client.get(f"{PREFIX}/infra-skills")
    imported = client.post(
        f"{PREFIX}/infra-skills/drafts/import?source=zip",
        content=_candidate_zip(),
        headers={
            "Authorization": f"Bearer {_control_token()}",
            "filename": f"{SKILL_ID}.zip",
        },
    )
    drafts = client.get(f"{PREFIX}/infra-skills/drafts?skill_id={SKILL_ID}")

    assert formal.status_code == 200
    assert SKILL_ID not in {item["skill_id"] for item in formal.json()}
    assert imported.status_code == 201, imported.text
    assert imported.json()["status"] == "editing"
    assert "scripts/pre_refund_flow.py" in imported.json()["raw_files"]
    assert drafts.status_code == 200
    assert drafts.json()["total"] == 1
    assert drafts.json()["items"][0]["skill_id"] == SKILL_ID
