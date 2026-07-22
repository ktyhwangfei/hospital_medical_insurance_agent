from __future__ import annotations

from typing import Any

from .models import PolicyFact, PolicyNode
from .utils import dumps_json


def join_non_empty(parts: list[Any], sep: str = " | ") -> str:
    return sep.join(str(x).strip() for x in parts if x is not None and str(x).strip())


def build_node_embedding_text(node: PolicyNode) -> str:
    parts = [
        f"政策标题：{node.policy_title}" if node.policy_title else None,
        f"条款路径：{node.path_text}" if node.path_text else None,
        f"摘要：{node.summary}" if node.summary else None,
        f"关键词：{'、'.join(node.keywords)}" if node.keywords else None,
        f"正文：{node.current_text}",
        f"上下文：{node.full_context_text}" if node.full_context_text else None,
    ]
    return "\n".join(p for p in parts if p)


def build_fact_embedding_text(fact: PolicyFact) -> str:
    value_text = ""
    if fact.amount is not None:
        value_text = f"金额：{fact.amount:g}{fact.unit if fact.unit != 'unknown' else ''}"
    elif fact.ratio is not None:
        value_text = f"比例：{fact.ratio:g}"
    elif fact.value is not None:
        value_text = f"数值：{fact.value}"
    elif fact.value_map is not None:
        value_text = f"数值映射：{dumps_json(fact.value_map)}"

    formula_text = ""
    if fact.formula:
        formula_text = f"公式：{dumps_json(fact.formula)}"

    parts = [
        "医保政策事实",
        f"政策标题：{fact.policy_title}" if fact.policy_title else None,
        f"事实类型：{fact.fact_type}",
        f"人群：{fact.population}" if fact.population != "unknown" else None,
        f"服务类型：{fact.service_type}" if fact.service_type != "unknown" else None,
        f"医院等级：{fact.hospital_level}" if fact.hospital_level != "unknown" else None,
        f"住院次数：{fact.admission_order}" if fact.admission_order != "unknown" else None,
        value_text,
        formula_text,
        f"关键词：{'、'.join(fact.keywords)}" if fact.keywords else None,
        f"原文：{fact.evidence_text}" if fact.evidence_text else None,
    ]
    return join_non_empty(parts)
