from fastapi import APIRouter

from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.mcp_registry.models import McpServer
from src.knowledge_extension.mcp_registry.service import McpRegistryService

router = APIRouter(prefix="/api/v1/medical-insurance-ai-agent/mcp", tags=["mcp"])
_storage = InMemoryMcpStorage()
_service = McpRegistryService(_storage)


@router.get("/storage/health")
def get_mcp_storage_health():
    return _storage.health()


@router.post("/servers")
def register_mcp_server(server: McpServer):
    registered = _service.register_server(server)
    return registered.to_public_dict()
