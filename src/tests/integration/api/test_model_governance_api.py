import base64
import json

import pytest
from fastapi.testclient import TestClient


SNAPSHOT_PATH = "/api/v1/medical-insurance-ai-agent/model-governance/snapshot"


def _token(*, permissions: list[str], subject: str = "governance-reader") -> str:
    payload = {
        "sub": subject,
        "roles": ["information_department"],
        "permissions": permissions,
        "exp": 4102444800,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"test.{encoded}.signature"


def _headers(permission: str, *, subject: str = "editor") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(permissions=[permission], subject=subject)}"
    }


def _prompt_payload() -> dict:
    return {
        "content": {
            "asset_type": "prompt",
            "asset_id": "prompt.api-demo",
            "name": "API 演示提示词",
            "scene": "policy_qa",
            "system_prompt": "只输出可追溯事实",
            "user_prompt_template": "问题：{question}",
            "variables": [{"name": "question", "required": True}],
        }
    }


def _model_payload(api_key: str = "sk-api-plaintext") -> dict:
    return {
        "content": {
            "asset_type": "model_profile",
            "asset_id": "model.api-demo",
            "name": "API 模型",
            "provider_id": "openai_compatible",
            "base_url": "https://models.example.test/v1/",
            "model_name": "demo-model",
            "credential_ref": "credential.api-demo",
            "timeout_seconds": 30,
            "temperature": 0.2,
            "max_tokens": 1024,
            "enabled": True,
        },
        "credential": {
            "credential_id": "credential.api-demo",
            "api_key": api_key,
        },
    }


def _management_client(monkeypatch) -> TestClient:
    async def no_op_session(self, *args):
        return None

    async def no_op_audit(self, **kwargs):
        return None

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_session",
        no_op_session,
    )
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_audit",
        no_op_audit,
    )
    from src.runtime.api.app import create_app
    from src.data_platform.storage.model_governance.factory import (
        get_model_governance_storage,
    )
    from src.runtime.api.model_governance_routes import get_model_governance_service

    get_model_governance_storage.cache_clear()
    get_model_governance_service.cache_clear()

    return TestClient(create_app())


def _assert_validation_does_not_echo_secret(
    client: TestClient,
    *,
    method: str,
    path: str,
    body: dict,
    secret: str,
) -> None:
    response = client.request(
        method,
        path,
        json=body,
        headers=_headers("model_governance:write"),
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert all("input" not in error for error in response.json()["detail"])

    from src.gateway.access_log import AccessLogger

    logger = AccessLogger()
    logger.log(
        request_id="validation-secret",
        method=method,
        path=path,
        status_code=422,
        duration_ms=1,
        request_body=body,
    )
    assert secret not in logger.get_entries()[0].request_body


def test_model_governance_snapshot_requires_identity_and_returns_typed_envelope(
    monkeypatch,
):
    async def no_op_session(self, *args):
        return None

    async def no_op_audit(self, **kwargs):
        return None

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    monkeypatch.delenv("MODEL_GOVERNANCE_DEV_MODE", raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "temporary-secret-key")
    monkeypatch.setenv(
        "MODEL_BASE_URL", "https://user:password@example.test:8443/v1?q=1"
    )
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_session",
        no_op_session,
    )
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_audit",
        no_op_audit,
    )

    from src.runtime.api.app import create_app

    client = TestClient(create_app())
    disabled = client.get(SNAPSHOT_PATH)
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["error_code"] == "MODEL_GOVERNANCE_DISABLED"
    assert "真实认证未接入" in disabled.json()["detail"]["message"]

    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "true")
    assert client.get(SNAPSHOT_PATH).status_code == 401
    authenticated = client.get(
        SNAPSHOT_PATH,
        headers={"Authorization": f"Bearer {_token(permissions=[])}"},
    )
    assert authenticated.status_code == 200

    authorization = {
        "Authorization": f"Bearer {_token(permissions=['model_governance:read'])}"
    }
    response = client.get(SNAPSHOT_PATH, headers=authorization)

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "model_governance"
    assert payload["status"] == "success"
    assert isinstance(payload["citations"], list)
    assert payload["uncertainties"] == payload["result"]["uncertainties"]
    assert set(payload["result"]) == {
        "prompts", "models", "routes", "providers", "citations", "uncertainties"
    }
    assert {prompt["prompt_id"] for prompt in payload["result"]["prompts"]} >= {
        "intent.classify",
        "policy.fact_extract",
    }
    routes = {
        (route["scene"], route["model_type"]): route
        for route in payload["result"]["routes"]
    }
    active_scenes = {
        "intent_recognition",
        "skill_routing",
        "policy_qa",
        "fee_explanation",
        "policy_fact_extraction",
    }
    assert active_scenes <= {
        scene
        for (scene, model_type), route in routes.items()
        if model_type == "llm" and route["explicit"] is True
    }
    serialized = response.text
    assert "temporary-secret-key" not in serialized
    assert "user:password" not in serialized
    assert "/v1" not in serialized
    assert "q=1" not in serialized
    assert client.post(SNAPSHOT_PATH, headers=authorization).status_code == 405


def test_governance_versions_can_be_read_by_any_authenticated_role_and_copied(
    monkeypatch,
):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    client = _management_client(monkeypatch)
    from src.model_service.governance_assets import (
        GovernanceEnvironment,
        PromptAssetContent,
    )
    from src.runtime.api.model_governance_routes import get_model_governance_service

    service = get_model_governance_service()
    content = PromptAssetContent.model_validate(_prompt_payload()["content"])
    draft = service.create_draft(content, actor="editor")
    validated = service.validate_draft(draft.draft_id, expected_revision=draft.revision)
    pending = service.request_review(
        draft.draft_id, expected_revision=validated.revision, actor="editor"
    )
    approved = service.approve(
        draft.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="审核通过",
    )
    service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    path = (
        "/api/v1/medical-insurance-ai-agent/model-governance/"
        "assets/prompt.api-demo/versions?environment=dev"
    )

    details = client.get(
        path,
        headers={"Authorization": f"Bearer {_token(permissions=[], subject='cashier')}"},
    )
    assert details.status_code == 200
    assert details.json()["result"]["versions"][0]["version_number"] == 1
    assert details.json()["result"]["releases"][0]["environment"] == "dev"

    copied = client.post(path, headers=_headers("model_governance:write"))
    assert copied.status_code == 201
    assert copied.json()["result"]["content"] == approved.content.model_dump(mode="json")
    assert copied.json()["result"]["draft_id"] != approved.draft_id


def test_assets_include_real_prompt_baselines_before_import(monkeypatch):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    client = _management_client(monkeypatch)

    response = client.get(
        "/api/v1/medical-insurance-ai-agent/model-governance/assets"
        "?environment=dev&asset_type=prompt",
        headers=_headers("model_governance:write", subject="cashier"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    prompt = next(
        item for item in result["baselines"] if item["asset_id"] == "intent.classify"
    )
    assert "可用意图" in prompt["user_prompt_template"]
    assert "用户消息：{message}" in prompt["user_prompt_template"]
    assert result["drafts"] == []


def test_governance_write_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MODEL_GOVERNANCE_DEV_MODE", raising=False)
    client = _management_client(monkeypatch)

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/model-governance/drafts",
        json=_prompt_payload(),
        headers=_headers("model_governance:write"),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "MODEL_GOVERNANCE_DISABLED"


def test_governance_rejects_missing_permission_and_stale_revision(monkeypatch):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    client = _management_client(monkeypatch)
    path = "/api/v1/medical-insurance-ai-agent/model-governance/drafts"

    forbidden = client.post(
        path,
        json=_prompt_payload(),
        headers=_headers("model_governance:read"),
    )
    assert forbidden.status_code == 403

    missing_identity = client.post(
        path,
        json=_prompt_payload(),
        headers=_headers("model_governance:write", subject=""),
    )
    assert missing_identity.status_code == 401

    created_response = client.post(
        path,
        json=_prompt_payload(),
        headers=_headers("model_governance:write"),
    )
    assert created_response.status_code == 201
    created = created_response.json()["result"]
    update_body = {"content": created["content"], "expected_revision": 1}
    saved = client.patch(
        f"{path}/{created['draft_id']}",
        json=update_body,
        headers=_headers("model_governance:write"),
    )
    assert saved.status_code == 200
    assert saved.json()["result"]["revision"] == 2

    stale = client.patch(
        f"{path}/{created['draft_id']}",
        json=update_body,
        headers=_headers("model_governance:write"),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "MODEL_GOVERNANCE_CONFLICT"


def test_governance_imports_current_assets_once_and_deletes_by_revision(monkeypatch):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    client = _management_client(monkeypatch)
    prefix = "/api/v1/medical-insurance-ai-agent/model-governance"
    write_headers = _headers("model_governance:write")

    forbidden = client.post(
        f"{prefix}/import-current",
        headers=_headers("model_governance:read"),
    )
    assert forbidden.status_code == 403

    first = client.post(f"{prefix}/import-current", headers=write_headers)
    assert first.status_code == 201
    imported = first.json()["result"]
    assert imported["created_count"] > 0
    assert imported["counts"]["prompt"] == 11
    assert imported["counts"]["model_profile"] > 0
    assert imported["counts"]["route_rule"] > 0

    repeated = client.post(f"{prefix}/import-current", headers=write_headers)
    assert repeated.status_code == 201
    assert repeated.json()["result"]["created_count"] == 0
    assert repeated.json()["result"]["skipped_count"] == imported["created_count"]

    draft = imported["drafts"][0]
    stale = client.delete(
        f"{prefix}/drafts/{draft['draft_id']}?expected_revision=2",
        headers=write_headers,
    )
    assert stale.status_code == 409
    deleted = client.delete(
        f"{prefix}/drafts/{draft['draft_id']}?expected_revision=1",
        headers=write_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["result"]["draft_id"] == draft["draft_id"]


def test_model_credential_is_encrypted_and_never_echoed_by_api(monkeypatch, caplog):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    client = _management_client(monkeypatch)
    prefix = "/api/v1/medical-insurance-ai-agent/model-governance"
    secret = "sk-api-plaintext"

    created = client.post(
        f"{prefix}/drafts",
        json=_model_payload(secret),
        headers=_headers("model_governance:write"),
    )
    assets = client.get(
        f"{prefix}/assets?environment=dev&asset_type=model_profile",
        headers=_headers("model_governance:read"),
    )

    assert created.status_code == 201
    assert assets.status_code == 200
    assert secret not in created.text
    assert secret not in assets.text
    assert secret not in caplog.text
    from src.gateway.access_log import AccessLogger, access_logger

    assert all(secret not in entry.request_body for entry in access_logger.get_entries())
    logger = AccessLogger()
    logger.log(
        request_id="credential-test",
        method="POST",
        path=f"{prefix}/drafts",
        status_code=201,
        duration_ms=1,
        request_body=_model_payload(secret),
    )
    assert secret not in logger.get_entries()[0].request_body
    from src.data_platform.storage.model_governance.factory import (
        get_model_governance_storage,
    )

    stored = get_model_governance_storage().get_credential("credential.api-demo")
    assert stored.encrypted_api_key != secret
    assert secret not in stored.model_dump_json()


def test_model_credential_writes_follow_injected_service_storage(monkeypatch):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    client = _management_client(monkeypatch)
    from src.data_platform.storage.model_governance.factory import (
        get_model_governance_storage,
    )
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )
    from src.data_platform.storage.model_governance.ports import (
        ModelGovernanceNotFoundError,
    )
    from src.model_service.governance_service import ModelGovernanceService
    from src.runtime.api.model_governance_routes import get_model_governance_service

    injected_storage = InMemoryModelGovernanceStorage()
    injected_service = ModelGovernanceService(injected_storage)
    client.app.dependency_overrides[get_model_governance_service] = (
        lambda: injected_service
    )
    global_storage = get_model_governance_storage()
    prefix = "/api/v1/medical-insurance-ai-agent/model-governance/drafts"

    created_response = client.post(
        prefix,
        json=_model_payload("injected-original-key"),
        headers=_headers("model_governance:write"),
    )

    assert created_response.status_code == 201
    created = created_response.json()["result"]
    assert injected_storage.get_draft(created["draft_id"]).revision == 1
    assert injected_storage.get_credential("credential.api-demo").revision == 1
    with pytest.raises(ModelGovernanceNotFoundError):
        global_storage.get_credential("credential.api-demo")

    changed = _model_payload("injected-replacement-key")
    changed["content"]["model_name"] = "replacement-model"
    changed["expected_revision"] = created["revision"]
    updated_response = client.patch(
        f"{prefix}/{created['draft_id']}",
        json=changed,
        headers=_headers("model_governance:write"),
    )

    assert updated_response.status_code == 200
    assert injected_storage.get_draft(created["draft_id"]).revision == 2
    assert injected_storage.get_credential("credential.api-demo").revision == 2
    with pytest.raises(ModelGovernanceNotFoundError):
        global_storage.get_credential("credential.api-demo")


def test_model_credential_ref_must_match_and_failed_encryption_removes_new_draft(
    monkeypatch,
):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    monkeypatch.setenv("MODEL_GOVERNANCE_MASTER_KEY", "invalid-key")
    client = _management_client(monkeypatch)
    prefix = "/api/v1/medical-insurance-ai-agent/model-governance"
    payload = _model_payload()

    mismatched = _model_payload()
    mismatched["credential"]["credential_id"] = "credential.other"
    response = client.post(
        f"{prefix}/drafts",
        json=mismatched,
        headers=_headers("model_governance:write"),
    )
    assert response.status_code == 422

    failed = client.post(
        f"{prefix}/drafts",
        json=payload,
        headers=_headers("model_governance:write"),
    )
    assert failed.status_code == 422
    drafts = client.get(
        f"{prefix}/assets?environment=dev&asset_type=model_profile",
        headers=_headers("model_governance:read"),
    )
    assert drafts.status_code == 200
    assert drafts.json()["result"]["drafts"] == []


def test_mismatched_credential_422_and_access_log_never_expose_api_key(
    monkeypatch, caplog
):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    client = _management_client(monkeypatch)
    secret = "mismatch-" + "secret-value"
    payload = _model_payload(secret)
    payload["credential"]["credential_id"] = "credential.other"

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/model-governance/drafts",
        json=payload,
        headers=_headers("model_governance:write"),
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert secret not in caplog.text

    from src.gateway.access_log import AccessLogger

    logger = AccessLogger()
    logger.log(
        request_id="nested-secret",
        method="POST",
        path="/model-governance/drafts",
        status_code=422,
        duration_ms=1,
        request_body={"items": [payload]},
    )
    assert secret not in logger.get_entries()[0].request_body
    assert "mismatch-***alue" not in logger.get_entries()[0].request_body

    oversized_secret = "x" * 4097
    oversized = client.post(
        "/api/v1/medical-insurance-ai-agent/model-governance/drafts",
        json=_model_payload(oversized_secret),
        headers=_headers("model_governance:write"),
    )
    assert oversized.status_code == 422
    assert oversized_secret not in oversized.text


def test_patch_bad_key_keeps_draft_and_credential_unchanged(monkeypatch):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    valid_master_key = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
    monkeypatch.setenv("MODEL_GOVERNANCE_MASTER_KEY", valid_master_key)
    client = _management_client(monkeypatch)
    prefix = "/api/v1/medical-insurance-ai-agent/model-governance/drafts"
    created_response = client.post(
        prefix,
        json=_model_payload("original-key"),
        headers=_headers("model_governance:write"),
    )
    assert created_response.status_code == 201
    created = created_response.json()["result"]

    from src.data_platform.storage.model_governance.factory import (
        get_model_governance_storage,
    )

    storage = get_model_governance_storage()
    original_draft = storage.get_draft(created["draft_id"])
    original_credential = storage.get_credential("credential.api-demo")
    changed = _model_payload("replacement-key")
    changed["content"]["model_name"] = "changed-model"
    changed["expected_revision"] = created["revision"]
    monkeypatch.setenv("MODEL_GOVERNANCE_MASTER_KEY", "invalid-key")

    response = client.patch(
        f"{prefix}/{created['draft_id']}",
        json=changed,
        headers=_headers("model_governance:write"),
    )

    assert response.status_code == 422
    assert storage.get_draft(created["draft_id"]) == original_draft
    assert storage.get_credential("credential.api-demo") == original_credential


def test_failed_credential_create_rolls_back_new_draft_when_asset_has_history(
    monkeypatch,
):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    monkeypatch.setenv("MODEL_GOVERNANCE_MASTER_KEY", "invalid-key")
    client = _management_client(monkeypatch)
    from src.model_service.governance_assets import (
        GovernanceEnvironment,
        ModelProfileAssetContent,
    )
    from src.runtime.api.model_governance_routes import get_model_governance_service

    service = get_model_governance_service()
    content = ModelProfileAssetContent.model_validate(_model_payload()["content"])
    draft = service.create_draft(content, actor="editor")
    validated = service.validate_draft(draft.draft_id, expected_revision=draft.revision)
    pending = service.request_review(
        draft.draft_id, expected_revision=validated.revision, actor="editor"
    )
    approved = service.approve(
        draft.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="审核通过",
    )
    service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    drafts_before = service.list_drafts()
    payload = _model_payload("new-key")
    payload["content"]["model_name"] = "next-model"

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/model-governance/drafts",
        json=payload,
        headers=_headers("model_governance:write"),
    )

    assert response.status_code == 422
    assert service.list_drafts() == drafts_before


@pytest.mark.parametrize(
    ("method", "path", "body_factory"),
    [
        pytest.param(
            "POST",
            "/api/v1/medical-insurance-ai-agent/model-governance/drafts",
            lambda secret: {
                "credential": {
                    "credential_id": "credential.api-demo",
                    "api_key": secret,
                }
            },
            id="create_missing_content",
        ),
        pytest.param(
            "POST",
            "/api/v1/medical-insurance-ai-agent/model-governance/drafts",
            lambda secret: {
                **_model_payload(secret),
                "credential": {"api_key": secret},
            },
            id="credential_missing_id",
        ),
        pytest.param(
            "PATCH",
            "/api/v1/medical-insurance-ai-agent/model-governance/drafts/missing",
            lambda secret: _model_payload(secret),
            id="patch_missing_revision",
        ),
        pytest.param(
            "PATCH",
            "/api/v1/medical-insurance-ai-agent/model-governance/drafts/missing",
            lambda secret: {**_model_payload(secret), "expected_revision": "wrong"},
            id="patch_wrong_revision_type",
        ),
    ],
)
def test_default_validation_errors_never_echo_api_key(
    monkeypatch, method, path, body_factory
):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    client = _management_client(monkeypatch)
    secret = "validation-" + "secret-value"
    _assert_validation_does_not_echo_secret(
        client,
        method=method,
        path=path,
        body=body_factory(secret),
        secret=secret,
    )
