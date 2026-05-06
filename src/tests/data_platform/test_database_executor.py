from src.data_platform.persistence.executors import UnavailableDatabaseExecutor
from src.data_platform.persistence.models import DatabaseBackend, DatabaseHealthStatus, SqlStatement


def test_unavailable_executor_reports_driver_not_installed():
    executor = UnavailableDatabaseExecutor(DatabaseBackend.POSTGRESQL, "driver_not_installed")

    health = executor.health()

    assert health.status == DatabaseHealthStatus.UNHEALTHY
    assert health.backend == DatabaseBackend.POSTGRESQL
    assert health.available is False
    assert health.details["reason"] == "driver_not_installed"


def test_unavailable_executor_raises_on_query():
    executor = UnavailableDatabaseExecutor(DatabaseBackend.POSTGRESQL, "driver_not_installed")

    try:
        executor.fetch_one(SqlStatement(sql="select 1"))
    except RuntimeError as exc:
        assert "driver_not_installed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
