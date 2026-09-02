"""提取单元去重修复测试（设计 docs/superpowers/specs/2026-08-25-extraction-unit-dedup-design.md §4.4）。

复现缺陷（真实库 13 组）：首轮提取 unit=NULL，重跑切出 unit 后查重
SELECT `unit_id=%s` 对 NULL 永远失配 → 同 doc+hash 两行活跃并存。
"""
from __future__ import annotations

import pytest

from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore


class FakeClient:
    """最小 SQL 桩：只实现去重 SELECT 与写入，逐条记录执行语句。"""

    def __init__(self, rows: list[dict] | None = None):
        self.rows = rows or []          # SELECT 结果
        self.statements: list[tuple[str, tuple]] = []
        self._tx = False

    def execute(self, sql: str, params: tuple = ()):
        self.statements.append((sql, params))
        if sql.strip().upper().startswith("SELECT"):
            return self.rows
        return []

    def transaction(self):
        import contextlib

        return contextlib.nullcontext()

    def select_for_update(self, sql: str, params: tuple = ()):
        return self.rows


def _store(client: FakeClient) -> PipelineStore:
    store = PipelineStore.__new__(PipelineStore)
    store._client = client
    store._database_url = None
    return store


def _dedup_select_params(client: FakeClient) -> tuple | None:
    for sql, params in client.statements:
        if "FROM policy_extractions" in sql and sql.strip().upper().startswith("SELECT"):
            return params
    return None


ITEM = {"doc_id": "d1", "source_text": "同一原文", "unit_id": "n_x", "extracted_fields": {}}


def test_drift_takes_over_null_row():
    """漂移承接：旧行 NULL、新行带 unit → 命中旧行 UPDATE，不插新行。"""
    client = FakeClient(rows=[{"extraction_id": "ext_old"}])
    _store(client).batch_create_extractions([dict(ITEM)])
    updates = [s for s, _ in client.statements if s.strip().upper().startswith("UPDATE")]
    inserts = [s for s, _ in client.statements if s.strip().upper().startswith("INSERT")]
    assert updates and not inserts
    update_params = [p for s, p in client.statements if s.strip().upper().startswith("UPDATE")][0]
    assert update_params[0] == "n_x"  # unit 承接补值


def test_unit_not_regressed_to_null():
    """unit 不倒退：旧行带 unit、新行 unit=None → UPDATE 用 COALESCE 保原值。"""
    client = FakeClient(rows=[{"extraction_id": "ext_old"}])
    _store(client).batch_create_extractions([{"doc_id": "d1", "source_text": "同一原文",
                                              "unit_id": None}])
    update_sql = next(s for s, _ in client.statements if "COALESCE" in s.upper())
    assert "COALESCE" in update_sql


def test_archived_not_matched_and_not_revived():
    """archived 不复活：查重 SELECT 过滤 archived；命中 archived 行时不 UPDATE 它。"""
    client = FakeClient(rows=[])  # 查重无结果（SELECT 已滤 archived）
    _store(client).batch_create_extractions([dict(ITEM)])
    select_sql = next(s for s, _ in client.statements
                      if s.strip().upper().startswith("SELECT") and "policy_extractions" in s)
    assert "archived" in select_sql


def test_cross_unit_same_text_inserts_new_row():
    """跨单元同文：旧行 unit=n_y、新行 unit=n_x → 不命中，INSERT 新行。"""
    client = FakeClient(rows=[])
    count = _store(client).batch_create_extractions([dict(ITEM)])
    inserts = [s for s, _ in client.statements if s.strip().upper().startswith("INSERT")]
    assert count == 1 and inserts


def test_reconcile_uses_same_dedup():
    """reconcile 与 batch_create 共用同一查重语义（SELECT 滤 archived + NULL 承接）。"""
    client = FakeClient(rows=[{"extraction_id": "ext_old"}])
    _store(client).reconcile_extractions("d1", [dict(ITEM, extraction_id="ext_new")])
    selects = [s for s, _ in client.statements
               if s.strip().upper().startswith("SELECT") and "FROM policy_extractions" in s]
    assert selects
    for sql in selects:
        assert "archived" in sql, "reconcile 查重必须过滤 archived"
    # 命中旧行后走 ON CONFLICT 更新而非纯 INSERT 新 id
    upserts = [s for s, _ in client.statements if "ON CONFLICT" in s]
    assert upserts


def test_unique_index_in_schema():
    """表达式部分唯一索引随 schema 创建（doc + COALESCE(unit,'') + hash，仅活跃行）。"""
    from src.knowledge_extension.rule_explanation import pipeline_store as ps
    ddl = ps.EXTRACTIONS_TABLE + ps.EXTRACTIONS_MIGRATION
    assert "uq_ext_active_doc_unit_text" in ddl
    assert "COALESCE(unit_id, '')" in ddl
    assert "WHERE status <> 'archived'" in ddl
