"""模型治理服务组装入口。"""

from functools import lru_cache

from src.data_platform.storage.model_governance.factory import (
    get_model_governance_storage,
)
from src.model_service.governance_service import ModelGovernanceService


@lru_cache(maxsize=1)
def get_model_governance_service() -> ModelGovernanceService:
    return ModelGovernanceService(get_model_governance_storage())
