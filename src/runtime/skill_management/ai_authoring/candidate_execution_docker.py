"""Docker 隔离候选 Skill 行为执行适配器。"""

from __future__ import annotations

import json
import subprocess

from pydantic import ValidationError

from src.runtime.skill_management.ai_authoring.candidate_evaluation import (
    SkillCandidateArtifact,
)
from src.runtime.skill_management.ai_authoring.candidate_execution_ports import (
    SkillCandidateBehaviorRequest,
    SkillCandidateBehaviorResult,
)


class DockerCandidateExecutionAdapter:
    def __init__(
        self,
        *,
        image: str,
        docker_binary: str = "docker",
        timeout_seconds: int = 10,
        memory_limit: str = "128m",
        cpu_limit: str = "0.5",
        pids_limit: int = 32,
        output_limit_bytes: int = 64 * 1024,
    ) -> None:
        self._image = image
        self._docker_binary = docker_binary
        self._timeout_seconds = timeout_seconds
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._pids_limit = pids_limit
        self._output_limit_bytes = output_limit_bytes

    def execute(
        self,
        artifact: SkillCandidateArtifact,
        request: SkillCandidateBehaviorRequest,
    ) -> SkillCandidateBehaviorResult:
        command = [
            self._docker_binary,
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            self._memory_limit,
            "--cpus",
            self._cpu_limit,
            "--pids-limit",
            str(self._pids_limit),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "-v",
            f"{artifact.path.resolve()}:/candidate:ro",
            self._image,
        ]
        try:
            completed = subprocess.run(
                command,
                input=request.model_dump_json(),
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
                shell=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return self._blocked(request.case_id, "sandbox_unavailable")
        if completed.returncode != 0:
            return self._blocked(request.case_id, "sandbox_execution_failed")
        if len(completed.stdout.encode("utf-8")) > self._output_limit_bytes:
            return self._blocked(request.case_id, "sandbox_output_limit_exceeded")
        try:
            result = SkillCandidateBehaviorResult.model_validate_json(completed.stdout)
            if result.case_id != request.case_id:
                return self._blocked(request.case_id, "sandbox_output_invalid")
            return result
        except (ValidationError, json.JSONDecodeError):
            return self._blocked(request.case_id, "sandbox_output_invalid")

    @staticmethod
    def _blocked(case_id: str, reason: str) -> SkillCandidateBehaviorResult:
        return SkillCandidateBehaviorResult(
            case_id=case_id,
            status="blocked_by_evaluator",
            passed=False,
            blocked_reason=reason,
        )
