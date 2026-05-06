from fastapi import APIRouter

from src.config.mcp import load_mcp_settings
from src.data_platform.storage.mcp.factory import create_mcp_storage
from src.knowledge_extension.mcp_registry.models import McpServer
from src.knowledge_extension.mcp_registry.service import McpRegistryService

router = APIRouter(prefix="/api/v1/medical-insurance-ai-agent/mcp", tags=["mcp"])
_storage = create_mcp_storage(load_mcp_settings())
_service = McpRegistryService(_storage)


@router.get("/storage/health")
def get_mcp_storage_health():
    return _storage.health()


@router.post("/servers")
def register_mcp_server(server: McpServer):
    registered = _service.register_server(server)
    return registered.to_public_dict()
