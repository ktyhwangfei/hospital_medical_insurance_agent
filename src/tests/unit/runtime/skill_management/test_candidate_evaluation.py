from __future__ import annotations

from pathlib import Path
import json
import subprocess

import pytest

from src.domain.skill.draft_models import (
    SkillDraft,
    SkillDraftSourceType,
    SkillDraftStatus,
)
from src.domain.skill.governance_models import SkillEvalCase
from src.domain.skill.regression_models import (
    CalculationAssertions,
    SkillErrorDimension,
    SkillRegressionCase,
)
from src.runtime.skill_management.ai_authoring.candidate_evaluation import (
    SkillCandidateArtifactError,
    SkillCandidateEvaluationService,
    SkillCandidateEvaluationStatus,
)
from src.runtime.skill_management.ai_authoring.candidate_execution_ports import (
    DisabledCandidateExecutionAdapter,
    SkillCandidateBehaviorRequest,
)
from src.runtime.skill_management.ai_authoring.candidate_execution_docker import (
    DockerCandidateExecutionAdapter,
)
from src.runtime.skill_management.package_generator import SkillPackageGenerator


def _draft() -> SkillDraft:
    return SkillDraft(
        draft_id="draft-candidate-1",
        skill_id="deductible_explain",
        skill_name="Deductible explain",
        source_type=SkillDraftSourceType.AI_GENERATED,
        structured_config={
            "basic": {
                "skill_id": "deductible_explain",
                "skill_name": "Deductible explain",
            },
            "business_mounting": {
                "business_action": "explain",
                "business_object": "settlement",
                "include_keywords": ["deductible"],
                "excluded_intents": [],
            },
        },
        raw_files={
            "assembler.py": "def assemble(data):\n    return {'value': data['amount']}\n",
            "prompt_template.yaml": "system: explain deductible\n",
        },
        status=SkillDraftStatus.VALIDATED,
        revision=2,
        created_by="tester",
    )


def _service(tmp_path: Path) -> SkillCandidateEvaluationService:
    return SkillCandidateEvaluationService(
        package_generator=SkillPackageGenerator(),
        candidate_root=tmp_path / "candidate-quarantine",
        runtime_skills_root=tmp_path / "runtime-skills",
        executor=DisabledCandidateExecutionAdapter("sandbox_unavailable"),
    )


def test_candidate_artifact_is_written_outside_runtime_skills(tmp_path: Path) -> None:
    service = _service(tmp_path)

    artifact = service.build_artifact(_draft())

    assert artifact.path.is_dir()
    assert not artifact.path.is_relative_to(tmp_path / "runtime-skills")
    assert len(artifact.artifact_hash) == 64
    assert (
        (artifact.path / "assembler.py")
        .read_text(encoding="utf-8")
        .startswith("def assemble")
    )


def test_candidate_root_inside_runtime_skills_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SkillCandidateArtifactError, match="outside runtime"):
        SkillCandidateEvaluationService(
            package_generator=SkillPackageGenerator(),
            candidate_root=tmp_path / "skills" / "candidates",
            runtime_skills_root=tmp_path / "skills",
            executor=DisabledCandidateExecutionAdapter(),
        )


def test_unsafe_ai_candidate_is_rejected_before_writing(tmp_path: Path) -> None:
    draft = _draft().model_copy(
        update={
            "raw_files": {
                "assembler.py": "import os\ndef assemble(data):\n    return data\n",
                "prompt_template.yaml": "system: explain deductible\n",
            }
        }
    )
    service = _service(tmp_path)

    with pytest.raises(SkillCandidateArtifactError, match="security scan failed"):
        service.build_artifact(draft)

    assert not (tmp_path / "candidate-quarantine").exists()


def test_route_evaluation_reads_manifest_without_loading_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("candidate loader/import must never be called")

    monkeypatch.setattr(
        "src.skill_infra.skill_loader.SkillLoader.discover", fail_if_called
    )
    result = _service(tmp_path).evaluate_routes(
        _draft(),
        [
            SkillEvalCase(
                case_id="route-1",
                suite_version=1,
                question_template="How is the deductible calculated?",
                expected_skill_id="deductible_explain",
                created_by="tester",
            )
        ],
    )

    assert result.status is SkillCandidateEvaluationStatus.COMPLETED
    assert result.metrics is not None
    assert result.metrics.gate_passed is True
    assert result.results[0].candidate_skill_id == "deductible_explain"
    assert len(result.case_snapshot_hash) == 64


def test_behavior_evaluation_without_sandbox_is_blocked(tmp_path: Path) -> None:
    case = SkillRegressionCase(
        case_id="behavior-1",
        target_skill_id="deductible_explain",
        case_type=SkillErrorDimension.CALCULATION,
        input_template={"amount": 100.0},
        expected_assertions=CalculationAssertions(expected_value=100.0),
        source_ref="qa-turn-1",
        source_hash="a" * 64,
        confirmed_by="tester",
    )

    result = _service(tmp_path).evaluate_behavior(_draft(), [case])

    assert result.status is SkillCandidateEvaluationStatus.BLOCKED_BY_EVALUATOR
    assert result.blocked_reason == "sandbox_unavailable"
    assert result.results[0].status == "blocked_by_evaluator"
    assert result.results[0].output is None


def test_docker_execution_uses_fixed_isolation_flags(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = _service(tmp_path).build_artifact(_draft())
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "case_id": "behavior-docker",
                    "status": "passed",
                    "passed": True,
                    "output": {"value": 100.0},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "src.runtime.skill_management.ai_authoring.candidate_execution_docker.subprocess.run",
        fake_run,
    )
    adapter = DockerCandidateExecutionAdapter(
        image="hospital-skill-candidate-runner:local",
        timeout_seconds=3,
    )

    result = adapter.execute(
        artifact,
        SkillCandidateBehaviorRequest(
            case_id="behavior-docker",
            case_type="calculation",
            input={"amount": 100.0},
            assertions={"case_type": "calculation", "expected_value": 100.0},
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert command[:2] == ["docker", "run"]
    assert ["--pull", "never"] == command[
        command.index("--pull") : command.index("--pull") + 2
    ]
    assert ["--network", "none"] == command[
        command.index("--network") : command.index("--network") + 2
    ]
    assert "--read-only" in command
    assert ["--cap-drop", "ALL"] == command[
        command.index("--cap-drop") : command.index("--cap-drop") + 2
    ]
    assert "--memory" in command
    assert "--cpus" in command
    assert "--pids-limit" in command
    assert "--tmpfs" in command
    assert f"{artifact.path.resolve()}:/candidate:ro" in command
    assert captured["kwargs"]["shell"] is False
    assert result.passed is True


def test_docker_unavailable_fails_closed(tmp_path: Path, monkeypatch) -> None:
    artifact = _service(tmp_path).build_artifact(_draft())

    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(
        "src.runtime.skill_management.ai_authoring.candidate_execution_docker.subprocess.run",
        unavailable,
    )

    result = DockerCandidateExecutionAdapter(image="runner:test").execute(
        artifact,
        SkillCandidateBehaviorRequest(
            case_id="behavior-blocked",
            case_type="calculation",
            input={},
            assertions={"case_type": "calculation", "expected_value": 1.0},
        ),
    )

    assert result.status == "blocked_by_evaluator"
    assert result.output is None
