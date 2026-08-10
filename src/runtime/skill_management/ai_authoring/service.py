"""通过 ModelGateway 生成安全、不可变且可追溯的 Skill proposal。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import ValidationError

from src.domain.common.actions import (
    BusinessAction,
    BusinessObject,
    VALID_ACTION_OBJECT_PAIRS,
)
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
from src.security.desensitization.detection import detect_sensitive_patterns
from src.security.desensitization.service import sanitize_regression_snapshot


_MODEL_TYPE = "reasoning"
_SCENE = "skill_authoring"
_MAX_DESCRIPTION_LENGTH = 4000
_MAX_METRIC_CODES = 100
# 384 KiB 原始文件总预算 + 256 KiB 结构化 DTO/溯源预算。
_MAX_MODEL_RESPONSE_BYTES = (384 + 256) * 1024
_MAX_STRICT_JSON_DEPTH = 32
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

    def __init__(
        self,
        *,
        category: str,
        model_name: str = "",
        error_type: str = "",
        error_hash: str = "",
    ) -> None:
        super().__init__(f"Skill AI 模型调用失败（{category}）")
        self.category = category
        self.model_name = model_name
        self.error_type = error_type
        self.error_hash = error_hash


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


@dataclass(frozen=True)
class _SkillAIGenerationEvidence:
    proposal: SkillAIGenerationResponse
    metric_snapshot_hash: str


class SkillMetricRegistryPort(Protocol):
    """只读指标版本窄端口，用于生成与接受时冻结同一证据。"""

    def get_metric(self, metric_code: str) -> Any | None: ...

    def get_object(self, object_code: str) -> Any | None: ...

    def get_object_version(
        self, object_code: str, version: str
    ) -> Any | None: ...


class SkillInputValidationPort(Protocol):
    def validate_inputs(self, specs: list[InputSpec]) -> Any: ...


class SkillAIAuthoringService:
    """执行描述校验、指标冻结、模型生成、修复、安全扫描与哈希。"""

    def __init__(
        self,
        *,
        gateway: _Gateway,
        input_service: SkillInputValidationPort,
        metric_registry: SkillMetricRegistryPort | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        max_tokens: int = 4096,
    ) -> None:
        if not 1 <= max_tokens <= 8192:
            raise ValueError("max_tokens 必须位于 1..8192")
        self._gateway = gateway
        self._input_service = input_service
        # 旧调用方未显式注入时仅做兼容适配；新组装点必须传入窄端口。
        self._metric_registry = metric_registry or getattr(
            input_service, "_registry", None
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._max_tokens = max_tokens

    def generate(self, request: _GenerationRequest) -> SkillAIGenerationResponse:
        """生成 proposal；任何失败都不会写草稿、文件或 proposal 存储。"""

        return self.generate_with_evidence(request).proposal

    def generate_with_evidence(
        self, request: _GenerationRequest
    ) -> _SkillAIGenerationEvidence:
        """生成公开 proposal 及仅供短期服务端证据使用的指标快照指纹。"""

        description, metric_codes = self._validate_request(request)
        metric_versions, prompt_snapshots = self._freeze_metric_versions(metric_codes)
        metric_snapshot_hash = _canonical_hash(list(prompt_snapshots))
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
        generated_at = self._clock()
        provenance = SkillAIGenerationProvenance(
            model_type=model_name,
            scene=_SCENE,
            prompt_version=SKILL_AUTHORING_PROMPT_VERSION,
            metric_versions=metric_versions,
            generated_at=generated_at,
            content_hash=security.content_hash,
        )
        proposal_hash = _proposal_hash(
            evidence_hash=input_hash[:12],
            structured_config=model_output.structured_config.model_dump(mode="json"),
            raw_files=dict(model_output.raw_files),
            validation_preview=validation_preview.model_dump(mode="json"),
            provenance=provenance.model_dump(mode="json"),
            citations=model_output.citations,
            uncertainties=model_output.uncertainties,
        )
        generation_id = self._generation_id(input_hash)
        proposal = SkillAIGenerationResponse(
            generation_id=generation_id,
            proposal_hash=proposal_hash,
            structured_config=model_output.structured_config,
            raw_files=model_output.raw_files,
            validation_preview=validation_preview,
            provenance=provenance,
            citations=model_output.citations,
            uncertainties=model_output.uncertainties,
        )
        return _SkillAIGenerationEvidence(
            proposal=proposal,
            metric_snapshot_hash=metric_snapshot_hash,
        )

    def verify_for_accept(
        self,
        proposal: SkillAIGenerationResponse,
        *,
        metric_snapshot_hash: str | None = None,
    ) -> None:
        """接受前重算哈希、复验已发布指标快照并重跑安全扫描。"""

        expected_hash = _proposal_hash(
            evidence_hash=_generation_evidence_hash(proposal.generation_id),
            structured_config=proposal.structured_config.model_dump(mode="json"),
            raw_files=dict(proposal.raw_files),
            validation_preview=proposal.validation_preview.model_dump(mode="json"),
            provenance=proposal.provenance.model_dump(mode="json"),
            citations=proposal.citations,
            uncertainties=proposal.uncertainties,
        )
        if expected_hash != proposal.proposal_hash:
            raise SkillAIOutputInvalidError("proposal hash 校验失败")
        metric_codes = tuple(
            item.metric_code for item in proposal.provenance.metric_versions
        )
        current_versions, current_snapshots = self._freeze_metric_versions(metric_codes)
        if current_versions != proposal.provenance.metric_versions:
            stale_code = metric_codes[0] if metric_codes else "unknown"
            raise SkillAIMetricNotPublishedError(stale_code)
        if (
            metric_snapshot_hash is not None
            and _canonical_hash(list(current_snapshots)) != metric_snapshot_hash
        ):
            stale_code = metric_codes[0] if metric_codes else "unknown"
            raise SkillAIMetricNotPublishedError(stale_code)
        security = scan_ai_generated_files(proposal.raw_files)
        if not security.passed:
            raise SkillAISecurityRejectedError(security.issues)
        if security.content_hash != proposal.provenance.content_hash:
            raise SkillAISecurityRejectedError(
                (
                    SkillAISecurityIssue(
                        code="CONTENT_HASH_MISMATCH",
                        message="AI 生成文件内容哈希不匹配",
                    ),
                )
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
        registry = self._metric_registry
        if registry is None:
            raise SkillAIInputInvalidError("未注入指标版本注册表")
        if any(
            not callable(getattr(registry, method_name, None))
            for method_name in ("get_metric", "get_object", "get_object_version")
        ):
            raise SkillAIInputInvalidError("指标注册表不支持不可变版本快照")
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
            metric_snapshot = snapshot_metric.model_dump(mode="python")
            object_snapshot = object_version_record.snapshot
            _validate_strict_json(metric_snapshot)
            _validate_strict_json(object_snapshot)
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
                    "metric": metric_snapshot,
                    "object_code": object_version_record.object_code,
                    "object_snapshot": object_snapshot,
                    "object_version": object_version,
                    "snapshot_id": object_version_record.version_id,
                    "status": "published",
                }
            )
        return tuple(versions), tuple(prompt_snapshots)

    def _call_gateway(self, messages: list[Message]) -> ModelResponse:
        safe_error: SkillAIModelError | None = None
        try:
            return self._gateway.generate(
                messages,
                model_type=_MODEL_TYPE,
                scene=_SCENE,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            safe_error = _model_error(exc)
        # 在 except 作用域外抛出，避免 provider 原始异常进入 cause/context 链。
        raise safe_error from None

    def _parse_or_repair(
        self, response: ModelResponse
    ) -> tuple[SkillAIModelOutput, ModelResponse]:
        _validate_model_response_content(response.content)
        try:
            output = SkillAIModelOutput.model_validate_json(response.content)
        except (ValidationError, ValueError):
            if _contains_sensitive_content(response.content):
                raise SkillAIOutputInvalidError(
                    "模型输出包含敏感信息，拒绝结构修复"
                ) from None
        else:
            _ensure_complete_output_safe(output)
            try:
                _validate_business_pair(output)
            except SkillAIOutputInvalidError:
                pass
            else:
                return output, response

        repair_messages = [
            Message(role="system", content=build_system_prompt(operation="repair")),
            Message(role="user", content=build_repair_prompt(response.content)),
        ]
        repaired = self._call_gateway(repair_messages)
        _validate_model_response_content(repaired.content)
        try:
            repaired_output = SkillAIModelOutput.model_validate_json(repaired.content)
        except (ValidationError, ValueError) as final_error:
            raise SkillAIOutputInvalidError(
                "模型输出在一次结构修复后仍不符合严格 DTO"
            ) from final_error
        _ensure_complete_output_safe(repaired_output)
        _validate_business_pair(repaired_output)
        return repaired_output, repaired

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
    error_text = str(exc)
    return SkillAIModelError(
        category=category,
        model_name=str(getattr(exc, "model_name", "")),
        error_type=type(exc).__name__,
        error_hash=hashlib.sha256(
            error_text.encode("utf-8", errors="replace")
        ).hexdigest(),
    )


def _validate_model_response_content(content: str) -> None:
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError:
        raise SkillAIOutputInvalidError("模型响应不是可编码的 UTF-8 文本") from None
    if len(encoded) > _MAX_MODEL_RESPONSE_BYTES:
        raise SkillAIOutputInvalidError("模型响应大小超过 640 KiB 上限")


def _ensure_complete_output_safe(output: SkillAIModelOutput) -> None:
    canonical_output = json.dumps(
        output.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if _contains_sensitive_content(canonical_output):
        raise SkillAISecurityRejectedError(
            (
                SkillAISecurityIssue(
                    code="AI_SENSITIVE_CONTENT",
                    message="AI 生成提案包含不允许输出的敏感信息",
                    path="model_output",
                ),
            )
        )


def _validate_business_pair(output: SkillAIModelOutput) -> None:
    mounting = output.structured_config.business_mounting
    try:
        pair = (
            BusinessAction(mounting.business_action),
            BusinessObject(mounting.business_object),
        )
    except ValueError:
        raise SkillAIOutputInvalidError("业务动作与业务对象不在平台能力矩阵中") from None
    if pair not in VALID_ACTION_OBJECT_PAIRS:
        raise SkillAIOutputInvalidError("业务动作与业务对象不在平台能力矩阵中")


def _validate_strict_json(value: object, *, depth: int = 0) -> None:
    if depth > _MAX_STRICT_JSON_DEPTH:
        raise SkillAIInputInvalidError("指标快照超过允许的 JSON 嵌套深度")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SkillAIInputInvalidError("指标快照包含非有限浮点数")
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise SkillAIInputInvalidError("指标快照包含不可编码文本") from None
        return
    if isinstance(value, list):
        for item in value:
            _validate_strict_json(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise SkillAIInputInvalidError("指标快照 JSON 对象键必须为字符串")
        for item in value.values():
            _validate_strict_json(item, depth=depth + 1)
        return
    raise SkillAIInputInvalidError("指标快照仅允许严格 JSON 数据类型")


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _proposal_hash(
    *,
    evidence_hash: str,
    structured_config: Mapping[str, Any],
    raw_files: Mapping[str, str],
    validation_preview: Mapping[str, Any],
    provenance: Mapping[str, Any],
    citations: Sequence[Any],
    uncertainties: Sequence[str],
) -> str:
    return _canonical_hash(
        {
            "citations": [
                {
                    "source_type": citation.source_type,
                    "source_id": citation.source_id,
                    "summary": citation.summary,
                }
                for citation in citations
            ],
            "evidence_hash": evidence_hash,
            "provenance": dict(provenance),
            "raw_files": dict(raw_files),
            "structured_config": dict(structured_config),
            "uncertainties": list(uncertainties),
            "validation_preview": dict(validation_preview),
        }
    )


def _generation_evidence_hash(generation_id: str) -> str:
    parts = generation_id.split("_", 2)
    if len(parts) != 3 or parts[0] != "gen":
        raise SkillAIOutputInvalidError("generation_id 缺少生成证据哈希")
    return parts[1]


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
