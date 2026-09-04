import pytest
from fastapi.testclient import TestClient

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.governance_in_memory import (
    InMemorySkillGovernanceStorage,
)
from src.data_platform.storage.skill.version_in_memory import (
    InMemorySkillVersionStorage,
)
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    SkillControlPrincipal,
    get_skill_evaluation_principal,
    get_skill_governance_service,
)
from src.runtime.skill_management.governance_service import SkillGovernanceService
from src.skill_infra.skill_loader import SkillLoader


PREFIX = "/api/v1/medical-insurance-ai-agent"


@pytest.fixture
def client() -> TestClient:
    loader = SkillLoader(SKILLS_DIR)
    loader.discover()
    app = create_app()
    service = SkillGovernanceService(
        storage=InMemorySkillGovernanceStorage(),
        version_storage=InMemorySkillVersionStorage(),
        loader=loader,
    )
    app.dependency_overrides[get_skill_governance_service] = lambda: service
    app.dependency_overrides[get_skill_evaluation_principal] = lambda: (
        SkillControlPrincipal(user_id="quality-user", roles=("quality",))
    )
    return TestClient(app)


def test_skill_eval_suite_can_be_created_populated_and_listed(
    client: TestClient,
) -> None:
    suite = client.post(
        f"{PREFIX}/infra-skills/eval-suites",
        json={
            "name": "费用解释路由回归",
            "scope": "skill",
            "skill_id": "settlement_explain_skill",
            "purpose": "验证费用解释问题路由",
        },
    )
    assert suite.status_code == 201
    suite_id = suite.json()["suite_id"]

    case = client.post(
        f"{PREFIX}/infra-skills/eval-cases",
        json={
            "suite_id": suite_id,
            "question_template": "为什么统筹自付这么多",
            "expected_skill_id": "settlement_explain_skill",
            "required": True,
            "risk_tags": ["settlement"],
            "business_tags": ["personal-liability"],
            "source_type": "manual",
            "source_ref": "flow-test",
            "contains_sensitive_data": False,
        },
    )
    assert case.status_code == 201

    listed = client.get(
        f"{PREFIX}/infra-skills/eval-cases",
        params={"suite_id": suite_id},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["question_template"] == "为什么统筹自付这么多"

    protected = client.delete(f"{PREFIX}/infra-skills/eval-suites/{suite_id}")
    assert protected.status_code == 409
    assert protected.json()["detail"]["error_code"] == "SKILL_RELEASE_GATE_FAILED"
