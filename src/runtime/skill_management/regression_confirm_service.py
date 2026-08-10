"""Skill 错误案例人工确认投影服务。

按维度唯一分流：
- routing → 现有 SkillEvalCase（路由评测用例），source_type=policy_qa_feedback、source_ref=qa_turn_id
- other → 拒绝（不可执行，必须重新分型或 reject）
- 其余五类可执行维度 → SkillRegressionCase（分型回归用例，冻结类型化断言）

confirm 使用 pool ID 作为业务幂等键：重复确认已 confirmed 的条目返回同一资产。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceConflictError,
    SkillGovernanceStorage,
)
from src.data_platform.storage.skill.regression_ports import (
    SkillRegressionConflictError,
    SkillRegressionNotFoundError,
    SkillRegressionStorage,
)
from src.domain.skill.governance_models import SkillEvalCase
from src.domain.skill.regression_models import (
    AnswerQualityCaseProposal,
    CalculationCaseProposal,
    CitationCaseProposal,
    PolicyContentCaseProposal,
    RoutingCaseProposal,
    SafetyCaseProposal,
    SkillErrorDimension,
    SkillEvalCasePoolStatus,
    SkillRegressionCase,
)


class SkillRegressionCaseNotExecutableError(ValueError):
    """该维度不可确认为可执行资产（other）。"""


_PROPOSAL_TO_ASSERTION_TYPE: dict[str, type] = {
    "calculation": CalculationCaseProposal,
    "policy_content": PolicyContentCaseProposal,
    "citation": CitationCaseProposal,
    "answer_quality": AnswerQualityCaseProposal,
    "safety": SafetyCaseProposal,
}


@dataclass(frozen=True)
class ConfirmResult:
    pool_id: str
    case_type: str
    case_id: str
    revision: int


class RegressionConfirmService:
    def __init__(
        self,
        *,
        regression_storage: SkillRegressionStorage,
        governance_storage: SkillGovernanceStorage,
    ) -> None:
        self._regression_storage = regression_storage
        self._governance_storage = governance_storage

    def confirm(
        self,
        pool_id: str,
        *,
        request,
        confirmed_by: str,
        tenant_id: str,
    ) -> ConfirmResult:
        pool = self._regression_storage.get_pool_item(pool_id, tenant_id=tenant_id)
        if pool is None:
            raise SkillRegressionNotFoundError(pool_id)

        # 幂等：已确认且存在资产引用 → 直接返回
        if (
            pool.status == SkillEvalCasePoolStatus.CONFIRMED
            and pool.eval_case_ref is not None
        ):
            return ConfirmResult(
                pool_id=pool.pool_id,
                case_type=pool.eval_case_ref.case_type,
                case_id=pool.eval_case_ref.case_id,
                revision=pool.revision,
            )

        dimension = SkillErrorDimension(request.error_dimension)
        proposal_dict = request.case_proposal

        if dimension is SkillErrorDimension.ROUTING:
            case_type, case_id = self._project_routing(
                pool=pool, proposal_dict=proposal_dict, confirmed_by=confirmed_by
            )
        elif dimension is SkillErrorDimension.OTHER:
            raise SkillRegressionCaseNotExecutableError(
                f"pool {pool_id} 维度为 other，不可确认为可执行资产"
            )
        else:
            case_type, case_id = self._project_regression_case(
                pool=pool,
                dimension=dimension,
                proposal_dict=proposal_dict,
                confirmed_by=confirmed_by,
            )

        updated = self._regression_storage.confirm_pool_item(
            pool_id,
            tenant_id=tenant_id,
            case_type=case_type,
            case_id=case_id,
            expected_revision=request.expected_revision,
        )
        return ConfirmResult(
            pool_id=updated.pool_id,
            case_type=case_type,
            case_id=case_id,
            revision=updated.revision,
        )

    def _project_routing(
        self,
        *,
        pool,
        proposal_dict: dict | None,
        confirmed_by: str,
    ) -> tuple[str, str]:
        proposal = RoutingCaseProposal.model_validate(
            proposal_dict or {"case_type": "routing", "question_template": pool.question_excerpt}
        )
        case = SkillEvalCase(
            case_id=f"route_{uuid.uuid4().hex}",
            suite_version=self._governance_storage.next_suite_version(),
            question_template=proposal.question_template,
            expected_skill_id=proposal.expected_skill_id,
            required=proposal.required,
            risk_tags=list(proposal.risk_tags),
            source_type="policy_qa_feedback",
            source_ref=pool.source_qa_turn_id,
            created_by=confirmed_by,
        )
        saved = self._governance_storage.save_case(case)
        return "route", saved.case_id

    def _project_regression_case(
        self,
        *,
        pool,
        dimension: SkillErrorDimension,
        proposal_dict: dict | None,
        confirmed_by: str,
    ) -> tuple[str, str]:
        model = _PROPOSAL_TO_ASSERTION_TYPE.get(str(dimension.value))
        if model is None or proposal_dict is None:
            raise SkillRegressionCaseNotExecutableError(
                f"维度 {dimension.value} 缺少可执行 proposal"
            )
        proposal = model.model_validate(proposal_dict)  # type: ignore[arg-type]
        case = SkillRegressionCase(
            case_id=f"regcase_{uuid.uuid4().hex}",
            target_skill_id=proposal.target_skill_id,
            case_type=dimension,
            input_template=proposal.input_template,
            expected_assertions=proposal.assertions,
            required=True,
            evaluator_status="blocked_by_evaluator",
            source_type="policy_qa_feedback",
            source_ref=pool.source_qa_turn_id,
            source_hash=pool.source_hash,
            confirmed_by=confirmed_by,
            enabled=True,
        )
        saved = self._regression_storage.create_case(case)
        return str(dimension.value), saved.case_id
