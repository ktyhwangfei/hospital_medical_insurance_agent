"""模型服务配置 — 门户运行时所需，管理 CRUD 已移除。"""

import os
from dataclasses import dataclass, field


@dataclass
class ModelServiceConfig:
    """模型服务网关配置，环境变量可覆盖。"""
    base_url: str = field(default_factory=lambda: os.getenv("MODEL_BASE_URL", "dummy"))
    api_key: str = field(default_factory=lambda: os.getenv("MODEL_API_KEY", ""))
    default_timeout: int = field(
        default_factory=lambda: int(os.getenv("MODEL_TIMEOUT", "30"))
    )
    max_retries: int = 3
    default_model: str = "gpt-4"
