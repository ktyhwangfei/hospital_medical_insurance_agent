from pydantic import ValidationError
import pytest

from src.domain.skill.governance_models import (
    SkillEvalAssertion,
    SkillEvalBenchmark,
    SkillEvalDataLocator,
    SkillEvalDatasetVersion,
    SkillEvalDimension,
    SkillEvalEnvironmentSnapshot,
    SkillEvalPartition,
    SkillEvalTask,
    SkillEvalTaskInput,
    canonical_eval_hash,
)
from src.domain.skill.regression_models import CalculationAssertions


def _task() -> SkillEvalTask:
    return SkillEvalTask(
        task_id="EVT_person_21",
        suite_id="EVS_mz",
        target_skill_id="mzsettlement_verify_skill",
        name="退休职工门诊费用组成",
        partition=SkillEvalPartition.REGRESSION,
        input=SkillEvalTaskInput(
            question="费用组成",
            settlement_id="011100030X260417004975",
        ),
        data_locators=[
            SkillEvalDataLocator(
                resource_type="settlement",
                resource_id="011100030X260417004975",
            )
        ],
        assertions=[
            SkillEvalAssertion(
                assertion_id="self_pay_one",
                dimension=SkillEvalDimension.BEHAVIOR,
                output_adapter="self_pay_one",
                expected=CalculationAssertions(
                    expected_value=510.96,
                    tolerance=0.0,
                ),
            )
        ],
        source_type="outpatient_self_test",
        source_ref="person-21",
        created_by="quality-user",
        updated_by="quality-user",
    )


def test_dataset_hash_is_stable_and_version_is_frozen() -> None:
    task = _task()
    task_payload = [task.model_dump(mode="json")]
    content_hash = canonical_eval_hash(task_payload)
    assert content_hash == canonical_eval_hash(task_payload)

    version = SkillEvalDatasetVersion(
        dataset_version_id="EVD_1",
        suite_id=task.suite_id,
        suite_revision=1,
        version_number=1,
        task_snapshots=[task],
        environment_contract_hash="a" * 64,
        evaluator_plan_hash="b" * 64,
        content_hash=content_hash,
        created_by="quality-user",
    )

    assert isinstance(version.task_snapshots, tuple)
    assert version.task_snapshots[0].data_locators[0].resource_type == "settlement"
    with pytest.raises(ValidationError):
        version.task_snapshots += (task,)


def test_task_rejects_missing_assertions() -> None:
    with pytest.raises(ValidationError, match="assertion"):
        SkillEvalTask.model_validate({**_task().model_dump(), "assertions": []})


def test_benchmark_uses_typed_environment_and_gate_defaults() -> None:
    benchmark = SkillEvalBenchmark(
        benchmark_id="EVB_mz_v1",
        name="门诊结算解释 V1",
        skill_id="mzsettlement_verify_skill",
        dataset_version_id="EVD_1",
        environment_snapshot=SkillEvalEnvironmentSnapshot(
            runtime_version="test",
            data_source_mode="memory",
        ),
        environment_hash="c" * 64,
        evaluator_plan_hash="d" * 64,
        created_by="quality-user",
    )

    assert benchmark.gate_thresholds.required_hard_pass_rate == 1.0
    assert benchmark.gate_thresholds.max_new_failures == 0

    with pytest.raises(ValidationError):
        SkillEvalBenchmark.model_validate(
            {
                **benchmark.model_dump(),
                "environment_snapshot": {
                    "runtime_version": "test",
                    "data_source_mode": "memory",
                    "unknown": "not-allowed",
                },
            }
        )
