import pytest

from src.data_platform.persistence.dialects import KingbaseDialect, PostgresDialect


def test_postgres_dialect_generates_psycopg_placeholders_and_upsert():
    dialect = PostgresDialect()

    assert dialect.placeholder(1) == "%s"
    sql = dialect.upsert_sql(
        table="mcp_servers",
        key_columns=("server_id",),
        insert_columns=("server_id", "payload_json", "status"),
        update_columns=("payload_json", "status"),
    )

    assert "insert into mcp_servers" in sql
    assert "on conflict (server_id) do update" in sql
    assert "payload_json = excluded.payload_json" in sql


def test_kingbase_dialect_keeps_postgres_compatible_boundary():
    dialect = KingbaseDialect()

    assert dialect.placeholder(1) == "%s"
    assert dialect.name == "kingbase"
    assert dialect.json_load(dialect.json_dump({"a": 1})) == {"a": 1}
    sql = dialect.upsert_sql(
        table="mcp_servers",
        key_columns=("server_id",),
        insert_columns=("server_id", "payload_json"),
        update_columns=("payload_json",),
    )

    assert sql == (
        "insert into mcp_servers (server_id, payload_json) values (%s, %s) "
        "on conflict (server_id) do update set payload_json = excluded.payload_json"
    )


@pytest.mark.parametrize(
    ("table", "key_columns", "insert_columns", "update_columns"),
    [
        ("", ("server_id",), ("server_id", "payload_json"), ("payload_json",)),
        ("mcp-servers", ("server_id",), ("server_id", "payload_json"), ("payload_json",)),
        ("1mcp_servers", ("server_id",), ("server_id", "payload_json"), ("payload_json",)),
        ("mcp_servers", ("server-id",), ("server_id", "payload_json"), ("payload_json",)),
        ("mcp_servers", ("server_id",), ("server_id", "payload-json"), ("payload_json",)),
        ("mcp_servers", ("server_id",), ("server_id", "payload_json"), ("payload-json",)),
    ],
)
def test_postgres_upsert_rejects_invalid_table_and_column_identifiers(
    table: str,
    key_columns: tuple[str, ...],
    insert_columns: tuple[str, ...],
    update_columns: tuple[str, ...],
):
    dialect = PostgresDialect()

    with pytest.raises(ValueError):
        dialect.upsert_sql(
            table=table,
            key_columns=key_columns,
            insert_columns=insert_columns,
            update_columns=update_columns,
        )


@pytest.mark.parametrize(
    ("key_columns", "insert_columns", "update_columns"),
    [
        ((), ("server_id", "payload_json"), ("payload_json",)),
        (("server_id",), (), ("payload_json",)),
        (("server_id",), ("server_id", "payload_json"), ()),
    ],
)
def test_postgres_upsert_rejects_empty_column_sets(
    key_columns: tuple[str, ...],
    insert_columns: tuple[str, ...],
    update_columns: tuple[str, ...],
):
    dialect = PostgresDialect()

    with pytest.raises(ValueError):
        dialect.upsert_sql(
            table="mcp_servers",
            key_columns=key_columns,
            insert_columns=insert_columns,
            update_columns=update_columns,
        )


def test_postgres_upsert_rejects_update_columns_missing_from_insert_columns():
    dialect = PostgresDialect()

    with pytest.raises(ValueError, match="update_columns"):
        dialect.upsert_sql(
            table="mcp_servers",
            key_columns=("server_id",),
            insert_columns=("server_id", "payload_json"),
            update_columns=("payload_json", "status"),
        )


def test_postgres_upsert_rejects_key_columns_missing_from_insert_columns():
    dialect = PostgresDialect()

    with pytest.raises(ValueError, match="key_columns"):
        dialect.upsert_sql(
            table="mcp_servers",
            key_columns=("server_id",),
            insert_columns=("payload_json", "status"),
            update_columns=("payload_json",),
        )


@pytest.mark.parametrize("value", ['["a"]', '"a"', "1", "true"])
def test_json_load_rejects_non_object_json(value: str):
    dialect = PostgresDialect()

    with pytest.raises(ValueError, match="object"):
        dialect.json_load(value)


def test_json_load_rejects_invalid_json():
    dialect = PostgresDialect()

    with pytest.raises(ValueError, match="valid JSON"):
        dialect.json_load("{")


def test_json_load_returns_empty_dict_for_none():
    dialect = PostgresDialect()

    assert dialect.json_load(None) == {}


def test_json_load_returns_dict_values_unchanged():
    dialect = PostgresDialect()
    payload = {"a": 1}

    assert dialect.json_load(payload) is payload
