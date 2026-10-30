"""结算事实侧车：原始交易/登记行 → 公开结算事实视图（Issue #78 费用解释改造）。

方案依据（docs/superpowers/plans/2026-10-15-fee-explanation-refactor-plan.md §53）：
- 事实区独立于算法：金额算法不支持或解释缺口存在时，已取得的结算事实仍可查看；
  只要原始行已取到，unavailable 早退路径同样携带 facts；
- 金额为十进制字符串原样透传，缺失=None（前端显示"未返回"）；
  零值不吞——Decimal("0.00")/int 0 是 falsy，取数必须显式 is None 判断；
- 姓名/身份证/医保卡号不进入视图（查询层本就不 SELECT 身份原文列，此处不新增）；
- 金额结构 SettlementDecompositionResult 1.0 不动，facts 走侧车随结果同行。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from src.adapters.data_supply.record_query_mappings import (
    DEFAULT_RECORD_QUERY_MAPPING,
    RecordQueryMapping,
)
from src.adapters.data_supply.settlement_record_queries import _k
from src.adapters.data_supply.settlement_template_bindings import bind_template_values
from src.config.settlement_templates import SettlementDisplayTemplate, get_settlement_template, select_settlement_template
from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult


class SettlementFactsItem(BaseModel):
    """单条结算事实：标签 + 原样值；value=None 表示源记录未返回（区别于零值）。"""

    model_config = ConfigDict(extra="forbid")

    label: str
    value: str | None = None


class SettlementDisplayField(BaseModel):
    """公开模板字段：只含业务名称、位置和已绑定金额，不含数据库位置。"""
    model_config = ConfigDict(extra='forbid')

    key: str
    label: str
    semantic_label: str | None = None
    field_code: str | None = None
    section: Literal['basic', 'transaction', 'hospital']
    row: int
    column: int
    span: int = 1
    scope: Literal['metadata', 'patient_actual', 'patient_book', 'hospital_quota']
    value: str | None = None
    source_kind: Literal['record', 'derived', 'unmapped', 'context']
    status: Literal['available', 'missing', 'unmapped']
    context_key: str | None = None
    note: str | None = None


class SettlementDisplayView(BaseModel):
    model_config = ConfigDict(extra='forbid')

    template_id: str
    version: str
    title: str
    layout_status: Literal['image_verified', 'provisional']
    fields: list[SettlementDisplayField]


class SettlementFactsView(BaseModel):
    """结算事实区公开视图：参照原结算单的基本信息、交易金额、基金及补助、支付方式。

    items 为金额事实（顺序参照医院结算单）；payment_items 单独标注账户/现金支付方式。
    """

    model_config = ConfigDict(extra="forbid")

    chain: Literal["outpatient", "special"]
    identifier: str | None = None
    trade_date: str | None = None
    medical_category: str | None = None
    insurance_type: str | None = None
    person_type: str | None = None
    hospital_level: str | None = None
    retire_officer_flag: str | None = None
    metadata_names: dict[str, str] = Field(default_factory=dict, exclude_if=lambda value: not value)
    items: list[SettlementFactsItem] = Field(default_factory=list)
    payment_items: list[SettlementFactsItem] = Field(default_factory=list)
    display_template: SettlementDisplayView | None = Field(default=None, exclude_if=lambda value: value is None)


@dataclass(frozen=True)
class DecompositionOutcome:
    """分解结果 + 结算事实侧车（四个 decompose_* 快照服务入口的统一返回）。"""

    result: SettlementDecompositionResult
    facts: SettlementFactsView | None = None


def label_facts(facts: SettlementFactsView, domains: Mapping[str, Mapping[str, str]]) -> SettlementFactsView:
    """按字段来源选择码表：门特 300 与普通门诊 yllbss 不混用。"""
    fields = {"insurance_type": "fund", "person_type": "290", "hospital_level": "310",
              "medical_category": "300" if facts.chain == "special" else "yllbss"}
    names = {field: domains[domain][code] for field, domain in fields.items()
             if (code := getattr(facts, field)) is not None and code in domains.get(domain, {})}
    display = facts.display_template
    if display:
        fields = [field.model_copy(update={
            'value': names.get(field.context_key) or _text(getattr(facts, field.context_key, None)),
            'status': 'available' if names.get(field.context_key) or _text(getattr(facts, field.context_key, None)) is not None else 'missing',
        }) if field.source_kind == 'context' and field.context_key and not field.context_key.startswith('patient.') else field
            for field in display.fields]
        display = display.model_copy(update={'fields': fields})
    return facts.model_copy(update={"metadata_names": names, 'display_template': display})


def _text(value: Any) -> str | None:
    """事实值原样字符串化：None/空白 → None；零值（0/"0.00"）显式保留不吞。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text if text else None


def _attach_template(facts: SettlementFactsView, rows: Mapping[str, Mapping[str, Any]],
                     template: SettlementDisplayTemplate, *, display_enabled: bool = True,
                     mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING) -> SettlementFactsView:
    bound = bind_template_values(template, rows, mapping)
    display_fields = [SettlementDisplayField(
        key=field.key, label=field.label, semantic_label=field.legacy_label,
        field_code=field.field_code, section=field.section, row=field.row,
        column=field.column, span=field.span, scope=field.scope,
        value=bound.values[field.key],
        source_kind=('context' if field.operation == 'context' else 'unmapped' if field.operation == 'unmapped'
                     else 'derived' if field.operation in ('sum', 'sum_present') else 'record'),
        status='unmapped' if field.operation == 'unmapped' else 'missing' if bound.values[field.key] is None else 'available',
        context_key=field.context_key, note=field.note,
    ) for field in template.fields if field.visible]
    legacy = sorted((field for field in template.fields if field.legacy_label), key=lambda field: field.legacy_order)
    # 旧载荷继续可读；新展示与算法都按配置键关联，旧中文标签只用于兼容旧消费者。
    facts.items = [SettlementFactsItem(label=field.legacy_label, value=bound.values[field.key])
                   for field in legacy if field.legacy_label is not None and field.key not in ('account_pay', 'cash_pay')]
    facts.payment_items = [SettlementFactsItem(label=field.legacy_label, value=bound.values[field.key])
                           for field in legacy if field.legacy_label is not None and field.key in ('account_pay', 'cash_pay')]
    if display_enabled:
        facts.display_template = SettlementDisplayView(template_id=template.template_id, version=template.version,
            title=template.title, layout_status=template.layout_status, fields=display_fields)
    return label_facts(facts, {})


def build_outpatient_facts(
    trade_row: Mapping[str, Any],
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> SettlementFactsView:
    """o_Trade 交易行 → 结算事实视图（普通门诊链）。

    行键为 _fetch_all 口径的物理列名小写（取键经 _k()，跨院区列名不同时仍能取到）。
    """
    fund = _text(trade_row.get(_k(mapping, 'op_fund_type')))
    insurance = 'employee' if fund == '3' else 'resident' if fund in ('91', '92', '93') else 'unknown'
    template = select_settlement_template(insurance, 'outpatient')
    # 未识别险种仍保留同一物理表的原始事实，不发布待遇模板或猜测身份。
    source_template = template or get_settlement_template('employee_outpatient')
    return _attach_template(SettlementFactsView(
        chain="outpatient",
        identifier=_text(trade_row.get(_k(mapping, "op_trade_no"))),
        trade_date=_text(trade_row.get(_k(mapping, "op_trade_date"))),
        medical_category=_text(trade_row.get(_k(mapping, "op_cure_type"))),
        insurance_type=_text(trade_row.get(_k(mapping, "op_fund_type"))),
        person_type=_text(trade_row.get(_k(mapping, "op_person_type"))),
        hospital_level=None,  # o_Trade 无机构等级列，不拿院区码冒充
        retire_officer_flag=_text(trade_row.get(_k(mapping, "op_retire_officer_flag"))),
    ), {'outpatient_trade_table': trade_row}, source_template, display_enabled=template is not None, mapping=mapping)


def build_special_mz_facts(
    settlement_row: Mapping[str, Any],
    registration_row: Mapping[str, Any] | None = None,
    *, fixed: bool = False,
) -> SettlementFactsView:
    """yb_mzjyxx 结算行 + yb_brdjxx 登记行 → 结算事实视图（门特链）。

    险种/医疗类别/人员类别取自登记行原始码（FUND_TYPE/yllb/cblb，小写键），不做码表
    翻译；登记行缺失时对应字段 None（不猜测）。
    """
    registration = registration_row or {}
    fund = _text(registration.get('fund_type'))
    insurance = 'employee' if fund == '3' else 'resident' if fund in ('91', '92', '93') else 'unknown'
    template = select_settlement_template(insurance, 'special', fixed=fixed)
    source_template = template or get_settlement_template('employee_special')
    return _attach_template(SettlementFactsView(
        chain="special",
        identifier=_text(settlement_row.get("djh") or registration.get("djh")),
        trade_date=_text(settlement_row.get("jyrq")),
        medical_category=_text(registration.get("yllb")),
        insurance_type=_text(registration.get("fund_type")),
        person_type=_text(registration.get("cblb")),
        hospital_level=None,
    ), {'outpatient_settlement_table': settlement_row, 'registration_table': registration},
        source_template, display_enabled=template is not None)
