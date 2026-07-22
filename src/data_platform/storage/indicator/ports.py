"""
指标值存储端口（Port）

定义 IndicatorStorage Protocol，遵循 data_platform/storage 的 ports/adapter 模式。
对标 storage/skill/ports.py 的 SkillStorage Protocol。
"""
from typing import Protocol

from src.domain.indicator.models import IndicatorValue


class IndicatorStorage(Protocol):
    """指标值存储端口

    存储指标运行时值（IndicatorValue），支持按 definition_id + 上下文键存取。
    上下文键通常为 settlement_id，确保同一结算单的指标可以整体管理。
    """

    def save_value(self, value: IndicatorValue) -> None:
        """保存一个指标值"""
        ...

    def get_value(self, definition_id: str, context_key: str) -> IndicatorValue | None:
        """获取指定指标在指定上下文中的值

        Args:
            definition_id: 指标定义ID
            context_key: 上下文键（通常是 settlement_id）

        Returns:
            指标值实例，不存在时返回 None
        """
        ...

    def get_context(self, settlement_id: str) -> dict[str, IndicatorValue]:
        """获取某次结算的全部指标值

        Args:
            settlement_id: 结算单号

        Returns:
            definition_id → IndicatorValue 的字典
        """
        ...

    def delete_context(self, settlement_id: str) -> bool:
        """删除某次结算的指标缓存

        Args:
            settlement_id: 结算单号

        Returns:
            是否成功删除
        """
        ...

    def health(self) -> dict:
        """健康检查"""
        ...
