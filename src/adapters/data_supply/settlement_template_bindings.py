"""受控行投影：模板绑定同时供原单展示和算法观测使用，不执行配置中的 SQL。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from pydantic import BaseModel

from src.adapters.data_supply.record_query_mappings import DEFAULT_RECORD_QUERY_MAPPING, RecordQueryMapping
from src.adapters.data_supply.settlement_record_queries import _k
from src.config.settlement_templates import SettlementDisplayTemplate


class BoundTemplateValues(BaseModel):
    values: dict[str, str | None]
    paths: dict[str, list[str]] = {}


def resolve_template_paths(template: SettlementDisplayTemplate, mapping: RecordQueryMapping) -> dict[str, list[str]]:
    """每个字段绑定的物理路径（库.表.字段），供人工核对：库名取模板 source_database。"""
    database = template.source_database
    paths: dict[str, list[str]] = {}
    for field in template.fields:
        if field.operation == 'unmapped' or not field.column_keys:
            paths[field.key] = []
            continue
        table = getattr(mapping, field.source_table)
        columns = [mapping.column(key).split('.')[-1] if field.record_mapping else key for key in field.column_keys]
        paths[field.key] = [f'{database}.{table}.{column}' for column in columns]
    return paths


def bind_template_values(template: SettlementDisplayTemplate, rows: Mapping[str, Mapping[str, Any]],
                         mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING) -> BoundTemplateValues:
    values: dict[str, str | None] = {}
    paths = resolve_template_paths(template, mapping)
    for field in template.fields:
        value = None
        if field.operation == 'text_column':
            row = rows.get(field.source_table, {})
            column = _k(mapping, field.column_keys[0]) if field.record_mapping else field.column_keys[0].lower()
            raw = row.get(column)
            values[field.key] = None if raw is None or str(raw).strip() == '' else str(raw).strip()
            continue
        if field.operation not in ('context', 'unmapped'):
            row = rows.get(field.source_table, {})
            columns = [_k(mapping, key) if field.record_mapping else key.lower() for key in field.column_keys]
            raw = [row.get(column) for column in columns]
            if field.operation == 'column':
                value = None if raw[0] is None or str(raw[0]).strip() == '' else str(raw[0]).strip()
                if value is not None:
                    try:
                        if not Decimal(value).is_finite():
                            raise ValueError(f'模板金额非法：{field.key}')
                    except InvalidOperation as exc:
                        raise ValueError(f'模板金额非法：{field.key}') from exc
            elif (all(item is not None for item in raw) if field.operation == 'sum' else any(item is not None for item in raw)):
                try:
                    amounts = [Decimal(str(item)) for item in raw if item is not None]
                    if not all(item.is_finite() for item in amounts):
                        raise ValueError('金额非有限数')
                    value = str(sum(amounts, Decimal('0')))
                except InvalidOperation as exc:
                    raise ValueError(f'模板金额非法：{field.key}') from exc
        values[field.key] = value
    return BoundTemplateValues(values=values, paths=paths)


def observed_template_amounts(template: SettlementDisplayTemplate, rows: Mapping[str, Mapping[str, Any]],
                              mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING) -> dict[str, Decimal | None]:
    bound = bind_template_values(template, rows, mapping)
    observed: dict[str, Decimal | None] = {}
    for field in template.fields:
        if not field.observed_attribute:
            continue
        value = bound.values[field.key]
        amount = Decimal(value) if value is not None else None
        if amount is not None and not amount.is_finite():
            raise ValueError(f'模板金额非法：{field.key}')
        observed[field.observed_attribute] = amount
    return observed
