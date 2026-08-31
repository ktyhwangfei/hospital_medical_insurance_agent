"""Skill 批量评测、人工审批与 test shadow 发布应用服务。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceConflictError,
    SkillGovernanceNotFoundError,
    SkillGovernanceStorage,
)
from src.data_platform.storage.skill.version_ports import SkillVersionStorage
from src.domain.skill.governance_models import (
    DEFAULT_ROUTING_SUITE_ID,
    SkillEvalBenchmark,
    SkillEvalDatasetVersion,
    SkillEvalEnvironmentSnapshot,
    SkillEvalGateThresholds,
    SkillEvalCase,
    SkillEvalRun,
    SkillEvalRunStatus,
    SkillEvalSuite,
    SkillEvalSuiteScope,
    SkillEvalSuiteStatus,
    SkillEvalTask,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
    canonical_eval_hash,
)
from src.domain.skill.version_models import SkillValidationStatus, SkillVersion
from src.security.desensitization.detection import detect_sensitive_patterns
from src.skill_infra.route_evaluator import evaluate_route_suite

# 预置黄金 routing 用例：覆盖 settlement_explain_skill 核心关键词，作为路由回归基线。
# expected_skill_id 必须是已物化 skill（当前仅 settlement_explain_skill）。
GOLDEN_ROUTING_CASES: list[tuple[str, str, list[str]]] = [
    ("起付线怎么算", "settlement_explain_skill", ["settlement"]),
    ("起付线是多少", "settlement_explain_skill", ["settlement"]),
    ("统筹自付为什么这么多", "settlement_explain_skill", ["settlement"]),
    ("门槛费是什么意思", "settlement_explain_skill", ["settlement"]),
    ("报销比例是多少", "settlement_explain_skill", ["settlement"]),
    ("大额自付怎么算", "settlement_explain_skill", ["settlement"]),
    ("医保报销比例", "settlement_explain_skill", ["settlement"]),
    ("住院起付线多少", "settlement_explain_skill", ["settlement"]),
]


class SkillGovernanceGateError(ValueError):
    """评测、审批或基线门禁未通过。"""

    def __init__(self, message: str, gate_failures: list[str]) -> None:
        super().__init__(message)
        self.gate_failures = gate_failures


class _LoadedSkill(Protocol):
    manifest: dict[str, Any]


class _LoaderView(Protocol):
    def get_all(self) -> dict[str, _LoadedSkill]: ...


class SkillGovernanceService:
    _GATE_CONFIG: dict[str, object] = {
        "router": "keyword_v1",
        "required_pass_rate": 1.0,
        "allow_accuracy_regression": False,
        "max_new_false_takeovers": 0,
        "runtime_mode": "shadow",
    }
    _EVALUATOR_PLAN_ID = "deterministic_v1"

    def __init__(
        self,
        *,
        storage: SkillGovernanceStorage,
        version_storage: SkillVersionStorage,
        loader: _LoaderView,
    ) -> None:
        self._storage = storage
        self._version_storage = version_storage
        self._loader = loader

    def list_suites(
        self,
        *,
        skill_id: str | None = None,
        include_inactive: bool = True,
    ) -> list[SkillEvalSuite]:
        return self._storage.list_suites(
            skill_id=skill_id,
            include_inactive=include_inactive,
        )

    def get_suite(self, suite_id: str) -> SkillEvalSuite:
        suite = self._storage.get_suite(suite_id)
        if suite is None:
            raise SkillGovernanceNotFoundError(f"测评集不存在: {suite_id}")
        return suite

    def create_suite(
        self,
        *,
        name: str,
        scope: SkillEvalSuiteScope | str,
        skill_id: str | None,
        purpose: str,
        created_by: str,
    ) -> SkillEvalSuite:
        resolved_scope = SkillEvalSuiteScope(scope)
        if resolved_scope == SkillEvalSuiteScope.SKILL:
            if not skill_id or skill_id not in self._loader.get_all():
                raise SkillGovernanceNotFoundError(f"Skill 不存在: {skill_id}")
        else:
            skill_id = None
        now = datetime.now(timezone.utc)
        return self._storage.save_suite(
            SkillEvalSuite(
                suite_id=f"EVS_{uuid4().hex}",
                name=name.strip(),
                scope=resolved_scope,
                skill_id=skill_id,
                purpose=purpose.strip(),
                created_by=created_by.strip(),
                updated_by=created_by.strip(),
                created_at=now,
                updated_at=now,
            )
        )

    def update_suite(
        self,
        suite_id: str,
        *,
        name: str,
        purpose: str,
        status: SkillEvalSuiteStatus | str,
        expected_revision: int,
        updated_by: str,
    ) -> SkillEvalSuite:
        current = self.get_suite(suite_id)
        resolved_status = SkillEvalSuiteStatus(status)
        if (
            suite_id == DEFAULT_ROUTING_SUITE_ID
            and resolved_status != SkillEvalSuiteStatus.ACTIVE
        ):
            raise SkillGovernanceGateError(
                "平台默认路由测评集不能停用",
                ["default_eval_suite_protected"],
            )
        updated = current.model_copy(
            update={
                "name": name.strip(),
                "purpose": purpose.strip(),
                "status": resolved_status,
                "revision": expected_revision + 1,
                "updated_by": updated_by.strip(),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self._storage.update_suite(
            SkillEvalSuite.model_validate(updated.model_dump()),
            expected_revision=expected_revision,
        )

    def delete_suite(self, suite_id: str) -> None:
        if suite_id == DEFAULT_ROUTING_SUITE_ID:
            raise SkillGovernanceGateError(
                "平台默认路由测评集不能删除",
                ["default_eval_suite_protected"],
            )
        self.get_suite(suite_id)
        if self._storage.count_cases(suite_id) > 0 or self._storage.list_tasks(suite_id):
            raise SkillGovernanceGateError(
                "测评集包含用例，只能停用",
                ["eval_suite_not_empty"],
            )
        if not self._storage.delete_suite(suite_id):
            raise SkillGovernanceNotFoundError(f"测评集不存在: {suite_id}")

    def list_tasks(
        self,
        suite_id: str,
        *,
        enabled_only: bool = False,
    ) -> list[SkillEvalTask]:
        self.get_suite(suite_id)
        return self._storage.list_tasks(suite_id, enabled_only=enabled_only)

    def get_task(self, task_id: str) -> SkillEvalTask:
        task = self._storage.get_task(task_id)
        if task is None:
            raise SkillGovernanceNotFoundError(f"评测任务不存在: {task_id}")
        return task

    def create_task(
        self,
        task: SkillEvalTask,
        *,
        created_by: str,
    ) -> SkillEvalTask:
        suite = self.get_suite(task.suite_id)
        now = datetime.now(timezone.utc)
        created = SkillEvalTask.model_validate(
            task.model_copy(
                update={
                    "revision": 1,
                    "created_by": created_by.strip(),
                    "updated_by": created_by.strip(),
                    "created_at": now,
                    "updated_at": now,
                },
                deep=True,
            ).model_dump()
        )
        self._validate_task_for_suite(created, suite)
        return self._storage.save_task(created)

    def import_tasks(
        self,
        suite_id: str,
        tasks: list[SkillEvalTask],
        *,
        created_by: str,
    ) -> list[SkillEvalTask]:
        """幂等导入已转换的任务，不覆盖质量人员维护过的同 ID 任务。"""
        suite = self.get_suite(suite_id)
        imported: list[SkillEvalTask] = []
        now = datetime.now(timezone.utc)
        for task in tasks:
            existing = self._storage.get_task(task.task_id)
            if existing is not None:
                if existing.suite_id != suite_id:
                    raise SkillGovernanceConflictError(
                        f"评测任务 ID 已属于其他测评集: {task.task_id}"
                    )
                imported.append(existing)
                continue
            candidate = SkillEvalTask.model_validate(
                task.model_copy(
                    update={
                        "suite_id": suite_id,
                        "created_by": created_by.strip(),
                        "updated_by": created_by.strip(),
                        "created_at": now,
                        "updated_at": now,
                    },
                    deep=True,
                ).model_dump()
            )
            self._validate_task_for_suite(candidate, suite)
            imported.append(self._storage.save_task(candidate))
        return imported

    def update_task(
        self,
        task: SkillEvalTask,
        *,
        expected_revision: int,
        updated_by: str,
    ) -> SkillEvalTask:
        current = self._storage.get_task(task.task_id)
        if current is None:
            raise SkillGovernanceNotFoundError(f"评测任务不存在: {task.task_id}")
        suite = self.get_suite(current.suite_id)
        updated = SkillEvalTask.model_validate(
            task.model_copy(
                update={
                    "suite_id": current.suite_id,
                    "revision": expected_revision + 1,
                    "created_by": current.created_by,
                    "created_at": current.created_at,
                    "updated_by": updated_by.strip(),
                    "updated_at": datetime.now(timezone.utc),
                },
                deep=True,
            ).model_dump()
        )
        self._validate_task_for_suite(updated, suite)
        return self._storage.update_task(updated, expected_revision=expected_revision)

    def freeze_dataset(
        self,
        suite_id: str,
        *,
        created_by: str,
    ) -> SkillEvalDatasetVersion:
        suite = self.get_suite(suite_id)
        if suite.status != SkillEvalSuiteStatus.ACTIVE:
            raise SkillGovernanceGateError("测评集已停用", ["eval_suite_inactive"])
        tasks = self._storage.list_tasks(suite_id, enabled_only=True)
        if not tasks:
            raise SkillGovernanceGateError(
                "测评集没有可冻结的任务",
                ["eval_dataset_empty"],
            )
        ordered = sorted(tasks, key=lambda item: item.task_id)
        content_hash = canonical_eval_hash(
            [task.model_dump(mode="json") for task in ordered]
        )
        environment_contract_hash = canonical_eval_hash(
            [
                requirement.model_dump(mode="json")
                for task in ordered
                for requirement in task.environment_requirements
            ]
        )
        evaluator_plan_hash = canonical_eval_hash(
            {"evaluator_plan_id": self._EVALUATOR_PLAN_ID}
        )
        versions = self._storage.list_dataset_versions(suite_id)
        existing = next(
            (
                version
                for version in versions
                if version.content_hash == content_hash
                and version.environment_contract_hash == environment_contract_hash
                and version.evaluator_plan_hash == evaluator_plan_hash
            ),
            None,
        )
        if existing is not None:
            return existing
        version = SkillEvalDatasetVersion(
            dataset_version_id=f"EVD_{uuid4().hex}",
            suite_id=suite_id,
            suite_revision=suite.revision,
            version_number=max((item.version_number for item in versions), default=0) + 1,
            task_snapshots=tuple(ordered),
            environment_contract_hash=environment_contract_hash,
            evaluator_plan_hash=evaluator_plan_hash,
            content_hash=content_hash,
            created_by=created_by.strip(),
        )
        return self._storage.save_dataset_version(version)

    def list_dataset_versions(
        self,
        suite_id: str,
    ) -> list[SkillEvalDatasetVersion]:
        self.get_suite(suite_id)
        return self._storage.list_dataset_versions(suite_id)

    def create_benchmark(
        self,
        *,
        name: str,
        skill_id: str,
        dataset_version_id: str,
        environment_snapshot: SkillEvalEnvironmentSnapshot,
        evaluator_plan_id: str,
        judge_version: str | None,
        gate_thresholds: SkillEvalGateThresholds,
        created_by: str,
    ) -> SkillEvalBenchmark:
        if evaluator_plan_id not in {
            "deterministic_v1",
            "deterministic_judge_v1",
        }:
            raise SkillGovernanceGateError(
                "评测器方案未注册",
                ["evaluator_plan_not_registered"],
            )
        if evaluator_plan_id == "deterministic_judge_v1" and not judge_version:
            raise SkillGovernanceGateError(
                "Judge 方案必须冻结 judge_version",
                ["judge_version_missing"],
            )
        if skill_id not in self._loader.get_all():
            raise SkillGovernanceNotFoundError(f"Skill 不存在: {skill_id}")
        dataset = self._storage.get_dataset_version(dataset_version_id)
        if dataset is None:
            raise SkillGovernanceNotFoundError(
                f"数据集版本不存在: {dataset_version_id}"
            )
        suite = self.get_suite(dataset.suite_id)
        if suite.scope == SkillEvalSuiteScope.SKILL and suite.skill_id != skill_id:
            raise SkillGovernanceGateError(
                "Benchmark Skill 与数据集不一致",
                ["benchmark_skill_mismatch"],
            )
        if any(task.target_skill_id != skill_id for task in dataset.task_snapshots):
            raise SkillGovernanceGateError(
                "Benchmark 数据集包含其他目标 Skill 的任务",
                ["benchmark_task_skill_mismatch"],
            )
        environment_hash = canonical_eval_hash(
            environment_snapshot.model_dump(mode="json")
        )
        evaluator_plan_hash = canonical_eval_hash(
            {
                "evaluator_plan_id": evaluator_plan_id,
                "judge_version": judge_version,
            }
        )
        benchmark = SkillEvalBenchmark(
            benchmark_id=f"EVB_{uuid4().hex}",
            name=name.strip(),
            skill_id=skill_id,
            dataset_version_id=dataset_version_id,
            environment_snapshot=environment_snapshot,
            environment_hash=environment_hash,
            evaluator_plan_id=evaluator_plan_id,
            evaluator_plan_hash=evaluator_plan_hash,
            judge_version=judge_version,
            gate_thresholds=gate_thresholds,
            created_by=created_by.strip(),
        )
        return self._storage.save_benchmark(benchmark)

    def list_benchmarks(
        self,
        skill_id: str | None = None,
    ) -> list[SkillEvalBenchmark]:
        return self._storage.list_benchmarks(skill_id)

    @staticmethod
    def _validate_task_for_suite(
        task: SkillEvalTask,
        suite: SkillEvalSuite,
    ) -> None:
        if suite.status != SkillEvalSuiteStatus.ACTIVE:
            raise SkillGovernanceGateError("测评集已停用", ["eval_suite_inactive"])
        if suite.scope == SkillEvalSuiteScope.SKILL and task.target_skill_id != suite.skill_id:
            raise SkillGovernanceGateError(
                "评测任务的目标 Skill 与测评集不一致",
                ["eval_task_skill_mismatch"],
            )
        if task.contains_sensitive_data or detect_sensitive_patterns(task.input.question):
            raise SkillGovernanceGateError(
                "评测任务包含敏感信息，必须脱敏后再保存",
                ["sensitive_data_detected"],
            )

    def list_cases(
        self,
        *,
        suite_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillEvalCase]:
        return self._storage.list_cases(
            suite_id=suite_id,
            enabled_only=enabled_only,
        )

    def current_suite_version(self) -> int:
        return self._storage.current_suite_version()

    def create_case(
        self,
        *,
        suite_id: str = DEFAULT_ROUTING_SUITE_ID,
        question_template: str,
        expected_skill_id: str | None,
        required: bool,
        risk_tags: list[str],
        business_tags: list[str],
        source_type: str,
        source_ref: str,
        contains_sensitive_data: bool,
        created_by: str,
    ) -> SkillEvalCase:
        suite = self.get_suite(suite_id)
        if suite.status != SkillEvalSuiteStatus.ACTIVE:
            raise SkillGovernanceGateError("测评集已停用", ["eval_suite_inactive"])
        if (
            suite.scope == SkillEvalSuiteScope.SKILL
            and expected_skill_id != suite.skill_id
        ):
            raise SkillGovernanceGateError(
                "路由用例的期望 Skill 与测评集不一致",
                ["eval_case_skill_mismatch"],
            )
        if contains_sensitive_data or detect_sensitive_patterns(question_template):
            raise SkillGovernanceGateError(
                "评测用例包含敏感信息，必须脱敏后再保存",
                ["sensitive_data_detected"],
            )
        # 去重：同 (question_template, expected_skill_id) 已存在则复用，避免反馈/投影重复入池
        normalized_q = question_template.strip()
        for existing in self._storage.list_cases():
            if (
                existing.suite_id == suite_id
                and existing.question_template.strip() == normalized_q
                and existing.expected_skill_id == expected_skill_id
            ):
                return existing
        return self._storage.save_case_with_new_suite_version(
            SkillEvalCase(
                case_id=f"EVC_{uuid4().hex}",
                suite_id=suite_id,
                suite_version=1,
                question_template=question_template.strip(),
                expected_skill_id=expected_skill_id,
                required=required,
                risk_tags=risk_tags,
                business_tags=business_tags,
                source_type=source_type,
                source_ref=source_ref,
                contains_sensitive_data=contains_sensitive_data,
                created_by=created_by.strip(),
            )
        )

    def update_case(
        self,
        case_id: str,
        *,
        question_template: str,
        expected_skill_id: str | None,
        required: bool,
        risk_tags: list[str],
        business_tags: list[str],
        source_type: str,
        source_ref: str,
        enabled: bool,
        contains_sensitive_data: bool,
    ) -> SkillEvalCase:
        if contains_sensitive_data or detect_sensitive_patterns(question_template):
            raise SkillGovernanceGateError(
                "评测用例包含敏感信息，必须脱敏后再保存",
                ["sensitive_data_detected"],
            )
        current = self._storage.get_case(case_id)
        if current is None:
            raise SkillGovernanceNotFoundError(f"评测用例不存在: {case_id}")
        suite = self.get_suite(current.suite_id)
        if (
            suite.scope == SkillEvalSuiteScope.SKILL
            and expected_skill_id != suite.skill_id
        ):
            raise SkillGovernanceGateError(
                "路由用例的期望 Skill 与测评集不一致",
                ["eval_case_skill_mismatch"],
            )
        updated = current.model_copy(
            update={
                "question_template": question_template.strip(),
                "expected_skill_id": expected_skill_id,
                "required": required,
                "risk_tags": risk_tags,
                "business_tags": business_tags,
                "source_type": source_type,
                "source_ref": source_ref,
                "enabled": enabled,
                "contains_sensitive_data": contains_sensitive_data,
                "updated_at": datetime.now(timezone.utc),
            },
            deep=True,
        )
        return self._storage.save_case_with_new_suite_version(
            SkillEvalCase.model_validate(updated.model_dump())
        )

    def delete_case(self, case_id: str) -> None:
        if not self._storage.delete_case(case_id):
            raise SkillGovernanceNotFoundError(f"评测用例不存在: {case_id}")

    def dedupe_cases(self) -> int:
        """同测评集内按问题和期望 Skill 去重，保留最新一条。"""
        # ponytail: O(n) 分组扫描，用例规模小；上万条改 SQL GROUP BY
        groups: dict[tuple[str, str, str | None], list[SkillEvalCase]] = {}
        for c in self._storage.list_cases():
            groups.setdefault(
                (c.suite_id, c.question_template.strip(), c.expected_skill_id), []
            ).append(c)
        removed = 0
        for group in groups.values():
            if len(group) <= 1:
                continue
            group.sort(key=lambda c: c.suite_version, reverse=True)
            for dup in group[1:]:
                self._storage.delete_case(dup.case_id)
                removed += 1
        return removed

    def seed_golden_cases(self) -> list[SkillEvalCase]:
        """灌入预置黄金 routing 用例（覆盖核心关键词），幂等。"""
        self.dedupe_cases()
        seeded: list[SkillEvalCase] = []
        for template, skill_id, tags in GOLDEN_ROUTING_CASES:
            seeded.append(
                self.create_case(
                    suite_id=DEFAULT_ROUTING_SUITE_ID,
                    question_template=template,
                    expected_skill_id=skill_id,
                    required=True,
                    risk_tags=[],
                    business_tags=tags,
                    source_type="golden_seed",
                    source_ref="golden-seed-v1",
                    contains_sensitive_data=False,
                    created_by="system",
                )
            )
        return seeded

    def create_eval_run(
        self,
        skill_id: str,
        *,
        version_id: str,
        baseline_version_id: str | None,
        created_by: str,
    ) -> SkillEvalRun:
        candidate = self._require_version(skill_id, version_id)
        if candidate.validation_status != SkillValidationStatus.PASSED:
            raise SkillGovernanceGateError(
                "候选版本校验未通过", ["version_validation_failed"]
            )
        suite_version, cases = self._storage.snapshot_enabled_cases()
        if not cases:
            raise SkillGovernanceGateError("固定评测集为空", ["eval_suite_empty"])

        resolved_baseline = self._resolve_baseline_version(
            skill_id, baseline_version_id
        )
        candidate_manifests = self._manifests_with_version(candidate)
        baseline_manifests = (
            self._manifests_with_version(resolved_baseline)
            if resolved_baseline is not None
            else self._runtime_manifests()
        )
        evaluation = evaluate_route_suite(
            cases, candidate_manifests, baseline_manifests
        )
        now = datetime.now(timezone.utc)
        config_hash = self._config_hash(suite_version)
        routing_manifest_hash = self._manifests_hash(candidate_manifests)
        run = SkillEvalRun(
            run_id=uuid4().hex,
            skill_id=skill_id,
            version_id=version_id,
            baseline_version_id=(
                resolved_baseline.version_id if resolved_baseline is not None else None
            ),
            suite_version=suite_version,
            config_hash=config_hash,
            routing_manifest_hash=routing_manifest_hash,
            status=(
                SkillEvalRunStatus.PASSED
                if evaluation.metrics.gate_passed
                else SkillEvalRunStatus.FAILED
            ),
            metrics=evaluation.metrics,
            results=evaluation.results,
            case_snapshots=[case.model_copy(deep=True) for case in cases],
            created_by=created_by.strip(),
            created_at=now,
            completed_at=now,
        )
        return self._storage.save_run(run)

    def list_eval_runs(self, skill_id: str | None = None) -> list[SkillEvalRun]:
        return self._storage.list_runs(skill_id)

    def get_eval_run(self, skill_id: str, run_id: str) -> SkillEvalRun:
        run = self._storage.get_run(skill_id, run_id)
        if run is None:
            raise SkillGovernanceNotFoundError(f"评测运行不存在: {run_id}")
        return run

    def create_candidate(
        self,
        skill_id: str,
        *,
        version_id: str,
        eval_run_id: str,
        environment: SkillReleaseEnvironment | str,
        created_by: str,
        release_id: str | None = None,
    ) -> SkillRelease:
        resolved_environment = SkillReleaseEnvironment(environment)
        if release_id is not None:
            existing = self._storage.get_release(release_id)
            if existing is not None:
                if (
                    existing.skill_id == skill_id
                    and existing.version_id == version_id
                    and existing.eval_run_id == eval_run_id
                    and existing.environment == resolved_environment
                    and existing.created_by == created_by.strip()
                ):
                    return existing
                raise SkillGovernanceConflictError(
                    "Idempotency-Key 已绑定到不同的候选发布请求"
                )
        version = self._require_version(skill_id, version_id)
        run = self.get_eval_run(skill_id, eval_run_id)
        active = self.resolve_shadow(skill_id, resolved_environment)
        failures: list[str] = []
        if version.validation_status != SkillValidationStatus.PASSED:
            failures.append("version_validation_failed")
        if run.status != SkillEvalRunStatus.PASSED or not run.metrics.gate_passed:
            failures.append("evaluation_failed")
        if run.version_id != version_id:
            failures.append("evaluation_version_mismatch")
        if run.config_hash != self._config_hash(run.suite_version):
            failures.append("evaluation_config_changed")
        if run.routing_manifest_hash != self._manifests_hash(
            self._manifests_with_version(version)
        ):
            failures.append("routing_manifest_changed")
        expected_baseline_version_id = active.version_id if active is not None else None
        if run.baseline_version_id != expected_baseline_version_id:
            failures.append("evaluation_baseline_mismatch")
        if failures:
            raise SkillGovernanceGateError("评测未通过，不能创建候选发布", failures)

        release = SkillRelease(
            release_id=release_id or uuid4().hex,
            skill_id=skill_id,
            version_id=version_id,
            environment=resolved_environment,
            status=SkillReleaseStatus.CANDIDATE,
            baseline_release_id=active.release_id if active is not None else None,
            eval_run_id=eval_run_id,
            artifact_hash=version.artifact_hash,
            config_hash=run.config_hash,
            created_by=created_by.strip(),
        )
        return self._storage.save_release(release)

    def request_approval(
        self,
        skill_id: str,
        release_id: str,
        *,
        expected_revision: int,
    ) -> SkillRelease:
        release = self._require_release(skill_id, release_id)
        self._require_revision(release, expected_revision)
        if release.status != SkillReleaseStatus.CANDIDATE:
            raise SkillGovernanceGateError(
                "只有 candidate 可以申请人工审批", ["invalid_release_status"]
            )
        self._validate_frozen_evidence(release)
        pending = release.model_copy(
            update={
                "status": SkillReleaseStatus.APPROVAL_PENDING,
                "revision": release.revision + 1,
            },
            deep=True,
        )
        return self._storage.update_release(
            pending, expected_revision=expected_revision
        )

    def approve_release(
        self,
        skill_id: str,
        release_id: str,
        *,
        expected_revision: int,
        approved_by: str,
        approver_role: str,
        reason: str,
    ) -> SkillRelease:
        release = self._require_release(skill_id, release_id)
        self._require_revision(release, expected_revision)
        if release.status != SkillReleaseStatus.APPROVAL_PENDING:
            raise SkillGovernanceGateError(
                "发布尚未申请人工审批", ["approval_not_requested"]
            )
        if approver_role.strip() != "information_department":
            raise SkillGovernanceGateError(
                "只有信息科管理员可以审批 test 发布",
                ["approver_role_forbidden"],
            )
        if approved_by.strip() == release.created_by:
            raise SkillGovernanceGateError(
                "候选发布创建人不能审批自己的发布",
                ["self_approval_forbidden"],
            )
        self._validate_frozen_evidence(release)
        approval = SkillReleaseApproval(
            approval_id=uuid4().hex,
            release_id=release.release_id,
            artifact_hash=release.artifact_hash,
            eval_run_id=release.eval_run_id,
            config_hash=release.config_hash,
            baseline_release_id=release.baseline_release_id,
            approved_by=approved_by.strip(),
            approver_role=approver_role.strip(),
            reason=reason.strip(),
        )
        approved = release.model_copy(
            update={
                "status": SkillReleaseStatus.APPROVED,
                "revision": release.revision + 1,
            },
            deep=True,
        )
        return self._storage.approve_release(
            approved,
            approval,
            expected_revision=expected_revision,
        )

    def activate_release(
        self,
        skill_id: str,
        release_id: str,
        *,
        expected_revision: int,
    ) -> SkillRelease:
        release = self._require_release(skill_id, release_id)
        self._require_revision(release, expected_revision)
        if release.status != SkillReleaseStatus.APPROVED:
            raise SkillGovernanceGateError(
                "必须完成人工审批后才能激活 test release",
                ["manual_approval_required"],
            )
        self._validate_frozen_evidence(release)
        approval = self._storage.get_approval(release.release_id)
        if approval is None:
            raise SkillGovernanceGateError(
                "人工审批证据不存在", ["approval_evidence_missing"]
            )
        if (
            approval.artifact_hash != release.artifact_hash
            or approval.eval_run_id != release.eval_run_id
            or approval.config_hash != release.config_hash
            or approval.baseline_release_id != release.baseline_release_id
        ):
            raise SkillGovernanceGateError(
                "人工审批证据已过期", ["approval_evidence_changed"]
            )
        active = self.resolve_shadow(skill_id, release.environment)
        active_id = active.release_id if active is not None else None
        if active_id != release.baseline_release_id:
            raise SkillGovernanceGateError(
                "活动基线已变化，需要重新评测和审批", ["baseline_changed"]
            )
        run = self.get_eval_run(skill_id, release.eval_run_id)
        return self._storage.activate_release(
            release.release_id,
            expected_revision=expected_revision,
            expected_suite_version=run.suite_version,
        )

    def list_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str | None = None,
    ) -> list[SkillRelease]:
        return self._storage.list_releases(skill_id, environment)

    def find_release(self, skill_id: str, release_id: str) -> SkillRelease | None:
        release = self._storage.get_release(release_id)
        if release is None or release.skill_id != skill_id:
            return None
        return release

    def get_release_approval(
        self, release_id: str
    ) -> SkillReleaseApproval | None:
        return self._storage.get_approval(release_id)

    def resolve_shadow(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str,
    ) -> SkillRelease | None:
        active = self._storage.list_active_releases(skill_id, environment)
        if len(active) > 1:
            raise SkillGovernanceConflictError(
                "同一 Skill 和环境存在多个 active release"
            )
        return active[0] if active else None

    def _require_version(self, skill_id: str, version_id: str) -> SkillVersion:
        version = self._version_storage.get_version(skill_id, version_id)
        if version is None:
            raise SkillGovernanceNotFoundError(f"Skill 版本不存在: {version_id}")
        return version

    def _require_release(self, skill_id: str, release_id: str) -> SkillRelease:
        release = self._storage.get_release(release_id)
        if release is None or release.skill_id != skill_id:
            raise SkillGovernanceNotFoundError(f"Skill 发布不存在: {release_id}")
        return release

    @staticmethod
    def _require_revision(release: SkillRelease, expected_revision: int) -> None:
        if release.revision != expected_revision:
            raise SkillGovernanceConflictError("发布 revision 已变化")

    def _resolve_baseline_version(
        self, skill_id: str, baseline_version_id: str | None
    ) -> SkillVersion | None:
        if baseline_version_id is not None:
            return self._require_version(skill_id, baseline_version_id)
        active = self.resolve_shadow(skill_id, SkillReleaseEnvironment.TEST)
        if active is None:
            return None
        return self._require_version(skill_id, active.version_id)

    def _runtime_manifests(self) -> list[dict[str, Any]]:
        return [dict(skill.manifest) for skill in self._loader.get_all().values()]

    def _manifests_with_version(self, version: SkillVersion) -> list[dict[str, Any]]:
        manifests = self._runtime_manifests()
        replacement = dict(version.manifest_snapshot)
        replaced = False
        for index, manifest in enumerate(manifests):
            if str(manifest.get("skill_id")) == version.skill_id:
                manifests[index] = replacement
                replaced = True
                break
        if not replaced:
            manifests.append(replacement)
        return manifests

    def _config_hash(self, suite_version: int) -> str:
        payload = {**self._GATE_CONFIG, "suite_version": suite_version}
        serialized = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _manifests_hash(manifests: list[dict[str, Any]]) -> str:
        ordered = sorted(
            (dict(manifest) for manifest in manifests),
            key=lambda manifest: str(manifest.get("skill_id") or ""),
        )
        serialized = json.dumps(
            ordered,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _validate_frozen_evidence(self, release: SkillRelease) -> None:
        version = self._require_version(release.skill_id, release.version_id)
        run = self.get_eval_run(release.skill_id, release.eval_run_id)
        failures: list[str] = []
        if version.artifact_hash != release.artifact_hash:
            failures.append("artifact_changed")
        if run.version_id != release.version_id:
            failures.append("evaluation_version_mismatch")
        if run.status != SkillEvalRunStatus.PASSED or not run.metrics.gate_passed:
            failures.append("evaluation_failed")
        if run.config_hash != release.config_hash:
            failures.append("config_changed")
        if run.config_hash != self._config_hash(run.suite_version):
            failures.append("evaluation_config_changed")
        if run.routing_manifest_hash != self._manifests_hash(
            self._manifests_with_version(version)
        ):
            failures.append("routing_manifest_changed")
        latest_suite = self._storage.current_suite_version()
        if run.suite_version != latest_suite:
            failures.append("eval_suite_changed")
        if failures:
            raise SkillGovernanceGateError("发布证据已变化", failures)
