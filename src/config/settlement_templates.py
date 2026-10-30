"""结算单字段标准：AI 首次匹配后固化，运行时只读经过校验的配置。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettlementTemplateField(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    key: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    label: str = Field(min_length=1)
    section: Literal['basic', 'transaction', 'hospital']
    row: int = Field(ge=1)
    column: int = Field(ge=1, le=4)
    span: int = Field(default=1, ge=1, le=4)
    scope: Literal['metadata', 'patient_actual', 'patient_book', 'hospital_quota']
    source_table: Literal['outpatient_trade_table', 'outpatient_settlement_table', 'registration_table']
    column_keys: tuple[str, ...] = ()
    record_mapping: bool = False
    operation: Literal['column', 'text_column', 'sum', 'sum_present', 'unmapped', 'context']
    context_key: str | None = None
    field_code: str | None = None
    observed_attribute: str | None = None
    legacy_label: str | None = None
    legacy_order: int = 0
    visible: bool = True
    evidence: str = Field(min_length=1)
    binding_status: Literal['schema_verified', 'code_verified', 'pending', 'unmapped'] = 'code_verified'
    note: str | None = None

    @model_validator(mode='after')
    def check_binding(self) -> SettlementTemplateField:
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', column) for column in self.column_keys):
            raise ValueError('来源列只能使用安全标识符，不接受 SQL 或表达式')
        if self.operation in ('column', 'text_column') and len(self.column_keys) != 1:
            raise ValueError('单列字段必须且只能绑定一个列')
        if self.operation in ('sum', 'sum_present') and len(self.column_keys) < 2:
            raise ValueError('合计字段必须声明全部参与列')
        if self.operation == 'unmapped' and self.column_keys:
            raise ValueError('未映射字段不得伪造来源列')
        if self.operation == 'context' and not self.context_key:
            raise ValueError('上下文字段必须声明上下文键')
        if self.section != 'basic' and self.column + self.span > 3:
            raise ValueError('金额区只允许双列布局')
        if self.section == 'basic' and self.column + self.span > 5:
            raise ValueError('基本信息区只允许四列布局')
        return self


class SettlementDisplayTemplate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    template_id: str
    version: str
    chain: Literal['outpatient', 'special']
    insurance_type: Literal['employee', 'resident']
    title: str
    # 数据源库名：用于生成 库.表.字段 全路径，供人工核对与审计。
    source_database: str = 'bjybdb'
    layout_status: Literal['image_verified', 'provisional']
    generation_method: str
    reference: str
    fields: tuple[SettlementTemplateField, ...]

    @model_validator(mode='after')
    def check_unique_fields(self) -> SettlementDisplayTemplate:
        keys: set[str] = set()
        cells: set[tuple[str, int, int]] = set()
        attributes: set[str] = set()
        codes: set[str] = set()
        for field in self.fields:
            if field.key in keys:
                raise ValueError(f'重复字段键：{field.key}')
            keys.add(field.key)
            if field.field_code:
                if field.field_code in codes:
                    raise ValueError(f'重复计算目标：{field.field_code}')
                codes.add(field.field_code)
            if field.observed_attribute:
                if field.observed_attribute in attributes:
                    raise ValueError(f'重复算法观测绑定：{field.observed_attribute}')
                attributes.add(field.observed_attribute)
            if not field.visible:
                continue
            for column in range(field.column, field.column + field.span):
                cell = (field.section, field.row, column)
                if cell in cells:
                    raise ValueError(f'字段布局重叠：{field.key}')
                cells.add(cell)
        return self


class _TemplateFile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    templates: list[SettlementDisplayTemplate]


@lru_cache(maxsize=1)
def _templates() -> dict[str, SettlementDisplayTemplate]:
    templates: dict[str, SettlementDisplayTemplate] = {}
    for family in ('employee_outpatient', 'resident_outpatient', 'employee_special', 'resident_special'):
        path = Path(__file__).with_suffix('') / f'{family}.json'
        for template in _TemplateFile.model_validate_json(path.read_text(encoding='utf-8')).templates:
            if template.template_id in templates:
                raise ValueError(f'重复模板：{template.template_id}')
            templates[template.template_id] = template
    return templates


def get_settlement_template(template_id: str) -> SettlementDisplayTemplate:
    return _templates()[template_id]


def settlement_template_columns(template_id: str, source_table: str) -> tuple[str, ...]:
    """只返回校验过的列名，查询层负责引用；不把配置当 SQL 执行。"""
    template = get_settlement_template(template_id)
    return tuple(dict.fromkeys(column for field in template.fields
        if field.source_table == source_table and field.operation not in ('context', 'unmapped')
        for column in field.column_keys))


def select_settlement_template(insurance_type: str, chain: str, *, fixed: bool = False) -> SettlementDisplayTemplate | None:
    if insurance_type not in ('employee', 'resident') or chain not in ('outpatient', 'special'):
        return None
    if fixed and (insurance_type, chain) != ('employee', 'special'):
        return None
    key = f'{insurance_type}_{chain}' + ('_fixed_kidney' if fixed else '')
    return get_settlement_template(key)
