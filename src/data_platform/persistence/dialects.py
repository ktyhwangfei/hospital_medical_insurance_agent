import json
import re
from typing import Any


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(identifier: str, field_name: str) -> None:
    if not isinstance(identifier, str) or not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"{field_name} must be a valid SQL identifier")


def validate_columns(columns: tuple[str, ...], field_name: str) -> None:
    if not columns:
        raise ValueError(f"{field_name} must not be empty")
    for column in columns:
        validate_identifier(column, field_name)


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
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("value must be valid JSON") from exc
        if not isinstance(loaded, dict):
            raise ValueError("JSON value must be an object")
        return loaded

    def upsert_sql(
        self,
        table: str,
        key_columns: tuple[str, ...],
        insert_columns: tuple[str, ...],
        update_columns: tuple[str, ...],
    ) -> str:
        validate_identifier(table, "table")
        validate_columns(key_columns, "key_columns")
        validate_columns(insert_columns, "insert_columns")
        validate_columns(update_columns, "update_columns")
        insert_column_set = set(insert_columns)
        missing_key_columns = set(key_columns) - insert_column_set
        if missing_key_columns:
            raise ValueError("key_columns must be included in insert_columns")
        missing_update_columns = set(update_columns) - insert_column_set
        if missing_update_columns:
            raise ValueError("update_columns must be included in insert_columns")
        columns = ", ".join(insert_columns)
        placeholders = ", ".join(self.placeholder(index + 1) for index, _ in enumerate(insert_columns))
        conflict_columns = ", ".join(key_columns)
        assignments = ", ".join(f"{column} = excluded.{column}" for column in update_columns)
        return f"insert into {table} ({columns}) values ({placeholders}) on conflict ({conflict_columns}) do update set {assignments}"


class KingbaseDialect(PostgresDialect):
    name = "kingbase"
