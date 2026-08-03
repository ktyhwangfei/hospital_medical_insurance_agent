import re

import pytest
from src.data_platform.persistence.models import SqlStatement
from src.data_platform.persistence.semantic_migrations import SEMANTIC_LAYER_STATEMENTS

_TABLE_PATTERN = re.compile(r"EXISTS\s+(\S+)")


def _extract_table_name(sql: str) -> str | None:
    """Extract table name from a CREATE TABLE IF NOT EXISTS statement."""
    match = _TABLE_PATTERN.search(sql)
    return match.group(1).strip().strip('"').strip("'") if match else None


def _get_ddl_by_table(table: str) -> str:
    """Get the DDL for the given table name."""
    return next(
        s.sql for s in SEMANTIC_LAYER_STATEMENTS if _extract_table_name(s.sql) == table
    )


class TestSemanticMigration:
    def test_all_statements_use_if_not_exists(self):
        for stmt in SEMANTIC_LAYER_STATEMENTS:
            sql = stmt.sql.upper()
            assert "CREATE TABLE" in sql
            assert "IF NOT EXISTS" in sql

    def test_all_tables_have_primary_keys(self):
        for stmt in SEMANTIC_LAYER_STATEMENTS:
            assert "PRIMARY KEY" in stmt.sql.upper()

    def test_semantic_alignment_tables_are_defined(self):
        table_names: list[str] = []
        for stmt in SEMANTIC_LAYER_STATEMENTS:
            name = _extract_table_name(stmt.sql)
            assert name is not None, f"Could not extract table name from: {stmt.sql}"
            table_names.append(name)
        assert len(table_names) == 8
        assert "business_domain" in table_names
        assert "business_object" in table_names
        assert "metric" in table_names
        assert "value_domain" in table_names
        assert "value_domain_mapping" in table_names
        assert "metric_source_binding" in table_names
        assert "source_value_mapping" in table_names
        assert "standard_value_proposal" in table_names

    def test_metric_has_usage_count_and_quality_score(self):
        metric_ddl = _get_ddl_by_table("metric")
        assert "usage_count" in metric_ddl.lower()
        assert "quality_score" in metric_ddl.lower()

    def test_object_has_relations_jsonb(self):
        object_ddl = _get_ddl_by_table("business_object")
        assert "relations" in object_ddl.lower()
        assert "jsonb" in object_ddl.lower()

    def test_metric_value_domain_has_foreign_key(self):
        metric_ddl = _get_ddl_by_table("metric")
        assert "REFERENCES VALUE_DOMAIN" in metric_ddl.upper()

    def test_value_domain_mapping_has_unique_constraint(self):
        mapping_ddl = _get_ddl_by_table("value_domain_mapping")
        assert "UNIQUE(domain_code, source_value)" in mapping_ddl

    def test_metric_source_binding_keeps_source_version_and_uniqueness(self):
        binding_ddl = _get_ddl_by_table("metric_source_binding")
        assert "source_version" in binding_ddl
        assert "UNIQUE(metric_code, source_type, source_ref, source_field, source_version)" in binding_ddl
