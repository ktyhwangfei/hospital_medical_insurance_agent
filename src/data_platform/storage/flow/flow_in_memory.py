"""治理 Flow 内存存储（开发/测试；USE_MEMORY_STORAGE=1）。"""
from __future__ import annotations

import threading

from src.domain.governed_flow.models import (
    FlowDefinition,
    FlowNotFoundError,
    FlowPublishedRevision,
    FlowRevisionConflictError,
)


class InMemoryGovernedFlowStorage:
    """dict + 深拷贝隔离 + 乐观锁；活跃版本用独立指针维护（单活跃约束）。"""

    def __init__(self) -> None:
        self._flows: dict[str, FlowDefinition] = {}
        self._revisions: dict[str, FlowPublishedRevision] = {}
        self._active: dict[str, str] = {}  # flow_id → 活跃 revision_id
        self._lock = threading.RLock()

    def create_flow(self, flow: FlowDefinition) -> FlowDefinition:
        with self._lock:
            if flow.flow_id in self._flows:
                raise FlowRevisionConflictError(f"flow {flow.flow_id} 已存在")
            stored = flow.model_copy(deep=True)
            self._flows[flow.flow_id] = stored
            return stored.model_copy(deep=True)

    def get_flow(self, flow_id: str) -> FlowDefinition | None:
        with self._lock:
            flow = self._flows.get(flow_id)
            return None if flow is None else flow.model_copy(deep=True)

    def list_flows(self) -> list[FlowDefinition]:
        with self._lock:
            return [f.model_copy(deep=True) for f in self._flows.values()]

    def update_flow(self, flow: FlowDefinition, expected_revision: int) -> FlowDefinition:
        with self._lock:
            current = self._flows.get(flow.flow_id)
            if current is None:
                raise FlowNotFoundError(flow.flow_id)
            if current.revision != expected_revision:
                raise FlowRevisionConflictError(
                    f"乐观锁冲突：期望 revision={expected_revision}，实际 {current.revision}"
                )
            stored = flow.model_copy(deep=True)
            self._flows[flow.flow_id] = stored
            return stored.model_copy(deep=True)

    def delete_flow(self, flow_id: str, expected_revision: int) -> None:
        with self._lock:
            current = self._flows.get(flow_id)
            if current is None:
                raise FlowNotFoundError(flow_id)
            if current.revision != expected_revision:
                raise FlowRevisionConflictError(
                    f"乐观锁冲突：期望 revision={expected_revision}，实际 {current.revision}"
                )
            del self._flows[flow_id]

    def save_published_revision(self, revision: FlowPublishedRevision) -> None:
        """写入发布证据并将新版本置为活跃（与 PG 单语句切换同语义）。"""
        with self._lock:
            self._revisions[revision.revision_id] = revision.model_copy(deep=True)
            self._active[revision.flow_id] = revision.revision_id

    def get_published_revision(self, revision_id: str) -> FlowPublishedRevision | None:
        with self._lock:
            revision = self._revisions.get(revision_id)
            return None if revision is None else revision.model_copy(deep=True)

    def list_published_revisions(self, flow_id: str) -> list[FlowPublishedRevision]:
        with self._lock:
            revisions = [
                r.model_copy(deep=True)
                for r in self._revisions.values()
                if r.flow_id == flow_id
            ]
            return sorted(revisions, key=lambda r: r.flow_revision)

    def get_active_revision(self, flow_id: str) -> FlowPublishedRevision | None:
        with self._lock:
            revision_id = self._active.get(flow_id)
            if revision_id is None:
                return None
            revision = self._revisions.get(revision_id)
            return None if revision is None else revision.model_copy(deep=True)

    def set_active_revision(self, flow_id: str, revision_id: str) -> None:
        """回滚/发布共用的活跃版本切换；目标必须属于同一 flow。"""
        with self._lock:
            target = self._revisions.get(revision_id)
            if target is None or target.flow_id != flow_id:
                raise FlowNotFoundError(f"发布版本 {revision_id} 不属于 flow {flow_id}")
            self._active[flow_id] = revision_id
