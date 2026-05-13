import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from src.knowledge_extension.mcp_registry.models import McpServer, McpTransportType

_MCP_PROTOCOL_VERSION = "2025-03-26"
_CLIENT_NAME = "hospital-medical-insurance-agent"
_CLIENT_VERSION = "0.1.0"


def _resolve_command(command: str) -> tuple[str, list[str]]:
    if sys.platform == "win32" and command in ("npx", "npx.cmd"):
        node_exe = shutil.which("node")
        if node_exe:
            npx_prefix = Path(node_exe).parent / "node_modules" / "npm" / "bin" / "npx-cli.js"
            if npx_prefix.exists():
                return node_exe, [str(npx_prefix)]
    resolved = shutil.which(command)
    return (resolved or command), []


class StdioMcpClient:
    def __init__(self, timeout_seconds: float = 15.0):
        self._timeout = timeout_seconds

    async def list_tools(self, server: McpServer) -> list[dict[str, Any]]:
        proc = await self._spawn_proc(server)
        try:
            await self._send_request(proc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": _CLIENT_NAME, "version": _CLIENT_VERSION},
                },
            })
            await self._send_notification(proc, {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            })
            tools_result = await self._send_request(proc, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            })
            tools = tools_result.get("result", {}).get("tools", [])
            return tools if isinstance(tools, list) else []
        finally:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    async def _send_request(self, proc: asyncio.subprocess.Process, message: dict[str, Any]) -> dict[str, Any]:
        line = json.dumps(message, separators=(",", ":")) + "\n"
        if proc.stdin is None:
            raise RuntimeError("Process stdin not available")
        proc.stdin.write(line.encode("utf-8"))
        await proc.stdin.drain()
        return await asyncio.wait_for(self._read_response(proc), timeout=self._timeout)

    async def _send_notification(self, proc: asyncio.subprocess.Process, message: dict[str, Any]) -> None:
        line = json.dumps(message, separators=(",", ":")) + "\n"
        if proc.stdin is None:
            raise RuntimeError("Process stdin not available")
        proc.stdin.write(line.encode("utf-8"))
        await proc.stdin.drain()

    async def _read_response(self, proc: asyncio.subprocess.Process) -> dict[str, Any]:
        if proc.stdout is None:
            raise RuntimeError("Process stdout not available")
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                raise RuntimeError("MCP process closed stdout unexpectedly")
            text = raw.decode("utf-8").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if "error" in msg:
                error = msg["error"]
                raise RuntimeError(f"MCP error {error.get('code')}: {error.get('message')}")
            if "result" in msg:
                return msg
            if "method" in msg:
                continue
            return msg

    async def call_tool(self, server: McpServer, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if server.transport != McpTransportType.STDIO:
            raise ValueError(f"StdioMcpClient only supports stdio transport, got {server.transport}")
        proc = await self._spawn_proc(server)
        try:
            await self._send_request(proc, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": _CLIENT_NAME, "version": _CLIENT_VERSION},
                },
            })
            await self._send_notification(proc, {
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
            result = await self._send_request(proc, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            })
            return result.get("result", {})
        finally:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    async def _spawn_proc(self, server: McpServer) -> asyncio.subprocess.Process:
        connection = server.connection_config
        command = connection.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"Server {server.server_id} missing command in connection_config")
        args = connection.get("args", [])
        if not isinstance(args, list):
            args = []
        env_vars = connection.get("env", {})
        if not isinstance(env_vars, dict):
            env_vars = {}
        cwd = connection.get("cwd")
        process_env = {**os.environ, **{str(k): str(v) for k, v in env_vars.items()}}
        resolved_command, prefix_args = _resolve_command(command)
        full_args = [*prefix_args, *[str(a) for a in args]]
        return await asyncio.create_subprocess_exec(
            resolved_command, *full_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd if isinstance(cwd, str) else None,
            env=process_env,
        )

    async def call_tool_sequence(self, server: McpServer, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if server.transport != McpTransportType.STDIO:
            raise ValueError(f"StdioMcpClient only supports stdio transport, got {server.transport}")
        proc = await self._spawn_proc(server)
        results: list[dict[str, Any]] = []
        try:
            await self._send_request(proc, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": _CLIENT_NAME, "version": _CLIENT_VERSION},
                },
            })
            await self._send_notification(proc, {
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
            req_id = 2
            for call in tool_calls:
                result = await self._send_request(proc, {
                    "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                    "params": {"name": call["name"], "arguments": call.get("arguments", {})},
                })
                results.append(result.get("result", {}))
                req_id += 1
            return results
        finally:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    def call_tool_sequence_sync(self, server: McpServer, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.call_tool_sequence(server, tool_calls))
                return future.result(timeout=self._timeout * len(tool_calls) + 30)
        return asyncio.run(self.call_tool_sequence(server, tool_calls))

    def call_tool_sync(self, server: McpServer, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.call_tool(server, tool_name, arguments))
                return future.result(timeout=self._timeout + 25)
        return asyncio.run(self.call_tool(server, tool_name, arguments))

    def list_tools_sync(self, server: McpServer) -> list[dict[str, Any]]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.list_tools(server))
                return future.result(timeout=self._timeout + 5)
        return asyncio.run(self.list_tools(server))
