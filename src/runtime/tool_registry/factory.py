"""ToolRegistryService 单例工厂，登记全部内置 Tool。"""

from functools import lru_cache

from src.runtime.tool_registry.builtin_tools import register_builtin_tools
from src.runtime.tool_registry.calc_tools import register_calc_tools
from src.runtime.tool_registry.data_tools import register_data_tools
from src.runtime.tool_registry.knowledge_tools import register_knowledge_tools
from src.runtime.tool_registry.service import ToolRegistryService


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistryService:
    registry = ToolRegistryService()
    register_builtin_tools(registry)
    register_data_tools(registry)
    register_knowledge_tools(registry)
    register_calc_tools(registry)
    return registry
