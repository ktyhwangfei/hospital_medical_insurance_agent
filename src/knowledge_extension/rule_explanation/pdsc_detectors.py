"""PDSC 确定性发现信号检测器（设计 §4.2）。

六类检测器全部基于可重放事实（提取行 + registry 值域 + bjyb 字段画像），
不调用模型、不保存"这是正确指标"的结论。信号经 PdscService.intake_signal
进入语义发现簇；重复证据由簇侧指纹去重。
"""
from __future__ import annotations

import re
from typing import Any

from src.knowledge_extension.rule_explanation.pdsc import POLICY_OBJECT_CODE
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    DiscoveryEvidence,
    DiscoverySignal,
    TriggerSource,
)
from src.semantic_layer.registry import SemanticRegistry

# 维度字段值中疑似主体/结果污染的特征（纯数字、比例、金额词）
_NUMERIC_VALUE = re.compile(r"^[\d.,，%\s]+$")
_RESULT_WORDS = ("比例", "金额", "起付", "封顶", "标准")

DETECTOR_KINDS = (
    "axis_value_conflict",        # 1 轴和值类型不一致
    "structure_compression",      # 2 原文区分被结构压缩
    "cross_unit_inconsistency",   # 3 跨单元映射不一致
    "subject_pollution",          # 4 规则主体与条件冲突
    "value_domain_violation",     # 5 值域越界
    "business_role_conflict",     # 6 业务字段角色冲突（需库画像）
)


def _dimension_fields(registry: SemanticRegistry) -> dict[str, str]:
    """zcgz 下全部 Enum 维度字段 → 值域编码。"""
    result: dict[str, str] = {}
    for metric in registry.list_metrics(POLICY_OBJECT_CODE):
        if metric.semantic_type == "Enum" and metric.value_domain:
            result[metric.metric_code.split(".", 1)[1]] = metric.value_domain
    return result


def _dimension_names(registry: SemanticRegistry) -> dict[str, str]:
    """zcgz 指标字段 → 注册表中文名（用于生成业务可读的发现文案）。"""
    result: dict[str, str] = {}
    for metric in registry.list_metrics(POLICY_OBJECT_CODE):
        result[metric.metric_code.split(".", 1)[1]] = metric.name
    return result


def _field_label(names: dict[str, str], field: str) -> str:
    """业务可读字段标签：'人员类别（psn_type）'；注册表未登记时回退为字段名本身。"""
    cn = names.get(field)
    return f"{cn}（{field}）" if cn and cn != field else field


def _domain_values(registry: SemanticRegistry, domain_code: str) -> list[str]:
    domain = registry.get_value_domain(domain_code)
    return list(domain.standard_values) if domain else []


def _make_signal(
    field: str,
    *,
    source_ref: str,
    doc_id: str,
    unit_id: str,
    extraction_id: str,
    excerpt: str,
    concept: str,
    diagnosis: str,
    values: list[str],
    kind: str,
    trigger: TriggerSource = TriggerSource.EXTRACTION_UNKNOWN,
    table_name: str | None = None,
    field_name: str | None = None,
    rule_ids: list[str] | None = None,
    non_null_rate: float | None = None,
    distinct_count: int | None = None,
    extracted_values: list[str] | None = None,
) -> DiscoverySignal:
    return DiscoverySignal(
        trigger_source=trigger,
        evidence=DiscoveryEvidence(
            source_ref=source_ref,
            evidence_kind="database" if trigger == TriggerSource.DATA_SCAN else "policy",
            doc_id=doc_id or None,
            unit_id=unit_id or None,
            extraction_id=extraction_id or None,
            excerpt=excerpt or None,
            sample_values=list(values),
            extracted_values=list(extracted_values or []),
            table_name=table_name,
            field_name=field_name,
            rule_ids=rule_ids or [],
            observations=[f"detector:{kind}"],
            non_null_rate=non_null_rate,
            distinct_count=distinct_count,
        ),
        concept=concept,
        diagnosis=diagnosis,
        semantic_type="Enum",
        object_code=POLICY_OBJECT_CODE,
        metric_code=f"{POLICY_OBJECT_CODE}.{field}",
    )


def _iter_units(extractions: list[dict[str, Any]]):
    """只产出可重放的提取行（§4.2），并归一为规则列表。

    提取值位于 extracted_fields.rules[]（每条规则一份维度值）；
    顶层无字段键——旧实现读顶层导致全线误报「结构化缺失」。
    兼容扁平结构：顶层字段视为单条规则。
    """
    for row in extractions:
        text = row.get("source_text") or ""
        if not text.strip():
            continue
        if not (row.get("doc_id") and row.get("extraction_id") and row.get("unit_id")):
            continue
        fields = row.get("extracted_fields") or {}
        rules = fields.get("rules")
        if isinstance(rules, list) and rules and all(isinstance(r, dict) for r in rules):
            yield row, rules, text
        else:
            yield row, [fields], text


def _rule_values(rules: list[dict[str, Any]], field: str) -> list[str]:
    """某维度字段在全部规则中的非空取值（保序去重）。"""
    seen: list[str] = []
    for rule in rules:
        raw = rule.get(field)
        if isinstance(raw, str) and raw.strip() and raw.strip() not in seen:
            seen.append(raw.strip())
    return seen


def _detect_axis_value_conflict(
    extractions: list[dict[str, Any]], registry: SemanticRegistry, dims: dict[str, str],
    names: dict[str, str],
) -> list[DiscoverySignal]:
    """1 同一维度字段的值跨多个已发布值域 → 轴承载了不同角色。"""
    signals: list[DiscoverySignal] = []
    for row, rules, text in _iter_units(extractions):
        for field, domain_code in dims.items():
            for value in _rule_values(rules, field):
                # 值同时出现在另一个已发布值域 → 字段承载了不同角色
                others = [
                    code for code in set(dims.values())
                    if code != domain_code and value in _domain_values(registry, code)
                ]
                if others:
                    signals.append(_make_signal(
                        field,
                        source_ref=f"det:axis:{row.get('extraction_id')}:{field}",
                        doc_id=row.get("doc_id", ""),
                        unit_id=row.get("unit_id", ""),
                        extraction_id=row.get("extraction_id", ""),
                        excerpt=text[:300],
                        concept=names.get(field) or field,
                        diagnosis=(
                            f"{_field_label(names, field)}的取值与其他业务口径冲突，"
                            f"疑似字段角色混用（值「{value}」同属 {len(others) + 1} 个值域）"
                        ),
                        values=[value],
                        kind="axis_value_conflict",
                        extracted_values=_rule_values(rules, field),
                    ))
    return signals


def _detect_structure_compression(
    extractions: list[dict[str, Any]], registry: SemanticRegistry, dims: dict[str, str],
    names: dict[str, str],
) -> list[DiscoverySignal]:
    """2 原文区分多个类别值，但结构化结果缺失或只保留部分值。

    提取落值取 rules[] 内该字段的全部取值；全部覆盖则不报（回归线上误报）。
    """
    signals: list[DiscoverySignal] = []
    all_domain_values: dict[str, list[str]] = {
        domain: _domain_values(registry, domain) for domain in set(dims.values())
    }
    for row, rules, text in _iter_units(extractions):
        for field, domain_code in dims.items():
            mentioned = [
                v for v in all_domain_values.get(domain_code, [])
                if v and v in text
            ]
            if len(mentioned) < 2:
                continue
            extracted = _rule_values(rules, field)
            if all(v in extracted for v in mentioned):
                continue  # 区分已完整保留
            signals.append(_make_signal(
                field,
                source_ref=f"det:compress:{row.get('extraction_id')}:{field}",
                doc_id=row.get("doc_id", ""),
                unit_id=row.get("unit_id", ""),
                extraction_id=row.get("extraction_id", ""),
                excerpt=text[:300],
                concept=names.get(field) or field,
                diagnosis=(
                    f"政策原文对{_field_label(names, field)}作了明确区分"
                    f"（{'、'.join(mentioned)}），但结构化结果缺失或只保留了单一值"
                ),
                values=mentioned,
                kind="structure_compression",
                extracted_values=extracted,
            ))
    return signals


def _normalized_excerpt_key(text: str) -> str:
    return re.sub(r"\s+", "", text or "")[:80]


def _detect_cross_unit_inconsistency(
    extractions: list[dict[str, Any]], registry: SemanticRegistry, dims: dict[str, str],
    names: dict[str, str],
) -> list[DiscoverySignal]:
    """3 近似政策表达在不同单元落位到不同维度字段。"""
    by_excerpt: dict[str, list[tuple[dict, dict]]] = {}
    for row, rules, _text in _iter_units(extractions):
        key = _normalized_excerpt_key(row.get("source_text", ""))
        if key:
            by_excerpt.setdefault(key, []).append((row, rules))
    signals: list[DiscoverySignal] = []
    for key, group in by_excerpt.items():
        if len({row.get("unit_id") for row, _ in group}) < 2:
            continue
        used_fields_per_unit = [
            {f for f in dims if _rule_values(rules, f)}
            for _, rules in group
        ]
        # 至少一个单元有维度且各单元维度集合互不一致
        if not any(used_fields_per_unit):
            continue
        distinct_sets = {frozenset(s) for s in used_fields_per_unit}
        if len(distinct_sets) > 1:
            row, rules = group[0]
            differing = sorted(set().union(*distinct_sets))
            diff_labels = "、".join(_field_label(names, f) for f in differing[:5])
            signals.append(_make_signal(
                differing[0] if differing else "unknown",
                source_ref=f"det:crossunit:{key[:40]}",
                doc_id=row.get("doc_id", ""),
                unit_id=",".join(sorted({r.get("unit_id", "") for r, _ in group}))[:100],
                extraction_id=row.get("extraction_id", ""),
                excerpt=row.get("source_text", "")[:300],
                concept=names.get(differing[0]) or differing[0] if differing else "未知字段",
                diagnosis=f"相同的政策表述在不同条款被映射到不同字段（涉及：{diff_labels}）",
                values=differing[:5],
                kind="cross_unit_inconsistency",
            ))
    return signals


def _detect_subject_pollution(
    extractions: list[dict[str, Any]], registry: SemanticRegistry, dims: dict[str, str],
    names: dict[str, str],
) -> list[DiscoverySignal]:
    """4 维度字段承载结果类值（数字/比例词）→ 主体与条件互相污染。"""
    signals: list[DiscoverySignal] = []
    for row, rules, text in _iter_units(extractions):
        for field in dims:
            for value in _rule_values(rules, field):
                polluted = _NUMERIC_VALUE.fullmatch(value) or any(
                    word in value and len(value) > 6 for word in _RESULT_WORDS
                )
                if polluted:
                    signals.append(_make_signal(
                        field,
                        source_ref=f"det:pollute:{row.get('extraction_id')}:{field}",
                        doc_id=row.get("doc_id", ""),
                        unit_id=row.get("unit_id", ""),
                        extraction_id=row.get("extraction_id", ""),
                        excerpt=f"{text[:200]}[extracted:{field}={value}]",
                        concept=names.get(field) or field,
                        diagnosis=(
                            f"{_field_label(names, field)}疑似写入了比例/金额等结果值"
                            f"（「{value}」），条件与结果语义混杂"
                        ),
                        values=[value],
                        kind="subject_pollution",
                    ))
    return signals


def _detect_value_domain_violation(
    extractions: list[dict[str, Any]], registry: SemanticRegistry, dims: dict[str, str],
    names: dict[str, str],
) -> list[DiscoverySignal]:
    """5 抽取值不属于已发布值域且无映射来源。"""
    signals: list[DiscoverySignal] = []
    domain_cache: dict[str, set[str]] = {}
    mapping_cache: dict[str, set[str]] = {}
    for domain in set(dims.values()):
        domain_cache[domain] = set(_domain_values(registry, domain))
        mapping_cache[domain] = {
            m.standard_value for m in registry.get_value_mappings(domain)
        }
    for row, rules, text in _iter_units(extractions):
        for field, domain_code in dims.items():
            for value in _rule_values(rules, field):
                legal = domain_cache.get(domain_code, set()) | mapping_cache.get(domain_code, set())
                if legal and value not in legal:
                    signals.append(_make_signal(
                        field,
                        source_ref=f"det:violation:{row.get('extraction_id')}:{field}:{value}",
                        doc_id=row.get("doc_id", ""),
                        unit_id=row.get("unit_id", ""),
                        extraction_id=row.get("extraction_id", ""),
                        excerpt=text[:300],
                        concept=names.get(field) or field,
                        diagnosis=f"{_field_label(names, field)}出现值域外取值「{value}」",
                        values=[value],
                        kind="value_domain_violation",
                        extracted_values=_rule_values(rules, field),
                    ))
    return signals


def _detect_business_role_conflict(
    db_fields: list[dict[str, Any]], registry: SemanticRegistry, dims: dict[str, str],
) -> list[DiscoverySignal]:
    """6 同一物理字段的样本值跨多个值域 → 业务字段角色冲突（需库画像）。

    DATA_SCAN 证据门禁要求 non_null_rate/distinct_count，缺画像统计的字段跳过
    （生产扫描字段必含，不伪造统计值）。
    """
    if not db_fields:
        return []
    domain_values = {
        domain: [v for v in _domain_values(registry, domain) if v]
        for domain in set(dims.values())
    }
    signals: list[DiscoverySignal] = []
    for field in db_fields:
        samples = [str(v) for v in (field.get("sample_values") or []) if str(v).strip()]
        if len(samples) < 2:
            continue
        non_null_rate = field.get("non_null_rate")
        distinct_count = field.get("distinct_count")
        if non_null_rate is None or distinct_count is None:
            continue
        hit_domains = {
            domain: [v for v in values if v in samples]
            for domain, values in domain_values.items()
        }
        hit_domains = {d: v for d, v in hit_domains.items() if v}
        if len(hit_domains) >= 2:
            table = field.get("table_name", "")
            name = field.get("field_name", "")
            domains = sorted(hit_domains)
            signal = _make_signal(
                domains[0],
                source_ref=f"det:role:{table}.{name}",
                doc_id="", unit_id="", extraction_id="",
                excerpt=f"库字段 {table}.{name} 样本值跨值域: {domains}",
                concept=f"{table}.{name}",
                diagnosis=f"数据库字段 {table}.{name} 的样本值横跨多个业务值域，字段角色冲突",
                values=sorted({v for vs in hit_domains.values() for v in vs})[:8],
                kind="business_role_conflict",
                trigger=TriggerSource.DATA_SCAN,
                table_name=table,
                field_name=name,
                non_null_rate=float(non_null_rate),
                distinct_count=int(distinct_count),
            )
            signals.append(signal)
    return signals


def detect_signals(
    extractions: list[dict[str, Any]],
    registry: SemanticRegistry,
    db_fields: list[dict[str, Any]] | None = None,
) -> dict[str, list[DiscoverySignal]]:
    """运行六类检测器，返回 kind → 信号列表（未进簇，调用方负责 intake）。"""
    dims = _dimension_fields(registry)
    names = _dimension_names(registry)
    result: dict[str, list[DiscoverySignal]] = {
        "axis_value_conflict": _detect_axis_value_conflict(extractions, registry, dims, names),
        "structure_compression": _detect_structure_compression(extractions, registry, dims, names),
        "cross_unit_inconsistency": _detect_cross_unit_inconsistency(extractions, registry, dims, names),
        "subject_pollution": _detect_subject_pollution(extractions, registry, dims, names),
        "value_domain_violation": _detect_value_domain_violation(extractions, registry, dims, names),
        "business_role_conflict": _detect_business_role_conflict(db_fields or [], registry, dims),
    }
    return result
