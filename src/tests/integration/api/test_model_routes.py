"""
Comprehensive API endpoint tests for ALL 17 model management endpoints.

Groups:
  A. Model Config Management (2 endpoints)  — GET/PUT /model-config
  B. Model Route Management (9 endpoints)   — /model-routes/* CRUD + fallbacks + params
  C. Provider Management     (6 endpoints)  — /model-providers/* CRUD + test
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.runtime.api.model_routes import router as model_router

PREFIX = "/api/v1/medical-insurance-ai-agent"

# Build a minimal FastAPI app with ONLY the model router to avoid
# DB-dependent components from other routers (routes.py's create_data_store,
# knowledge_routes, GatewayAuditMiddleware, etc.). The model router is
# fully self-contained with in-memory dicts.
def _build_app() -> FastAPI:
    app = FastAPI(title="test-model-routes")
    app.include_router(model_router, prefix=PREFIX)
    return app


def _client() -> TestClient:
    return TestClient(_build_app())


# Access module-level in-memory stores for state reset across tests.
import src.runtime.api.model_routes as _mr


def _reset_stores() -> None:
    """Reset all in-memory stores to clean initial condition.

    model_routes.py uses module-level dicts for storage. Since these persist
    across tests in the same session, we reset them before each test.
    """
    from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS
    _mr._routes_store.clear()
    _mr._next_route_id = 1
    _mr._providers_store.clear()
    _mr._fallback_chains.clear()
    _mr._fallback_chains.update({k: list(v) for k, v in FALLBACK_CHAINS.items()})
    _mr._model_params_store.clear()
    _mr._model_params_store.update({k: dict(v) for k, v in MODEL_PARAMS.items()})


# =============================================================================
# Group A: Model Config (2 endpoints)
# =============================================================================


class TestModelConfig:
    """GET /model-config  and  PUT /model-config"""

    # ── GET /model-config ──────────────────────────────────────────────────

    def test_get_model_config_returns_expected_structure(self):
        """GET returns base_url, timeout, max_retries, default_model — no api_key."""
        client = _client()
        resp = client.get(f"{PREFIX}/model-config")
        assert resp.status_code == 200
        data = resp.json()

        assert "base_url" in data
        assert isinstance(data["base_url"], str)
        assert data["base_url"]

        assert "timeout" in data
        assert isinstance(data["timeout"], int)

        assert "max_retries" in data
        assert isinstance(data["max_retries"], int)

        assert "default_model" in data
        assert isinstance(data["default_model"], str)

        # api_key MUST NOT be leaked in GET response
        assert "api_key" not in data

    # ── PUT /model-config ──────────────────────────────────────────────────

    def test_update_model_config_all_fields(self):
        """PUT with all allowed fields updates config and response reflects changes."""
        client = _client()
        resp = client.put(
            f"{PREFIX}/model-config",
            json={
                "base_url": "https://custom-url.example.com/v1",
                "timeout": 60,
                "max_retries": 5,
                "default_model": "custom-test-model",
                "api_key": "sk-this-should-be-masked-internal",
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["base_url"] == "https://custom-url.example.com/v1"
        assert data["timeout"] == 60
        assert data["max_retries"] == 5
        assert data["default_model"] == "custom-test-model"
        # api_key accepted in request but MUST NOT leak in response
        assert "api_key" not in data

    def test_update_model_config_partial_update(self):
        """Sending only one field should merge with existing config, not replace."""
        client = _client()
        # Set a known baseline first
        client.put(
            f"{PREFIX}/model-config",
            json={
                "base_url": "https://base-a.com/v1",
                "timeout": 30,
                "max_retries": 3,
                "default_model": "model-a",
            },
        )
        # Partial: only timeout
        resp = client.put(f"{PREFIX}/model-config", json={"timeout": 99})
        assert resp.status_code == 200
        data = resp.json()
        assert data["timeout"] == 99
        assert data["base_url"] == "https://base-a.com/v1"
        assert data["max_retries"] == 3
        assert data["default_model"] == "model-a"

    def test_update_model_config_ignores_invalid_fields(self):
        """Unknown fields in PUT body are silently ignored."""
        client = _client()
        resp = client.put(
            f"{PREFIX}/model-config",
            json={"timeout": 45, "nonexistent_field": "should-be-ignored"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "nonexistent_field" not in data
        assert data["timeout"] == 45

    def test_update_model_config_rejects_api_key_in_response(self):
        """api_key sent in request body must NOT appear in response."""
        client = _client()
        resp = client.put(
            f"{PREFIX}/model-config", json={"api_key": "super-secret-key-12345"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "api_key" not in data


# =============================================================================
# Group B: Model Routes (9 endpoints)
#
# GET    /model-routes                        — list
# POST   /model-routes                        — create
# GET    /model-routes/{route_id}             — get detail (+ 404)
# PUT    /model-routes/{route_id}             — update     (+ 404)
# DELETE /model-routes/{route_id}             — delete     (+ 404)
# GET    /model-routes/fallbacks/{model_name}  — get fallbacks
# PUT    /model-routes/fallbacks/{model_name}  — update fallbacks
# GET    /model-routes/params/{model_name}     — get params
# PUT    /model-routes/params/{model_name}     — update params
# =============================================================================


class TestModelRoutes:
    """Full CRUD lifecycle for /model-routes/*."""

    def setup_method(self) -> None:
        _reset_stores()

    # ── GET /model-routes ──────────────────────────────────────────────────

    def test_list_routes_initial_empty(self):
        """GET /model-routes returns empty list when no routes exist."""
        client = _client()
        resp = client.get(f"{PREFIX}/model-routes")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}

    # ── POST /model-routes ─────────────────────────────────────────────────

    def test_create_route_returns_created_route(self):
        """POST creates a route and returns it with auto-assigned route_id."""
        client = _client()
        resp = client.post(
            f"{PREFIX}/model-routes",
            json={
                "scene": "settlement_exception_guidance",
                "model_type": "llm",
                "model_name": "deepseek-ai/DeepSeek-V3.2",
                "priority": 10,
                "enabled": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["route_id"] == "1"
        assert data["scene"] == "settlement_exception_guidance"
        assert data["model_type"] == "llm"
        assert data["model_name"] == "deepseek-ai/DeepSeek-V3.2"
        assert data["priority"] == 10
        assert data["enabled"] is True

    def test_create_route_with_defaults(self):
        """Omitting optional fields (priority, enabled) uses defaults."""
        client = _client()
        resp = client.post(
            f"{PREFIX}/model-routes",
            json={
                "scene": "default_scene",
                "model_type": "embedding",
                "model_name": "text-embedding-3-small",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["route_id"] == "1"
        assert data["priority"] == 0  # default
        assert data["enabled"] is True  # default

    def test_create_multiple_routes_sequential_ids(self):
        """route_id auto-increments for each created route."""
        client = _client()
        assert client.post(f"{PREFIX}/model-routes", json={"scene": "s1", "model_type": "llm", "model_name": "m1"}).json()["route_id"] == "1"
        assert client.post(f"{PREFIX}/model-routes", json={"scene": "s2", "model_type": "llm", "model_name": "m2"}).json()["route_id"] == "2"
        assert client.post(f"{PREFIX}/model-routes", json={"scene": "s3", "model_type": "llm", "model_name": "m3"}).json()["route_id"] == "3"

    def test_list_routes_after_create(self):
        """GET /model-routes reflects created routes with total count."""
        client = _client()
        client.post(f"{PREFIX}/model-routes", json={"scene": "s1", "model_type": "llm", "model_name": "m1"})
        client.post(f"{PREFIX}/model-routes", json={"scene": "s2", "model_type": "llm", "model_name": "m2"})
        resp = client.get(f"{PREFIX}/model-routes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    # ── GET /model-routes/{route_id} ───────────────────────────────────────

    def test_get_route_by_id(self):
        """GET /model-routes/{route_id} returns the full route object."""
        client = _client()
        client.post(f"{PREFIX}/model-routes", json={"scene": "my_scene", "model_type": "llm", "model_name": "my_model", "priority": 5, "enabled": False})
        resp = client.get(f"{PREFIX}/model-routes/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["route_id"] == "1"
        assert data["scene"] == "my_scene"
        assert data["model_type"] == "llm"
        assert data["model_name"] == "my_model"
        assert data["priority"] == 5
        assert data["enabled"] is False

    def test_get_route_not_found_returns_404(self):
        """GET /model-routes/{route_id} for non-existent id returns 404."""
        client = _client()
        resp = client.get(f"{PREFIX}/model-routes/9999")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "ROUTE_NOT_FOUND"

    # ── PUT /model-routes/{route_id} ───────────────────────────────────────

    def test_update_route_modifies_fields(self):
        """PUT /model-routes/{route_id} updates specified fields, keeps others."""
        client = _client()
        client.post(f"{PREFIX}/model-routes", json={"scene": "old_scene", "model_type": "llm", "model_name": "old_model", "priority": 1})
        resp = client.put(f"{PREFIX}/model-routes/1", json={"scene": "new_scene", "model_name": "new_model", "priority": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["route_id"] == "1"
        assert data["scene"] == "new_scene"
        assert data["model_name"] == "new_model"
        assert data["priority"] == 5
        # Unchanged fields persist
        assert data["model_type"] == "llm"
        assert data["enabled"] is True

    def test_update_route_not_found_returns_404(self):
        """PUT /model-routes/{route_id} for non-existent id returns 404."""
        client = _client()
        resp = client.put(f"{PREFIX}/model-routes/9999", json={"scene": "any"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "ROUTE_NOT_FOUND"

    # ── DELETE /model-routes/{route_id} ────────────────────────────────────

    def test_delete_route_removes_it(self):
        """DELETE /model-routes/{route_id} returns {'deleted': true}."""
        client = _client()
        client.post(f"{PREFIX}/model-routes", json={"scene": "s1", "model_type": "llm", "model_name": "m1"})
        resp = client.delete(f"{PREFIX}/model-routes/1")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True}
        # Confirm deleted
        assert client.get(f"{PREFIX}/model-routes/1").status_code == 404

    def test_delete_route_not_found_returns_404(self):
        """DELETE /model-routes/{route_id} for non-existent id returns 404."""
        client = _client()
        resp = client.delete(f"{PREFIX}/model-routes/9999")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "ROUTE_NOT_FOUND"

    # ── GET /model-routes/fallbacks/{model_name} ───────────────────────────

    def test_get_fallbacks_returns_list(self):
        """GET /model-routes/fallbacks/{model_name} returns fallback chain."""
        client = _client()
        resp = client.get(f"{PREFIX}/model-routes/fallbacks/text-embedding-3-small")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_name"] == "text-embedding-3-small"
        assert isinstance(data["fallbacks"], list)

    # ── PUT /model-routes/fallbacks/{model_name} ───────────────────────────

    def test_update_fallbacks(self):
        """PUT /model-routes/fallbacks/{model_name} updates fallback chain and persists."""
        client = _client()
        resp = client.put(f"{PREFIX}/model-routes/fallbacks/text-embedding-3-small", json={"fallbacks": ["deepseek-ai/DeepSeek-V4-Flash"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_name"] == "text-embedding-3-small"
        assert data["fallbacks"] == ["deepseek-ai/DeepSeek-V4-Flash"]
        # Verify persisted
        get_resp = client.get(f"{PREFIX}/model-routes/fallbacks/text-embedding-3-small")
        assert get_resp.json()["fallbacks"] == ["deepseek-ai/DeepSeek-V4-Flash"]

    def test_update_fallbacks_new_model(self):
        """PUT for a model not yet in store creates a new entry."""
        client = _client()
        resp = client.put(f"{PREFIX}/model-routes/fallbacks/brand-new-model", json={"fallbacks": ["fb1", "fb2"]})
        assert resp.status_code == 200
        assert resp.json()["fallbacks"] == ["fb1", "fb2"]

    # ── GET /model-routes/params/{model_name} ──────────────────────────────

    def test_get_params_returns_defaults_for_unknown_model(self):
        """Unknown model returns default params (temperature=0.7, max_tokens=2048)."""
        client = _client()
        resp = client.get(f"{PREFIX}/model-routes/params/unknown-model-x")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_name"] == "unknown-model-x"
        assert data["temperature"] == 0.7
        assert data["max_tokens"] == 2048

    # ── PUT /model-routes/params/{model_name} ──────────────────────────────

    def test_update_params(self):
        """PUT /model-routes/params/{model_name} updates model parameters and persists."""
        client = _client()
        resp = client.put(f"{PREFIX}/model-routes/params/test-model-param", json={"temperature": 0.3, "max_tokens": 4096, "top_p": 0.9})
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_name"] == "test-model-param"
        assert data["temperature"] == 0.3
        assert data["max_tokens"] == 4096
        assert data["top_p"] == 0.9
        # Verify persisted
        get_data = client.get(f"{PREFIX}/model-routes/params/test-model-param").json()
        assert get_data["temperature"] == 0.3
        assert get_data["max_tokens"] == 4096

    def test_update_params_partial(self):
        """Partial PUT merges with defaults for unspecified fields."""
        client = _client()
        data = client.put(f"{PREFIX}/model-routes/params/partial-model", json={"temperature": 0.1}).json()
        assert data["model_name"] == "partial-model"
        assert data["temperature"] == 0.1
        assert data["max_tokens"] == 2048  # default


# =============================================================================
# Group C: Providers (6 endpoints)
#
# GET    /model-providers                        — list
# POST   /model-providers                        — create (+ duplicate 409)
# GET    /model-providers/{provider_id}          — get detail (+ 404)
# PUT    /model-providers/{provider_id}          — update
# DELETE /model-providers/{provider_id}          — delete
# POST   /model-providers/{provider_id}/test     — connectivity test
# =============================================================================


class TestModelProviders:
    """Full CRUD lifecycle for /model-providers/*."""

    def setup_method(self) -> None:
        _reset_stores()

    # ── GET /model-providers ───────────────────────────────────────────────

    def test_list_providers_initial_empty(self):
        """GET /model-providers returns empty list when none registered."""
        client = _client()
        resp = client.get(f"{PREFIX}/model-providers")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}

    def test_list_providers_after_create(self):
        """GET /model-providers reflects created providers with masked api_keys."""
        client = _client()
        client.post(f"{PREFIX}/model-providers", json={"provider_id": "prov-a", "provider_type": "openai_compatible", "base_url": "https://a.example.com/v1", "api_key": "key-a"})
        client.post(f"{PREFIX}/model-providers", json={"provider_id": "prov-b", "provider_type": "openai_compatible", "base_url": "https://b.example.com/v1", "api_key": "key-b-longer-key-123"})
        resp = client.get(f"{PREFIX}/model-providers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert {p["provider_id"] for p in data["items"]} == {"prov-a", "prov-b"}

    # ── POST /model-providers ──────────────────────────────────────────────

    def test_create_provider_returns_masked_api_key(self):
        """POST creates provider and returns it with masked api_key."""
        client = _client()
        resp = client.post(f"{PREFIX}/model-providers", json={
            "provider_id": "test-provider-001",
            "provider_type": "openai_compatible",
            "base_url": "https://api.test.com/v1",
            "api_key": "sk-test-key-12345",
            "enabled": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_id"] == "test-provider-001"
        assert data["provider_type"] == "openai_compatible"
        assert data["base_url"] == "https://api.test.com/v1"
        assert data["enabled"] is True
        # api_key must be masked
        assert "****" in data["api_key"]
        assert data["api_key"] != "sk-test-key-12345"
        assert len(data["api_key"]) > 4

    def test_create_provider_without_id_generates_uuid(self):
        """Omitting provider_id auto-generates a UUID."""
        client = _client()
        resp = client.post(f"{PREFIX}/model-providers", json={"provider_type": "openai_compatible", "base_url": "https://api.test.com/v1", "api_key": "key123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "provider_id" in data
        assert len(data["provider_id"]) == 36
        assert "-" in data["provider_id"]

    def test_create_duplicate_provider_returns_409(self):
        """POST with existing provider_id returns 409 CONFLICT."""
        client = _client()
        client.post(f"{PREFIX}/model-providers", json={"provider_id": "dup-provider", "provider_type": "openai_compatible", "base_url": "https://api.test.com/v1", "api_key": "key123"})
        resp = client.post(f"{PREFIX}/model-providers", json={"provider_id": "dup-provider", "provider_type": "openai_compatible", "base_url": "https://api.test.com/v2", "api_key": "key456"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "PROVIDER_EXISTS"

    def test_create_provider_with_default_headers(self):
        """Provider creation supports default_headers field."""
        client = _client()
        data = client.post(f"{PREFIX}/model-providers", json={"provider_id": "prov-headers", "provider_type": "openai_compatible", "base_url": "https://api.test.com/v1", "api_key": "sk-key", "default_headers": {"X-Custom": "value123"}}).json()
        assert data["default_headers"] == {"X-Custom": "value123"}

    # ── GET /model-providers/{provider_id} ─────────────────────────────────

    def test_get_provider_returns_masked_api_key(self):
        """GET /model-providers/{provider_id} returns details with masked api_key."""
        client = _client()
        client.post(f"{PREFIX}/model-providers", json={"provider_id": "test-provider-get", "provider_type": "openai_compatible", "base_url": "https://api.get.com/v1", "api_key": "sk-test-get-key-99999"})
        resp = client.get(f"{PREFIX}/model-providers/test-provider-get")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_id"] == "test-provider-get"
        assert "****" in data["api_key"]
        assert data["api_key"] != "sk-test-get-key-99999"
        assert data["api_key"].startswith("sk-t")

    def test_get_provider_not_found_returns_404(self):
        """GET /model-providers/{provider_id} for non-existent returns 404."""
        client = _client()
        resp = client.get(f"{PREFIX}/model-providers/non-existent-provider")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "PROVIDER_NOT_FOUND"

    # ── PUT /model-providers/{provider_id} ─────────────────────────────────

    def test_update_provider_modifies_fields(self):
        """PUT /model-providers/{provider_id} updates fields, masks api_key."""
        client = _client()
        client.post(f"{PREFIX}/model-providers", json={"provider_id": "test-provider-upd", "provider_type": "openai_compatible", "base_url": "https://api.old.com/v1", "api_key": "old-key"})
        resp = client.put(f"{PREFIX}/model-providers/test-provider-upd", json={"base_url": "https://api.new.com/v1", "api_key": "new-key-1234567890", "enabled": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_id"] == "test-provider-upd"
        assert data["base_url"] == "https://api.new.com/v1"
        assert data["enabled"] is False
        assert "****" in data["api_key"]
        assert data["api_key"] != "new-key-1234567890"
        # Verify persisted
        assert client.get(f"{PREFIX}/model-providers/test-provider-upd").json()["base_url"] == "https://api.new.com/v1"

    def test_update_partial_provider_preserves_other_fields(self):
        """Partial PUT only modifies specified fields, keeps others intact."""
        client = _client()
        client.post(f"{PREFIX}/model-providers", json={"provider_id": "prov-partial", "provider_type": "openai_compatible", "base_url": "https://api.orig.com/v1", "api_key": "orig-key", "default_headers": {"Keep": "This"}})
        data = client.put(f"{PREFIX}/model-providers/prov-partial", json={"enabled": False}).json()
        assert data["provider_id"] == "prov-partial"
        assert data["enabled"] is False
        assert data["base_url"] == "https://api.orig.com/v1"
        assert data["default_headers"] == {"Keep": "This"}

    def test_update_provider_not_found_returns_404(self):
        """PUT /model-providers/{provider_id} for non-existent returns 404."""
        client = _client()
        resp = client.put(f"{PREFIX}/model-providers/non-existent", json={"base_url": "https://x.com"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "PROVIDER_NOT_FOUND"

    # ── DELETE /model-providers/{provider_id} ──────────────────────────────

    def test_delete_provider_removes_it(self):
        """DELETE /model-providers/{provider_id} returns {'deleted': true}."""
        client = _client()
        client.post(f"{PREFIX}/model-providers", json={"provider_id": "test-provider-del", "provider_type": "openai_compatible", "base_url": "https://api.del.com/v1", "api_key": "del-key"})
        resp = client.delete(f"{PREFIX}/model-providers/test-provider-del")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True}
        # Confirm deleted
        assert client.get(f"{PREFIX}/model-providers/test-provider-del").status_code == 404

    def test_delete_provider_not_found_returns_404(self):
        """DELETE /model-providers/{provider_id} for non-existent returns 404."""
        client = _client()
        resp = client.delete(f"{PREFIX}/model-providers/non-existent")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "PROVIDER_NOT_FOUND"

    # ── POST /model-providers/{provider_id}/test ───────────────────────────

    def test_provider_connectivity_empty_base_url(self):
        """Test endpoint returns immediately with empty base_url (no real HTTP call)."""
        client = _client()
        client.post(f"{PREFIX}/model-providers", json={"provider_id": "test-provider-empty", "provider_type": "openai_compatible", "base_url": "", "api_key": "test-key"})
        resp = client.post(f"{PREFIX}/model-providers/test-provider-empty/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["latency_ms"] == 0
        assert data["error"] == "base_url 为空"

    def test_provider_connectivity_not_found(self):
        """Test endpoint for non-existent provider returns 404."""
        client = _client()
        resp = client.post(f"{PREFIX}/model-providers/non-existent/test")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "PROVIDER_NOT_FOUND"
