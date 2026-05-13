"""页面上下文模块

管理患者、住院号、页面来源等页面上下文信息。
"""
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PageContext(BaseModel):
    """页面上下文

    携带当前页面相关的患者信息、住院信息和页面来源。
    """

    patient_id: str = Field("", description="患者编号")
    patient_name: str = Field("", description="患者姓名")
    encounter_id: str = Field("", description="住院就诊编号")
    department: str = Field("", description="科室")
    page_source: str = Field("", description="页面来源标识")
    extra: dict[str, Any] = Field(default_factory=dict, description="额外上下文")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class PageContextManager:
    """页面上下文管理器

    管理前端页面传入的上下文，确保后续操作能获取正确的患者和业务上下文。
    """

    def __init__(self) -> None:
        self.contexts: dict[str, PageContext] = {}
        self._current_context_id: str = ""

    def create_context(
        self,
        context_id: str,
        patient_id: str = "",
        patient_name: str = "",
        encounter_id: str = "",
        department: str = "",
        page_source: str = "",
        extra: dict[str, Any] | None = None,
    ) -> PageContext:
        """创建页面上下文

        Args:
            context_id: 上下文唯一标识
            patient_id: 患者编号
            patient_name: 患者姓名
            encounter_id: 住院就诊编号
            department: 科室
            page_source: 页面来源标识
            extra: 额外上下文

        Returns:
            创建的页面上下文
        """
        context = PageContext(
            patient_id=patient_id,
            patient_name=patient_name,
            encounter_id=encounter_id,
            department=department,
            page_source=page_source,
            extra=extra or {},
        )
        self.contexts[context_id] = context
        self._current_context_id = context_id
        logger.info(
            "创建页面上下文 %s: 患者 %s(%s), 住院 %s, 来源 %s",
            context_id, patient_name, patient_id, encounter_id, page_source,
        )
        return context

    def get_context(self, context_id: str | None = None) -> PageContext | None:
        """获取页面上下文

        Args:
            context_id: 上下文标识，None 时返回当前上下文

        Returns:
            页面上下文，不存在时返回 None
        """
        cid = context_id or self._current_context_id
        return self.contexts.get(cid)

    def current_context(self) -> PageContext | None:
        """获取当前页面上下文

        Returns:
            当前页面上下文，未设置时返回 None
        """
        if not self._current_context_id:
            return None
        return self.contexts.get(self._current_context_id)

    def update_context(self, context_id: str, **updates: Any) -> PageContext | None:
        """更新页面上下文字段

        Args:
            context_id: 上下文标识
            **updates: 要更新的字段

        Returns:
            更新后的页面上下文，不存在时返回 None
        """
        context = self.contexts.get(context_id)
        if not context:
            logger.warning("页面上下文 %s 不存在", context_id)
            return None
        for key, value in updates.items():
            if hasattr(context, key):
                setattr(context, key, value)
        logger.info("页面上下文 %s 已更新", context_id)
        return context

    def set_current(self, context_id: str) -> bool:
        """设置当前激活的上下文

        Args:
            context_id: 上下文标识

        Returns:
            设置是否成功
        """
        if context_id in self.contexts:
            self._current_context_id = context_id
            logger.info("当前上下文切换至 %s", context_id)
            return True
        logger.warning("上下文 %s 不存在，无法切换", context_id)
        return False


# 全局页面上下文管理器单例
page_context_manager = PageContextManager()
