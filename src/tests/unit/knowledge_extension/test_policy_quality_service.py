from __future__ import annotations

from collections import defaultdict

import pytest

from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    PolicyQATestCase,
    QualityRun,
)
from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore


QUALITY_CONFIG_HASH = "197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22"


class SequenceSearcher:
    def __init__(self, results: dict[str, list[list[str]]]) -> None:
        self.results = results
        self.calls: dict[str, int] = defaultdict(int)

    def search(self, release: KnowledgeRelease, case: PolicyQATestCase) -> list[str]:
        index = self.calls[release.release_id]
        self.calls[release.release_id] += 1
        sequence = self.results[release.release_id]
        return sequence[index % len(sequence)]


def _store_with_case_and_baseline(
    store: InMemoryPolicyQualityStore | None = None,
) -> InMemoryPolicyQualityStore:
    store = store or InMemoryPolicyQualityStore()
    store.save_test_case(PolicyQATestCase(
        case_id="case_1",
        name="职工住院支付比例",
        query="职工住院支付比例",
        mode="semantic",
        expected_knowledge_ids=["kn_expected"],
        required=True,
    ))
    store.save_release(KnowledgeRelease(
        release_id="baseline",
        status="passed",
        facts_collection="policy_facts_baseline",
        rules_collection="policy_rules_baseline",
        contract_version="1",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    store.save_run(QualityRun(
        run_id="run_baseline",
        release_id="baseline",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))
    store.promote_release("baseline", "reviewer")
    store.save_release(KnowledgeRelease(
        release_id="candidate",
        status="ready",
        facts_collection="policy_facts_candidate",
        rules_collection="policy_rules_candidate",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    return store


def test_equal_quality_to_baseline_is_blocked() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    store = _store_with_case_and_baseline()
    searcher = SequenceSearcher({
        "baseline": [["kn_expected"]],
        "candidate": [["kn_expected"]],
    })

    run = PolicyQualityService(store, searcher).run_release("candidate", repeat_count=3)

    assert run.status == "failed"
    assert "候选质量必须严格高于当前版本" in run.blocked_reasons
    assert store.get_release("candidate").status == "failed"  # type: ignore[union-attr]
    assert store.get_active_release().release_id == "baseline"  # type: ignore[union-attr]


def test_unstable_repeated_results_block_release() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    store = _store_with_case_and_baseline()
    searcher = SequenceSearcher({
        "baseline": [[]],
        "candidate": [["kn_expected"], ["kn_other"], ["kn_expected"]],
    })

    run = PolicyQualityService(store, searcher).run_release(
        "candidate", repeat_count=3, minimum_consistency=0.9,
    )

    assert run.status == "failed"
    assert run.consistency_score < 0.9  # type: ignore[operator]
    assert "重复运行一致性低于门槛" in run.blocked_reasons


def test_strictly_better_stable_candidate_passes_gate() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    store = _store_with_case_and_baseline()
    searcher = SequenceSearcher({
        "baseline": [[]],
        "candidate": [["kn_expected"]],
    })

    run = PolicyQualityService(store, searcher).run_release("candidate", repeat_count=3)

    assert run.status == "passed"
    assert run.candidate_score == 1.0
    assert run.baseline_score == 0.0
    assert run.consistency_score == 1.0
    assert store.get_release("candidate").status == "passed"  # type: ignore[union-attr]
    assert store.get_active_release().release_id == "baseline"  # type: ignore[union-attr]


def test_required_case_failure_blocks_even_when_average_threshold_is_low() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import (
        PolicyQualityService,
        quality_config_hash,
    )

    store = _store_with_case_and_baseline()
    candidate = store.get_release("candidate")
    assert candidate is not None
    store.releases["candidate"] = candidate.model_copy(update={
        "config_hash": quality_config_hash(3, 0.0, 0.9)
    })
    searcher = SequenceSearcher({"baseline": [[]], "candidate": [["kn_other"]]})

    run = PolicyQualityService(store, searcher).run_release(
        "candidate", repeat_count=3, minimum_quality=0.0,
    )

    assert run.status == "failed"
    assert "必测用例未全部通过" in run.blocked_reasons


def test_without_baseline_candidate_uses_absolute_threshold() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    store = InMemoryPolicyQualityStore()
    store.save_test_case(PolicyQATestCase(
        case_id="case_1",
        name="首版必测",
        query="首版必测",
        mode="semantic",
        expected_knowledge_ids=["kn_expected"],
    ))
    store.save_release(KnowledgeRelease(
        release_id="candidate",
        status="ready",
        facts_collection="policy_facts_candidate",
        rules_collection="policy_rules_candidate",
        contract_version="1",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))

    run = PolicyQualityService(
        store, SequenceSearcher({"candidate": [["kn_expected"]]})
    ).run_release("candidate", repeat_count=3)

    assert run.status == "passed"
    assert run.baseline_score is None


def test_run_rejects_release_config_that_does_not_match_runtime_configuration() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    store = _store_with_case_and_baseline()
    candidate = store.get_release("candidate")
    assert candidate is not None
    store.releases["candidate"] = candidate.model_copy(update={"config_hash": "forged"})

    with pytest.raises(ValueError, match="测试配置.*不一致"):
        PolicyQualityService(
            store,
            SequenceSearcher({"baseline": [[]], "candidate": [["kn_expected"]]}),
        ).run_release("candidate", repeat_count=3)


def test_comparison_retests_stale_baseline_with_current_candidate_case_set() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    store = _store_with_case_and_baseline()
    baseline = store.get_release("baseline")
    assert baseline is not None
    store.releases["baseline"] = baseline.model_copy(update={"case_set_version": 0})
    store.save_test_case(PolicyQATestCase(
        case_id="case_2",
        name="新增当前用例",
        query="新增当前用例",
        mode="semantic",
        expected_knowledge_ids=["kn_expected"],
    ))
    candidate = store.get_release("candidate")
    assert candidate is not None
    store.releases["candidate"] = candidate.model_copy(
        update={"case_set_version": store.current_case_set_version()}
    )

    run = PolicyQualityService(
        store,
        SequenceSearcher({"baseline": [[]], "candidate": [["kn_expected"]]}),
    ).run_release("candidate", repeat_count=3)

    assert run.case_set_version == store.current_case_set_version()


def test_run_rejects_candidate_from_an_older_case_set() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    store = _store_with_case_and_baseline()
    store.save_test_case(PolicyQATestCase(
        case_id="case_2",
        name="新增当前用例",
        query="新增当前用例",
        mode="semantic",
        expected_knowledge_ids=["kn_expected"],
    ))

    with pytest.raises(ValueError, match="候选版本.*用例集"):
        PolicyQualityService(
            store,
            SequenceSearcher({"baseline": [[]], "candidate": [["kn_expected"]]}),
        ).run_release("candidate", repeat_count=3)


def test_score_rewards_expected_order_and_penalizes_swapped_ids() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import _score_result

    exact, _, exact_diagnostics = _score_result(["kn_a", "kn_b"], ["kn_a", "kn_b"])
    swapped, _, swapped_diagnostics = _score_result(["kn_b", "kn_a"], ["kn_a", "kn_b"])

    assert exact == 1.0
    assert swapped < exact
    assert swapped_diagnostics["rank_score"] < exact_diagnostics["rank_score"]


def test_repeat_consistency_is_order_sensitive() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityCaseResult
    from src.knowledge_extension.rule_explanation.quality_service import _repeat_consistency

    results = [
        QualityCaseResult(run_id="run", target="candidate", case_id="case", repeat_index=0, result_knowledge_ids=["kn_a", "kn_b"], score=1, passed=True),
        QualityCaseResult(run_id="run", target="candidate", case_id="case", repeat_index=1, result_knowledge_ids=["kn_b", "kn_a"], score=0.5, passed=True),
    ]

    assert _repeat_consistency(results) < 1.0


def test_repeat_count_cannot_be_less_than_three() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    with pytest.raises(ValueError, match="至少重复运行 3 次"):
        PolicyQualityService(
            _store_with_case_and_baseline(),
            SequenceSearcher({"baseline": [[]], "candidate": [[]]}),
        ).run_release("candidate", repeat_count=2)


def test_search_failure_records_failed_run_and_restores_ready_release() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    class FailingSearcher:
        def search(self, release, case):
            raise RuntimeError("backend unavailable")

    store = _store_with_case_and_baseline()

    with pytest.raises(RuntimeError, match="backend unavailable"):
        PolicyQualityService(store, FailingSearcher()).run_release("candidate")

    run = store.get_latest_run("candidate")
    assert run is not None
    assert run.status == "failed"
    assert run.blocked_reasons == ["质量运行异常: RuntimeError"]
    assert store.get_release("candidate").status == "ready"  # type: ignore[union-attr]


def test_initial_testing_state_failure_marks_persisted_run_failed_and_restores_ready() -> None:
    from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService

    class FailingTestingStore(InMemoryPolicyQualityStore):
        failed_once = False

        def save_release(self, release):
            if release.status == "testing" and not self.failed_once:
                self.failed_once = True
                raise RuntimeError("testing state unavailable")
            return super().save_release(release)

    store = _store_with_case_and_baseline(FailingTestingStore())

    with pytest.raises(RuntimeError, match="testing state unavailable"):
        PolicyQualityService(
            store,
            SequenceSearcher({"baseline": [[]], "candidate": [["kn_expected"]]}),
        ).run_release("candidate")

    run = store.get_latest_run("candidate")
    assert run is not None
    assert run.status == "failed"
    assert run.blocked_reasons == ["质量运行异常: RuntimeError"]
    assert store.get_release("candidate").status == "ready"  # type: ignore[union-attr]
