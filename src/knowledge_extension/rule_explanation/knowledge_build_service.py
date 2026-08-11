"""政策知识构建任务的候选单元读取与提交前校验。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from src.knowledge_extension.rule_explanation.change_set_models import (
    SourceUnitRevision,
)
from src.knowledge_extension.rule_explanation.change_set_service import (
    ChangeSetService,
    SelectedKnowledgeUnit,
    change_set_id_for_task,
)

from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    CreateKnowledgeBuildTaskRequest,
    EligibleKnowledgeUnit,
    KnowledgeBuildBlocker,
    KnowledgeBuildPreflight,
    KnowledgeBuildTask,
    KnowledgeBuildTaskUnit,
    KnowledgeBuildWarning,
    utc_now,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    KnowledgeBuildStore,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeWorkbenchDocument,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)
from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
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


class KnowledgeExtractionFailed(RuntimeError):
    """所选单元未能生成可供构建的提取结果。"""

    def __init__(self, *, doc_id: str, unit_id: str, message: str) -> None:
        self.doc_id = doc_id
        self.unit_id = unit_id
        self.task_id: str | None = None
        super().__init__(message)


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
        orchestrator: PipelineOrchestrator | None = None,
        clock: Callable[[], datetime] = utc_now,
        task_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._workbench = workbench_service
        self._change_set_service = change_set_service
        self._store = store
        self._orchestrator = orchestrator
        self._clock = clock
        self._task_id_factory = task_id_factory

    def list_eligible_units(self) -> list[EligibleKnowledgeUnit]:
        """列出全部审核通过单元及当前占用/重建状态（批量加载，避免 N+1）。"""
        claims_by_logical = {
            (claim.doc_id, claim.unit_id): claim
            for claim in self._store.list_claims()
        }
        tasks_by_id = self._store.get_many(
            [claim.task_id for claim in claims_by_logical.values()]
        )
        eligible: list[tuple[int, EligibleKnowledgeUnit]] = []
        for document in self._load_documents():
            for unit in document.units:
                claim = claims_by_logical.get((unit.doc_id, unit.unit_id))
                task = tasks_by_id.get(claim.task_id) if claim is not None else None
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
        result, _resolved = self._evaluate_preflight(request)
        return result

    def create_task(
        self,
        request: CreateKnowledgeBuildTaskRequest,
    ) -> KnowledgeBuildTask:
        """从单次服务端快照校验、占用并构建待审核候选。"""
        preflight, resolved = self._evaluate_preflight(request)
        if not preflight.can_submit or preflight.semantic_contract_version is None:
            raise KnowledgeBuildPreflightBlocked(preflight)

        created_at = self._clock_now()
        task_id = (
            self._task_id_factory()
            if self._task_id_factory is not None
            else f"KB_{created_at.astimezone(timezone.utc):%Y%m%d}_{uuid4().hex[:12]}"
        )
        if not task_id.strip():
            raise ValueError("知识构建任务 ID 不能为空")

        queued = KnowledgeBuildTask(
            task_id=task_id,
            name=request.name,
            status="QUEUED",
            build_mode=request.build_mode,
            rebuild_reason=request.rebuild_reason,
            semantic_contract_version=preflight.semantic_contract_version,
            pipeline_version=self.pipeline_version,
            model_scene=self.model_scene,
            config_hash=self.config_hash,
            created_by=request.created_by,
            units=[
                KnowledgeBuildTaskUnit(
                    doc_id=selected.source_revision.doc_id,
                    doc_title=selected.source_revision.doc_title,
                    unit_id=selected.source_revision.unit_id,
                    unit_revision_id=selected.source_revision.unit_revision_id,
                    path=list(selected.source_revision.path),
                )
                for selected in resolved
            ],
            created_at=created_at,
            updated_at=created_at,
        )
        created = self._store.create_with_claims(queued)
        expected_change_set_id = change_set_id_for_task(task_id)
        result_change_set_id: str | None = None
        try:
            running = self._store.save(
                created.model_copy(
                    update={"status": "RUNNING", "started_at": self._clock_now()},
                    deep=True,
                )
            )
            change_set = self._change_set_service.build_for_units(
                task_id=task_id,
                task_name=request.name,
                units=self._units_with_knowledge(list(resolved)),
                semantic_contract_version=preflight.semantic_contract_version,
                supersedes_candidate_id=None,
            )
            result_change_set_id = change_set.change_set_id
            completed_units = [
                unit.model_copy(
                    update={
                        "status": "BUILT",
                        "candidate_result_ids": [
                            item.item_id
                            for item in change_set.items
                            if item.doc_id == unit.doc_id
                            and item.unit_id == unit.unit_id
                        ],
                    },
                    deep=True,
                )
                for unit in running.units
            ]
            return self._store.save(
                running.model_copy(
                    update={
                        "status": "WAITING_REVIEW",
                        "units": completed_units,
                        "processed_units": len(completed_units),
                        "result_change_set_id": change_set.change_set_id,
                        "result_summary": {
                            key: int(value) for key, value in change_set.summary.items()
                        },
                        "finished_at": self._clock_now(),
                    },
                    deep=True,
                )
            )
        except Exception as error:
            if isinstance(error, KnowledgeExtractionFailed):
                error.task_id = created.task_id
            if result_change_set_id is None:
                try:
                    persisted = self._change_set_service.get_change_set(
                        expected_change_set_id
                    )
                    if persisted is not None:
                        result_change_set_id = persisted.change_set_id
                except Exception as lookup_error:
                    error.add_note(
                        "查询已持久化知识构建候选时出错: "
                        f"{type(lookup_error).__name__}: {lookup_error}"
                    )
            self._record_failure(created, error, result_change_set_id)
            raise

    def _record_failure(
        self,
        created: KnowledgeBuildTask,
        error: Exception,
        result_change_set_id: str | None,
    ) -> None:
        failed_task: KnowledgeBuildTask | None = None
        try:
            failed_task = self._store.fail_and_release(
                created.task_id,
                error_code=type(error).__name__,
                error_message=str(error),
                result_change_set_id=result_change_set_id,
            )
        except Exception as recording_error:
            error.add_note(
                "记录知识构建任务失败状态时出错: "
                f"{type(recording_error).__name__}: {recording_error}"
            )
        if (
            result_change_set_id is None
            or failed_task is None
            or failed_task.status != "FAILED"
        ):
            return
        try:
            self._change_set_service.fail_candidate(
                result_change_set_id,
                reason=str(error),
            )
        except Exception as candidate_error:
            error.add_note(
                "失效知识构建候选时出错: "
                f"{type(candidate_error).__name__}: {candidate_error}"
            )

    def _evaluate_preflight(
        self,
        request: CreateKnowledgeBuildTaskRequest,
    ) -> tuple[KnowledgeBuildPreflight, tuple[SelectedKnowledgeUnit, ...]]:
        documents = self._load_documents()
        current_units = {
            (unit.doc_id, unit.unit_id): (document, unit)
            for document in documents
            for unit in document.units
        }
        blockers: list[KnowledgeBuildBlocker] = []
        warnings: list[KnowledgeBuildWarning] = []
        selected_contract_versions: list[str | None] = []
        resolved: list[SelectedKnowledgeUnit] = []
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
            current_revision_id = unit_revision_id_for(
                doc_id=unit.doc_id,
                unit_id=unit.unit_id,
                source_text=unit.source_text,
            )
            resolved.append(
                SelectedKnowledgeUnit(
                    unit=unit.model_copy(deep=True),
                    source_revision=SourceUnitRevision(
                        doc_id=unit.doc_id,
                        doc_title=unit.doc_title,
                        unit_id=unit.unit_id,
                        unit_revision_id=current_revision_id,
                        path=list(unit.path),
                    ),
                )
            )
            unit_blocked = False
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

        return (
            KnowledgeBuildPreflight(
                selected_count=len(request.unit_revisions),
                buildable_count=buildable_count,
                blocking_count=len(blockers),
                rebuild_count=rebuild_count,
                can_submit=not blockers,
                semantic_contract_version=semantic_contract_version,
                blockers=blockers,
                warnings=warnings,
            ),
            tuple(resolved),
        )

    def _clock_now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("知识构建任务时钟必须返回带时区时间")
        return current

    def _load_documents(self) -> list[KnowledgeWorkbenchDocument]:
        # 单遍加载：直接枚举文档 id 再逐篇读取，避免 list_documents 内部
        # 已逐篇 get_document 后又重复加载一遍（性能瓶颈，迭代 16 修复）。
        return [
            self._workbench.get_document(doc_id, include_knowledge=False)
            for doc_id in self._workbench.list_document_ids()
        ]

    def _units_with_knowledge(
        self,
        resolved: list[SelectedKnowledgeUnit],
    ) -> list[SelectedKnowledgeUnit]:
        """重新加载所选单元的完整 knowledge，供变更集聚合使用。

        ``_load_documents`` 为性能只做轻量加载（include_knowledge=False），
        此时单元 knowledge 为空；聚合候选必须重新读取完整 knowledge，
        否则变更集 items 为空（审核页无候选可审）。
        """
        by_key: dict[tuple[str, str], ApprovedUnit] = {}
        for doc_id in {unit.unit.doc_id for unit in resolved}:
            document = self._workbench.get_document(doc_id, include_knowledge=True)
            by_key.update(
                {(unit.doc_id, unit.unit_id): unit for unit in document.units}
            )
        extracted = False
        if self._orchestrator is not None:
            for selected in resolved:
                unit = by_key.get((selected.unit.doc_id, selected.unit.unit_id))
                if unit is not None and unit.knowledge:
                    continue
                result = self._orchestrator.extract_single(
                    selected.unit.doc_id,
                    selected.unit.source_text,
                    unit_id=selected.unit.unit_id,
                    reset_status="reviewed",
                )
                if not result.get("success"):
                    raise KnowledgeExtractionFailed(
                        doc_id=selected.unit.doc_id,
                        unit_id=selected.unit.unit_id,
                        message=(
                            result.get("error") or "知识构建未生成提取结果"
                        ),
                    )
                extracted = True

        if extracted:
            by_key.clear()
            for doc_id in {unit.unit.doc_id for unit in resolved}:
                document = self._workbench.get_document(
                    doc_id, include_knowledge=True
                )
                by_key.update(
                    {(unit.doc_id, unit.unit_id): unit for unit in document.units}
                )
        refreshed: list[SelectedKnowledgeUnit] = []
        for selected in resolved:
            unit = by_key.get((selected.unit.doc_id, selected.unit.unit_id))
            if unit is not None and unit.knowledge:
                # 重新加载的完整单元（含 knowledge）优先，供聚合使用
                refreshed.append(
                    SelectedKnowledgeUnit(
                        unit=unit, source_revision=selected.source_revision
                    )
                )
            elif self._orchestrator is not None:
                raise KnowledgeExtractionFailed(
                    doc_id=selected.unit.doc_id,
                    unit_id=selected.unit.unit_id,
                    message="知识提取未生成候选规则",
                )
            else:
                # 回退：重新加载后仍无 knowledge（如测试替身）时保持原单元，
                # 由 build_for_units 按既有行为处理。
                refreshed.append(selected)
        return refreshed

    @staticmethod
    def _semantic_contract_version(
        versions: list[str | None],
    ) -> str | None:
        normalized = [version.strip() if version is not None else "" for version in versions]
        unique = set(normalized)
        if len(unique) == 1 and "" not in unique:
            return next(iter(unique))
        return None
