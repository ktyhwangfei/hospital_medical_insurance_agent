from __future__ import annotations

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
