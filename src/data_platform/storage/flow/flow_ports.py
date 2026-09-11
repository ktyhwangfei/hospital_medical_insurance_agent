"""治理 Flow 存储端口 — Phase 1。

遵循项目 ports/adapter 模式（照 skill 版本存储四件套）：
in_memory（开发/测试，USE_MEMORY_STORAGE=1）与 postgres 双实现。
"""
from typing import Protocol

from src.domain.governed_flow.models import FlowDefinition, FlowPublishedRevision


class GovernedFlowStorage(Protocol):
    """Flow 草稿主表 + 不可变发布版本证据的存储契约。"""

    def create_flow(self, flow: FlowDefinition) -> FlowDefinition: ...
    def get_flow(self, flow_id: str) -> FlowDefinition | None: ...
    def list_flows(self) -> list[FlowDefinition]: ...
    def update_flow(self, flow: FlowDefinition, expected_revision: int) -> FlowDefinition: ...
    def delete_flow(self, flow_id: str, expected_revision: int) -> None: ...

    def save_published_revision(self, revision: FlowPublishedRevision) -> None: ...
    def get_published_revision(self, revision_id: str) -> FlowPublishedRevision | None: ...
    def list_published_revisions(self, flow_id: str) -> list[FlowPublishedRevision]: ...
    def get_active_revision(self, flow_id: str) -> FlowPublishedRevision | None: ...
    def set_active_revision(self, flow_id: str, revision_id: str) -> None: ...


class FlowViewDeployer(Protocol):
    """发布视图 DDL 的部署端口（Phase 3：publish/rollback 前先落 PG 落地库）。

    DDL 由编译器产出并锁定进 artifact_hash，部署方不得改写；
    部署失败必须抛异常（fail closed：无部署则无发布证据）。
    """

    def deploy_view(self, view_sql: str) -> None: ...


class FlowViewReader(Protocol):
    """受控问数视图读取端口（Phase 3：消费只读已部署视图，禁止改写 SQL）。

    列名由服务层从发布定义白名单推导；读取方不得拼接任意 SQL。
    """

    def read(self, view_name: str, columns: list[str]) -> list[dict]: ...
