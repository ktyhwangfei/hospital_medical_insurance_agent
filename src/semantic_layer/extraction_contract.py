"""政策管线提取契约：从语义层只读构建结构化提取 schema。

设计要点（[来源: docs/steering/政策知识管线设计文档.md §7.1 / §1.1]）：
- 单向只读依赖语义层；本模块不修改语义层状态。
- 只返回 status=published 的指标（draft 不进入契约）。
- 按 metric_kind 分流：field → fields / entity → entities / relation → relations。
- 值域字典（value_domain）解析为标准值列表，供政策提取与数据取数统一口径（语义拉齐）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.semantic_layer.registry import SemanticRegistry


# ── 契约模型（对应设计文档 §7.1 返回结构）──────────────────────

class FieldContract(BaseModel):
    """字段型指标契约：核心检索维度(indexed) 或详情字段。"""
    code: str
    name: str
    kind: Literal["field"] = "field"
    indexed: bool = False
    extraction_hint: Optional[str] = None
    value_domain: Optional[str] = None
    semantic_type: Optional[str] = None


class EntityContract(BaseModel):
    """实体型指标契约（metric_kind=entity，设计文档 D1：实体也是指标）。"""
    code: str
    name: str
    kind: Literal["entity"] = "entity"
    extraction_hint: Optional[str] = None
    value_domain: Optional[str] = None


class RelationContract(BaseModel):
    """关系型指标契约（metric_kind=relation）。三元组提示从 transformation 取。"""
    code: str
    name: str
    kind: Literal["relation"] = "relation"
    subject_hint: Optional[str] = None
    predicate_hint: Optional[str] = None
    object_hint: Optional[str] = None


class ExtractionSchema(BaseModel):
    """提取契约整体（§7.1 顶层结构）。"""
    schema_version: int = 1
    fields: list[FieldContract] = Field(default_factory=list)
    entities: list[EntityContract] = Field(default_factory=list)
    relations: list[RelationContract] = Field(default_factory=list)
    dictionaries: dict[str, list[str]] = Field(default_factory=dict)


# ── 契约构建 ──────────────────────────────────────────────────

def _short_code(metric_code: str) -> str:
    """zcgz.insu_type → insu_type（契约字段短码，与 Milvus dynamic field 名对齐）。"""
    return metric_code.split(".", 1)[1] if "." in metric_code else metric_code


def build_extraction_schema(
    registry: "SemanticRegistry", object_code: str = "zcgz"
) -> ExtractionSchema:
    """从语义层只读构建提取契约。

    只含 status=published 的指标；按 metric_kind 分组；解析值域字典。
    不修改语义层状态（单向只读依赖）。
    """
    store = registry._store
    published = [
        m for m in store.list_metrics(object_code=object_code) if m.status == "published"
    ]

    fields: list[FieldContract] = []
    entities: list[EntityContract] = []
    relations: list[RelationContract] = []

    for m in published:
        code = _short_code(m.metric_code)
        if m.metric_kind == "entity":
            entities.append(EntityContract(
                code=code, name=m.name,
                extraction_hint=m.extraction_hint, value_domain=m.value_domain,
            ))
        elif m.metric_kind == "relation":
            t = m.transformation or {}
            relations.append(RelationContract(
                code=code, name=m.name,
                subject_hint=t.get("subject_hint"),
                predicate_hint=t.get("predicate_hint"),
                object_hint=t.get("object_hint"),
            ))
        else:  # field（默认）
            fields.append(FieldContract(
                code=code, name=m.name, indexed=m.indexed,
                extraction_hint=m.extraction_hint, value_domain=m.value_domain,
                semantic_type=m.semantic_type,
            ))

    # 值域字典：published 指标引用的 value_domain → 标准值列表
    domain_codes = sorted({m.value_domain for m in published if m.value_domain})
    dictionaries: dict[str, list[str]] = {}
    for dc in domain_codes:
        vd = store.get_value_domain(dc)
        dictionaries[dc] = list(vd.standard_values) if vd else []

    schema_version = max((m.schema_version for m in published), default=1)
    return ExtractionSchema(
        schema_version=schema_version, fields=fields, entities=entities,
        relations=relations, dictionaries=dictionaries,
    )
