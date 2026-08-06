"""Skill 草稿管理 API 测试（T2a）。

覆盖草稿 CRUD、复制、乐观锁 409、权限门禁。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.skill.draft_in_memory import (
    InMemorySkillDraftStorage,
)
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import get_skill_draft_service
from src.runtime.skill_management.draft_service import SkillDraftService

PREFIX = "/api/v1/medical-insurance-ai-agent"


def _control_token(
    user_id: str = "information-admin",
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
) -> str:
    payload = {
        "sub": user_id,
        "roles": roles or ["information_department"],
        "permissions": permissions or ["skill:release:test"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"test.{encoded}.signature"


def _auth_headers(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or _control_token()}"}


class _FakeLoader:
    def __init__(self) -> None:
        self.skills: dict[str, SimpleNamespace] = {}

    def get(self, skill_id: str):
        return self.skills.get(skill_id)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SKILL_CONTROL_DEV_MODE", "1")
    app = create_app()
    loader = _FakeLoader()
    service = SkillDraftService(
        storage=InMemorySkillDraftStorage(),
        loader=loader,
        skills_root="/nonexistent-skills-root",
    )
    app.dependency_overrides[get_skill_draft_service] = lambda: service
    client = TestClient(app)
    client._loader = loader  # type: ignore[attr-defined]
    return client


# ── 创建 ──────────────────────────────────────────────────────────


def test_create_draft_returns_201(client):
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={
            "skill_id": "my_skill",
            "skill_name": "My Skill",
            "business_action": "explain",
            "business_object": "settlement",
            "include_keywords": ["费用"],
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["skill_id"] == "my_skill"
    assert data["source_type"] == "template"
    assert data["status"] == "editing"
    assert data["revision"] == 1
    assert data["structured_config"]["business_mounting"]["business_action"] == "explain"


def test_create_draft_requires_auth(client):
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
    )
    assert resp.status_code == 401


def test_create_draft_disabled_without_dev_mode(client, monkeypatch):
    monkeypatch.delenv("SKILL_CONTROL_DEV_MODE", raising=False)
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "SKILL_CONTROL_DISABLED"


# ── 复制 ──────────────────────────────────────────────────────────


def test_copy_skill_creates_draft(client):
    client._loader.skills["src_skill"] = SimpleNamespace(  # type: ignore[attr-defined]
        skill_id="src_skill",
        skill_name="Source Skill",
        business_action="explain",
        business_object="settlement",
        include_keywords=["费用"],
        excluded_intents=[],
        manifest={"description": "源", "owner": "信息科"},
    )
    resp = client.post(
        f"{PREFIX}/infra-skills/src_skill/copy",
        json={"new_skill_id": "copied_skill"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["source_type"] == "copy"
    assert data["source_skill_id"] == "src_skill"
    assert data["skill_id"] == "copied_skill"


def test_copy_skill_source_not_found(client):
    resp = client.post(
        f"{PREFIX}/infra-skills/missing/copy",
        json={"new_skill_id": "copied"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "SKILL_SOURCE_NOT_FOUND"


# ── 列表与详情 ────────────────────────────────────────────────────


def test_list_drafts(client):
    client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    )
    resp = client.get(f"{PREFIX}/infra-skills/drafts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(item["deleted_at"] is None for item in data["items"])


def test_get_draft(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    resp = client.get(f"{PREFIX}/infra-skills/drafts/{create['draft_id']}")
    assert resp.status_code == 200
    assert resp.json()["draft_id"] == create["draft_id"]


def test_get_draft_not_found(client):
    resp = client.get(f"{PREFIX}/infra-skills/drafts/missing")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "SKILL_DRAFT_NOT_FOUND"


# ── 保存（乐观锁）────────────────────────────────────────────────


def test_save_draft_updates_and_increments_revision(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    resp = client.patch(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}",
        json={
            "structured_config": {
                "basic": {"skill_id": "s1", "skill_name": "Renamed"},
                "business_mounting": {
                    "business_action": "query",
                    "business_object": "benefit",
                    "include_keywords": [],
                    "excluded_intents": [],
                },
                "inputs": [],
                "schemas": {},
            },
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["revision"] == 2
    assert data["skill_name"] == "Renamed"


def test_save_draft_stale_revision_returns_409(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    # 第一次保存成功
    client.patch(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}",
        json={
            "structured_config": {"basic": {"skill_name": "v2"}},
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )
    # 用过期 revision 再保存 → 409
    resp = client.patch(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}",
        json={
            "structured_config": {"basic": {"skill_name": "v3"}},
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "SKILL_DRAFT_CONFLICT"


def test_save_draft_not_found(client):
    resp = client.patch(
        f"{PREFIX}/infra-skills/drafts/missing",
        json={"structured_config": {}, "expected_revision": 1},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


# ── 删除 ──────────────────────────────────────────────────────────


def test_delete_draft_soft_deletes(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    resp = client.delete(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}?expected_revision=1",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    # 再 GET 应 404
    assert client.get(f"{PREFIX}/infra-skills/drafts/{create['draft_id']}").status_code == 404


def test_delete_draft_stale_revision_returns_409(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    client.patch(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}",
        json={"structured_config": {}, "expected_revision": 1},
        headers=_auth_headers(),
    )
    resp = client.delete(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}?expected_revision=1",
        headers=_auth_headers(),
    )
    assert resp.status_code == 409


# ── 导入端点（P3 实现）───────────────────────────────────


def test_import_zip_creates_draft(client):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "pkg/skill_manifest.yaml",
            "skill_id: imp\nskill_name: Imp\nbusiness_action: explain\nbusiness_object: settlement\n",
        )
        zf.writestr("pkg/SKILL.md", "# Imp")
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/import?source=zip",
        content=buf.getvalue(),
        headers={**_auth_headers(), "filename": "pkg.zip"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["source_type"] == "import"
    assert data["skill_id"] == "imp"
    assert "SKILL.md" in data["raw_files"]


def test_import_rejects_path_traversal(client):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.yaml", "x")
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/import?source=zip",
        content=buf.getvalue(),
        headers={**_auth_headers(), "filename": "x.zip"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "SKILL_IMPORT_REJECTED"
