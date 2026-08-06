from fastapi.testclient import TestClient

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.version_in_memory import InMemorySkillVersionStorage
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import get_skill_version_service
from src.runtime.skill_management.version_service import SkillVersionService
from src.skill_infra.skill_loader import get_loader


PREFIX = "/api/v1/medical-insurance-ai-agent"


def test_catalog_to_version_evidence_flow() -> None:
    app = create_app()
    service = SkillVersionService(
        storage=InMemorySkillVersionStorage(),
        loader=get_loader(),
        skills_root=SKILLS_DIR,
        source_commit_resolver=lambda: "abc1234",
    )
    app.dependency_overrides[get_skill_version_service] = lambda: service
    client = TestClient(app)

    initial_catalog = client.get(f"{PREFIX}/infra-skills/catalog")
    assert initial_catalog.status_code == 200
    initial_item = initial_catalog.json()["items"][0]
    assert initial_item["artifact_status"] == "unregistered"

    synced = client.post(
        f"{PREFIX}/infra-skills/{initial_item['skill_id']}/versions/sync",
        json={"created_by": "flow-test"},
    )
    assert synced.status_code == 201

    versions = client.get(
        f"{PREFIX}/infra-skills/{initial_item['skill_id']}/versions"
    )
    updated_catalog = client.get(f"{PREFIX}/infra-skills/catalog")

    assert versions.status_code == 200
    assert versions.json()[0]["version_id"] == synced.json()["version_id"]
    assert updated_catalog.status_code == 200
    updated_item = updated_catalog.json()["items"][0]
    assert updated_item["artifact_status"] == "registered"
    assert updated_item["registered_version"]["source_commit"] == "abc1234"
