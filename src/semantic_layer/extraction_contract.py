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


SCHEMA_EXTRACTION_PROMPT_TEMPLATE = """你是一个医保政策分析专家。请从政策文本中提取所有"政策事实"，并从每个事实提取结构化规则。

## 提取字段（来自语义层 published 指标，schema_version={schema_version}）
{fields_desc}

## 实体
{entities_desc}

## 关系
{relations_desc}

## 政策文件
{title}

## 原文
{text}

## 输出格式
返回 JSON 数组，每个事实含 fact_text + rules（rules 含上述字段 {field_codes}，原文未提及填空字符串""）：
[
  {{
    "fact_text": "完整事实描述",
    "rules": [{{ {fields_json_example} }}]
  }}
]
"""


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


def build_prompt_from_schema(text: str, title: str, schema: ExtractionSchema) -> str:
    """从提取契约动态拼 LLM 提示词（schema-driven，加维度不改此函数）。

    [来源: §3.1 extraction_hint 动态拼 prompt；§7.1 契约结构]
    """
    # 字段说明（核心检索维度 + 详情字段）
    if schema.fields:
        fields_desc = "\n".join(
            f"- {f.code}（{f.name}）"
            + (f"：{f.extraction_hint}" if f.extraction_hint else "")
            + (f" 值域：{', '.join(schema.dictionaries[f.value_domain])}"
               if f.value_domain and f.value_domain in schema.dictionaries else "")
            for f in schema.fields
        )
    else:
        fields_desc = "（无 published 字段——请先 publish_object）"

    # 实体说明
    entities_desc = "\n".join(
        f"- {e.code}（{e.name}）" + (f"：{e.extraction_hint}" if e.extraction_hint else "")
        for e in schema.entities
    ) or "（无）"

    # 关系说明（三元组）
    relations_desc = "\n".join(
        f"- {r.code}：({r.subject_hint}, {r.predicate_hint}, {r.object_hint})"
        for r in schema.relations
    ) or "（无）"

    field_codes = [f.code for f in schema.fields]
    fields_json_example = ", ".join(f'"{c}": ""' for c in field_codes)
    return SCHEMA_EXTRACTION_PROMPT_TEMPLATE.format(
        schema_version=schema.schema_version,
        fields_desc=fields_desc,
        entities_desc=entities_desc,
        relations_desc=relations_desc,
        title=title,
        text=text,
        field_codes=field_codes,
        fields_json_example=fields_json_example,
    )
