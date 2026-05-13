import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from src.knowledge_extension.mcp_registry.models import (
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpTransportType,
)
from src.knowledge_extension.mcp_registry.transport import (
    McpTransport,
    McpTransportConnectionError,
    McpTransportError,
    McpTransportProtocolError,
    McpTransportTimeoutError,
)


# ------------------------------------------------------------------
# MCP SDK import test
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_sdk_import():
    """Verify that the required mcp SDK modules can be imported correctly."""
    # These are already imported at the module level; this test ensures
    # the SDK is available and the expected types exist.
    import mcp
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import CallToolResult, ListToolsResult, Tool, TextContent

    assert hasattr(ClientSession, "initialize")
    assert hasattr(ClientSession, "list_tools")
    assert hasattr(ClientSession, "call_tool")
    assert issubclass(CallToolResult, object)
    assert issubclass(ListToolsResult, object)
    assert issubclass(Tool, object)
    assert callable(streamable_http_client)
    assert callable(stdio_client)


# ------------------------------------------------------------------
# Transport type selection
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_transport_selection(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """streamable_http transport calls the SDK's streamable_http_client."""
    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ) as mock_http_fn,
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)
        await transport.initialize()

        mock_http_fn.assert_called_once_with(
            url=streamable_http_server.endpoint,
            http_client=None,
        )
        mock_session.initialize.assert_awaited_once()
        assert transport._initialized is True


@pytest.mark.asyncio
async def test_stdio_transport_selection(
    stdio_server: McpServer,
    mock_session: AsyncMock,
    mock_stdio_transport_cm: MagicMock,
):
    """stdio transport calls the SDK's stdio_client."""
    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.stdio_client",
            return_value=mock_stdio_transport_cm,
        ) as mock_stdio_fn,
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(stdio_server)
        await transport.initialize()

        mock_stdio_fn.assert_called_once()
        mock_session.initialize.assert_awaited_once()
        assert transport._initialized is True


@pytest.mark.asyncio
async def test_unsupported_transport_raises_protocol_error(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """An unsupported transport type raises McpTransportProtocolError."""
    bad_server = streamable_http_server.model_copy(
        update={"transport": "unknown_transport"}  # type: ignore[arg-type]
    )

    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(bad_server)
        with pytest.raises(McpTransportProtocolError, match="Unsupported transport"):
            await transport.initialize()


# ------------------------------------------------------------------
# Connection failure handling
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_failure_raises_connection_error(
    streamable_http_server: McpServer,
):
    """Network-level failures are wrapped in McpTransportConnectionError."""
    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            side_effect=httpx.ConnectError("Connection refused"),
        ),
    ):
        transport = McpTransport(streamable_http_server)
        with pytest.raises(McpTransportConnectionError, match="Failed to connect"):
            await transport.initialize()


@pytest.mark.asyncio
async def test_os_error_on_connect_raises_connection_error(
    streamable_http_server: McpServer,
):
    """OS-level errors are wrapped in McpTransportConnectionError."""
    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            side_effect=OSError("No such file or directory"),
        ),
    ):
        transport = McpTransport(streamable_http_server)
        with pytest.raises(McpTransportConnectionError, match="Failed to connect"):
            await transport.initialize()


@pytest.mark.asyncio
async def test_initialize_after_failure_retries(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """A failed initialization does not leave the transport in an inconsistent state."""
    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            side_effect=[OSError("first fail"), mock_http_transport_cm],
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)

        with pytest.raises(McpTransportConnectionError):
            await transport.initialize()
        assert transport._initialized is False

        # Second attempt succeeds
        await transport.initialize()
        assert transport._initialized is True


# ------------------------------------------------------------------
# list_tools
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_mcp_capabilities(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """list_tools returns a list of McpCapability models mapped from SDK Tool objects."""
    sdk_tools = [
        Tool(
            name="get_policy",
            description="Retrieve insurance policy",
            inputSchema={"type": "object", "properties": {"code": {"type": "string"}}},
        ),
        Tool(
            name="calculate_premium",
            description="Calculate premium amount",
            inputSchema={"type": "object", "properties": {"base": {"type": "number"}}},
            outputSchema={"type": "object", "properties": {"result": {"type": "number"}}},
        ),
    ]
    mock_session.list_tools.return_value = ListToolsResult(tools=sdk_tools)

    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)
        await transport.initialize()
        capabilities = await transport.list_tools()

        assert len(capabilities) == 2

        # First capability
        c0 = capabilities[0]
        assert c0.name == "get_policy"
        assert c0.capability_id == f"{streamable_http_server.server_id}/get_policy"
        assert c0.server_id == streamable_http_server.server_id
        assert c0.capability_type is McpCapabilityType.TOOL
        assert c0.description == "Retrieve insurance policy"
        assert c0.risk_level is McpRiskLevel.LOW
        assert c0.input_schema["properties"]["code"]["type"] == "string"

        # Second capability with output_schema
        c1 = capabilities[1]
        assert c1.name == "calculate_premium"
        assert c1.output_schema["properties"]["result"]["type"] == "number"

        mock_session.list_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_tools_uninitialized_raises_error(
    streamable_http_server: McpServer,
):
    """Calling list_tools before initialize raises McpTransportError."""
    transport = McpTransport(streamable_http_server)
    with pytest.raises(McpTransportError, match="not initialized"):
        await transport.list_tools()


@pytest.mark.asyncio
async def test_list_tools_timeout_raises_timeout_error(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """A timed-out list_tools raises McpTransportTimeoutError."""
    mock_session.list_tools.side_effect = asyncio.TimeoutError

    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)
        await transport.initialize()

        with pytest.raises(McpTransportTimeoutError, match="timed out"):
            await transport.list_tools()


# ------------------------------------------------------------------
# call_tool
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_returns_dict(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """call_tool returns the tool result as a plain dict."""
    sdk_result = CallToolResult(
        content=[TextContent(type="text", text='{"status": "ok"}')],
        isError=False,
    )
    mock_session.call_tool.return_value = sdk_result

    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)
        await transport.initialize()

        result = await transport.call_tool("get_policy", {"code": "YLB-2024"})

        assert isinstance(result, dict)
        assert result["isError"] is False
        assert len(result["content"]) == 1
        assert result["content"][0]["text"] == '{"status": "ok"}'

        mock_session.call_tool.assert_awaited_once_with("get_policy", {"code": "YLB-2024"})


@pytest.mark.asyncio
async def test_call_tool_uninitialized_raises_error(
    streamable_http_server: McpServer,
):
    """Calling call_tool before initialize raises McpTransportError."""
    transport = McpTransport(streamable_http_server)
    with pytest.raises(McpTransportError, match="not initialized"):
        await transport.call_tool("any_tool")


@pytest.mark.asyncio
async def test_call_tool_timeout_raises_timeout_error(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """A timed-out call_tool raises McpTransportTimeoutError."""
    mock_session.call_tool.side_effect = asyncio.TimeoutError

    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)
        await transport.initialize()

        with pytest.raises(McpTransportTimeoutError, match="timed out"):
            await transport.call_tool("slow_tool", {"wait": "10"})


# ------------------------------------------------------------------
# Session lifecycle
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_cleans_up_session_and_transport(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """close() tears down the session and sets initialized to False."""
    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)
        await transport.initialize()
        assert transport._initialized is True

        await transport.close()
        assert transport._initialized is False

        # Calling methods after close should fail
        with pytest.raises(McpTransportError, match="not initialized"):
            await transport.list_tools()


@pytest.mark.asyncio
async def test_async_context_manager(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """The transport can be used as an async context manager."""
    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        async with McpTransport(streamable_http_server) as transport:
            assert transport._initialized is True

        # After exiting the context, the transport should be torn down
        assert transport._initialized is False


@pytest.mark.asyncio
async def test_double_initialize_is_idempotent(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """Calling initialize() twice does not create a second session."""
    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ) as mock_http_fn,
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)
        await transport.initialize()
        await transport.initialize()

        # streamable_http_client and session should only be created once
        mock_http_fn.assert_called_once()


@pytest.mark.asyncio
async def test_session_lifecycle(
    streamable_http_server: McpServer,
    mock_session: AsyncMock,
    mock_http_transport_cm: MagicMock,
):
    """Full session lifecycle: initialize → list_tools → call_tool → close."""
    sdk_tools = [
        Tool(
            name="get_policy",
            description="Get policy details",
            inputSchema={"type": "object"},
        ),
    ]
    mock_session.list_tools.return_value = ListToolsResult(tools=sdk_tools)
    mock_session.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text='{"ok": true}')],
        isError=False,
    )

    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.streamable_http_client",
            return_value=mock_http_transport_cm,
        ),
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(streamable_http_server)

        # 1. Initialize
        await transport.initialize()
        assert transport._initialized is True
        mock_session.initialize.assert_awaited_once()

        # 2. List tools
        capabilities = await transport.list_tools()
        assert len(capabilities) == 1
        assert capabilities[0].name == "get_policy"
        mock_session.list_tools.assert_awaited_once()

        # 3. Call tool
        result = await transport.call_tool("get_policy", {"code": "X"})
        assert isinstance(result, dict)
        assert result["isError"] is False
        mock_session.call_tool.assert_awaited_once_with("get_policy", {"code": "X"})

        # 4. Close
        await transport.close()
        assert transport._initialized is False

        # 5. Verify post-close calls fail
        with pytest.raises(McpTransportError, match="not initialized"):
            await transport.list_tools()


# ------------------------------------------------------------------
# Stdio transport specifics
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_server_missing_command_raises_error(
    stdio_server: McpServer,
    mock_session: AsyncMock,
    mock_stdio_transport_cm: MagicMock,
):
    """A stdio server without a command in connection_config raises an error."""
    bad_server = stdio_server.model_copy(
        update={"connection_config": {"args": ["-y", "test"]}}  # no "command"
    )

    with (
        patch(
            "src.knowledge_extension.mcp_registry.transport.stdio_client",
            return_value=mock_stdio_transport_cm,
        ) as mock_stdio_fn,
        patch(
            "src.knowledge_extension.mcp_registry.transport.ClientSession",
            return_value=mock_session,
        ),
    ):
        transport = McpTransport(bad_server)
        with pytest.raises(McpTransportConnectionError, match="missing 'command'"):
            await transport.initialize()

        # stdio_client should NOT have been called
        mock_stdio_fn.assert_not_called()
