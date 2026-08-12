"""Skill 错误案例 AI 转换服务。

将案例池条目经 ModelGateway 转换为类型化回归 proposal：
- 只向模型发送脱敏摘要、当时 selected skill、Skill manifest 摘要和可追溯政策证据。
- 模型输出 error_dimension + case_proposal（判别联合）。
- 严格校验：other 不得携带可执行 proposal；可执行维度必须有 proposal；proposal 的
  case_type 必须与 dimension 一致。最多一次结构修复；证据不足强制 other + None。
- 失败时不改变状态和 revision。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ValidationError

from src.data_platform.storage.skill.regression_ports import (
    SkillRegressionConflictError,
    SkillRegressionNotFoundError,
    SkillRegressionStorage,
)
from src.domain.skill.regression_models import (
    AnswerQualityCaseProposal,
    CalculationCaseProposal,
    CaseProposal,
    CitationCaseProposal,
    PolicyContentCaseProposal,
    RoutingCaseProposal,
    SafetyAssertions,
    SafetyCaseProposal,
    SkillErrorDimension,
)

logger = logging.getLogger(__name__)


class SkillRegressionTransformError(ValueError):
    """模型转换输出不符合严格分型约束。"""


_PROPOSAL_MODELS: dict[str, type[BaseModel]] = {
    "routing": RoutingCaseProposal,
    "calculation": CalculationCaseProposal,
    "policy_content": PolicyContentCaseProposal,
    "citation": CitationCaseProposal,
    "answer_quality": AnswerQualityCaseProposal,
    "safety": SafetyCaseProposal,
}


class RawTransformOutput(BaseModel):
    """模型解析后的转换输出（人工确认前的候选）。"""

    error_dimension: SkillErrorDimension
    root_cause: str | None = None
    target_skill_id: str | None = None
    case_proposal: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = []
    uncertainties: list[str] = []


@dataclass(frozen=True)
class TransformContext:
    """提供给模型的脱敏上下文（不含原始患者标识）。"""

    question_excerpt: str
    answer_excerpt: str
    comment: str
    source_selected_skill_id: str | None
    available_skill_manifest: list[dict[str, Any]]


class TransformModelProvider(Protocol):
    def __call__(self, context: TransformContext) -> RawTransformOutput: ...


@dataclass(frozen=True)
class TransformResult:
    pool_id: str
    transformed_dimension: SkillErrorDimension
    case_proposal: CaseProposal | None
    root_cause: str | None
    citations: list[dict[str, Any]]
    uncertainties: list[str]
    revision: int


class RegressionTransformService:
    def __init__(
        self,
        *,
        storage: SkillRegressionStorage,
        model_provider: TransformModelProvider,
        manifest_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._storage = storage
        self._model_provider = model_provider
        self._manifest_provider = manifest_provider or _default_manifest

    def transform(
        self,
        pool_id: str,
        *,
        expected_revision: int,
        tenant_id: str,
    ) -> TransformResult:
        pool = self._storage.get_pool_item(pool_id, tenant_id=tenant_id)
        if pool is None:
            raise SkillRegressionNotFoundError(pool_id)

        context = TransformContext(
            question_excerpt=pool.question_excerpt,
            answer_excerpt=pool.answer_excerpt,
            comment=pool.comment,
            source_selected_skill_id=pool.source_selected_skill_id,
            available_skill_manifest=self._manifest_provider(),
        )

        try:
            raw = self._model_provider(context)
        except Exception as exc:  # noqa: BLE001 - 模型失败不改状态
            logger.warning("transform model call failed for %s: %s", pool_id, exc)
            raise SkillRegressionTransformError("模型转换失败") from exc

        dimension, proposal = self._validate_and_parse(raw)

        try:
            updated = self._storage.transform_pool_item(
                pool_id,
                tenant_id=tenant_id,
                transformed_dimension=dimension,
                transformed_proposal=(
                    proposal.model_dump() if proposal is not None else None
                ),
                transformed_root_cause=raw.root_cause,
                transformed_citations=raw.citations,
                transformed_uncertainties=raw.uncertainties,
                expected_revision=expected_revision,
            )
        except SkillRegressionConflictError:
            raise

        return TransformResult(
            pool_id=updated.pool_id,
            transformed_dimension=dimension,
            case_proposal=proposal,
            root_cause=raw.root_cause,
            citations=raw.citations,
            uncertainties=raw.uncertainties,
            revision=updated.revision,
        )

    @staticmethod
    def _validate_and_parse(
        raw: RawTransformOutput,
    ) -> tuple[SkillErrorDimension, CaseProposal | None]:
        dimension = raw.error_dimension

        if dimension is SkillErrorDimension.OTHER:
            if raw.case_proposal is not None:
                raise SkillRegressionTransformError(
                    "other 维度不得携带可执行 proposal"
                )
            return dimension, None

        if raw.case_proposal is None:
            raise SkillRegressionTransformError(
                "可执行维度必须有 proposal"
            )

        proposal_type = raw.case_proposal.get("case_type")
        if proposal_type != str(dimension.value):
            raise SkillRegressionTransformError(
                f"dimension {dimension.value} 与 proposal case_type "
                f"{proposal_type} 不一致"
            )

        model = _PROPOSAL_MODELS.get(str(dimension.value))
        if model is None:
            raise SkillRegressionTransformError(
                f"未知可执行维度 {dimension.value}"
            )

        try:
            proposal = model.model_validate(raw.case_proposal)
        except ValidationError as exc:
            raise SkillRegressionTransformError(
                f"proposal 校验失败: {exc}"
            ) from exc

        return dimension, proposal  # type: ignore[return-value]


def _default_manifest() -> list[dict[str, Any]]:
    """提供可用 Skill manifest 摘要给模型（最小实现）。"""
    try:
        from src.skill_infra.skill_loader import get_loader

        loader = get_loader()
        return [
            {"skill_id": s.skill_id, "skill_name": s.skill_name}
            for s in loader.list_skills()
        ]
    except Exception:  # noqa: BLE001
        return []


def _extract_json(content: str) -> dict[str, Any]:
    """从模型输出中抽取首个 JSON 对象（兼容 ```json 代码块）。"""
    import json
    import re

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        return json.loads(brace.group(0))
    raise SkillRegressionTransformError("模型输出未包含可解析的 JSON")


class GatewayTransformModelProvider:
    """生产环境适配器：通过 ModelGateway 调用模型并解析为 RawTransformOutput。"""

    SCENE = "skill_eval_transform"

    def __init__(self, gateway=None) -> None:
        from src.model_service.gateway import ModelGateway
        from src.model_service.models import Message

        self._Message = Message
        self._gateway = gateway or ModelGateway()

    def __call__(self, context: TransformContext) -> RawTransformOutput:
        from src.runtime.skill_management.regression_transform_prompts import (
            build_transform_prompt,
        )

        prompt = build_transform_prompt(context)
        messages = [
            self._Message(role="system", content="你是医保 Skill 错误归因助手，只输出严格 JSON。"),
            self._Message(role="user", content=prompt),
        ]
        response = self._gateway.generate(
            messages, model_type="text", scene=self.SCENE
        )
        raw_dict = _extract_json(response.content)
        return RawTransformOutput.model_validate(raw_dict)
