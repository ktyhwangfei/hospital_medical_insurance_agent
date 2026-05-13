"""聊天模块

会话管理、消息处理、历史记录。
"""
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ChatSession(BaseModel):
    """聊天会话

    维护一次对话的完整状态，包含会话标识、用户身份、历史消息。
    """

    session_id: str = Field(..., description="会话唯一标识")
    user_id: str = Field(..., description="用户标识")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="最后更新时间")
    history: list[dict[str, Any]] = Field(default_factory=list, description="消息历史")

    def add_message(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        """添加消息到历史记录

        Args:
            role: 消息角色（user / assistant / system）
            content: 消息内容
            metadata: 附加元数据
        """
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            message["metadata"] = metadata
        self.history.append(message)
        self.updated_at = datetime.now()
        logger.info("会话 %s 添加 %s 消息: %s...", self.session_id, role, content[:50])

    def get_context(self, max_messages: int = 10) -> list[dict[str, Any]]:
        """获取最近的消息上下文

        Args:
            max_messages: 返回的最大消息数

        Returns:
            最近的消息列表
        """
        return self.history[-max_messages:]

    def clear_history(self) -> None:
        """清空消息历史"""
        self.history.clear()
        self.updated_at = datetime.now()
        logger.info("会话 %s 历史已清空", self.session_id)


class MessageHandler:
    """消息处理器

    负责消息的发送、接收和格式化处理。
    """

    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}

    def create_session(self, session_id: str, user_id: str) -> ChatSession:
        """创建新会话

        Args:
            session_id: 会话标识
            user_id: 用户标识

        Returns:
            创建的会话实例
        """
        session = ChatSession(session_id=session_id, user_id=user_id)
        self.sessions[session_id] = session
        logger.info("创建会话 %s (用户 %s)", session_id, user_id)
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        """获取会话

        Args:
            session_id: 会话标识

        Returns:
            会话实例，不存在时返回 None
        """
        return self.sessions.get(session_id)

    def send_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """发送消息（记录到会话历史）

        Args:
            session_id: 会话标识
            role: 消息角色
            content: 消息内容
            metadata: 附加元数据

        Returns:
            格式化的消息字典，会话不存在时返回 None
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning("会话 %s 不存在，无法发送消息", session_id)
            return None
        session.add_message(role, content, metadata)
        return self.format_message(role, content, metadata)

    @staticmethod
    def format_message(
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """格式化消息为统一结构

        Args:
            role: 消息角色
            content: 消息内容
            metadata: 附加元数据

        Returns:
            统一格式的消息字典
        """
        message: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            message["metadata"] = metadata
        return message


# 全局聊天处理器单例
chat_handler = MessageHandler()
