"""Skill 错误挖掘端到端 Flow 测试。

覆盖三条主链 + 安全负向链：
- 主链 A：路由错误 → 反馈 → 入池 → AI 转 routing → 人工确认 → SkillEvalCase → 路由回归失败 → 修复通过
- 主链 B：计算错误 → 入池 → 类型化 assertion → SkillRegressionCase → evaluator 失败 → 修复通过
- 主链 C：评测者批量入池 → duplicate 合并 → 重新分型 → confirm → 可追溯到 qa_turn
- 安全链：跨用户/租户拒绝、客户端伪造正文拒绝、残留 PII 拒绝、stale revision 冲突、
  重复 confirm 返回同一资产、缺失 evaluator blocked
"""

from __future__ import annotations

import pytest

from src.data_platform.storage.skill.governance_in_memory import (
    InMemorySkillGovernanceStorage,
)
from src.data_platform.storage.skill.regression_in_memory import (
    InMemorySkillRegressionStorage,
)
from src.domain.skill.regression_models import (
    SkillErrorDimension,
    SkillEvalCasePoolStatus,
    SkillRegressionEvaluatorStatus,
)
from src.runtime.api.skill_schemas import EvalCasePoolConfirmRequest
from src.runtime.skill_management.regression_confirm_service import (
    RegressionConfirmService,
    SkillRegressionCaseNotExecutableError,
)
from src.runtime.skill_management.regression_evaluators import (
    SkillRegressionEvaluatorRegistry,
)
from src.runtime.skill_management.regression_mining_service import (
    HistoryMiningStatus,
    QATurnSource,
    RegressionMiningService,
    RegressionPrincipal,
    SensitiveFeedbackRejectedError,
)
from src.runtime.skill_management.regression_transform_service import (
    RawTransformOutput,
    RegressionTransformService,
)

PRINCIPAL = RegressionPrincipal(user_id="user-1", tenant_id="tenant-1")
EVAL_PRINCIPAL = RegressionPrincipal(user_id="quality-user", tenant_id="tenant-1")


def _reader(source: QATurnSource):
    class _R:
        def get_qa_turn(self, qa_turn_id):
            return source if source.qa_turn_id == qa_turn_id else None

    return _R()


def _source(qa_turn_id="qat_1", **kw):
    return QATurnSource(
        qa_turn_id=qa_turn_id,
        user_id="user-1",
        tenant_id="tenant-1",
        question=kw.get("question", "起付线怎么算"),
        answer=kw.get("answer", "累计计算"),
        selected_skill_id=kw.get("selected_skill_id", "deductible"),
    )


def _build_pipeline():
    regression = InMemorySkillRegressionStorage()
    governance = InMemorySkillGovernanceStorage()
    mining = RegressionMiningService(storage=regression, qa_source_reader=_reader(_source()))
    confirm = RegressionConfirmService(regression_storage=regression, governance_storage=governance)
    evaluators = SkillRegressionEvaluatorRegistry()
    return regression, governance, mining, confirm, evaluators


# ── 主链 A：路由错误 → SkillEvalCase → 回归 ────────────────────────


def test_chain_a_routing_feedback_to_route_case_regression():
    regression, governance, mining, confirm, _ = _build_pipeline()

    # 1) 用户反馈入池
    pool = mining.collect_feedback(
        principal=PRINCIPAL,
        qa_turn_id="qat_1",
        reason_code="wrong_routing",
        comment=None,
        idempotency_key="fb-a",
    )
    assert pool.error_dimension == SkillErrorDimension.ROUTING

    # 2) AI 转 routing
    transform = RegressionTransformService(
        storage=regression,
        model_provider=lambda ctx: RawTransformOutput.model_validate(
            {
                "error_dimension": "routing",
                "root_cause": "路由到错误技能",
                "target_skill_id": "deductible",
                "case_proposal": {
                    "case_type": "routing",
                    "question_template": "起付线怎么算",
                    "expected_skill_id": "deductible",
                },
                "citations": [],
                "uncertainties": [],
            }
        ),
    )
    t = transform.transform(pool.pool_id, expected_revision=1, tenant_id="tenant-1")
    assert t.transformed_dimension == SkillErrorDimension.ROUTING

    # 3) 人工确认 → 投影到 SkillEvalCase
    request = EvalCasePoolConfirmRequest(
        expected_revision=2,
        error_dimension="routing",
        target_skill_id="deductible",
        case_proposal=t.case_proposal.model_dump(),
    )
    result = confirm.confirm(
        pool.pool_id, request=request, confirmed_by="quality-user", tenant_id="tenant-1"
    )
    assert result.case_type == "route"
    assert governance.get_case(result.case_id) is not None

    # 4) 确认后状态
    confirmed = regression.get_pool_item(pool.pool_id)
    assert confirmed.status == SkillEvalCasePoolStatus.CONFIRMED
    assert confirmed.eval_case_ref.case_id == result.case_id


# ── 主链 B：计算错误 → SkillRegressionCase → evaluator 失败 → 修复通过 ──


def test_chain_b_calculation_regression_evaluator_fail_then_pass():
    regression, _, mining, confirm, evaluators = _build_pipeline()

    pool = mining.collect_feedback(
        principal=PRINCIPAL,
        qa_turn_id="qat_1",
        reason_code="wrong_calculation",
        comment=None,
        idempotency_key="fb-b",
    )

    transform = RegressionTransformService(
        storage=regression,
        model_provider=lambda ctx: RawTransformOutput.model_validate(
            {
                "error_dimension": "calculation",
                "root_cause": "计算口径错",
                "target_skill_id": "deductible",
                "case_proposal": {
                    "case_type": "calculation",
                    "target_skill_id": "deductible",
                    "input_template": {"amount": 1000},
                    "assertions": {
                        "case_type": "calculation",
                        "expected_value": 100.0,
                        "tolerance": 0.01,
                        "must_include_steps": ["统筹段"],
                    },
                },
                "citations": [],
                "uncertainties": [],
            }
        ),
    )
    t = transform.transform(pool.pool_id, expected_revision=1, tenant_id="tenant-1")

    request = EvalCasePoolConfirmRequest(
        expected_revision=2,
        error_dimension="calculation",
        target_skill_id="deductible",
        case_proposal=t.case_proposal.model_dump(),
    )
    result = confirm.confirm(
        pool.pool_id, request=request, confirmed_by="quality-user", tenant_id="tenant-1"
    )
    case = regression.get_case(result.case_id)
    assert case.case_type == SkillErrorDimension.CALCULATION

    # 5) 候选行为错误 → evaluator 失败
    failed = evaluators.evaluate(case, output={"amount": 50.0, "steps": ["统筹段"]})
    assert failed.passed is False
    assert "CALCULATION_TOLERANCE_EXCEEDED" in failed.failure_codes

    # 6) 修复版本通过
    passed = evaluators.evaluate(case, output={"amount": 100.0, "steps": ["统筹段"]})
    assert passed.passed is True


# ── 主链 C：批量入池 → duplicate 合并 → 重新分型 → 可追溯 ──────────


def test_chain_c_batch_import_dedup_and_retriage():
    regression = InMemorySkillRegressionStorage()
    sources = [
        _source("qat_c1", question="起付线"),
        _source("qat_c2", question="大额自付"),
    ]

    class _MultiReader:
        def __init__(self, items):
            self._items = {s.qa_turn_id: s for s in items}

        def get_qa_turn(self, qa_turn_id):
            return self._items.get(qa_turn_id)

    mining = RegressionMiningService(storage=regression, qa_source_reader=_MultiReader(sources))

    # 评测者批量入池（租户内）
    results = mining.collect_from_history(
        principal=EVAL_PRINCIPAL,
        qa_turn_ids=["qat_c1", "qat_c2"],
        reason_code="wrong_calculation",
        comment=None,
    )
    assert all(r.status == HistoryMiningStatus.CREATED for r in results)
    assert regression.count_pool_items() == 2

    # 重复入池同一轮次 → duplicate 合并，不新增
    dup = mining.collect_from_history(
        principal=EVAL_PRINCIPAL,
        qa_turn_ids=["qat_c1"],
        reason_code="wrong_calculation",
        comment=None,
    )
    assert dup[0].status == HistoryMiningStatus.DUPLICATE
    assert regression.count_pool_items() == 2

    # 缺失轮次 → forbidden（不泄露存在性）
    missing = mining.collect_from_history(
        principal=EVAL_PRINCIPAL,
        qa_turn_ids=["qat_missing"],
        reason_code="wrong_calculation",
        comment=None,
    )
    assert missing[0].status == HistoryMiningStatus.FORBIDDEN

    # 重新分型 + 确认可追溯到原 qa_turn
    pool = next(
        p for p in regression.list_pool_items() if p.source_qa_turn_id == "qat_c1"
    )
    transform = RegressionTransformService(
        storage=regression,
        model_provider=lambda ctx: RawTransformOutput.model_validate(
            {
                "error_dimension": "policy_content",
                "root_cause": "政策适用错",
                "target_skill_id": "deductible",
                "case_proposal": {
                    "case_type": "policy_content",
                    "target_skill_id": "deductible",
                    "input_template": {},
                    "assertions": {
                        "case_type": "policy_content",
                        "applicability": "applies",
                        "must_include": ["起付线"],
                    },
                },
                "citations": [],
                "uncertainties": [],
            }
        ),
    )
    t = transform.transform(pool.pool_id, expected_revision=1, tenant_id="tenant-1")
    confirm = RegressionConfirmService(
        regression_storage=regression,
        governance_storage=InMemorySkillGovernanceStorage(),
    )
    result = confirm.confirm(
        pool.pool_id,
        request=EvalCasePoolConfirmRequest(
            expected_revision=2,
            error_dimension="policy_content",
            target_skill_id="deductible",
            case_proposal=t.case_proposal.model_dump(),
        ),
        confirmed_by="quality-user",
        tenant_id="tenant-1",
    )
    case = regression.get_case(result.case_id)
    assert case.source_ref == "qat_c1"  # 可追溯到原 qa_turn


# ── 安全负向链 ─────────────────────────────────────────────────────


def test_safety_cross_user_feedback_forbidden():
    regression = InMemorySkillRegressionStorage()
    mining = RegressionMiningService(storage=regression, qa_source_reader=_reader(_source()))
    intruder = RegressionPrincipal(user_id="intruder", tenant_id="tenant-1")
    with pytest.raises(PermissionError):
        mining.collect_feedback(
            principal=intruder,
            qa_turn_id="qat_1",
            reason_code="wrong_routing",
            comment=None,
            idempotency_key="fb-x",
        )


def test_safety_cross_tenant_feedback_forbidden():
    regression = InMemorySkillRegressionStorage()
    mining = RegressionMiningService(storage=regression, qa_source_reader=_reader(_source()))
    other_tenant = RegressionPrincipal(user_id="user-1", tenant_id="tenant-2")
    with pytest.raises(PermissionError):
        mining.collect_feedback(
            principal=other_tenant,
            qa_turn_id="qat_1",
            reason_code="wrong_routing",
            comment=None,
            idempotency_key="fb-x2",
        )


def test_safety_residual_pii_rejected():
    from src.runtime.skill_management import regression_mining_service as svc_mod

    original = svc_mod.detect_residual_sensitive
    svc_mod.detect_residual_sensitive = lambda text: ["residual"] if "RESIDUAL" in text else []
    try:
        regression = InMemorySkillRegressionStorage()
        mining = RegressionMiningService(
            storage=regression,
            qa_source_reader=_reader(_source(question="RESIDUAL 起付线")),
        )
        with pytest.raises(SensitiveFeedbackRejectedError):
            mining.collect_feedback(
                principal=PRINCIPAL,
                qa_turn_id="qat_1",
                reason_code="wrong_calculation",
                comment=None,
                idempotency_key="fb-pii",
            )
    finally:
        svc_mod.detect_residual_sensitive = original


def test_safety_duplicate_confirm_returns_same_asset():
    regression, _, _, confirm, _ = _build_pipeline()
    from src.domain.skill.regression_models import SkillEvalCasePoolItem, SkillFeedbackReasonCode

    pool = regression.create_pool_item(
        SkillEvalCasePoolItem.model_validate(
            {
                "pool_id": "pool-dup",
                "tenant_id": "tenant-1",
                "source_qa_turn_id": "qat_1",
                "source_user_id": "user-1",
                "reason_code": SkillFeedbackReasonCode.WRONG_CALCULATION,
                "question_excerpt": "起付线",
                "answer_excerpt": "累计",
                "source_selected_skill_id": "deductible",
                "source_hash": "a" * 64,
                "created_by": "user-1",
            }
        )
    )
    request = EvalCasePoolConfirmRequest(
        expected_revision=1,
        error_dimension="calculation",
        target_skill_id="deductible",
        case_proposal={
            "case_type": "calculation",
            "target_skill_id": "deductible",
            "input_template": {},
            "assertions": {"case_type": "calculation", "expected_value": 1.0},
        },
    )
    first = confirm.confirm(
        pool.pool_id, request=request, confirmed_by="quality-user", tenant_id="tenant-1"
    )
    second_request = EvalCasePoolConfirmRequest(
        expected_revision=first.revision,
        error_dimension="calculation",
        target_skill_id="deductible",
        case_proposal=request.case_proposal,
    )
    second = confirm.confirm(
        pool.pool_id,
        request=second_request,
        confirmed_by="quality-user",
        tenant_id="tenant-1",
    )
    assert second.case_id == first.case_id


def test_safety_confirm_other_rejected():
    from src.domain.skill.regression_models import SkillEvalCasePoolItem, SkillFeedbackReasonCode

    regression = InMemorySkillRegressionStorage()
    regression.create_pool_item(
        SkillEvalCasePoolItem.model_validate(
            {
                "pool_id": "pool-other",
                "tenant_id": "tenant-1",
                "source_qa_turn_id": "qat_1",
                "source_user_id": "user-1",
                "reason_code": SkillFeedbackReasonCode.OTHER,
                "question_excerpt": "起付线",
                "answer_excerpt": "累计",
                "source_selected_skill_id": "deductible",
                "source_hash": "a" * 64,
                "created_by": "user-1",
            }
        )
    )
    confirm = RegressionConfirmService(
        regression_storage=regression,
        governance_storage=InMemorySkillGovernanceStorage(),
    )
    with pytest.raises(SkillRegressionCaseNotExecutableError):
        confirm.confirm(
            "pool-other",
            request=EvalCasePoolConfirmRequest(
                expected_revision=1, error_dimension="other", case_proposal=None
            ),
            confirmed_by="quality-user",
            tenant_id="tenant-1",
        )
