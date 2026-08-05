"""政策知识构建任务的候选单元读取与提交前校验。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    CreateKnowledgeBuildTaskRequest,
    EligibleKnowledgeUnit,
    KnowledgeBuildBlocker,
    KnowledgeBuildPreflight,
    KnowledgeBuildTask,
    KnowledgeBuildWarning,
    utc_now,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    KnowledgeBuildStore,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    KnowledgeWorkbenchDocument,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)

if TYPE_CHECKING:
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )


_PIPELINE_VERSION = "policy-workbench-v1"
_MODEL_SCENE = "policy_structuring"
_CONFIG_HASH = hashlib.sha256(
    "\0".join((_PIPELINE_VERSION, _MODEL_SCENE)).encode("utf-8")
).hexdigest()


class KnowledgeBuildPreflightBlocked(ValueError):
    """创建任务前校验未通过，并携带可直接返回的类型化结果。"""

    def __init__(self, result: KnowledgeBuildPreflight) -> None:
        self.result = result
        super().__init__("知识构建任务预检未通过")


def unit_revision_id_for(*, doc_id: str, unit_id: str, source_text: str) -> str:
    payload = "\0".join((doc_id, unit_id, source_text)).encode("utf-8")
    return f"UR_{hashlib.sha256(payload).hexdigest()[:24]}"


def _claim_target(task: KnowledgeBuildTask | None, task_id: str) -> str:
    if (
        task is not None
        and task.status == "WAITING_REVIEW"
        and task.result_change_set_id
    ):
        return f"/policy-knowledge/knowledge/review/{task.result_change_set_id}"
    if task is not None and task.status == "APPROVED_PENDING_RELEASE":
        return "/policy-knowledge/knowledge/releases"
    return f"/policy-knowledge/knowledge/build?task_id={task_id}"


def _source_preview(source_text: str) -> str:
    return " ".join(source_text.split())[:120]


class KnowledgeBuildService:
    """基于服务端当前工作台快照读取候选单元并执行只读预检。"""

    pipeline_version = _PIPELINE_VERSION
    model_scene = _MODEL_SCENE
    config_hash = _CONFIG_HASH

    def __init__(
        self,
        workbench_service: KnowledgeWorkbenchService,
        change_set_service: "ChangeSetService",
        store: KnowledgeBuildStore,
        *,
        clock: Callable[[], datetime] = utc_now,
        task_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._workbench = workbench_service
        self._change_set_service = change_set_service
        self._store = store
        self._clock = clock
        self._task_id_factory = task_id_factory

    def list_eligible_units(self) -> list[EligibleKnowledgeUnit]:
        """列出全部审核通过单元及当前占用/重建状态。"""
        eligible: list[tuple[int, EligibleKnowledgeUnit]] = []
        for document in self._load_documents():
            for unit in document.units:
                claim = self._store.get_claim(unit.doc_id, unit.unit_id)
                task = self._store.get(claim.task_id) if claim is not None else None
                availability = (
                    "CLAIMED"
                    if claim is not None
                    else "REBUILD_REQUIRED"
                    if unit.status == "published"
                    else "AVAILABLE"
                )
                eligible.append(
                    (
                        unit.order_no,
                        EligibleKnowledgeUnit(
                            doc_id=unit.doc_id,
                            doc_title=unit.doc_title,
                            unit_id=unit.unit_id,
                            unit_revision_id=unit_revision_id_for(
                                doc_id=unit.doc_id,
                                unit_id=unit.unit_id,
                                source_text=unit.source_text,
                            ),
                            path=unit.path,
                            source_preview=_source_preview(unit.source_text),
                            status=unit.status,
                            knowledge_count=unit.knowledge_count,
                            availability=availability,
                            occupied_by=claim.task_id if claim is not None else None,
                            target_href=(
                                _claim_target(task, claim.task_id)
                                if claim is not None
                                else None
                            ),
                        ),
                    )
                )
        eligible.sort(
            key=lambda entry: (
                entry[1].doc_title,
                entry[0],
                tuple(entry[1].path),
                entry[1].unit_id,
                entry[1].doc_id,
            )
        )
        return [item for _order_no, item in eligible]

    def preflight(
        self,
        request: CreateKnowledgeBuildTaskRequest,
    ) -> KnowledgeBuildPreflight:
        """按服务端最新来源、占用和语义契约执行只读提交前校验。"""
        documents = self._load_documents()
        current_units = {
            (unit.doc_id, unit.unit_id): (document, unit)
            for document in documents
            for unit in document.units
        }
        blockers: list[KnowledgeBuildBlocker] = []
        warnings: list[KnowledgeBuildWarning] = []
        selected_contract_versions: list[str | None] = []
        buildable_count = 0
        rebuild_count = 0

        for selection in request.unit_revisions:
            current = current_units.get((selection.doc_id, selection.unit_id))
            if current is None:
                blockers.append(
                    KnowledgeBuildBlocker(
                        code="UNIT_NOT_APPROVED",
                        message="所选政策单元不存在或尚未审核通过",
                        doc_id=selection.doc_id,
                        unit_id=selection.unit_id,
                        unit_revision_id=selection.unit_revision_id,
                    )
                )
                continue

            document, unit = current
            selected_contract_versions.append(document.contract_version)
            unit_blocked = False
            current_revision_id = unit_revision_id_for(
                doc_id=unit.doc_id,
                unit_id=unit.unit_id,
                source_text=unit.source_text,
            )
            if selection.unit_revision_id != current_revision_id:
                blockers.append(
                    KnowledgeBuildBlocker(
                        code="UNIT_REVISION_CHANGED",
                        message="政策单元原文已变化，请刷新后重新选择",
                        doc_id=selection.doc_id,
                        unit_id=selection.unit_id,
                        unit_revision_id=current_revision_id,
                    )
                )
                unit_blocked = True

            claim = self._store.get_claim(unit.doc_id, unit.unit_id)
            if claim is not None:
                task = self._store.get(claim.task_id)
                blockers.append(
                    KnowledgeBuildBlocker(
                        code="UNIT_ALREADY_CLAIMED",
                        message=f"政策单元已由构建任务 {claim.task_id} 占用",
                        doc_id=selection.doc_id,
                        unit_id=selection.unit_id,
                        unit_revision_id=current_revision_id,
                        task_id=claim.task_id,
                        target_href=_claim_target(task, claim.task_id),
                    )
                )
                unit_blocked = True

            if unit.status == "published" and request.build_mode == "INITIAL":
                blockers.append(
                    KnowledgeBuildBlocker(
                        code="REBUILD_MODE_REQUIRED",
                        message="已发布政策单元必须使用重建模式",
                        doc_id=selection.doc_id,
                        unit_id=selection.unit_id,
                        unit_revision_id=current_revision_id,
                    )
                )
                unit_blocked = True

            if unit_blocked:
                continue

            buildable_count += 1
            if unit.status == "published" and request.build_mode == "REBUILD":
                rebuild_count += 1
                warnings.append(
                    KnowledgeBuildWarning(
                        code="REBUILDING_PUBLISHED_UNIT",
                        message="该政策单元已发布，本次将生成重建候选",
                        doc_id=unit.doc_id,
                        unit_id=unit.unit_id,
                    )
                )

        semantic_contract_version = self._semantic_contract_version(
            selected_contract_versions
        )
        if selected_contract_versions and semantic_contract_version is None:
            blockers.append(
                KnowledgeBuildBlocker(
                    code="SEMANTIC_CONTRACT_MISMATCH",
                    message="所选政策单元必须共享同一个非空语义契约版本",
                )
            )
        if request.build_mode == "REBUILD" and not request.rebuild_reason:
            blockers.append(
                KnowledgeBuildBlocker(
                    code="REBUILD_REASON_REQUIRED",
                    message="重建模式必须填写重建原因",
                )
            )

        return KnowledgeBuildPreflight(
            selected_count=len(request.unit_revisions),
            buildable_count=buildable_count,
            blocking_count=len(blockers),
            rebuild_count=rebuild_count,
            can_submit=not blockers,
            semantic_contract_version=semantic_contract_version,
            blockers=blockers,
            warnings=warnings,
        )

    def _load_documents(self) -> list[KnowledgeWorkbenchDocument]:
        summaries = self._workbench.list_documents()
        return [
            self._workbench.get_document(summary.doc_id)
            for summary in summaries.items
        ]

    @staticmethod
    def _semantic_contract_version(
        versions: list[str | None],
    ) -> str | None:
        normalized = [version.strip() if version is not None else "" for version in versions]
        unique = set(normalized)
        if len(unique) == 1 and "" not in unique:
            return next(iter(unique))
        return None
