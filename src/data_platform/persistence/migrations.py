from src.data_platform.persistence.models import SqlStatement
from src.data_platform.persistence.ports import DatabaseExecutor


class StatementSchemaMigrator:
    def __init__(self, executor: DatabaseExecutor, statements: list[SqlStatement]):
        self._executor = executor
        self._statements = statements

    def bootstrap(self) -> None:
        for statement in self._statements:
            self._executor.execute(statement)
