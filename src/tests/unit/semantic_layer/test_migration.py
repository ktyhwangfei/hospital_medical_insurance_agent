"""Tests for semantic layer database migration."""
import pytest
from src.data_platform.persistence.semantic_migrations import SEMANTIC_LAYER_STATEMENTS


class TestSemanticMigration:
    """Verify migration DDL is well-formed and non-destructive."""

    def test_all_statements_use_if_not_exists(self):
        """All CREATE TABLE statements must use IF NOT EXISTS."""
        for stmt in SEMANTIC_LAYER_STATEMENTS:
            sql = stmt.sql.upper()
            assert "CREATE TABLE" in sql
            assert "IF NOT EXISTS" in sql, (
                f"Statement missing IF NOT EXISTS: {stmt.sql[:80]}..."
            )

    def test_all_tables_have_primary_keys(self):
        """Every table must have a primary key."""
        for stmt in SEMANTIC_LAYER_STATEMENTS:
            assert "PRIMARY KEY" in stmt.sql.upper(), (
                f"Statement missing PRIMARY KEY: {stmt.sql[:80]}..."
            )

    def test_exactly_five_tables_defined(self):
        """V1 should create exactly 5 tables."""
        table_names = []
        for stmt in SEMANTIC_LAYER_STATEMENTS:
            # Extract table name: CREATE TABLE IF NOT EXISTS <name> (
            sql = stmt.sql
            exists_pos = sql.upper().index("EXISTS") + 6
            paren_pos = sql.index("(", exists_pos)
            table_name = sql[exists_pos:paren_pos].strip().strip('"').strip("'")
            table_names.append(table_name)
        assert len(table_names) == 5, f"Expected 5 tables, got {len(table_names)}: {table_names}"
        assert "business_domain" in table_names
        assert "business_object" in table_names
        assert "metric" in table_names
        assert "value_domain" in table_names
        assert "value_domain_mapping" in table_names

    def test_metric_has_usage_count_and_quality_score(self):
        """Metric table must include data value exploration fields."""
        metric_ddl = next(
            s.sql for s in SEMANTIC_LAYER_STATEMENTS
            if "metric" in s.sql.lower().split("(")[0]
        )
        assert "usage_count" in metric_ddl.lower()
        assert "quality_score" in metric_ddl.lower()

    def test_object_has_relations_jsonb(self):
        """Object table must have relations JSONB field."""
        object_ddl = next(
            s.sql for s in SEMANTIC_LAYER_STATEMENTS
            if "business_object" in s.sql.lower().split("(")[0]
        )
        assert "relations" in object_ddl.lower()
        assert "jsonb" in object_ddl.lower()
