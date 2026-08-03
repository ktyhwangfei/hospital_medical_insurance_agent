def test_policy_quality_schema_contains_atomic_release_pointer() -> None:
    from src.data_platform.storage.postgresql.policy_quality_store import QUALITY_SCHEMA

    ddl = QUALITY_SCHEMA.upper()
    assert "POLICY_QA_TEST_CASES" in ddl
    assert "POLICY_KNOWLEDGE_RELEASES" in ddl
    assert "POLICY_QUALITY_RUNS" in ddl
    assert "POLICY_QUALITY_CASE_RESULTS" in ddl
    assert "POLICY_ACTIVE_RELEASE" in ddl
    assert "SINGLETON_ID BOOLEAN PRIMARY KEY" in ddl
    assert "CHECK (SINGLETON_ID)" in ddl
    assert "TARGET VARCHAR(16)" in ddl
    assert "PRIMARY KEY (RUN_ID, TARGET, CASE_ID, REPEAT_INDEX)" in ddl
