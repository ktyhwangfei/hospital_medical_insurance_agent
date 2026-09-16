"""Flow 物化模式测试（V3.0 Slice 2）：模型映射 → dwd 明细视图 SQL。"""
from __future__ import annotations

import pytest

from src.domain.data_model.models import DataModelMapping
from src.domain.governed_flow.compiler import (
    FlowCompileError,
    compile_model_materialization,
)


def _m(field: str, col: str, table: str = "mz_trade", status: str = "confirmed", rule=None):
    return DataModelMapping(
        model_code="dwd_mz_settlement", field_code=field, source_id="bjybdb",
        physical_table=table, physical_column=col,
        transform_rule=rule, status=status,
    )


def test_straight_through_mapping_generates_rename_view():
    sql = compile_model_materialization("dwd_mz_settlement", [
        _m("trade_no", "T_TradeNo"), _m("total_fee", "T_FeeAll"),
    ])
    assert "CREATE OR REPLACE VIEW dwd_dwd_mz_settlement AS" not in sql  # 视图名不带双前缀
    assert "CREATE OR REPLACE VIEW dwd_mz_settlement AS" in sql
    assert '"T_TradeNo" AS "trade_no"' in sql
    assert '"T_FeeAll" AS "total_fee"' in sql
    assert 'FROM "mz_trade"' in sql


def test_no_confirmed_mapping_fails_closed():
    with pytest.raises(FlowCompileError, match="FLOW_MATERIALIZE_NO_MAPPING"):
        compile_model_materialization("dwd_mz_settlement", [
            _m("trade_no", "T_TradeNo", status="draft"),
        ])


def test_transform_rule_unsupported_fails_closed():
    with pytest.raises(FlowCompileError, match="FLOW_MATERIALIZE_TRANSFORM_UNSUPPORTED"):
        compile_model_materialization("dwd_mz_settlement", [
            _m("trade_no", "T_TradeNo", rule="value_domain:MZ_CURE_TYPE"),
        ])


def test_multi_source_tables_union_all():
    sql = compile_model_materialization("dwd_mz_settlement", [
        _m("trade_no", "T_TradeNo", table="mz_trade"),
        _m("trade_no", "TradeNo", table="his_trade",),
    ])
    assert "UNION ALL" in sql
    assert 'FROM "his_trade"' in sql
