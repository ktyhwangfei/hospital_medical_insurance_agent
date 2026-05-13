import logging
import os

from src.runtime.runtime_state.models import WorkflowInstance

logger = logging.getLogger(__name__)


def create_runtime_state_store():
    """创建运行时状态存储（使用PostgreSQL，失败时回退到内存实现）"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    
    if not use_memory:
        try:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.postgresql.client import PostgreSQLClient
            from src.runtime.runtime_state.postgresql_store import PostgreSQLRuntimeStateStore
            client = PostgreSQLClient(DATABASE_URL)
            logger.info("Using PostgreSQL runtime state store")
            return PostgreSQLRuntimeStateStore(client)
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL runtime state store, falling back to in-memory: {e}")
    
    # 内存实现回退
    class InMemoryRuntimeStateStore:
        def __init__(self):
            self._workflows: dict[str, WorkflowInstance] = {}

        def save_workflow(self, workflow: WorkflowInstance) -> WorkflowInstance:
            self._workflows[workflow.workflow_id] = workflow
            return workflow

        def get_workflow(self, workflow_id: str) -> WorkflowInstance | None:
            return self._workflows.get(workflow_id)

        def list_workflows(
            self,
            scenario: str | None = None,
            status: str | None = None,
        ) -> list[WorkflowInstance]:
            result = list(self._workflows.values())
            if scenario:
                result = [w for w in result if w.scenario == scenario]
            if status:
                allowed_statuses = set(status.split(','))
                result = [w for w in result if w.status in allowed_statuses]
            return result
    
    logger.info("Using in-memory runtime state store")
    return InMemoryRuntimeStateStore()


runtime_state_store = create_runtime_state_store()
