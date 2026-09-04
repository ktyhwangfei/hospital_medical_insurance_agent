"""质量运行孤儿回收测试：后端崩溃残留 running run + testing release 必须可自动回收重试。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.knowledge_extension.rule_explanation.quality_store import (
    InMemoryPolicyQualityStore,
)
from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    QualityRun,
)


def _store_with_stale_run() -> InMemoryPolicyQualityStore:
    store = InMemoryPolicyQualityStore()
    store.save_release(KnowledgeRelease(
        release_id="REL_X", facts_collection="f", rules_collection="r",
        contract_version="1.0", case_set_version=1, config_hash="h",
        status="testing", quality_run_id="run_stale",
    ))
    store.save_run(QualityRun(
        run_id="run_stale", release_id="REL_X", baseline_release_id=None,
        case_set_version=1, config_hash="h", repeat_count=3,
        status="running", created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    ))
    return store


def test_reclaim_stale_running_run_frees_release():
    store = _store_with_stale_run()
    reclaimed = store.reclaim_stale_runs("REL_X", stale_after_seconds=1800)
    assert reclaimed == 1
    rel = store.get_release("REL_X")
    assert rel.status == "failed"
    assert rel.quality_run_id is None


def test_fresh_running_run_not_reclaimed():
    store = _store_with_stale_run()
    # 把 run 时间改成刚刚
    store.runs["run_stale"] = store.runs["run_stale"].model_copy(
        update={"created_at": datetime.now(timezone.utc)}
    )
    assert store.reclaim_stale_runs("REL_X", stale_after_seconds=1800) == 0
    assert store.get_release("REL_X").status == "testing"
