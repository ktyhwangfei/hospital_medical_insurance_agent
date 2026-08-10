"""候选 Skill 制品隔离构建与评测服务。"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.domain.skill.draft_models import SkillDraft, SkillDraftSourceType
from src.domain.skill.governance_models import (
    SkillEvalCase,
    SkillEvalMetrics,
    SkillEvalResult,
)
from src.domain.skill.regression_models import SkillRegressionCase
from src.runtime.skill_management.ai_authoring.candidate_execution_ports import (
    CandidateExecutionPort,
    SkillCandidateBehaviorRequest,
    SkillCandidateBehaviorResult,
)
from src.runtime.skill_management.ai_authoring.security import (
    scan_ai_generated_files,
)
from src.runtime.skill_management.package_generator import SkillPackageGenerator
from src.skill_infra.route_evaluator import evaluate_route_suite


class SkillCandidateArtifactError(ValueError):
    pass


class SkillCandidateEvaluationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED_BY_EVALUATOR = "blocked_by_evaluator"


class SkillCandidateArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft_id: str
    draft_revision: int = Field(ge=1)
    path: Path
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: dict[str, Any]
    config: dict[str, Any]


class SkillCandidateRouteEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: SkillCandidateEvaluationStatus
    metrics: SkillEvalMetrics | None = None
    results: list[SkillEvalResult] = Field(default_factory=list)
    blocked_reason: str | None = None


class SkillCandidateBehaviorEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: SkillCandidateEvaluationStatus
    results: list[SkillCandidateBehaviorResult] = Field(default_factory=list)
    blocked_reason: str | None = None


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SkillCandidateEvaluationService:
    def __init__(
        self,
        *,
        package_generator: SkillPackageGenerator,
        candidate_root: str | Path,
        runtime_skills_root: str | Path,
        executor: CandidateExecutionPort,
    ) -> None:
        self._package_generator = package_generator
        self._candidate_root = Path(candidate_root).resolve()
        self._runtime_skills_root = Path(runtime_skills_root).resolve()
        self._executor = executor
        if (
            self._candidate_root == self._runtime_skills_root
            or self._candidate_root.is_relative_to(self._runtime_skills_root)
        ):
            raise SkillCandidateArtifactError(
                "candidate root must be outside runtime skills root"
            )

    def build_artifact(self, draft: SkillDraft) -> SkillCandidateArtifact:
        if draft.source_type is SkillDraftSourceType.AI_GENERATED:
            generated_files = {
                path: content
                for path, content in draft.raw_files.items()
                if not path.startswith("__")
            }
            security = scan_ai_generated_files(generated_files)
            if not security.passed:
                codes = ",".join(issue.code for issue in security.issues)
                raise SkillCandidateArtifactError(
                    f"candidate security scan failed: {codes}"
                )

        package = self._package_generator.generate(draft)
        artifact_hash = _canonical_hash(
            [[path, package.files[path]] for path in sorted(package.files)]
        )
        artifact_path = (
            self._candidate_root
            / draft.draft_id
            / f"r{draft.revision}-{artifact_hash[:16]}"
        ).resolve()
        if artifact_path.is_relative_to(self._runtime_skills_root):
            raise SkillCandidateArtifactError(
                "candidate artifact must be outside runtime skills root"
            )
        artifact_path.mkdir(parents=True, exist_ok=True)
        for relative_name, content in package.files.items():
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise SkillCandidateArtifactError(
                    f"unsafe candidate package path: {relative_name}"
                )
            destination = (artifact_path / relative_path).resolve()
            if not destination.is_relative_to(artifact_path):
                raise SkillCandidateArtifactError(
                    f"unsafe candidate package path: {relative_name}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

        config_content = package.files.get("config.yaml", "")
        config = yaml.safe_load(config_content) or {} if config_content else {}
        return SkillCandidateArtifact(
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            path=artifact_path,
            artifact_hash=artifact_hash,
            manifest=package.manifest(),
            config=config,
        )

    def evaluate_routes(
        self,
        draft: SkillDraft,
        cases: Sequence[SkillEvalCase],
        baseline_manifests: Sequence[Mapping[str, Any]] = (),
    ) -> SkillCandidateRouteEvaluation:
        artifact = self.build_artifact(draft)
        case_snapshot_hash = _canonical_hash(
            [case.model_dump(mode="json") for case in cases]
        )
        evaluation = evaluate_route_suite(
            cases,
            candidate_manifests=[artifact.manifest],
            baseline_manifests=baseline_manifests,
        )
        return SkillCandidateRouteEvaluation(
            artifact_hash=artifact.artifact_hash,
            case_snapshot_hash=case_snapshot_hash,
            status=SkillCandidateEvaluationStatus.COMPLETED,
            metrics=evaluation.metrics,
            results=evaluation.results,
        )

    def evaluate_behavior(
        self,
        draft: SkillDraft,
        cases: Sequence[SkillRegressionCase],
    ) -> SkillCandidateBehaviorEvaluation:
        artifact = self.build_artifact(draft)
        case_snapshot_hash = _canonical_hash(
            [case.model_dump(mode="json") for case in cases]
        )
        results = [
            self._executor.execute(
                artifact,
                SkillCandidateBehaviorRequest(
                    case_id=case.case_id,
                    case_type=case.case_type.value,
                    input=case.input_template,
                    assertions=case.expected_assertions.model_dump(mode="json"),
                ),
            )
            for case in cases
        ]
        blocked = next(
            (item for item in results if item.status == "blocked_by_evaluator"),
            None,
        )
        if blocked is not None:
            evaluation_status = SkillCandidateEvaluationStatus.BLOCKED_BY_EVALUATOR
        elif all(item.passed for item in results):
            evaluation_status = SkillCandidateEvaluationStatus.COMPLETED
        else:
            evaluation_status = SkillCandidateEvaluationStatus.FAILED
        return SkillCandidateBehaviorEvaluation(
            artifact_hash=artifact.artifact_hash,
            case_snapshot_hash=case_snapshot_hash,
            status=evaluation_status,
            results=results,
            blocked_reason=blocked.blocked_reason if blocked else None,
        )
