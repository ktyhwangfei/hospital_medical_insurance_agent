"""请求安全校验模块

提供参数校验、敏感动作检测与拦截等请求安全防护功能。
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# 高风险动作关键词（命中即需人工确认）
HIGH_RISK_ACTIONS: set[str] = {
    "退费", "冲正", "正式结算", "病案修改",
    "删除", "注销", "封存", "作废",
}

# SQL 注入检测正则
_SQL_INJECTION_PATTERN: re.Pattern[str] = re.compile(
    r"(\b(select|insert|update|delete|drop|alter|truncate|exec|union|create)\b.*\b(from|into|set|where|table|database)\b)",
    re.IGNORECASE,
)

# XSS 检测正则
_XSS_PATTERN: re.Pattern[str] = re.compile(
    r"<script[^>]*>.*</script[^>]*>|<[^>]*on\w+\s*=\s*['\"].*?['\"]|<iframe[^>]*>",
    re.IGNORECASE,
)

# 路径遍历检测
_PATH_TRAVERSAL_PATTERN: re.Pattern[str] = re.compile(
    r"\.\./|\.\.\\|%2e%2e%2f|%2e%2e\\",
    re.IGNORECASE,
)


@dataclass
class GuardResult:
    """安全校验结果

    Attributes:
        allowed: 是否允许通过
        risk_level: 风险等级（low / medium / high）
        blocked_reason: 拦截原因
        detected_actions: 检测到的高风险动作列表
        suggestions: 处理建议
    """
    allowed: bool = True
    risk_level: str = "low"
    blocked_reason: str = ""
    detected_actions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class ParameterValidation:
    """参数校验规则

    Attributes:
        required: 是否必填
        max_length: 最大长度
        pattern: 正则校验
        description: 参数说明
    """
    required: bool = False
    max_length: int | None = None
    pattern: str | None = None
    description: str = ""


class RequestGuard:
    """请求安全守卫

    执行参数校验、敏感动作检测、注入攻击防护等安全检查。
    """

    def __init__(self) -> None:
        self._param_rules: dict[str, dict[str, ParameterValidation]] = {}

    def register_param_rules(
        self,
        scene: str,
        rules: dict[str, ParameterValidation],
    ) -> None:
        """注册场景参数校验规则

        Args:
            scene: 业务场景标识
            rules: 参数字段到校验规则的映射
        """
        self._param_rules[scene] = rules
        logger.debug("Param rules registered for scene: %s (%d fields)", scene, len(rules))

    def validate_params(self, scene: str, params: dict[str, Any]) -> GuardResult:
        """校验请求参数

        Args:
            scene: 业务场景标识
            params: 请求参数字典

        Returns:
            校验结果
        """
        rules = self._param_rules.get(scene)
        if not rules:
            # 未注册规则时默认放行
            return GuardResult()

        errors: list[str] = []

        for field_name, rule in rules.items():
            value = params.get(field_name)

            # 必填校验
            if rule.required and (value is None or value == ""):
                errors.append(f"缺少必填参数: {field_name}")

            if value is None or value == "":
                continue

            str_value = str(value)

            # 最大长度校验
            if rule.max_length is not None and len(str_value) > rule.max_length:
                errors.append(f"参数 {field_name} 超过最大长度 {rule.max_length}")

            # 正则校验
            if rule.pattern and not re.match(rule.pattern, str_value):
                errors.append(f"参数 {field_name} 格式不合法")

        if errors:
            return GuardResult(
                allowed=False,
                risk_level="medium",
                blocked_reason="；".join(errors),
            )

        return GuardResult()

    def detect_high_risk(self, user_input: str) -> GuardResult:
        """检测用户输入中的高风险操作

        Args:
            user_input: 用户输入文本

        Returns:
            检测结果
        """
        detected: list[str] = []
        for action in HIGH_RISK_ACTIONS:
            if action in user_input:
                detected.append(action)

        if detected:
            return GuardResult(
                allowed=False,
                risk_level="high",
                blocked_reason=f"检测到高风险操作: {'、'.join(detected)}，需人工确认",
                detected_actions=detected,
                suggestions=["请联系人工审核后执行"],
            )

        return GuardResult()

    def detect_injection(self, user_input: str) -> GuardResult:
        """检测注入攻击（SQL / XSS / 路径遍历）

        Args:
            user_input: 用户输入文本

        Returns:
            检测结果
        """
        if _SQL_INJECTION_PATTERN.search(user_input):
            return GuardResult(
                allowed=False,
                risk_level="high",
                blocked_reason="检测到 SQL 注入风险",
                suggestions=["请移除输入中的 SQL 语句"],
            )

        if _XSS_PATTERN.search(user_input):
            return GuardResult(
                allowed=False,
                risk_level="high",
                blocked_reason="检测到 XSS 跨站脚本风险",
                suggestions=["请移除输入中的脚本标签"],
            )

        if _PATH_TRAVERSAL_PATTERN.search(user_input):
            return GuardResult(
                allowed=False,
                risk_level="high",
                blocked_reason="检测到路径遍历攻击风险",
                suggestions=["请移除输入中的路径遍历字符"],
            )

        return GuardResult()

    def check(self, scene: str, params: dict[str, Any], user_input: str = "") -> GuardResult:
        """综合安全检查（参数校验 + 敏感动作 + 注入检测）

        Args:
            scene: 业务场景
            params: 请求参数
            user_input: 用户输入文本

        Returns:
            综合安全检查结果
        """
        # 1. 参数校验
        param_result = self.validate_params(scene, params)
        if not param_result.allowed:
            return param_result

        if not user_input:
            return GuardResult()

        # 2. 注入攻击检测
        injection_result = self.detect_injection(user_input)
        if not injection_result.allowed:
            return injection_result

        # 3. 高风险动作检测
        risk_result = self.detect_high_risk(user_input)
        if not risk_result.allowed:
            return risk_result

        return GuardResult()

    def reset(self) -> None:
        """重置守卫状态"""
        self._param_rules.clear()


# 全局单例
request_guard = RequestGuard()


__all__ = [
    "GuardResult",
    "ParameterValidation",
    "RequestGuard",
    "request_guard",
]
