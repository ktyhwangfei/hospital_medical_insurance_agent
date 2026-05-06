from src.data_platform.persistence.migrations import StatementSchemaMigrator
from src.data_platform.persistence.models import QueryResult, SqlStatement


class RecordingExecutor:
    def __init__(self):
        self.statements: list[SqlStatement] = []

    def execute(self, statement: SqlStatement) -> QueryResult:
        self.statements.append(statement)
        return QueryResult(rowcount=0)


class FailingExecutor:
    def __init__(self, fail_on_sql: str):
        self.fail_on_sql = fail_on_sql
        self.statements: list[SqlStatement] = []

    def execute(self, statement: SqlStatement) -> QueryResult:
        self.statements.append(statement)
        if statement.sql == self.fail_on_sql:
            raise RuntimeError("migration_statement_failed")
        return QueryResult(rowcount=0)


def test_schema_migrator_executes_statements_in_order():
    executor = RecordingExecutor()
    migrator = StatementSchemaMigrator(executor, [SqlStatement(sql="create table a"), SqlStatement(sql="create index b")])

    migrator.bootstrap()

    assert [item.sql for item in executor.statements] == ["create table a", "create index b"]


def test_schema_migrator_stops_after_statement_failure():
    executor = FailingExecutor("create index b")
    migrator = StatementSchemaMigrator(executor, [SqlStatement(sql="create table a"), SqlStatement(sql="create index b"), SqlStatement(sql="create table c")])

    try:
        migrator.bootstrap()
    except RuntimeError as exc:
        assert str(exc) == "migration_statement_failed"
    else:
        raise AssertionError("expected RuntimeError")

    assert [item.sql for item in executor.statements] == ["create table a", "create index b"]
