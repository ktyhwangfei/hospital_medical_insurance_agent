from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.governance_in_memory import (
    InMemorySkillGovernanceStorage,
)
from src.data_platform.storage.skill.version_in_memory import InMemorySkillVersionStorage
from src.domain.skill.governance_models import (
    FailureAttribution,
    RouteAssertions,
    SkillEvalAssertion,
    SkillEvalDimension,
    SkillEvalEnvironmentSnapshot,
    SkillEvalTask,
    SkillEvalTaskInput,
    SkillEvalTaskResult,
    SkillEvalTaskStatus,
)
from src.domain.skill.version_models import SkillValidationStatus, SkillVersion
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    SkillControlPrincipal,
    get_skill_evaluation_principal,
    get_skill_governance_service,
)
from src.runtime.skill_management.governance_service import SkillGovernanceService
from src.runtime.task_closure import service as task_closure_service
from src.skill_infra.skill_loader import SkillLoader


PREFIX = "/api/v1/medical-insurance-ai-agent"
SKILL_ID = "mzsettlement_verify_skill"


def test_failed_benchmark_creates_improvement_task_and_passes_retest(
    monkeypatch,
) -> None:
    loader = SkillLoader(SKILLS_DIR)
    loader.discover()
    loaded = loader.get_all()[SKILL_ID]
    versions = InMemorySkillVersionStorage()
    version = SkillVersion(
        version_id="version-under-test",
        skill_id=SKILL_ID,
        semantic_version="1.0.0",
        source_commit="flow-test",
        source_path=f"skills/{SKILL_ID}",
        artifact_hash="a" * 64,
        manifest_snapshot=loaded.manifest,
        dependency_snapshot={},
        file_count=1,
        validation_status=SkillValidationStatus.PASSED,
        created_by="developer",
        created_at=datetime.now(timezone.utc),
    )
    versions.save_version(version)
    service = SkillGovernanceService(
        storage=InMemorySkillGovernanceStorage(),
        version_storage=versions,
        loader=loader,
    )
    suite = service.create_suite(
        name="门诊费用闭环",
        scope="skill",
        skill_id=SKILL_ID,
        purpose="验证失败修复和复测",
        created_by="quality-user",
    )
    service.create_task(
        SkillEvalTask(
            task_id="EVT_flow_outpatient",
            suite_id=suite.suite_id,
            target_skill_id=SKILL_ID,
            name="门诊费用组成",
            input=SkillEvalTaskInput(question="费用组成", settlement_id="T_flow"),
            assertions=(
                SkillEvalAssertion(
                    assertion_id="route",
                    dimension=SkillEvalDimension.ROUTE,
                    output_adapter="route",
                    expected=RouteAssertions(expected_skill_id=SKILL_ID),
                ),
            ),
            source_type="flow_test",
            created_by="quality-user",
            updated_by="quality-user",
        ),
        created_by="quality-user",
    )
    dataset = service.freeze_dataset(suite.suite_id, created_by="quality-user")
    benchmark = service.create_benchmark(
        name="门诊闭环 V1",
        skill_id=SKILL_ID,
        dataset_version_id=dataset.dataset_version_id,
        environment_snapshot=SkillEvalEnvironmentSnapshot(
            runtime_version="test",
            data_source_mode="memory",
        ),
        evaluator_plan_id="deterministic_v1",
        judge_version=None,
        gate_thresholds={},
        created_by="quality-user",
    )

    class Runner:
        fixed = False

        async def run(self, task):
            if self.fixed:
                return SkillEvalTaskResult(
                    task_id=task.task_id,
                    status=SkillEvalTaskStatus.PASSED,
                    selected_skill_id=task.target_skill_id,
                )
            return SkillEvalTaskResult(
                task_id=task.task_id,
                status=SkillEvalTaskStatus.FAILED,
                selected_skill_id=task.target_skill_id,
                failure_attributions=(
                    FailureAttribution(
                        task_id=task.task_id,
                        owner_type="agent",
                        stage="calculation",
                        failure_code="CALCULATION_TOLERANCE_EXCEEDED",
                        dimension="calculation",
                        summary="金额超出容差",
                        evidence_refs=("settlement:self_pay_one",),
                    ),
                ),
            )

    runner = Runner()
    monkeypatch.setattr(
        "src.runtime.skill_management.governance_service.PolicyQAEvaluationRunner",
        lambda **_kwargs: runner,
    )

    def create_improvement_task(**kwargs):
        runner.fixed = True
        return {**kwargs, "status": "pending"}

    monkeypatch.setattr(task_closure_service, "create_task", create_improvement_task)
    app = create_app()
    app.dependency_overrides[get_skill_governance_service] = lambda: service
    app.dependency_overrides[get_skill_evaluation_principal] = lambda: (
        SkillControlPrincipal(user_id="quality-user", roles=("quality",))
    )

    with TestClient(app) as client:
        run = client.post(
            f"{PREFIX}/infra-skills/eval-benchmarks/{benchmark.benchmark_id}/runs",
            json={"version_id": version.version_id},
        )
        assert run.status_code == 201
        assert run.json()["status"] == "failed"

        clusters = client.get(
            f"{PREFIX}/infra-skills/eval-runs/{run.json()['run_id']}/failure-clusters"
        ).json()
        improvement = client.post(
            f"{PREFIX}/infra-skills/eval-failure-clusters/"
            f"{clusters[0]['cluster']['cluster_id']}/improvement-task",
            json={"suggested_target": "assembler"},
        )
        assert improvement.status_code == 201

        retest = client.post(
            f"{PREFIX}/infra-skills/eval-runs/{run.json()['run_id']}/retest"
        )
        assert retest.status_code == 201
        assert retest.json()["status"] == "passed"
        assert retest.json()["metrics"]["gate_passed"] is True
