"""
缓存配置模块
包含全局缓存开关、各域 TTL、精细控制开关和熔断器参数。
所有值可通过环境变量覆盖，提供合理的默认值。
"""
import os

# ============================================================
# 全局开关
# ============================================================
# 全局缓存总开关: 1=启用, 0=禁用
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1")
# Redis 故障时是否回退到 InMemory 缓存: 1=回退, 0=抛异常
CACHE_FAIL_OPEN = os.getenv("CACHE_FAIL_OPEN", "1")
# 缓存键全局前缀（多租户隔离用）
CACHE_KEY_PREFIX = os.getenv("CACHE_KEY_PREFIX", "")

# ============================================================
# 各域 TTL（秒）
# ============================================================
# Skill 技能定义缓存 TTL（默认1小时）
CACHE_TTL_SKILL = int(os.getenv("CACHE_TTL_SKILL", "3600"))
# MCP 服务器/能力缓存 TTL（默认1小时）
CACHE_TTL_MCP = int(os.getenv("CACHE_TTL_MCP", "3600"))
# 错误码知识库缓存 TTL（默认2小时）
CACHE_TTL_KNOWLEDGE = int(os.getenv("CACHE_TTL_KNOWLEDGE", "7200"))
# 规则解释缓存 TTL（默认2小时）
CACHE_TTL_RULE = int(os.getenv("CACHE_TTL_RULE", "7200"))
# 知识资产+切片缓存 TTL（默认30分钟）
CACHE_TTL_ASSET = int(os.getenv("CACHE_TTL_ASSET", "1800"))
# 申诉模板缓存 TTL（默认2小时）
CACHE_TTL_APPEAL = int(os.getenv("CACHE_TTL_APPEAL", "7200"))

# ============================================================
# 按域精细控制开关
# ============================================================
CACHE_ENABLED_SKILL = os.getenv("CACHE_ENABLED_SKILL", "1")
CACHE_ENABLED_MCP = os.getenv("CACHE_ENABLED_MCP", "1")
CACHE_ENABLED_KNOWLEDGE = os.getenv("CACHE_ENABLED_KNOWLEDGE", "1")
CACHE_ENABLED_RULE = os.getenv("CACHE_ENABLED_RULE", "1")
CACHE_ENABLED_ASSET = os.getenv("CACHE_ENABLED_ASSET", "1")
CACHE_ENABLED_APPEAL = os.getenv("CACHE_ENABLED_APPEAL", "1")

# ============================================================
# 熔断器参数
# ============================================================
# 连续缓存操作失败阈值（达到此值后跳过缓存直连DB）
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CACHE_CIRCUIT_THRESHOLD", "5"))
# 熔断恢复窗口（秒）
CIRCUIT_BREAKER_WINDOW = int(os.getenv("CACHE_CIRCUIT_WINDOW", "60"))
