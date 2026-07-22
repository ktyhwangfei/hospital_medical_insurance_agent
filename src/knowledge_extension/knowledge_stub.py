"""
知识存储 stub — 原 knowledge/ 模块已删除，提供最小兼容接口。
"""
from typing import Any


class _StubKnowledgeStore:
    """空实现，所有方法返回默认值。"""
    def get_error_code(self, error_code: str) -> dict[str, Any]:
        return {}
    def list_error_codes(self, **kwargs) -> list[dict[str, Any]]:
        return []
    def health(self) -> dict[str, Any]:
        return {"status": "unavailable", "reason": "knowledge module removed"}


def create_knowledge_store() -> _StubKnowledgeStore:
    return _StubKnowledgeStore()
