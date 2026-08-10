"""知识构建任务创建后变更集候选非空回归测试（缺陷驱动）。

复现缺陷：选择单元继续知识审核 → 变更集 items=0 → 审核页空白。
根因：`KnowledgeBuildService._load_documents()` 用 `include_knowledge=False`
加载单元（迭代 16 性能优化），此时单元 `knowledge=[]`；`create_task` 聚合时
复用这些空 knowledge 单元 → `_aggregate_units` 产出 0 条 items。

本测试走真实组件链路（KnowledgeWorkbenchService → ChangeSetService →
KnowledgeBuildService），修复前应为红（items 为空），修复后应为绿。
"""
from __future__ import annotations

import pytest

from src.knowledge_extension.rule_explanation.change_set_service import ChangeSetService
from src.knowledge_extension.rule_explanation.change_set_store import InMemoryChangeSetStore
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    CreateKnowledgeBuildTaskRequest,
    KnowledgeBuildUnitRevision,
)
from src.knowledge_extension.rule_explanation.knowledge_build_service import (
    KnowledgeBuildService,
    unit_revision_id_for,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    InMemoryKnowledgeBuildStore,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)
from src.tests.unit.knowledge_extension.test_knowledge_workbench import (
    FakePipelineStore,
    _extraction,
    _leaf_ids,
    _rules,
)


class _ContractRegistry:
    """提供非空语义契约版本（真实 registry 的最小替身）。"""

    def __init__(self) -> None:
        self.contract = type(
            "Contract", (), {"current_version": "contract-v3", "version": "contract-v3"}
        )()

    def get_object(self, name: str):
        if name != "zcgz":
            return None
        return self.contract

    def list_metrics(self, name: str) -> list:
        return []


def _build_service() -> tuple[KnowledgeBuildService, ChangeSetService, KnowledgeWorkbenchService]:
    leaves = _leaf_ids()
    store = FakePipelineStore([_extraction(leaves[0], _rules())])
    workbench = KnowledgeWorkbenchService(store, registry=_ContractRegistry())
    change_set_service = ChangeSetService(workbench, InMemoryChangeSetStore())
    build_service = KnowledgeBuildService(
        workbench_service=workbench,
        change_set_service=change_set_service,
        store=InMemoryKnowledgeBuildStore(),
        task_id_factory=lambda: "KB_REGRESSION_FIXED",
    )
    return build_service, change_set_service, workbench


def test_create_task_change_set_items_are_non_empty_after_unit_selection() -> None:
    """用户选择单元继续知识审核 → 构建任务 → 变更集必须有候选条目。"""
    build_service, change_set_service, workbench = _build_service()
    document = workbench.get_document("doc_1")
    unit = document.units[0]
    assert unit.knowledge, "测试前置：所选单元应包含 knowledge"

    task = build_service.create_task(
        CreateKnowledgeBuildTaskRequest(
            name="选择单元继续知识审核",
            created_by="reviewer-1",
            build_mode="INITIAL",
            unit_revisions=[
                KnowledgeBuildUnitRevision(
                    doc_id="doc_1",
                    unit_id=unit.unit_id,
                    unit_revision_id=unit_revision_id_for(
                        doc_id="doc_1",
                        unit_id=unit.unit_id,
                        source_text=unit.source_text,
                    ),
                )
            ],
        )
    )

    assert task.status == "WAITING_REVIEW"
    change_set = change_set_service.get_change_set(task.result_change_set_id)
    assert change_set is not None
    # 缺陷修复点：聚合用的单元必须带 knowledge，items 不应为空
    assert len(change_set.items) > 0, "所选单元构建出的变更集候选为空，审核页将空白"
    assert change_set.summary["additions"] == len(change_set.items)
