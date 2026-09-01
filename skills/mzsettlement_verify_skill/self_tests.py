"""可由治理页面维护的门诊结算固定自测案例。"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.domain.skill.governance_models import (
    SkillEvalAssertion,
    SkillEvalDataLocator,
    SkillEvalDimension,
    SkillEvalEnvironmentRequirement,
    SkillEvalPartition,
    SkillEvalTask,
    SkillEvalTaskInput,
    TrajectoryPrefix,
)
from src.domain.skill.regression_models import (
    AnswerQualityAssertions,
    CalculationAssertions,
)

from .models import OutpatientSettlementContext
from .verifier import money, verify_settlement


SELF_TEST_CASES_PATH = Path(__file__).with_name("self_test_cases.yaml")
_WRITE_LOCK = RLock()
_CHANNEL_FIELDS = {
    "large_fund_payment": "大额基金",
    "supplementary_insurance_payment": "补充保险",
    "unit_supplement_payment": "公务员或公疗",
    "big_disease_payment": "大病保障",
    "retired_medical_payment": "退役医疗",
    "assistance_payment": "医疗救助",
    "disabled_soldier_payment": "军残补助",
}


class SettlementSelfTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    settlement_id: str = Field(min_length=6, max_length=80)
    expected_self_pay_one: Decimal = Field(ge=0)
    context: OutpatientSettlementContext
    enabled: bool = True
    note: str = Field(default="", max_length=500)

    @property
    def payment_channels(self) -> list[str]:
        return [
            label
            for field, label in _CHANNEL_FIELDS.items()
            if money(getattr(self.context, field)) not in {None, Decimal("0.00")}
        ]


class SettlementSelfTestCaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_id: str = Field(min_length=6, max_length=80)
    expected_self_pay_one: Decimal = Field(ge=0)
    context: OutpatientSettlementContext
    enabled: bool = True
    note: str = Field(default="", max_length=500)


class SettlementSelfTestCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: Literal["passed", "failed", "disabled"]
    actual_self_pay_one: Decimal | None = None
    expected_self_pay_one: Decimal
    message: str


class SettlementSelfTestSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SettlementSelfTestCase]
    total: int
    enabled: int


class SettlementSelfTestRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[SettlementSelfTestCaseResult]
    total: int
    passed: int
    failed: int


def load_self_test_cases(path: Path = SELF_TEST_CASES_PATH) -> list[SettlementSelfTestCase]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [SettlementSelfTestCase.model_validate(item) for item in rows]


def list_self_test_suite(path: Path = SELF_TEST_CASES_PATH) -> SettlementSelfTestSuite:
    items = load_self_test_cases(path)
    return SettlementSelfTestSuite(
        items=items,
        total=len(items),
        enabled=sum(item.enabled for item in items),
    )


def build_eval_tasks(
    suite_id: str,
    *,
    created_by: str,
    path: Path = SELF_TEST_CASES_PATH,
) -> list[SkillEvalTask]:
    """将历史门诊固定案例无副作用转换为通用端到端任务。"""
    tasks: list[SkillEvalTask] = []
    for case in load_self_test_cases(path):
        expected = str(case.expected_self_pay_one)
        business_tags = tuple(
            value
            for value in (
                case.context.person_type,
                case.context.insurance_type,
                case.context.service_type,
                *case.payment_channels,
            )
            if value
        )
        tasks.append(
            SkillEvalTask(
                task_id=f"EVT_mz_{case.case_id.replace('-', '_')}",
                suite_id=suite_id,
                target_skill_id="mzsettlement_verify_skill",
                name=(
                    f"{case.context.person_type or '未知人群'}·"
                    f"{case.context.service_type or '门诊'}费用组成"
                ),
                partition=SkillEvalPartition.REGRESSION,
                input=SkillEvalTaskInput(
                    question="费用组成",
                    settlement_id=case.settlement_id,
                ),
                data_locators=(
                    SkillEvalDataLocator(
                        resource_type="settlement",
                        resource_id=case.settlement_id,
                    ),
                ),
                environment_requirements=(
                    SkillEvalEnvironmentRequirement(
                        kind="data_source",
                        name="outpatient_settlement",
                    ),
                ),
                assertions=(
                    SkillEvalAssertion(
                        assertion_id="self_pay_one",
                        dimension=SkillEvalDimension.BEHAVIOR,
                        output_adapter="self_pay_one",
                        expected=CalculationAssertions(
                            expected_value=float(case.expected_self_pay_one),
                            tolerance=0.0,
                        ),
                    ),
                    SkillEvalAssertion(
                        assertion_id="reported_value_only",
                        dimension=SkillEvalDimension.ANSWER_QUALITY,
                        output_adapter="public_answer",
                        expected=AnswerQualityAssertions(
                            answerable=True,
                            must_include=[expected],
                            must_not_include=[
                                "医保范围内金额 - 基金支付总金额",
                                "医保范围内金额-基金支付总金额",
                                "医保范围内金额－基金支付总金额",
                            ],
                        ),
                    ),
                ),
                trajectory_prefixes=(
                    TrajectoryPrefix(
                        prefix_id="after_settlement_loaded",
                        boundary_kind="after_settlement_loaded",
                    ),
                ),
                enabled=case.enabled,
                source_type="outpatient_self_test",
                source_ref=case.case_id,
                business_tags=business_tags,
                created_by=created_by,
                updated_by=created_by,
            )
        )
    return tasks


def update_self_test_case(
    case_id: str,
    request: SettlementSelfTestCaseUpdate,
    path: Path = SELF_TEST_CASES_PATH,
) -> SettlementSelfTestCase:
    with _WRITE_LOCK:
        items = load_self_test_cases(path)
        index = next((i for i, item in enumerate(items) if item.case_id == case_id), None)
        if index is None:
            raise KeyError(case_id)
        updated = SettlementSelfTestCase(
            case_id=case_id,
            **request.model_dump(),
        )
        items[index] = updated
        payload = [item.model_dump(mode="json", exclude_none=True) for item in items]
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        temporary.replace(path)
        return updated


def run_self_tests(path: Path = SELF_TEST_CASES_PATH) -> SettlementSelfTestRun:
    results: list[SettlementSelfTestCaseResult] = []
    for case in load_self_test_cases(path):
        if not case.enabled:
            results.append(SettlementSelfTestCaseResult(
                case_id=case.case_id,
                status="disabled",
                expected_self_pay_one=case.expected_self_pay_one,
                message="案例已停用。",
            ))
            continue
        verification = verify_settlement(
            case.context,
            scenario_id="personal-liability-explanation",
            money_fields={"self_pay_one"},
            required_money_fields={"self_pay_one"},
        )
        explanation = next(
            (item for item in verification.field_explanations if item.field_name == "个人自付一"),
            None,
        )
        actual = None if explanation is None else explanation.value
        deprecated_check = any(
            item.name == "个人自付一组成勾稽" for item in verification.amount_checks
        )
        passed = actual == money(case.expected_self_pay_one) and not deprecated_check
        message = (
            "结算单个人自付一原值已正确保留。"
            if passed
            else f"期望 {money(case.expected_self_pay_one)} 元，实际 {actual} 元。"
        )
        if deprecated_check:
            message = "仍执行了不适用于全人群的个人自付一组成公式。"
        results.append(SettlementSelfTestCaseResult(
            case_id=case.case_id,
            status="passed" if passed else "failed",
            actual_self_pay_one=actual,
            expected_self_pay_one=case.expected_self_pay_one,
            message=message,
        ))
    enabled_results = [item for item in results if item.status != "disabled"]
    return SettlementSelfTestRun(
        results=results,
        total=len(enabled_results),
        passed=sum(item.status == "passed" for item in enabled_results),
        failed=sum(item.status == "failed" for item in enabled_results),
    )
