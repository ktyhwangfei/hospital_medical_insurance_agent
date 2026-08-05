from __future__ import annotations

import re

import pytest


QUALITY_CONFIG_HASH = "197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22"


def _release(release_id: str, status: str = "ready"):
    from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease

    return KnowledgeRelease(
        release_id=release_id,
        status=status,
        facts_collection=f"policy_facts_{release_id}",
        rules_collection=f"policy_rules_{release_id}",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    )


def _release_with_source(
    release_id: str,
    source_change_set_id: str,
    status: str = "ready",
):
    from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease

    return KnowledgeRelease(
        release_id=release_id,
        status=status,
        facts_collection=f"policy_facts_{release_id}",
        rules_collection=f"policy_rules_{release_id}",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
        source_change_set_id=source_change_set_id,
    )


class _FakePolicyQualityClient:
    """仅替代 PostgreSQL I/O，保留 release UPSERT 的真实字段语义。"""

    def __init__(self) -> None:
        self.releases: dict[str, dict] = {}

    def execute(self, sql: str, params=None):
        normalized = " ".join(sql.split())
        upper = normalized.upper()
        if upper.startswith("INSERT INTO POLICY_KNOWLEDGE_RELEASES"):
            assert params is not None
            columns_text = normalized.split("(", 1)[1].split(")", 1)[0]
            columns = [column.strip() for column in columns_text.split(",")]
            inserted = dict(zip(columns, params, strict=True))
            release_id = inserted["release_id"]
            existing = self.releases.get(release_id)
            if existing is not None and "DO NOTHING" in upper:
                return []
            if existing is None:
                self.releases[release_id] = inserted
            else:
                update_clause = normalized.split("DO UPDATE SET", 1)[1]
                update_clause = update_clause.split("RETURNING", 1)[0]
                for field in re.findall(r"(\w+)=EXCLUDED\.\w+", update_clause):
                    existing[field] = inserted[field]
            if "RETURNING *" in upper:
                return [self.releases[release_id].copy()]
            return []
        if upper.startswith("SELECT * FROM POLICY_KNOWLEDGE_RELEASES WHERE"):
            assert params is not None
            row = self.releases.get(params[0])
            return [row.copy()] if row else []
        if upper.startswith("SELECT * FROM POLICY_KNOWLEDGE_RELEASES ORDER BY"):
            return [row.copy() for row in reversed(self.releases.values())]
        raise AssertionError(f"未支持的 SQL: {normalized}")


def _postgres_store(client: _FakePolicyQualityClient):
    from src.data_platform.storage.postgresql.policy_quality_store import (
        PostgresPolicyQualityStore,
    )

    store = PostgresPolicyQualityStore("postgresql://test")
    store._client = client
    return store


def _save_passed_run(
    store, release_id: str, case_set_version: int = 1,
    baseline_release_id: str | None = None,
) -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun

    store.save_run(QualityRun(
        run_id=f"run_{release_id}",
        release_id=release_id,
        baseline_release_id=baseline_release_id,
        case_set_version=case_set_version,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))


def test_case_changes_create_new_case_set_version() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import PolicyQATestCase
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    first = store.save_test_case(PolicyQATestCase(
        case_id="case_1",
        name="职工住院支付比例",
        query="职工住院报销比例是多少",
        mode="semantic",
        expected_knowledge_ids=["kn_1"],
        required=True,
    ))
    updated = first.model_copy(update={"query": "在职职工住院支付比例"})
    second = store.save_test_case(updated)

    assert first.case_set_version == 1
    assert second.case_set_version == 2
    assert store.current_case_set_version() == 2


def test_ready_release_identity_is_immutable() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_release(_release("rel_1"))

    with pytest.raises(ValueError, match="不可修改"):
        store.save_release(_release("rel_1").model_copy(update={"contract_version": "3"}))


def test_release_without_source_lineage_roundtrips_in_memory() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    created = store.create_release(_release("legacy"))
    saved = store.save_release(created.model_copy(update={"status": "testing"}))

    assert created.source_change_set_id is None
    assert saved.source_change_set_id is None
    assert store.get_release("legacy").source_change_set_id is None  # type: ignore[union-attr]
    assert store.list_releases()[0].source_change_set_id is None


def test_release_source_lineage_roundtrips_in_memory() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    created = store.create_release(_release_with_source("candidate", "change_set_1"))
    saved = store.save_release(created.model_copy(update={"status": "testing"}))

    assert created.source_change_set_id == "change_set_1"
    assert saved.source_change_set_id == "change_set_1"
    assert store.get_release("candidate").source_change_set_id == "change_set_1"  # type: ignore[union-attr]
    assert store.list_releases()[0].source_change_set_id == "change_set_1"


def test_release_source_lineage_is_immutable_in_memory() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.create_release(_release_with_source("candidate", "change_set_1"))

    with pytest.raises(ValueError, match="不可修改"):
        store.save_release(_release_with_source("candidate", "change_set_2"))

    assert store.get_release("candidate").source_change_set_id == "change_set_1"  # type: ignore[union-attr]


def test_policy_quality_schema_migrates_release_source_lineage() -> None:
    from src.data_platform.storage.postgresql.policy_quality_store import QUALITY_SCHEMA

    ddl = " ".join(QUALITY_SCHEMA.upper().split())

    assert "SOURCE_CHANGE_SET_ID VARCHAR(64)" in ddl
    assert (
        "ALTER TABLE POLICY_KNOWLEDGE_RELEASES ADD COLUMN IF NOT EXISTS "
        "SOURCE_CHANGE_SET_ID VARCHAR(64)"
    ) in ddl


def test_release_without_source_lineage_roundtrips_in_postgres_store() -> None:
    client = _FakePolicyQualityClient()
    store = _postgres_store(client)
    legacy = _release("legacy")
    client.releases[legacy.release_id] = legacy.model_dump(
        exclude={"source_change_set_id"}
    )

    loaded = store.get_release("legacy")
    saved = store.save_release(legacy.model_copy(update={"status": "testing"}))

    assert loaded is not None and loaded.source_change_set_id is None
    assert saved.source_change_set_id is None
    assert store.list_releases()[0].source_change_set_id is None


def test_release_source_lineage_roundtrips_in_postgres_store() -> None:
    client = _FakePolicyQualityClient()
    store = _postgres_store(client)
    release = _release_with_source("candidate", "change_set_1")

    created = store.create_release(release)
    loaded = store.get_release("candidate")
    saved = store.save_release(release.model_copy(update={"status": "testing"}))

    assert created.source_change_set_id == "change_set_1"
    assert loaded is not None and loaded.source_change_set_id == "change_set_1"
    assert saved.source_change_set_id == "change_set_1"
    assert store.list_releases()[0].source_change_set_id == "change_set_1"


def test_release_source_lineage_is_immutable_in_postgres_store() -> None:
    client = _FakePolicyQualityClient()
    store = _postgres_store(client)
    store.create_release(_release_with_source("candidate", "change_set_1"))

    saved = store.save_release(_release_with_source("candidate", "change_set_2"))

    assert saved.source_change_set_id == "change_set_1"
    assert store.get_release("candidate").source_change_set_id == "change_set_1"  # type: ignore[union-attr]


def test_candidate_and_baseline_results_are_stored_separately() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityCaseResult
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_case_results([
        QualityCaseResult(
            run_id="run_1",
            target="candidate",
            case_id="case_1",
            repeat_index=0,
            result_knowledge_ids=["kn_new"],
            score=1,
            passed=True,
        ),
        QualityCaseResult(
            run_id="run_1",
            target="baseline",
            case_id="case_1",
            repeat_index=0,
            result_knowledge_ids=["kn_old"],
            score=0,
            passed=False,
        ),
    ])

    assert {(result.target, result.result_knowledge_ids[0]) for result in store.case_results} == {
        ("candidate", "kn_new"),
        ("baseline", "kn_old"),
    }


def test_latest_run_is_queryable_by_release() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_run(QualityRun(run_id="run_1", release_id="candidate", case_set_version=1, config_hash="cfg"))
    store.save_run(QualityRun(run_id="run_2", release_id="candidate", case_set_version=2, config_hash="cfg"))

    assert store.get_latest_run("candidate").run_id == "run_2"  # type: ignore[union-attr]


def test_only_passed_release_can_be_promoted_atomically() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store._case_set_version = 1
    store.save_release(_release("rel_old", status="passed"))
    _save_passed_run(store, "rel_old")
    store.promote_release("rel_old", promoted_by="reviewer")
    store.save_release(_release("rel_failed", status="failed"))

    with pytest.raises(ValueError, match="未通过质量门禁"):
        store.promote_release("rel_failed", promoted_by="reviewer")

    assert store.get_active_release().release_id == "rel_old"  # type: ignore[union-attr]
    assert store.get_release("rel_old").status == "active"  # type: ignore[union-attr]


def test_promotion_switches_one_pointer_and_rollback_restores_previous_release() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store._case_set_version = 1
    store.save_release(_release("rel_1", status="passed"))
    _save_passed_run(store, "rel_1")
    store.promote_release("rel_1", promoted_by="reviewer")
    store.save_release(_release("rel_2", status="passed"))
    _save_passed_run(store, "rel_2", baseline_release_id="rel_1")

    promoted = store.promote_release("rel_2", promoted_by="reviewer")

    assert promoted.release_id == "rel_2"
    assert store.get_active_release().release_id == "rel_2"  # type: ignore[union-attr]
    assert store.get_release("rel_1").status == "retired"  # type: ignore[union-attr]

    rolled_back = store.rollback_release("rel_1", promoted_by="reviewer")

    assert rolled_back.release_id == "rel_1"
    assert store.get_active_release().release_id == "rel_1"  # type: ignore[union-attr]
    assert store.get_release("rel_2").status == "retired"  # type: ignore[union-attr]


@pytest.mark.parametrize("status", ["ready", "testing", "passed"])
def test_rollback_rejects_release_that_was_never_active(status: str) -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_release(_release("candidate", status=status))

    with pytest.raises(ValueError, match="不可回滚"):
        store.rollback_release("candidate", promoted_by="reviewer")


def test_promotion_rejects_run_compared_to_stale_active_release() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store._case_set_version = 1
    store.save_release(_release("current", status="active"))
    store.active_release_id = "current"
    store.save_release(_release("candidate", status="passed"))
    store.save_run(QualityRun(
        run_id="run_candidate", release_id="candidate", baseline_release_id="previous",
        case_set_version=1, config_hash=QUALITY_CONFIG_HASH, status="passed",
    ))

    with pytest.raises(ValueError, match="活动基线"):
        store.promote_release("candidate", promoted_by="reviewer")


def test_create_release_is_atomic_and_preserves_existing_identity() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    original = store.create_release(_release("candidate"))

    with pytest.raises(ValueError, match="已存在"):
        store.create_release(_release("candidate").model_copy(update={"contract_version": "3"}))

    assert store.get_release("candidate") == original


def test_promotion_rejects_passed_run_after_case_set_changes() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import PolicyQATestCase
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_test_case(PolicyQATestCase(
        case_id="case_1", name="原用例", query="原用例", mode="semantic"
    ))
    store.save_release(_release("candidate", status="passed"))
    _save_passed_run(store, "candidate")
    store.save_test_case(PolicyQATestCase(
        case_id="case_2", name="新增用例", query="新增用例", mode="semantic"
    ))

    with pytest.raises(ValueError, match="最新用例集"):
        store.promote_release("candidate", promoted_by="reviewer")


def test_promotion_rejects_passed_run_with_different_config_hash() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store._case_set_version = 1
    store.save_release(_release("candidate", status="passed"))
    store.save_run(QualityRun(
        run_id="run_candidate",
        release_id="candidate",
        case_set_version=1,
        config_hash="forged",
        status="passed",
    ))

    with pytest.raises(ValueError, match="测试配置"):
        store.promote_release("candidate", promoted_by="reviewer")
