"""
MCP API performance scenario.

Exercises MCP server and capability CRUD operations along with
storage health checks. Uses randomized IDs to avoid collisions.
"""

from uuid import uuid4

from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


class McpAPIUser(HttpUser):
    """Simulates MCP management traffic."""

    wait_time = between(0.5, 1.5)

    @task(3)
    @tag("mcp", "readonly")
    def storage_health(self):
        self.client.get(
            f"{API_PREFIX}/mcp/storage/health",
            name="/mcp/storage/health",
        )

    @task(3)
    @tag("mcp", "crud")
    def servers_crud(self):
        suffix = uuid4().hex[:8]
        server_id = f"MCP-PERF-{suffix}"

        self.client.post(
            f"{API_PREFIX}/mcp/servers",
            json={
                "server_id": server_id,
                "name": "Performance MCP Server",
                "endpoint": "http://localhost:9999",
                "transport": "stdio",
                "status": "enabled",
            },
            name="/mcp/servers [POST]",
        )

        self.client.get(
            f"{API_PREFIX}/mcp/servers",
            name="/mcp/servers [GET list]",
        )

        self.client.get(
            f"{API_PREFIX}/mcp/servers/{server_id}",
            name="/mcp/servers [GET single]",
        )

    @task(2)
    @tag("mcp", "crud")
    def capabilities_crud(self):
        suffix = uuid4().hex[:8]
        server_suffix = uuid4().hex[:8]
        capability_id = f"CAP-PERF-{suffix}"

        self.client.post(
            f"{API_PREFIX}/mcp/capabilities",
            json={
                "capability_id": capability_id,
                "server_id": f"MCP-PERF-{server_suffix}",
                "name": "perf-capability",
                "type": "Tool",
                "risk_level": "low",
            },
            name="/mcp/capabilities [POST]",
        )

        self.client.get(
            f"{API_PREFIX}/mcp/capabilities",
            name="/mcp/capabilities [GET list]",
        )
