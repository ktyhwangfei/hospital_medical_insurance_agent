from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore


class SummaryClient:
    def execute(self, sql: str, _params=()):
        normalized = " ".join(sql.lower().split())
        if "from policy_documents" in normalized:
            return [{"cnt": 2, "raw_cnt": 1}]
        if "from policy_extractions" in normalized:
            return [{
                "cnt": 11,
                "draft_cnt": 2,
                "reviewed_cnt": 4,
                "published_cnt": 5,
            }]
        raise AssertionError(f"unexpected query: {normalized}")


def test_pipeline_summary_counts_real_units(monkeypatch) -> None:
    store = PipelineStore("postgresql://unused")
    store._client = SummaryClient()
    monkeypatch.setattr(store, "list_documents", lambda **_: {
        "items": [
            {"unit_total": 5, "unit_audited": 3, "pending_count": 2},
            {"unit_total": 4, "unit_audited": 4, "pending_count": 0},
        ],
        "total": 2,
    })

    assert store.get_summary() == {
        "documents_count": 2,
        "documents_raw": 1,
        "extractions_count": 11,
        "extractions_draft": 2,
        "extractions_reviewed": 4,
        "extractions_published": 5,
        "units_count": 9,
        "units_audited": 7,
        "units_pending": 2,
    }
