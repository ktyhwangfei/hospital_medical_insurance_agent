"""Comprehensive API endpoint tests for all 9 MCP management endpoints.

Endpoints under test (prefix: /api/v1/medical-insurance-ai-agent/mcp):
  1. GET  /storage/health
  2. GET  /servers
  3. POST /servers
  4. GET  /servers/{server_id}
  5. GET  /capabilities
  6. POST /capabilities
  7. GET  /capabilities/{capability_id}
  8. GET  /capabilities/by-server/{server_id}
  9. DELETE /capabilities/{capability_id}

NOTE: MCP storage is a module-level singleton (src.runtime.api.mcp_routes._storage),
      shared across all TestClient(create_app()) calls within a process. All tests
      therefore share a single client instance and use unique IDs to avoid collisions.
"""

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app

PREFIX = "/api/v1/medical-insurance-ai-agent/mcp"

# Single client instance shared by all tests to avoid repeated lifespan overhead.
_client: TestClient | None = None


def _get_client() -> TestClient:
    """Lazy-initialized shared TestClient singleton."""
    global _client
    if _client is None:
        _client = TestClient(create_app())
    return _client


# ── 1. GET /storage/health ────────────────────────────────────────────────────


def test_mcp_storage_health():
    """GET /mcp/storage/health returns health status dict."""
    client = _get_client()
    resp = client.get(f"{PREFIX}/storage/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in {"healthy", "degraded", "unhealthy"}
    assert "postgres_available" in data
    assert "redis_available" in data


# ── 2. GET /servers ───────────────────────────────────────────────────────────


def test_list_mcp_servers():
    """GET /mcp/servers returns a list."""
    client = _get_client()
    resp = client.get(f"{PREFIX}/servers")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── 3. POST /servers + 4. GET /servers/{server_id} ─────────────────────────


def test_register_and_get_mcp_server():
    """POST /mcp/servers registers a server, GET /mcp/servers/{id} retrieves it."""
    client = _get_client()
    server_id = "test-routes-server-001"

    body = {
        "server_id": server_id,
        "name": "Test Routes MCP Server",
        "endpoint": "https://mcp-routes.example.com/sse",
        "transport": "sse",
    }
    resp = client.post(f"{PREFIX}/servers", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_id"] == server_id
    assert data["name"] == "Test Routes MCP Server"
    assert data["endpoint"] == "https://mcp-routes.example.com/sse"
    assert data["transport"] == "sse"

    # Retrieve by ID
    resp = client.get(f"{PREFIX}/servers/{server_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_id"] == server_id
    assert data["name"] == "Test Routes MCP Server"


def test_get_mcp_server_not_found():
    """GET /mcp/servers/{id} returns 404 for non-existent server."""
    client = _get_client()
    resp = client.get(f"{PREFIX}/servers/nonexistent-server-routes-xyz")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_code"] == "SERVER_NOT_FOUND"


# ── 5. GET /capabilities ──────────────────────────────────────────────────────


def test_list_mcp_capabilities():
    """GET /mcp/capabilities returns a list."""
    client = _get_client()
    resp = client.get(f"{PREFIX}/capabilities")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── 6. POST /capabilities + 7. GET /capabilities/{capability_id} ─────────────


def test_register_and_get_mcp_capability():
    """POST /mcp/capabilities registers a capability, GET retrieves it."""
    client = _get_client()
    server_id = "test-routes-cap-server-001"
    cap_id = "test-routes-cap-001"

    # Prerequisite: register a server
    client.post(f"{PREFIX}/servers", json={
        "server_id": server_id,
        "name": "Cap Routes Server",
        "endpoint": "https://cap-routes.example.com",
        "transport": "stdio",
    })

    # Register capability
    body = {
        "capability_id": cap_id,
        "server_id": server_id,
        "name": "Test Routes Capability",
        "description": "A capability created during routes test",
        "capability_type": "tool",
        "risk_level": "low",
    }
    resp = client.post(f"{PREFIX}/capabilities", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["capability_id"] == cap_id
    assert data["name"] == "Test Routes Capability"
    assert data["capability_type"] == "tool"
    assert data["risk_level"] == "low"
    assert data["enabled"] is True

    # Retrieve by ID
    resp = client.get(f"{PREFIX}/capabilities/{cap_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["capability_id"] == cap_id
    assert data["server_id"] == server_id


def test_get_mcp_capability_not_found():
    """GET /mcp/capabilities/{id} returns 404 for non-existent capability."""
    client = _get_client()
    resp = client.get(f"{PREFIX}/capabilities/nonexistent-cap-routes-xyz")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_code"] == "CAPABILITY_NOT_FOUND"


# ── 8. GET /capabilities/by-server/{server_id} ────────────────────────────────


def test_list_capabilities_by_server():
    """GET /mcp/capabilities/by-server/{id} returns capabilities filtered by server."""
    client = _get_client()
    server_id = "test-routes-by-server-001"
    cap_id_1 = "test-routes-cap-bysrv-001"
    cap_id_2 = "test-routes-cap-bysrv-002"

    # Prerequisite: register a server and two capabilities
    client.post(f"{PREFIX}/servers", json={
        "server_id": server_id,
        "name": "ByServer Routes Server",
        "endpoint": "https://bysrv-routes.example.com",
        "transport": "stdio",
    })

    client.post(f"{PREFIX}/capabilities", json={
        "capability_id": cap_id_1,
        "server_id": server_id,
        "name": "Capability Alpha",
        "description": "First capability on this server",
        "capability_type": "tool",
        "risk_level": "low",
    })
    client.post(f"{PREFIX}/capabilities", json={
        "capability_id": cap_id_2,
        "server_id": server_id,
        "name": "Capability Beta",
        "description": "Second capability on this server",
        "capability_type": "resource",
        "risk_level": "medium",
    })

    # Filter by server
    resp = client.get(f"{PREFIX}/capabilities/by-server/{server_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    assert all(c["server_id"] == server_id for c in data)
    returned_ids = {c["capability_id"] for c in data}
    assert cap_id_1 in returned_ids
    assert cap_id_2 in returned_ids


def test_list_capabilities_by_server_empty():
    """GET /mcp/capabilities/by-server/{id} returns empty list for unknown server."""
    client = _get_client()
    resp = client.get(f"{PREFIX}/capabilities/by-server/nonexistent-server-routes-xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0


# ── 9. DELETE /capabilities/{capability_id} ──────────────────────────────────


def test_delete_mcp_capability():
    """DELETE /mcp/capabilities/{id} deletes the capability and returns confirmation."""
    client = _get_client()
    server_id = "test-routes-del-server-001"
    cap_id = "test-routes-cap-del-001"

    # Prerequisite: register server and capability
    client.post(f"{PREFIX}/servers", json={
        "server_id": server_id,
        "name": "Delete Routes Server",
        "endpoint": "https://del-routes.example.com",
        "transport": "stdio",
    })
    client.post(f"{PREFIX}/capabilities", json={
        "capability_id": cap_id,
        "server_id": server_id,
        "name": "Capability To Delete",
        "description": "Will be deleted in this test",
        "capability_type": "tool",
        "risk_level": "low",
    })

    # Delete
    resp = client.delete(f"{PREFIX}/capabilities/{cap_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}

    # Verify deleted via GET
    resp = client.get(f"{PREFIX}/capabilities/{cap_id}")
    assert resp.status_code == 404


def test_delete_mcp_capability_not_found():
    """DELETE /mcp/capabilities/{id} returns 404 for non-existent capability."""
    client = _get_client()
    resp = client.delete(f"{PREFIX}/capabilities/nonexistent-cap-del-routes-xyz")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_code"] == "CAPABILITY_NOT_FOUND"


# ── CRUD lifecycle: full create → read → list → delete → verify 404 ──────────


def test_mcp_crud_lifecycle():
    """Tests the complete CRUD lifecycle for MCP servers and capabilities
    within a single client session."""
    client = _get_client()
    sid = "test-lifecycle-routes-server"
    cid = "test-lifecycle-routes-cap"

    # ── CREATE server ──
    resp = client.post(f"{PREFIX}/servers", json={
        "server_id": sid,
        "name": "Lifecycle Routes Server",
        "endpoint": "https://lifecycle-routes.example.com",
        "transport": "streamable_http",
    })
    assert resp.status_code == 200
    assert resp.json()["server_id"] == sid

    # ── READ server ──
    resp = client.get(f"{PREFIX}/servers/{sid}")
    assert resp.status_code == 200
    assert resp.json()["server_id"] == sid

    # ── LIST servers includes the new server ──
    resp = client.get(f"{PREFIX}/servers")
    assert resp.status_code == 200
    all_servers = resp.json()
    assert any(s["server_id"] == sid for s in all_servers)

    # ── CREATE capability ──
    resp = client.post(f"{PREFIX}/capabilities", json={
        "capability_id": cid,
        "server_id": sid,
        "name": "Lifecycle Routes Capability",
        "description": "Created during lifecycle routes test",
        "capability_type": "tool",
        "risk_level": "low",
    })
    assert resp.status_code == 200
    assert resp.json()["capability_id"] == cid

    # ── READ capability ──
    resp = client.get(f"{PREFIX}/capabilities/{cid}")
    assert resp.status_code == 200
    assert resp.json()["capability_id"] == cid

    # ── LIST capabilities includes the new one ──
    resp = client.get(f"{PREFIX}/capabilities")
    assert resp.status_code == 200
    all_caps = resp.json()
    assert any(c["capability_id"] == cid for c in all_caps)

    # ── LIST capabilities by server ──
    resp = client.get(f"{PREFIX}/capabilities/by-server/{sid}")
    assert resp.status_code == 200
    server_caps = resp.json()
    assert all(c["server_id"] == sid for c in server_caps)
    assert cid in {c["capability_id"] for c in server_caps}

    # ── DELETE capability ──
    resp = client.delete(f"{PREFIX}/capabilities/{cid}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}

    # ── VERIFY 404 after delete ──
    resp = client.get(f"{PREFIX}/capabilities/{cid}")
    assert resp.status_code == 404

    # ── Server still exists (DELETE does not cascade to servers) ──
    resp = client.get(f"{PREFIX}/servers/{sid}")
    assert resp.status_code == 200
