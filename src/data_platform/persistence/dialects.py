import json
from typing import Any


class PostgresDialect:
    name = "postgresql"

    def placeholder(self, position: int) -> str:
        return "%s"

    def json_dump(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def json_load(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return json.loads(value)

    def upsert_sql(
        self,
        table: str,
        key_columns: tuple[str, ...],
        insert_columns: tuple[str, ...],
        update_columns: tuple[str, ...],
    ) -> str:
        columns = ", ".join(insert_columns)
        placeholders = ", ".join(self.placeholder(index + 1) for index, _ in enumerate(insert_columns))
        conflict_columns = ", ".join(key_columns)
        assignments = ", ".join(f"{column} = excluded.{column}" for column in update_columns)
        return f"insert into {table} ({columns}) values ({placeholders}) on conflict ({conflict_columns}) do update set {assignments}"


class KingbaseDialect(PostgresDialect):
    name = "kingbase"
