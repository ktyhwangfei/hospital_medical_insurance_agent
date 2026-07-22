"""
指标值内存存储实现

基于字典的 InMemoryIndicatorStorage，遵循 storage/skill/in_memory.py 的 InMemorySkillStorage 模式。
使用组合键 {definition_id}:{settlement_id} 存储 IndicatorValue，返回时深拷贝。
"""
from copy import deepcopy

from src.domain.indicator.models import IndicatorValue


class InMemoryIndicatorStorage:
    """指标值内存存储

    以 dict 存储 IndicatorValue 实例，键格式为 {definition_id}:{settlement_id}。
    所有读取操作返回深拷贝，防止外部修改内部状态。
    """

    def __init__(self) -> None:
        # 存储结构: {"deductible_amount:SETL001": IndicatorValue(...)}
        self._store: dict[str, IndicatorValue] = {}

    def _key(self, definition_id: str, context_key: str) -> str:
        """生成内部存储键"""
        return f"{definition_id}:{context_key}"

    def save_value(self, value: IndicatorValue) -> None:
        """保存指标值（深拷贝）"""
        key = self._key(value.definition_id, value.context.get("settlement_id", ""))
        self._store[key] = value.model_copy(deep=True)

    def get_value(self, definition_id: str, context_key: str) -> IndicatorValue | None:
        """获取指定上下文中的指标值

        返回深拷贝，防止外部修改影响内部状态。
        """
        key = self._key(definition_id, context_key)
        stored = self._store.get(key)
        return None if stored is None else stored.model_copy(deep=True)

    def get_context(self, settlement_id: str) -> dict[str, IndicatorValue]:
        """获取某次结算的全部指标值

        遍历所有以 {settlement_id} 结尾的键，返回深拷贝字典。
        """
        suffix = f":{settlement_id}"
        result: dict[str, IndicatorValue] = {}
        for key, value in self._store.items():
            if key.endswith(suffix):
                result[value.definition_id] = value.model_copy(deep=True)
        return result

    def delete_context(self, settlement_id: str) -> bool:
        """删除某次结算的全部指标缓存

        Returns:
            是否有任何数据被删除
        """
        suffix = f":{settlement_id}"
        keys_to_delete = [k for k in self._store if k.endswith(suffix)]
        for key in keys_to_delete:
            del self._store[key]
        return len(keys_to_delete) > 0

    def health(self) -> dict:
        """健康检查"""
        return {
            "status": "healthy",
            "backend": "in_memory",
            "total_values": len(self._store),
        }
