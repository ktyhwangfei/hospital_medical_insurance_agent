"""通知模块

待办提醒、风险提醒等消息通知服务。
"""
import logging
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    """通知类型枚举"""
    TODO_REMINDER = "todo_reminder"          # 待办提醒
    RISK_ALERT = "risk_alert"                # 风险提醒
    SYSTEM_NOTICE = "system_notice"          # 系统通知
    APPROVAL_REQUEST = "approval_request"    # 审批请求


class NotificationPriority(str, Enum):
    """通知优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Notification(BaseModel):
    """通知消息

    包含通知类型、内容、优先级、目标用户等完整信息。
    """

    notification_id: str = Field(..., description="通知唯一标识")
    type: NotificationType = Field(..., description="通知类型")
    title: str = Field(..., description="通知标题")
    content: str = Field(..., description="通知内容")
    priority: NotificationPriority = Field(NotificationPriority.MEDIUM, description="优先级")
    target_user: str = Field("", description="目标用户标识")
    source: str = Field("system", description="通知来源")
    read: bool = Field(False, description="是否已读")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    read_at: datetime | None = Field(None, description="阅读时间")


class NotificationService:
    """通知服务

    提供待办提醒、风险提醒等消息的发送和管理。
    """

    def __init__(self) -> None:
        self.notifications: dict[str, Notification] = {}

    def send(
        self,
        notification_id: str,
        type: NotificationType,
        title: str,
        content: str,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        target_user: str = "",
        source: str = "system",
    ) -> Notification:
        """发送通知

        Args:
            notification_id: 通知唯一标识
            type: 通知类型
            title: 通知标题
            content: 通知内容
            priority: 优先级
            target_user: 目标用户
            source: 通知来源

        Returns:
            创建的通知
        """
        notification = Notification(
            notification_id=notification_id,
            type=type,
            title=title,
            content=content,
            priority=priority,
            target_user=target_user,
            source=source,
        )
        self.notifications[notification_id] = notification
        logger.info(
            "发送通知 [%s] %s -> %s: %s",
            type.value, source, target_user or "全体", title,
        )
        return notification

    def send_todo_reminder(
        self,
        notification_id: str,
        title: str,
        content: str,
        target_user: str,
    ) -> Notification:
        """发送待办提醒

        Args:
            notification_id: 通知唯一标识
            title: 提醒标题
            content: 提醒内容
            target_user: 目标用户

        Returns:
            创建的通知
        """
        return self.send(
            notification_id=notification_id,
            type=NotificationType.TODO_REMINDER,
            title=title,
            content=content,
            priority=NotificationPriority.HIGH,
            target_user=target_user,
        )

    def send_risk_alert(
        self,
        notification_id: str,
        title: str,
        content: str,
        target_user: str = "",
    ) -> Notification:
        """发送风险提醒

        Args:
            notification_id: 通知唯一标识
            title: 提醒标题
            content: 提醒内容
            target_user: 目标用户

        Returns:
            创建的通知
        """
        return self.send(
            notification_id=notification_id,
            type=NotificationType.RISK_ALERT,
            title=title,
            content=content,
            priority=NotificationPriority.URGENT,
            target_user=target_user,
        )

    def mark_read(self, notification_id: str) -> bool:
        """标记通知为已读

        Args:
            notification_id: 通知标识

        Returns:
            操作是否成功
        """
        notification = self.notifications.get(notification_id)
        if not notification:
            logger.warning("通知 %s 不存在", notification_id)
            return False
        notification.read = True
        notification.read_at = datetime.now()
        logger.info("通知 %s 标记为已读", notification_id)
        return True

    def get_unread(self, target_user: str | None = None) -> list[Notification]:
        """获取未读通知

        Args:
            target_user: 用户过滤，None 时返回全部未读

        Returns:
            未读通知列表
        """
        result = []
        for notification in self.notifications.values():
            if not notification.read:
                if target_user and notification.target_user != target_user:
                    continue
                result.append(notification)
        return result

    def get_by_user(self, target_user: str) -> list[Notification]:
        """获取指定用户的所有通知

        Args:
            target_user: 用户标识

        Returns:
            用户通知列表
        """
        return [
            n for n in self.notifications.values()
            if n.target_user == target_user
        ]


# 全局通知服务单例
notification_service = NotificationService()
