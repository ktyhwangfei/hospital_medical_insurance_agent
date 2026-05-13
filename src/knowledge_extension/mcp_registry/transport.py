import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ListToolsResult, Tool

from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpTransportType,
)


class McpTransportError(Exception):
    """Base exception for MCP transport errors."""


class McpTransportConnectionError(McpTransportError):
    """Raised when connection or handshake with the MCP server fails."""


class McpTransportProtocolError(McpTransportError):
    """Raised on protocol-level errors during MCP communication."""


class McpTransportTimeoutError(McpTransportError):
    """Raised when an MCP operation exceeds the configured timeout."""


class McpTransport:
    """Wraps an MCP SDK transport and ClientSession for a single server.

    Supports both ``stdio`` and ``streamable_http`` transport types.
    Manages the full session lifecycle: connect, initialize, invoke, close.
    """

    def __init__(
        self,
        server: McpServer,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._server = server
        self._http_client = http_client
        self._timeout = timeout_seconds
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Connect to the MCP server and negotiate a session.

        Raises:
            McpTransportConnectionError: On connection or handshake failure.
            McpTransportProtocolError: On unsupported transport type.
        """
        if self._initialized:
            return
        try:
            if self._server.transport is McpTransportType.STREAMABLE_HTTP:
                streams = await self._stack.enter_async_context(
                    streamable_http_client(
                        url=self._server.endpoint,
                        http_client=self._http_client,
                    )
                )
                read_stream, write_stream, _ = streams
            elif self._server.transport is McpTransportType.STDIO:
                params = self._build_stdio_params()
                streams = await self._stack.enter_async_context(
                    stdio_client(params)
                )
                read_stream, write_stream = streams
            else:
                raise McpTransportProtocolError(
                    f"Unsupported transport type: {self._server.transport}"
                )

            self._session = await self._stack.enter_async_context(
                ClientSession(
                    read_stream=read_stream,
                    write_stream=write_stream,
                )
            )
            await self._session.initialize()
            self._initialized = True
        except McpTransportError:
            raise
        except (ConnectionError, OSError, httpx.HTTPError) as exc:
            raise McpTransportConnectionError(
                f"Failed to connect to server '{self._server.server_id}': {exc}"
            ) from exc
        except Exception as exc:
            raise McpTransportConnectionError(
                f"Initialization failed for server '{self._server.server_id}': {exc}"
            ) from exc

    async def list_tools(self) -> list[McpCapability]:
        """Retrieve available tools mapped to ``McpCapability`` models.

        Raises:
            McpTransportTimeoutError: If the operation exceeds the timeout.
            McpTransportError: If the transport is not initialized.
        """
        self._ensure_initialized()
        try:
            result: ListToolsResult = await asyncio.wait_for(
                self._session.list_tools(),
                timeout=self._timeout,
            )
            return [self._tool_to_capability(t) for t in result.tools]
        except asyncio.TimeoutError as exc:
            raise McpTransportTimeoutError(
                f"list_tools timed out for server '{self._server.server_id}' "
                f"(timeout={self._timeout}s)"
            ) from exc

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool and return the result as a plain dict.

        Raises:
            McpTransportTimeoutError: If the operation exceeds the timeout.
            McpTransportError: If the transport is not initialized.
        """
        self._ensure_initialized()
        try:
            result: CallToolResult = await asyncio.wait_for(
                self._session.call_tool(name, arguments),
                timeout=self._timeout,
            )
            return result.model_dump()
        except asyncio.TimeoutError as exc:
            raise McpTransportTimeoutError(
                f"call_tool '{name}' timed out for server '{self._server.server_id}' "
                f"(timeout={self._timeout}s)"
            ) from exc

    async def close(self) -> None:
        """Tear down the session and transport cleanly."""
        self._initialized = False
        self._session = None
        await self._stack.aclose()

    async def __aenter__(self) -> "McpTransport":
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        if not self._initialized or self._session is None:
            raise McpTransportError(
                f"Transport for server '{self._server.server_id}' is not initialized. "
                "Call initialize() first."
            )

    def _build_stdio_params(self) -> StdioServerParameters:
        cfg = self._server.connection_config
        command = cfg.get("command", "")
        if not isinstance(command, str) or not command.strip():
            raise McpTransportConnectionError(
                f"Server '{self._server.server_id}' missing 'command' in connection_config"
            )
        args: list[str] = list(cfg.get("args", [])) if isinstance(cfg.get("args"), list) else []
        env: dict[str, str] | None = cfg.get("env")
        if env is not None and not isinstance(env, dict):
            env = None
        cwd: str | None = cfg.get("cwd")
        return StdioServerParameters(
            command=command,
            args=args,
            env=env,
            cwd=cwd,
        )

    def _tool_to_capability(self, tool: Tool) -> McpCapability:
        return McpCapability(
            capability_id=f"{self._server.server_id}/{tool.name}",
            server_id=self._server.server_id,
            name=tool.name,
            title=tool.title,
            capability_type=McpCapabilityType.TOOL,
            description=tool.description or "",
            input_schema=tool.inputSchema,
            output_schema=tool.outputSchema or {},
            risk_level=McpRiskLevel.LOW,
        )
