"""把运营问数里的筛查问法收成确定性意图。识别不了就返回 NONE，不猜测指标。"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, time

from src.interaction.ops_screening.models import (
    ScreeningKind,
    ScreeningQuestion,
    VerifyMark,
)

_MANAGE = re.compile(
    r"上传材料|上传政策|上传清单|上传问题|批准规则|关闭规则|新建规则|创建规则|修改规则|执行跑数|帮我跑数"
)
_VERIFY = re.compile(
    r"(?:把)?疑点(?:编号)?\s*([A-Za-z0-9_-]+)\s*(?:标为|记为|核实为)\s*(不跟|材料不足|跟)"
)
_VERIFY_RANK = re.compile(r"第\s*(\d+)\s*条\s*(?:标为|记为|核实为)\s*(不跟|材料不足|跟)")
_INSUFFICIENT_LIST = re.compile(r"材料不足")
_OPEN = re.compile(r"看看依据|依据是什么|打开.{0,20}结算|下钻")
_TOP = re.compile(r"金额最高|金额最大|最高的几条|金额靠前")
_GROUP_RULE = re.compile(r"按规则|各规则|规则分布")
_GROUP_DEPT = re.compile(r"按科室|各科室|科室分布")
_COUNT = re.compile(r"疑点|待核实|明显对不上|筛查")
_COUNT_MEASURE = re.compile(r"多少|几条|金额")
_METRIC_ONLY = re.compile(r"药品|人次|趋势|占比|次均|统筹|目录")
_SETTLEMENT = re.compile(r"结算单(?:号)?\s*([A-Za-z0-9_-]+)")
_RANK = re.compile(r"第\s*(\d+)\s*条")
_TOP_N = re.compile(r"(?:前|最高的)\s*(\d+)\s*条")
_DATE = r"(\d{4})-(\d{2})-(\d{2})"
_RANGE = re.compile(_DATE + r"\s*(?:至|到|~)\s*" + _DATE)
_YM_RANGE = re.compile(r"(\d{4})年(\d{1,2})月\s*(?:至|到)\s*(\d{1,2})月")
_YMD = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_YM = re.compile(r"(\d{4})年(\d{1,2})月")

_MARKS = {
    "跟": VerifyMark.FOLLOW,
    "不跟": VerifyMark.NOT_FOLLOW,
    "材料不足": VerifyMark.INSUFFICIENT,
}


def parse_screening_question(question: str, *, today: datetime | None = None) -> ScreeningQuestion:
    """按问法优先级识别。管理动作一律拒绝，不落到查数。"""
    text = (question or "").strip()
    clock = today or datetime.now()
    start, end, label = _time_window(text, clock)
    if _MANAGE.search(text):
        return ScreeningQuestion(ScreeningKind.MANAGE_REFUSED, start, end, label)
    verify = _verify(text)
    if verify is not None:
        return verify
    if _INSUFFICIENT_LIST.search(text) and re.search(r"有哪些|哪些|列出|多少|几条", text):
        return ScreeningQuestion(ScreeningKind.INSUFFICIENT, start, end, label)
    if _OPEN.search(text) or (_RANK.search(text) and re.search(r"打开|依据|下钻", text)):
        settlement = _SETTLEMENT.search(text)
        rank = _RANK.search(text)
        return ScreeningQuestion(
            ScreeningKind.OPEN_SETTLEMENT,
            start,
            end,
            label,
            rank=int(rank.group(1)) if rank else None,
            settlement_key=settlement.group(1) if settlement else "",
        )
    if _TOP.search(text):
        found = _TOP_N.search(text)
        top_n = int(found.group(1)) if found else 5
        return ScreeningQuestion(
            ScreeningKind.TOP_AMOUNT, start, end, label, top_n=max(1, min(top_n, 20)),
        )
    if _GROUP_RULE.search(text) and not _metric_noise(text):
        return ScreeningQuestion(ScreeningKind.GROUP_BY_RULE, start, end, label)
    if _GROUP_DEPT.search(text) and re.search(r"分别|疑点|待核实|筛查|多少条", text) and not _metric_noise(text):
        return ScreeningQuestion(ScreeningKind.GROUP_BY_DEPARTMENT, start, end, label)
    if _COUNT.search(text) and _COUNT_MEASURE.search(text) and not _metric_noise(text):
        return ScreeningQuestion(ScreeningKind.COUNT_AMOUNT, start, end, label)
    return ScreeningQuestion(ScreeningKind.NONE)


def _metric_noise(text: str) -> bool:
    """指标问法里偶然出现「科室」时，不要抢走原有运营指标链路。"""
    return _METRIC_ONLY.search(text) is not None and not re.search(r"疑点|待核实|筛查|明显对不上", text)


def _verify(text: str) -> ScreeningQuestion | None:
    ranked = _VERIFY_RANK.search(text)
    if ranked:
        return ScreeningQuestion(
            ScreeningKind.RECORD_VERIFY,
            rank=int(ranked.group(1)),
            verify_mark=_MARKS[ranked.group(2)],
        )
    named = _VERIFY.search(text)
    if named:
        return ScreeningQuestion(
            ScreeningKind.RECORD_VERIFY,
            finding_id=named.group(1),
            verify_mark=_MARKS[named.group(2)],
        )
    return None


def _time_window(text: str, today: datetime) -> tuple[datetime | None, datetime | None, str]:
    ranged = _RANGE.search(text)
    if ranged:
        start = _day(int(ranged.group(1)), int(ranged.group(2)), int(ranged.group(3)))
        end = _day_end(int(ranged.group(4)), int(ranged.group(5)), int(ranged.group(6)))
        return start, end, f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
    year_months = _YM_RANGE.search(text)
    if year_months:
        year = int(year_months.group(1))
        start = _month_start(year, int(year_months.group(2)))
        end = _month_end(year, int(year_months.group(3)))
        return start, end, f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
    ymd = _YMD.search(text)
    if ymd:
        day = _day(int(ymd.group(1)), int(ymd.group(2)), int(ymd.group(3)))
        return day, _day_end(day.year, day.month, day.day), f"{day:%Y-%m-%d}"
    ym = _YM.search(text)
    if ym:
        start = _month_start(int(ym.group(1)), int(ym.group(2)))
        end = _month_end(start.year, start.month)
        return start, end, f"{start:%Y-%m}"
    if "本月" in text:
        start = _month_start(today.year, today.month)
        end = _month_end(today.year, today.month)
        return start, end, f"{start:%Y-%m}"
    if "上月" in text or "上个月" in text:
        year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        start = _month_start(year, month)
        end = _month_end(year, month)
        return start, end, f"{start:%Y-%m}"
    if "今年" in text:
        start = _day(today.year, 1, 1)
        end = _day_end(today.year, 12, 31)
        return start, end, f"{today.year}年"
    return None, None, ""


def _month_start(year: int, month: int) -> datetime:
    return _day(year, month, 1)


def _month_end(year: int, month: int) -> datetime:
    last = calendar.monthrange(year, month)[1]
    return _day_end(year, month, last)


def _day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day)


def _day_end(year: int, month: int, day: int) -> datetime:
    return datetime.combine(datetime(year, month, day).date(), time(23, 59, 59))
