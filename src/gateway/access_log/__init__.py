"""接入日志模块

记录所有请求/响应/审计信息，用于运维监控、安全审计和问题溯源。
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AccessLogEntry:
    """接入日志条目

    Attributes:
        request_id: 请求唯一标识
        timestamp: 日志时间戳
        channel: 请求渠道
        tenant_id: 租户 ID
        user_id: 用户 ID
        method: HTTP 方法
        path: 请求路径
        query_params: 查询参数
        status_code: HTTP 状态码
        duration_ms: 处理耗时（毫秒）
        client_ip: 客户端 IP
        user_agent: User-Agent
        request_body: 请求体（脱敏后）
        response_body: 响应体（脱敏后）
        error_code: 错误码
        risk_level: 风险等级
        audit_events: 审计事件列表
        metadata: 额外元数据
    """
    request_id: str = ""
    timestamp: str = ""
    channel: str = ""
    tenant_id: str = ""
    user_id: str = ""
    method: str = ""
    path: str = ""
    query_params: str = ""
    status_code: int = 0
    duration_ms: float = 0.0
    client_ip: str = ""
    user_agent: str = ""
    request_body: str = ""
    response_body: str = ""
    error_code: str = ""
    risk_level: str = "low"
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# 敏感字段，记录日志前自动脱敏
_SENSITIVE_FIELDS: set[str] = {
    "password", "secret", "token", "authorization",
    "id_card", "phone", "mobile", "bank_card",
}


def _mask_sensitive(data: dict[str, Any], parent_key: str = "") -> dict[str, Any]:
    """脱敏敏感数据

    Args:
        data: 原始数据
        parent_key: 父级键名（用于嵌套字段）

    Returns:
        脱敏后的数据
    """
    masked: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{parent_key}.{key}" if parent_key else key

        if isinstance(value, dict):
            masked[key] = _mask_sensitive(value, full_key)
        elif any(s in full_key.lower() for s in _SENSITIVE_FIELDS):
            s = str(value)
            masked[key] = s[:3] + "***" + s[-3:] if len(s) > 6 else "******"
        else:
            masked[key] = value

    return masked


class AccessLogger:
    """接入日志记录器

    记录并格式化所有请求的接入日志，支持结构化输出和审计追踪。
    """

    def __init__(self) -> None:
        self._entries: list[AccessLogEntry] = []

    def log(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        client_ip: str = "",
        user_agent: str = "",
        channel: str = "",
        tenant_id: str = "",
        user_id: str = "",
        query_params: dict[str, str] | None = None,
        request_body: dict[str, Any] | None = None,
        response_body: dict[str, Any] | None = None,
        error_code: str = "",
        risk_level: str = "low",
        audit_events: list[dict[str, Any]] | None = None,
    ) -> None:
        """记录一条接入日志

        Args:
            request_id: 请求唯一标识
            method: HTTP 方法
            path: 请求路径
            status_code: HTTP 状态码
            duration_ms: 处理耗时（毫秒）
            client_ip: 客户端 IP
            user_agent: User-Agent
            channel: 请求渠道
            tenant_id: 租户 ID
            user_id: 用户 ID
            query_params: 查询参数
            request_body: 请求体
            response_body: 响应体
            error_code: 错误码
            risk_level: 风险等级
            audit_events: 审计事件列表
        """
        # 请求体脱敏
        masked_request = _mask_sensitive(request_body or {})
        masked_response = _mask_sensitive(response_body or {})

        entry = AccessLogEntry(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            channel=channel,
            tenant_id=tenant_id,
            user_id=user_id,
            method=method.upper(),
            path=path,
            query_params=json.dumps(query_params or {}, ensure_ascii=False),
            status_code=status_code,
            duration_ms=round(duration_ms, 2),
            client_ip=client_ip,
            user_agent=user_agent,
            request_body=json.dumps(masked_request, ensure_ascii=False),
            response_body=json.dumps(masked_response, ensure_ascii=False),
            error_code=error_code,
            risk_level=risk_level,
            audit_events=audit_events or [],
        )

        self._entries.append(entry)
        self._write_entry(entry)

    def _write_entry(self, entry: AccessLogEntry) -> None:
        """写入日志条目到输出通道

        Args:
            entry: 日志条目
        """
        log_data = {
            "type": "access_log",
            "request_id": entry.request_id,
            "timestamp": entry.timestamp,
            "channel": entry.channel,
            "tenant_id": entry.tenant_id,
            "user_id": entry.user_id,
            "method": entry.method,
            "path": entry.path,
            "status": entry.status_code,
            "duration_ms": entry.duration_ms,
            "client_ip": entry.client_ip,
            "error_code": entry.error_code,
            "risk_level": entry.risk_level,
        }

        # 高风险或有错误的请求使用 WARNING 级别
        if entry.risk_level in ("high", "medium") or entry.status_code >= 400:
            logger.warning("AccessLog: %s", json.dumps(log_data, ensure_ascii=False))
        else:
            logger.info("AccessLog: %s", json.dumps(log_data, ensure_ascii=False))

    def get_entries(
        self,
        request_id: str | None = None,
        limit: int = 100,
    ) -> list[AccessLogEntry]:
        """获取日志条目

        Args:
            request_id: 按请求 ID 筛选
            limit: 返回条数上限

        Returns:
            符合条件的日志条目列表
        """
        if request_id:
            filtered = [e for e in self._entries if e.request_id == request_id]
        else:
            filtered = list(self._entries)

        return filtered[-limit:]

    def flush(self) -> None:
        """刷新日志缓冲区（当前为内存实现，后续对接外部日志系统）"""
        self._entries.clear()
        logger.debug("AccessLog buffer flushed")

    def reset(self) -> None:
        """重置日志记录器"""
        self.flush()


# 全局单例
access_logger = AccessLogger()


__all__ = [
    "AccessLogEntry",
    "AccessLogger",
    "access_logger",
]
