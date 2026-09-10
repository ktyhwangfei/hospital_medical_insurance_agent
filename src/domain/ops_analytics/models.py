"""门诊运营分析领域模型：指标卡 / 维度拆分 / 趋势 / 下钻 / 周报（#40）。

冻结契约（P3 受控问数）：
- 六指标 = 门诊医保就诊人次、有效结算笔数、总费用、统筹基金支付、个人支付、次均费用。
- 五维度 = 就诊时间、科室、门诊业务类别、险种、结算状态。
- 每个结果 result_status ∈ complete / partial / unavailable，且恰好携带一个 halt_reason。
- 就诊人次 / 次均费用依赖 HIS 就诊关联（P1 必需输入，禁止跨源临时 JOIN）→ 保持
  unavailable（halt_reason=data_unavailable）；科室维度 mz_trade 无科室列，同理。
- 所有结论必须可溯源到指标批次（mz_trade.data_batch_id）。

[来源: docs/superpowers/plans/2026-08-27-outpatient-p0-data-contract.md Task 5]
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

OpsResultStatus = Literal["complete", "partial", "unavailable"]

# 五维度中受支持的拆分/下钻维度；department（科室）无数据列，走 unavailable 分支。
OpsAnalyticsDimension = Literal["fund_type", "cure_type", "settle_state", "department"]


class OpsMetricCard(BaseModel):
    """单张指标卡：值或不可用原因，二选一（与 result_status 一致）。"""

    metric_code: str
    name: str
    unit: str = ""
    precision: int = 0
    result_status: OpsResultStatus
    value: float | None = None
    halt_reason: str | None = None
    halt_detail: str | None = None


class OpsOverview(BaseModel):
    """六指标总览：四卡 available（口径句 v4）+ 人次/次均 unavailable。"""

    result_status: OpsResultStatus
    halt_reason: str | None = None
    generated_at: str
    date_min: str | None = None
    date_max: str | None = None
    row_count: int = 0
    semantic_version: str | None = None
    data_batch_ids: list[str] = Field(default_factory=list)
    cards: list[OpsMetricCard]


class OpsDimensionItem(BaseModel):
    """维度拆分项：码 + 中文标签 + 四指标值 + 笔数占比。"""

    code: str
    label: str
    valid_count: int
    total_fee: float
    fund_pay: float
    self_pay: float
    share: float


class OpsDimensionBreakdown(BaseModel):
    """按维度拆分；department 维度返回 unavailable 单例。"""

    dimension: OpsAnalyticsDimension
    dimension_name: str
    result_status: OpsResultStatus
    halt_reason: str | None = None
    halt_detail: str | None = None
    data_batch_ids: list[str] = Field(default_factory=list)
    items: list[OpsDimensionItem] = Field(default_factory=list)


class OpsTrendPoint(BaseModel):
    """月度趋势点（口径句 v4 范围内）。"""

    month: str  # YYYY-MM
    valid_count: int
    total_fee: float
    fund_pay: float
    self_pay: float


class OpsDrillRow(BaseModel):
    """就诊行级下钻行：携带 data_batch_id 指标批次溯源。"""

    trade_no: str
    trade_date: str | None = None
    fund_type: str | None = None
    cure_type: str | None = None
    settle_state: str | None = None
    total_fee: float = 0.0
    fund_pay: float = 0.0
    self_pay: float = 0.0
    data_batch_id: str | None = None


class OpsDrillResult(BaseModel):
    """下钻结果：行列表 + 分页 + 批次溯源；无数据时 partial/data_unavailable。"""

    result_status: OpsResultStatus
    halt_reason: str | None = None
    total: int = 0
    limit: int = 50
    offset: int = 0
    data_batch_ids: list[str] = Field(default_factory=list)
    rows: list[OpsDrillRow] = Field(default_factory=list)


class OpsConclusion(BaseModel):
    """周报结论：文本 + 引用（指标批次 / 指标口径）。"""

    text: str
    citations: list[dict[str, str]] = Field(default_factory=list)


class OpsWeekDelta(BaseModel):
    """单指标周环比：本周/上周值 + 绝对差与百分比（除零时 pct=None）。"""

    metric_code: str
    name: str
    unit: str = ""
    precision: int = 0
    current: float | None = None
    previous: float | None = None
    delta: float | None = None
    pct: float | None = None
    direction: Literal["up", "down", "flat", "unknown"] = "unknown"


class OpsWeeklyReport(BaseModel):
    """周报：四指标环比 + 结论（每条带批次引用）+ AI 运营摘要（可降级）。"""

    week_start: str  # YYYY-MM-DD（ISO 周一）
    result_status: OpsResultStatus
    halt_reason: str | None = None
    current_week_rows: int = 0
    previous_week_rows: int = 0
    deltas: list[OpsWeekDelta] = Field(default_factory=list)
    conclusions: list[OpsConclusion] = Field(default_factory=list)
    summary: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
    data_batch_ids: list[str] = Field(default_factory=list)


def dec_to_float(value: Decimal | float | int | str | None, precision: int) -> float | None:
    """Decimal → 按 precision 量化的 float（JSON 可序列化）。"""
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return float(d.quantize(Decimal(1).scaleb(-precision)))
