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
