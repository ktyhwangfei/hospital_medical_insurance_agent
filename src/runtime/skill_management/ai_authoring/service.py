"""通过 ModelGateway 生成安全、不可变且可追溯的 Skill proposal。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import ValidationError

from src.domain.skill.draft_models import InputSpec
from src.model_service.exceptions import (
    ModelAuthError,
    ModelError,
    ModelExhaustedError,
    ModelRateLimitError,
    ModelServerError,
    ModelTimeoutError,
)
from src.model_service.models import Message, ModelResponse
from src.runtime.skill_management.ai_authoring.prompts import (
    SKILL_AUTHORING_PROMPT_VERSION,
    build_generation_prompt,
    build_repair_prompt,
    build_system_prompt,
)
from src.runtime.skill_management.ai_authoring.schemas import (
    SkillAIGenerationProvenance,
    SkillAIGenerationResponse,
    SkillAIModelOutput,
    SkillMetricVersionRef,
    SkillValidationIssueResponse,
    SkillValidationReportResponse,
)
from src.runtime.skill_management.ai_authoring.security import (
    SkillAISecurityIssue,
    scan_ai_generated_files,
)
from src.runtime.skill_management.skill_input_service import SkillInputService
from src.security.desensitization.detection import detect_sensitive_patterns
from src.security.desensitization.service import sanitize_regression_snapshot


_MODEL_TYPE = "reasoning"
_SCENE = "skill_authoring"
_MAX_DESCRIPTION_LENGTH = 4000
_MAX_METRIC_CODES = 100
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:password|passwd|pwd|api[_-]?key|secret)\s*[=:]\s*\S+"
)
_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")
_REQUIRED_RAW_FILES = frozenset({"assembler.py", "prompt_template.yaml"})


class SkillAIAuthoringError(ValueError):
    """Skill AI 编写服务的稳定错误基类。"""


class SkillAIInputInvalidError(SkillAIAuthoringError):
    """生成描述或指标列表不安全/不合法。"""


class SkillAIMetricNotFoundError(SkillAIAuthoringError):
    """请求引用了不存在的指标。"""

    def __init__(self, metric_code: str) -> None:
        super().__init__(f"指标不存在: {metric_code}")
        self.metric_code = metric_code


class SkillAIMetricNotPublishedError(SkillAIAuthoringError):
    """指标或所属对象没有可冻结的已发布版本。"""

    def __init__(self, metric_code: str) -> None:
        super().__init__(f"指标未发布: {metric_code}")
        self.metric_code = metric_code


class SkillAIOutputInvalidError(SkillAIAuthoringError):
    """模型在最多一次结构修复后仍不满足严格 DTO。"""


class SkillAISecurityRejectedError(SkillAIAuthoringError):
    """模型文件没有通过静态安全门禁。"""

    def __init__(self, issues: Sequence[SkillAISecurityIssue]) -> None:
        super().__init__("AI 生成文件未通过安全扫描")
        self.issues = tuple(issues)


class SkillAIModelError(SkillAIAuthoringError):
    """保留 ModelGateway 分类信息的稳定服务边界错误。"""

    def __init__(self, *, category: str, model_name: str = "") -> None:
        super().__init__(f"Skill AI 模型调用失败（{category}）")
        self.category = category
        self.model_name = model_name


class _GenerationRequest(Protocol):
    description: str
    metric_codes: list[str]


class _Gateway(Protocol):
    def generate(
        self,
        messages: list[Message],
        model_type: str,
        scene: str,
        max_tokens: int | None = None,
    ) -> ModelResponse: ...


class SkillAIAuthoringService:
    """执行描述校验、指标冻结、模型生成、修复、安全扫描与哈希。"""

    def __init__(
        self,
        *,
        gateway: _Gateway,
        input_service: SkillInputService,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        max_tokens: int = 4096,
    ) -> None:
        if not 1 <= max_tokens <= 8192:
            raise ValueError("max_tokens 必须位于 1..8192")
        self._gateway = gateway
        self._input_service = input_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._max_tokens = max_tokens

    def generate(self, request: _GenerationRequest) -> SkillAIGenerationResponse:
        """生成 proposal；任何失败都不会写草稿、文件或 proposal 存储。"""

        description, metric_codes = self._validate_request(request)
        metric_versions, prompt_snapshots = self._freeze_metric_versions(metric_codes)
        input_hash = _canonical_hash(
            {
                "description": description,
                "metric_snapshots": list(prompt_snapshots),
                "operation": "generate",
                "prompt_version": SKILL_AUTHORING_PROMPT_VERSION,
            }
        )
        if _contains_sensitive_content(
            json.dumps(
                list(prompt_snapshots),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        ):
            raise SkillAIInputInvalidError("指标快照包含不允许发送给模型的信息")
        user_prompt = build_generation_prompt(
            description=description,
            metric_snapshots=prompt_snapshots,
        )
        if _contains_sensitive_content(user_prompt):
            raise SkillAIInputInvalidError("生成 prompt 包含不允许发送给模型的信息")
        messages = [
            Message(role="system", content=build_system_prompt(operation="generate")),
            Message(role="user", content=user_prompt),
        ]
        response = self._call_gateway(messages)
        model_output, final_response = self._parse_or_repair(response)
        self._require_requested_metrics(model_output, metric_codes)
        if frozenset(model_output.raw_files) != _REQUIRED_RAW_FILES:
            raise SkillAIOutputInvalidError(
                "模型输出必须同时且仅包含 assembler.py 与 prompt_template.yaml"
            )
        model_name = str(getattr(final_response, "model_name", "") or "").strip()
        if not model_name:
            raise SkillAIModelError(category="identity_missing")

        security = scan_ai_generated_files(model_output.raw_files)
        if not security.passed:
            raise SkillAISecurityRejectedError(security.issues)

        validation_preview = self._validation_preview(model_output)
        proposal_hash = _canonical_hash(
            {
                "citations": [
                    {
                        "source_type": citation.source_type,
                        "source_id": citation.source_id,
                        "summary": citation.summary,
                    }
                    for citation in model_output.citations
                ],
                "content_hash": security.content_hash,
                "input_hash": input_hash,
                "metric_versions": [
                    item.model_dump(mode="json") for item in metric_versions
                ],
                "model_type": model_name,
                "prompt_version": SKILL_AUTHORING_PROMPT_VERSION,
                "raw_files": dict(model_output.raw_files),
                "structured_config": model_output.structured_config.model_dump(
                    mode="json"
                ),
                "uncertainties": list(model_output.uncertainties),
            }
        )
        generated_at = self._clock()
        provenance = SkillAIGenerationProvenance(
            model_type=model_name,
            scene=_SCENE,
            prompt_version=SKILL_AUTHORING_PROMPT_VERSION,
            metric_versions=metric_versions,
            generated_at=generated_at,
            content_hash=security.content_hash,
        )
        generation_id = self._generation_id(input_hash)
        return SkillAIGenerationResponse(
            generation_id=generation_id,
            proposal_hash=proposal_hash,
            structured_config=model_output.structured_config,
            raw_files=model_output.raw_files,
            validation_preview=validation_preview,
            provenance=provenance,
            citations=model_output.citations,
            uncertainties=model_output.uncertainties,
        )

    def _validate_request(
        self, request: _GenerationRequest
    ) -> tuple[str, tuple[str, ...]]:
        description = request.description.strip()
        if not description or len(description) > _MAX_DESCRIPTION_LENGTH:
            raise SkillAIInputInvalidError("description 长度必须为 1..4000")
        if "\x00" in description or _contains_sensitive_content(description):
            raise SkillAIInputInvalidError("description 包含不允许发送给模型的信息")

        raw_codes = request.metric_codes
        if not raw_codes or len(raw_codes) > _MAX_METRIC_CODES:
            raise SkillAIInputInvalidError("metric_codes 数量必须为 1..100")
        metric_codes = tuple(code.strip() for code in raw_codes)
        if any(not code or len(code) > 256 for code in metric_codes):
            raise SkillAIInputInvalidError("metric_code 长度必须为 1..256")
        if len(set(metric_codes)) != len(metric_codes):
            raise SkillAIInputInvalidError("metric_codes 不得重复")
        return description, metric_codes

    def _freeze_metric_versions(
        self, metric_codes: tuple[str, ...]
    ) -> tuple[tuple[SkillMetricVersionRef, ...], tuple[Mapping[str, object], ...]]:
        registry = self._input_service._registry  # noqa: SLF001
        versions: list[SkillMetricVersionRef] = []
        prompt_snapshots: list[Mapping[str, object]] = []
        for metric_code in metric_codes:
            metric = registry.get_metric(metric_code)
            if metric is None:
                raise SkillAIMetricNotFoundError(metric_code)
            obj = registry.get_object(metric.object_code)
            if (
                obj is None
                or obj.current_version is None
            ):
                raise SkillAIMetricNotPublishedError(metric_code)
            object_version_record = registry.get_object_version(
                metric.object_code, str(obj.current_version)
            )
            if object_version_record is None:
                raise SkillAIMetricNotPublishedError(metric_code)
            snapshot_metric = next(
                (
                    item
                    for item in object_version_record.metrics
                    if item.metric_code == metric_code
                ),
                None,
            )
            if snapshot_metric is None:
                raise SkillAIMetricNotPublishedError(metric_code)
            try:
                object_version = int(object_version_record.version)
            except (TypeError, ValueError) as exc:
                raise SkillAIMetricNotPublishedError(metric_code) from exc
            if object_version < 1:
                raise SkillAIMetricNotPublishedError(metric_code)
            versions.append(
                SkillMetricVersionRef(
                    metric_code=metric_code,
                    object_code=metric.object_code,
                    object_version=object_version,
                    status="published",
                )
            )
            prompt_snapshots.append(
                {
                    "metric": snapshot_metric.model_dump(mode="json"),
                    "object_code": object_version_record.object_code,
                    "object_snapshot": object_version_record.snapshot,
                    "object_version": object_version,
                    "snapshot_id": object_version_record.version_id,
                    "status": "published",
                }
            )
        return tuple(versions), tuple(prompt_snapshots)

    def _call_gateway(self, messages: list[Message]) -> ModelResponse:
        try:
            return self._gateway.generate(
                messages,
                model_type=_MODEL_TYPE,
                scene=_SCENE,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            raise _model_error(exc) from exc

    def _parse_or_repair(
        self, response: ModelResponse
    ) -> tuple[SkillAIModelOutput, ModelResponse]:
        try:
            return SkillAIModelOutput.model_validate_json(response.content), response
        except (ValidationError, ValueError):
            if _contains_sensitive_content(response.content):
                raise SkillAIOutputInvalidError(
                    "模型输出包含敏感信息，拒绝结构修复"
                ) from None
            repair_messages = [
                Message(role="system", content=build_system_prompt(operation="repair")),
                Message(role="user", content=build_repair_prompt(response.content)),
            ]
            repaired = self._call_gateway(repair_messages)
            try:
                return SkillAIModelOutput.model_validate_json(
                    repaired.content
                ), repaired
            except (ValidationError, ValueError) as final_error:
                raise SkillAIOutputInvalidError(
                    "模型输出在一次结构修复后仍不符合严格 DTO"
                ) from final_error

    @staticmethod
    def _require_requested_metrics(
        output: SkillAIModelOutput, requested: tuple[str, ...]
    ) -> None:
        generated = tuple(item.metric_code for item in output.structured_config.inputs)
        if generated != requested:
            raise SkillAIOutputInvalidError(
                "模型输出 inputs 必须按请求顺序完整使用已冻结指标"
            )

    def _validation_preview(
        self, output: SkillAIModelOutput
    ) -> SkillValidationReportResponse:
        specs = [
            InputSpec(
                metric_code=item.metric_code,
                alias=item.alias,
                required=item.required,
                purpose=item.purpose,
            )
            for item in output.structured_config.inputs
        ]
        report = self._input_service.validate_inputs(specs)
        issues = tuple(
            SkillValidationIssueResponse(
                code=issue.code,
                message=issue.message,
                severity=issue.severity.value,
                path=issue.path,
            )
            for issue in report.issues
        )
        return SkillValidationReportResponse(
            issues=issues,
            has_blocking=report.has_blocking,
            blocking_ok=report.blocking_ok,
        )

    def _generation_id(self, input_hash: str) -> str:
        unique_part = _SAFE_ID_PATTERN.sub("", str(self._id_factory()))[:48]
        if not unique_part:
            unique_part = uuid.uuid4().hex
        return f"gen_{input_hash[:12]}_{unique_part}"


def _model_error(exc: Exception) -> SkillAIModelError:
    categories: tuple[tuple[type[Exception], str], ...] = (
        (ModelTimeoutError, "timeout"),
        (ModelRateLimitError, "rate_limit"),
        (ModelAuthError, "auth"),
        (ModelServerError, "server"),
        (ModelExhaustedError, "exhausted"),
        (ModelError, "model"),
    )
    category = next(
        (label for error_type, label in categories if isinstance(exc, error_type)),
        "unexpected",
    )
    return SkillAIModelError(
        category=category,
        model_name=str(getattr(exc, "model_name", "")),
    )


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _contains_sensitive_content(text: str) -> bool:
    sanitized = sanitize_regression_snapshot(
        question=text,
        answer="",
        comment="",
    )
    return bool(
        sanitized.masked_patterns
        or detect_sensitive_patterns(text)
        or _CREDENTIAL_PATTERN.search(text)
        or any(pattern.search(text) for pattern in _SECRET_PATTERNS)
    )
