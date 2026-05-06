from src.data_platform.persistence.models import DatabaseBackend, DatabaseHealth, DatabaseHealthStatus, QueryResult, SqlStatement


def test_sql_statement_preserves_text_and_params():
    statement = SqlStatement(sql="select * from mcp_servers where server_id = %s", params=("srv-1",))

    assert statement.sql == "select * from mcp_servers where server_id = %s"
    assert statement.params == ("srv-1",)


def test_query_result_defaults_to_empty_rows():
    result = QueryResult()

    assert result.rows == []
    assert result.rowcount == 0


def test_database_health_models_backend_and_status():
    health = DatabaseHealth(
        status=DatabaseHealthStatus.HEALTHY,
        backend=DatabaseBackend.POSTGRESQL,
        available=True,
        details={"schema": "ready"},
    )

    assert health.status == DatabaseHealthStatus.HEALTHY
    assert health.backend == DatabaseBackend.POSTGRESQL
    assert health.available is True
    assert health.details["schema"] == "ready"
