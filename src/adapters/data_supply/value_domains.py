"""值域配置加载器（Issue #78）：value_domains.yaml 的唯一读取入口。

配置由 ``scripts/eval/build_value_domains.py`` 从 bjyb 字典表（yb_zdfl/yb_zdxm）
与需求规格说明书码表章节生成，逐字保留来源映射。

使用纪律（与内核 fail-closed 约定一致）：
- ``domains.*.values`` 是来源码表原文，可直接用于代码 → 名称解析、值域合法性判断；
- ``derived.*`` 是解释性分组（在职/退休归类、社区判定、目录类别映射等），
  ``status=candidate``，签核前调用方必须显式知情使用，不得静默生效；
- ``unresolved.*`` 记录生产数据中出现但码表未覆盖的代码，命中即未知，禁止猜测。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).with_name("value_domains.yaml")


@dataclass(frozen=True)
class ValueDomains:
    """值域配置只读视图。所有代码键统一为 str。"""

    meta: dict[str, Any]
    domains: dict[str, dict[str, Any]]
    derived: dict[str, dict[str, Any]]
    unresolved: dict[str, dict[str, Any]]

    def name_of(self, domain: str, code: object) -> str | None:
        """代码 → 名称；域不存在或代码未覆盖（含停用代码）返回 None，不猜测。"""
        d = self.domains.get(domain)
        if d is None:
            return None
        values = d.get("values") or {}
        return values.get(str(code).strip())

    def has_code(self, domain: str, code: object) -> bool:
        """代码是否在码表值域内（停用代码仍在值域内，仅标注）。"""
        return self.name_of(domain, code) is not None

    def is_disabled(self, domain: str, code: object) -> bool:
        """代码在码表中是否带停用标记（yb_zdxm.sybz<>1）。"""
        d = self.domains.get(domain) or {}
        return str(code).strip() in set(d.get("disabled_codes") or ())

    def derived_values(self, name: str) -> dict[str, Any]:
        """派生分组的 values；调用方自行承担 candidate 状态责任。"""
        d = self.derived.get(name)
        return dict(d.get("values") or {}) if d else {}

    def derived_status(self, name: str) -> str | None:
        d = self.derived.get(name)
        return d.get("status") if d else None

    def unresolved_codes(self, name: str) -> tuple[str, ...]:
        d = self.unresolved.get(name) or {}
        return tuple(str(c) for c in d.get("unresolved_codes") or ())


def _normalize(doc: dict[str, Any]) -> ValueDomains:
    """YAML 载入的代码键可能被解析为非 str（如 0508），统一归一为 str。"""
    domains: dict[str, dict[str, Any]] = {}
    for name, d in (doc.get("domains") or {}).items():
        d = dict(d)
        d["values"] = {str(k): str(v) for k, v in (d.get("values") or {}).items()}
        d["disabled_codes"] = [str(c) for c in (d.get("disabled_codes") or [])]
        domains[str(name)] = d
    derived: dict[str, dict[str, Any]] = {}
    for name, d in (doc.get("derived") or {}).items():
        d = dict(d)
        d["values"] = {str(k): v for k, v in (d.get("values") or {}).items()}
        derived[str(name)] = d
    unresolved = {str(k): dict(v) for k, v in (doc.get("unresolved") or {}).items()}
    return ValueDomains(
        meta=dict(doc.get("meta") or {}),
        domains=domains,
        derived=derived,
        unresolved=unresolved,
    )


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> ValueDomains:
    doc = yaml.safe_load(Path(path_str).read_text(encoding="utf-8"))
    return _normalize(doc)


def load_value_domains(path: Path | None = None) -> ValueDomains:
    """加载值域配置（默认 value_domains.yaml，进程内缓存）。"""
    return _load_cached(str(path or DEFAULT_PATH))
