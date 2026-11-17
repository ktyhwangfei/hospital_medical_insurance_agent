"""筛查问数的只读结果模型。金额用 Decimal，避免合计漂移。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal


class ScreeningKind(StrEnum):
    """运营问数里和筛查结果有关的问法。NONE 表示交给原有指标问数。"""

    NONE = "none"
    COUNT_AMOUNT = "count_amount"
    GROUP_BY_RULE = "group_by_rule"
    GROUP_BY_DEPARTMENT = "group_by_department"
    TOP_AMOUNT = "top_amount"
    OPEN_SETTLEMENT = "open_settlement"
    INSUFFICIENT = "insufficient"
    RECORD_VERIFY = "record_verify"
    MANAGE_REFUSED = "manage_refused"


class VerifyMark(StrEnum):
    FOLLOW = "follow"
    NOT_FOLLOW = "not_follow"
    INSUFFICIENT = "insufficient"


class FindingBook(StrEnum):
    """两本名单。默认只答明显对不上。"""

    MISMATCH = "mismatch"
    INSUFFICIENT_MATERIAL = "insufficient_material"


class ScreeningReadError(Exception):
    """读结果失败。子类区分「表还不存在」和「库暂时读不到」。"""


class ScreeningResultsMissing(ScreeningReadError):
    """结果表不存在，或还没有任何成功批次。问数不得把这种情况答成 0。"""


class ScreeningResultsUnreadable(ScreeningReadError):
    """连接或查询失败。不得改用猜出来的数字。"""


class PatientSpeechLeak(RuntimeError):
    """对患者的话术写入了监管判断。"""


@dataclass(frozen=True)
class ScreeningQuestion:
    kind: ScreeningKind
    time_start: datetime | None = None
    time_end: datetime | None = None
    time_label: str = ""
    top_n: int = 5
    rank: int | None = None
    settlement_key: str = ""
    finding_id: str = ""
    verify_mark: VerifyMark | None = None


@dataclass(frozen=True)
class ScreeningRun:
    run_id: str
    started_at: datetime | None
    finished_at: datetime | None
    time_range_start: datetime | None
    time_range_end: datetime | None
    status: str = "succeeded"


@dataclass(frozen=True)
class ScreeningFinding:
    finding_id: str
    primary_finding_id: str
    run_id: str
    rule_id: str
    rule_title: str
    source_clause: str
    settlement_key: str
    fee_line_id: str
    item_code: str
    item_name: str
    amount: Decimal | None
    finding_type: str
    evidence_clause: str
    evidence_facts: str
    verify_status: str
    department_name: str
    fee_item_name: str
    fee_amount: Decimal | None
    fee_item_code: str

    @property
    def is_primary(self) -> bool:
        return self.primary_finding_id == self.finding_id


@dataclass(frozen=True)
class ScreeningAnswer:
    """问数回答。show_table 为假时不附表格，避免把「没有批次」画成 0。"""

    answer: str
    answer_status: Literal["complete", "partial", "unavailable"]
    caliber: str
    summary: str
    metric_id: str
    metric_name: str
    columns: tuple[tuple[str, str], ...]
    rows: tuple[dict[str, str | int | float | None], ...]
    chart_name: str
    chart_labels: tuple[str, ...]
    chart_values: tuple[float, ...]
    uncertainties: tuple[str, ...]
    calculation_checked: bool
    settlement_checked: bool
    show_table: bool
