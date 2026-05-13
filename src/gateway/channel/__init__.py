"""渠道识别模块

检测请求来源渠道（门户、嵌入式、移动端、管理后台、API），
通过 Header / Referer / User-Agent 判定。
"""
import logging
from enum import StrEnum
from typing import Final

logger = logging.getLogger(__name__)


class ChannelType(StrEnum):
    """请求渠道类型枚举"""
    PORTAL = "portal"            # 门户网站
    EMBEDDED = "embedded"        # 嵌入式集成（第三方嵌入）
    MOBILE = "mobile"            # 移动端应用
    ADMIN = "admin"              # 管理后台
    API = "api"                  # 第三方 API 调用
    UNKNOWN = "unknown"          # 未知渠道


# 各渠道的特征标记
_PORTAL_HOSTS: Final[set[str]] = {"portal", "www"}
_EMBEDDED_HEADER: Final[str] = "x-embedded-source"
_ADMIN_PATHS: Final[tuple[str, ...]] = ("/admin", "/management")

# 常见的移动端 User-Agent 关键字
_MOBILE_UA_KEYWORDS: Final[set[str]] = {
    "mobile", "android", "iphone", "ipad", "ipod",
    "harmonyos", "huawei", "xiaomi", "oppo", "vivo",
}


class ChannelDetector:
    """渠道检测器

    通过分析请求的 Header、Referer、User-Agent 等信息，
    自动识别请求来源渠道。
    """

    def detect(
        self,
        *,
        host: str = "",
        user_agent: str = "",
        referer: str = "",
        headers: dict[str, str] | None = None,
        path: str = "",
    ) -> ChannelType:
        """检测请求来源渠道

        Args:
            host: 请求 Host
            user_agent: User-Agent 请求头
            referer: Referer 请求头
            headers: 其他自定义请求头
            path: 请求路径

        Returns:
            检测到的渠道类型
        """
        headers = headers or {}

        # 1. 嵌入式渠道：通过自定义 Header 标记
        if headers.get(_EMBEDDED_HEADER):
            logger.debug("Detected embedded channel via header: %s", headers[_EMBEDDED_HEADER])
            return ChannelType.EMBEDDED

        # 2. 管理后台：请求路径以 /admin 或 /management 开头
        if path.startswith(_ADMIN_PATHS):
            return ChannelType.ADMIN

        # 3. 移动端：User-Agent 包含移动端关键字
        ua_lower = user_agent.lower()
        if any(kw in ua_lower for kw in _MOBILE_UA_KEYWORDS):
            return ChannelType.MOBILE

        # 4. 门户网站：Host 包含门户关键字
        host_lower = host.lower()
        if any(h in host_lower for h in _PORTAL_HOSTS):
            return ChannelType.PORTAL

        # 5. Referer 辅助判断
        if referer:
            ref_lower = referer.lower()
            if any(h in ref_lower for h in _PORTAL_HOSTS):
                return ChannelType.PORTAL
            if any(kw in ref_lower for kw in _MOBILE_UA_KEYWORDS):
                return ChannelType.MOBILE

        # 6. 默认视为 API 调用
        return ChannelType.API

    def reset(self) -> None:
        """重置检测器状态（无状态实现，占位）"""
        pass


# 全局单例
channel_detector = ChannelDetector()


__all__ = [
    "ChannelType",
    "ChannelDetector",
    "channel_detector",
]
