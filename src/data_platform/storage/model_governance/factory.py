"""模型治理存储选择。"""

import os
from functools import lru_cache

from src.data_platform.storage.model_governance.in_memory import (
    InMemoryModelGovernanceStorage,
)
from src.data_platform.storage.model_governance.ports import ModelGovernanceStorage
from src.data_platform.storage.model_governance.postgres import (
    PostgresModelGovernanceStorage,
)


@lru_cache(maxsize=1)
def get_model_governance_storage() -> ModelGovernanceStorage:
    if os.environ.get("USE_MEMORY_STORAGE") == "1":
        return InMemoryModelGovernanceStorage()
    return PostgresModelGovernanceStorage()

