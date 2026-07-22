from __future__ import annotations

import ast
import json
import math
from typing import Any

import pandas as pd


HOSPITAL_LEVEL_MAP = {
    "primary": "一级及以下",
    "secondary": "二级",
    "tertiary": "三级",
    "一级及以下": "一级及以下",
    "一级": "一级",
    "二级": "二级",
    "三级": "三级",
}


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def safe_int(value: Any) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        v = float(value)
        if math.isnan(v):
            return None
        return v
    except Exception:
        return None


def parse_json_like(value: Any, default: Any = None) -> Any:
    if default is None:
        default = None
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    text = safe_str(value)
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return default


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def condition_value(conditions: list[dict[str, Any]], field: str) -> Any:
    for cond in conditions or []:
        if str(cond.get("field")) == field:
            return cond.get("value")
    return None


def normalize_unit(unit: Any) -> str:
    text = safe_str(unit)
    if text in ["元", "人民币", "CNY", "RMB"]:
        return "CNY"
    if text:
        return text
    return "unknown"


def normalize_ratio(value: Any) -> float | None:
    v = safe_float(value)
    if v is None:
        return None
    if v > 1:
        return v / 100
    return v
