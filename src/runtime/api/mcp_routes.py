from fastapi import APIRouter, HTTPException

from src.config.mcp import load_mcp_settings
from src.data_platform.storage.mcp.factory import create_mcp_storage
from src.knowledge_extension.mcp_registry.models import McpCapability, McpServer
from src.knowledge_extension.mcp_registry.service import McpRegistryService
from src.shared.schemas.responses import error_detail

router = APIRouter(prefix="/api/v1/medical-insurance-ai-agent/mcp", tags=["mcp"])
_storage = create_mcp_storage(load_mcp_settings())
_service = McpRegistryService(_storage)


# ── Health ────────────────────────────────────────────────────────────────────


@router.get("/storage/health")
def get_mcp_storage_health():
    return _storage.health()


# ── Servers ───────────────────────────────────────────────────────────────────


@router.get("/servers")
def list_mcp_servers() -> list[dict]:
    servers = _storage.list_servers()
    return [s.to_public_dict() for s in servers]


@router.post("/servers")
def register_mcp_server(server: McpServer):
    registered = _service.register_server(server)
    return registered.to_public_dict()


@router.get("/servers/{server_id}")
def get_mcp_server(server_id: str) -> dict:
    server = _storage.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail=error_detail('SERVER_NOT_FOUND', 'MCP 服务器不存在'))
    return server.to_public_dict()


# ── Capabilities ──────────────────────────────────────────────────────────────


@router.get("/capabilities")
def list_mcp_capabilities() -> list[dict]:
    capabilities = _storage.list_capabilities()
    return [c.model_dump() for c in capabilities]


@router.get("/capabilities/{capability_id}")
def get_mcp_capability(capability_id: str) -> dict:
    capability = _storage.get_capability(capability_id)
    if capability is None:
        raise HTTPException(status_code=404, detail=error_detail('CAPABILITY_NOT_FOUND', 'MCP 能力不存在'))
    return capability.model_dump()


@router.get("/capabilities/by-server/{server_id}")
def list_mcp_capabilities_by_server(server_id: str) -> list[dict]:
    capabilities = _storage.list_capabilities()
    filtered = [c for c in capabilities if c.server_id == server_id]
    return [c.model_dump() for c in filtered]


@router.post("/capabilities")
def register_mcp_capability(capability: McpCapability):
    registered = _service.register_capability(capability)
    return registered.model_dump()


@router.delete("/capabilities/{capability_id}")
def delete_mcp_capability(capability_id: str) -> dict:
    existing = _storage.get_capability(capability_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=error_detail('CAPABILITY_NOT_FOUND', 'MCP 能力不存在'))
    _storage.delete_capability(capability_id)
    return {"deleted": True}
