"""Skill management API endpoint tests — covers all 6 skill_routes.py endpoints.

Endpoints tested:
  - POST   /skills                          → create
  - GET    /skills                          → list
  - GET    /skills/{skill_id}               → get detail
  - PUT    /skills/{skill_id}               → update
  - DELETE /skills/{skill_id}               → delete
  - GET    /skills/by-role/{role}           → list by role

Error cases:
  - GET    /skills/nonexistent              → 404
  - PUT    /skills/nonexistent              → 404
  - DELETE /skills/nonexistent              → 404
  - POST   /skills with invalid data        → 400
"""

import os
from unittest.mock import patch

# ── Test infrastructure setup ──────────────────────────────────────────────────
#
# Force in-memory storage to avoid PostgreSQL dependency during tests.
os.environ["USE_MEMORY_STORAGE"] = "1"

# Patch psycopg.connect so the GatewayAuditMiddleware (which always attempts a
# PostgreSQL connection for session/audit writes) fails fast instead of hanging
# indefinitely when no database is available. The middleware catches this
# exception gracefully and skips the audit writes.
_patcher = patch("psycopg.connect", side_effect=Exception("No PostgreSQL available in test"))
_patcher.start()

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app

PREFIX = "/api/v1/medical-insurance-ai-agent"
client = TestClient(create_app())

# Use a unique skill ID to avoid collision with seed skills or other test files
SKILL_ID = "test-skill-api-001"
NONEXISTENT = "nonexistent-skill-id"

# ── Helpers ────────────────────────────────────────────────────────────────────


def _assert_skill_not_found(resp):
    """Assert a 404 response with SKILL_NOT_FOUND error detail."""
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["error_code"] == "SKILL_NOT_FOUND"
    assert body["detail"]["message"] == "技能不存在"


def _create_payload(**overrides) -> dict:
    """Return a valid SkillCreateRequest payload, with optional overrides."""
    payload = {
        "skill_id": SKILL_ID,
        "name": "API Test Skill",
        "description": "Skill for API testing",
        "owner": "cashier",
        "steps": [{"step_id": "s1", "tool_id": "tool-1", "depends_on": []}],
        "intent_keywords": ["test", "api"],
        "required_roles": ["doctor"],
        "risk_level": "low",
        "skill_metadata": {"version": "1.0"},
    }
    payload.update(overrides)
    return payload


# ── CRUD Lifecycle ─────────────────────────────────────────────────────────────


def test_crud_lifecycle():
    """Full CRUD lifecycle: create → get → list → update → get updated → delete → 404 after delete."""
    # ── 1. CREATE ──────────────────────────────────────────────────────────
    create_resp = client.post(f"{PREFIX}/skills", json=_create_payload())
    assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
    created = create_resp.json()
    assert created["skill_id"] == SKILL_ID
    assert created["name"] == "API Test Skill"
    assert created["description"] == "Skill for API testing"
    assert created["owner"] == "cashier"
    assert created["risk_level"] == "low"
    assert created["enabled"] is True
    assert len(created["steps"]) == 1
    assert created["steps"][0]["step_id"] == "s1"
    assert created["steps"][0]["tool_id"] == "tool-1"
    assert "test" in created["intent_keywords"]
    assert "doctor" in created["required_roles"]
    assert created["skill_metadata"]["version"] == "1.0"

    # ── 2. GET (detail) ────────────────────────────────────────────────────
    get_resp = client.get(f"{PREFIX}/skills/{SKILL_ID}")
    assert get_resp.status_code == 200, f"Get failed: {get_resp.text}"
    detail = get_resp.json()
    assert detail["skill_id"] == SKILL_ID
    assert detail["name"] == "API Test Skill"

    # ── 3. LIST (verify created skill appears) ─────────────────────────────
    list_resp = client.get(f"{PREFIX}/skills")
    assert list_resp.status_code == 200
    all_skills = list_resp.json()
    assert isinstance(all_skills, list)
    ids = [s["skill_id"] for s in all_skills]
    assert SKILL_ID in ids, f"Skill {SKILL_ID} not found in list"

    # ── 4. UPDATE ──────────────────────────────────────────────────────────
    update_resp = client.put(
        f"{PREFIX}/skills/{SKILL_ID}",
        json={
            "name": "Updated API Test Skill",
            "description": "Updated description",
            "required_roles": ["doctor", "cashier"],
        },
    )
    assert update_resp.status_code == 200, f"Update failed: {update_resp.text}"
    updated = update_resp.json()
    assert updated["skill_id"] == SKILL_ID
    assert updated["name"] == "Updated API Test Skill"
    assert updated["description"] == "Updated description"
    # Fields not sent in update should keep original values
    assert updated["owner"] == "cashier"
    assert updated["risk_level"] == "low"
    assert "doctor" in updated["required_roles"]
    assert "cashier" in updated["required_roles"]

    # ── 5. GET after update ────────────────────────────────────────────────
    get2_resp = client.get(f"{PREFIX}/skills/{SKILL_ID}")
    assert get2_resp.status_code == 200
    detail2 = get2_resp.json()
    assert detail2["name"] == "Updated API Test Skill"
    assert detail2["description"] == "Updated description"

    # ── 6. DELETE ──────────────────────────────────────────────────────────
    delete_resp = client.delete(f"{PREFIX}/skills/{SKILL_ID}")
    assert delete_resp.status_code == 200, f"Delete failed: {delete_resp.text}"
    assert delete_resp.json() == {"deleted": True}

    # ── 7. GET after delete → 404 ──────────────────────────────────────────
    _assert_skill_not_found(client.get(f"{PREFIX}/skills/{SKILL_ID}"))


# ── Error Cases ────────────────────────────────────────────────────────────────


def test_get_nonexistent_skill_returns_404():
    """GET /skills/{nonexistent} → 404."""
    _assert_skill_not_found(client.get(f"{PREFIX}/skills/{NONEXISTENT}"))


def test_update_nonexistent_skill_returns_404():
    """PUT /skills/{nonexistent} → 404."""
    _assert_skill_not_found(
        client.put(
            f"{PREFIX}/skills/{NONEXISTENT}",
            json={"name": "Irrelevant"},
        )
    )


def test_delete_nonexistent_skill_returns_404():
    """DELETE /skills/{nonexistent} → 404."""
    _assert_skill_not_found(client.delete(f"{PREFIX}/skills/{NONEXISTENT}"))


def test_create_skill_with_invalid_data_returns_400():
    """POST /skills with invalid allowed_tools → 400."""
    resp = client.post(
        f"{PREFIX}/skills",
        json=_create_payload(allowed_tools=["valid_tool", ""]),
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["error_code"] == "INVALID_SKILL"
    assert body["detail"]["audit_event"]["event_type"] == "invalid_skill"


# ── List by Role ───────────────────────────────────────────────────────────────


def test_list_skills_by_role_doctor():
    """GET /skills/by-role/doctor returns skills accessible by doctor role."""
    resp = client.get(f"{PREFIX}/skills/by-role/doctor")
    assert resp.status_code == 200
    skills = resp.json()
    assert isinstance(skills, list)
    # Seed skill "settlement_exception_guidance" has required_roles containing
    # "cashier", "medical_office", "information_department" but NOT "doctor".
    # However the by-role filter matches owner OR required_roles. So results
    # will contain whatever seed or other-created skills match "doctor".
    # We just verify the endpoint returns successfully with a list.
    if skills:
        for skill in skills:
            roles = skill.get("required_roles", [])
            owner = skill.get("owner", "")
            assert "doctor" in roles or owner == "doctor", (
                f"Skill {skill['skill_id']} has owner={owner}, required_roles={roles}, "
                f"neither matches 'doctor'"
            )


def test_list_skills_by_role_cashier():
    """GET /skills/by-role/cashier returns at least the seed 'settlement_exception_guidance' skill."""
    resp = client.get(f"{PREFIX}/skills/by-role/cashier")
    assert resp.status_code == 200
    skills = resp.json()
    assert isinstance(skills, list)
    assert len(skills) > 0
    for skill in skills:
        roles = skill.get("required_roles", [])
        owner = skill.get("owner", "")
        assert "cashier" in roles or owner == "cashier", (
            f"Skill {skill['skill_id']} has owner={owner}, required_roles={roles}, "
            f"neither matches 'cashier'"
        )
    # Verify seed data is included
    ids = [s["skill_id"] for s in skills]
    assert "settlement_exception_guidance" in ids
