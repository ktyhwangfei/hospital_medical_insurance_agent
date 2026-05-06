from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_mcp_storage_health_endpoint():
    client = TestClient(create_app())

    response = client.get("/api/v1/medical-insurance-ai-agent/mcp/storage/health")

    assert response.status_code == 200
    assert response.json()["status"] in {"healthy", "degraded", "unhealthy"}


def test_mcp_server_registration_endpoint_masks_secret():
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/mcp/servers",
        json={"server_id": "srv-policy", "name": "医保政策 MCP", "endpoint": "https://mcp.example.test/sse", "transport": "sse", "status": "enabled", "auth_headers": {"Authorization": "Bearer secret"}},
    )

    assert response.status_code == 200
    assert response.json()["auth_headers"]["Authorization"] == "***"
