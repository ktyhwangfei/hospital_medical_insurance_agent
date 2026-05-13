from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import ClientSession

from src.knowledge_extension.mcp_registry.models import (
    McpServer,
    McpServerStatus,
    McpTransportType,
)


@pytest.fixture
def streamable_http_server() -> McpServer:
    return McpServer(
        server_id="test-http-server",
        name="Test HTTP Server",
        endpoint="http://localhost:9999/mcp",
        transport=McpTransportType.STREAMABLE_HTTP,
        status=McpServerStatus.ENABLED,
    )


@pytest.fixture
def stdio_server() -> McpServer:
    return McpServer(
        server_id="test-stdio-server",
        name="Test Stdio Server",
        endpoint="stdio://local",
        transport=McpTransportType.STDIO,
        status=McpServerStatus.ENABLED,
        connection_config={"command": "python", "args": ["-m", "test_server"]},
    )


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock(spec=ClientSession)
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock()
    session.call_tool = AsyncMock()
    return session


@pytest.fixture
def mock_http_transport_cm() -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.fixture
def mock_stdio_transport_cm() -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm
