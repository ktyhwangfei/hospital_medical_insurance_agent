from src.data_platform.persistence.migrations import StatementSchemaMigrator
from src.data_platform.persistence.models import QueryResult, SqlStatement


class RecordingExecutor:
    def __init__(self):
        self.statements: list[SqlStatement] = []

    def execute(self, statement: SqlStatement) -> QueryResult:
        self.statements.append(statement)
        return QueryResult(rowcount=0)


def test_schema_migrator_executes_statements_in_order():
    executor = RecordingExecutor()
    migrator = StatementSchemaMigrator(executor, [SqlStatement(sql="create table a"), SqlStatement(sql="create index b")])

    migrator.bootstrap()

    assert [item.sql for item in executor.statements] == ["create table a", "create index b"]
