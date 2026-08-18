"""政策管线提取契约：从语义层只读构建结构化提取 schema。

设计要点（[来源: docs/steering/政策知识管线设计文档.md §7.1 / §1.1]）：
- 单向只读依赖语义层；本模块不修改语义层状态。
- 优先读取最新对象发布快照；未发布对象才兼容读取 status=published 的指标。
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

    优先使用最新不可变对象版本；未发布对象兼容使用 status=published 指标。
    按 metric_kind 分组并解析值域字典。
    不修改语义层状态（单向只读依赖）。
    """
    store = registry._store
    versions = registry.list_object_versions(object_code)
    published = list(versions[-1].metrics) if versions else [
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


# ── 提取质量约束（迭代 19 修改5：相对比例 / 跨单元引用 / 关键人群 / 多条件）──

EXTRACTION_QUALITY_GUIDANCE = """## 提取质量约束（必须遵守）
1. **相对比例与系数**：原文出现「…的60%」「为职工支付比例的60%」等相对表达时，必须提取比例数字（60%）并保留其与基数的引用关系（rule_value 描述计算逻辑，如“个人支付比例 = 职工支付比例 × 60%”），不得因非绝对数值而漏提。
2. **跨单元引用**：出现「上述比例」「按前款」「职工支付比例」等对前文条款的引用时，视为与本单元关联的约束条件，必须在 rule_value / relation 中体现该引用关系（subject=本单元主体, predicate=引用, object=被引用条款或数值）。
3. **关键人群强调**：psn_type 等人群标签（退休人员/在职职工/学生儿童等）只要在原文出现一次就必须提取，不得因句子简短而遗漏。
4. **多条件拆条**：一段文本含多个并列条件（医院等级 × 金额分段 × 人群 × 时间），每个条件组合拆成独立规则（一条规则 = 一个完整条件组合），不得合并或只取其一。
5. **比例规则形态统一（必须）**：一段原文（如「统筹基金支付85%，职工支付15%」）提取为**一条规则**，payment_ratio（基金）与 personal_payment_ratio（职工个人）作为该规则的字段同时填写，不得拆成两条；psn_type 按原文人群标注（原文写「职工」就标在职职工），不得按在职/退休重复提取；原文出现「退休人员个人支付比例为职工支付比例的60%」这类相对表达时，只提取该公式本身（rule_value 描述「个人支付比例 = 职工支付比例 × 60%」），不展开成各级医院、各费用段的绝对数值；禁止跨单元拼凑推导。
"""


UNKNOWN_CONCEPT_GUIDANCE = """## 未知概念（必须结构化返回）
每个事实都必须包含 `unknown_concepts` 数组；没有未知概念时返回空数组。只报告以下两类：
1. **完全新指标**：语义上无法归入上述任何字段（不是已有字段的细分取值）。
2. **枚举新取值或新别名**：能归入某个已有枚举字段，但不在其值域中，或只是已有标准值的新说法。

每项格式如下；不适用字段填 null。`excerpt` 必须逐字摘自原文；出现次数由系统按输入原文精确计数，无需输出：
{
  "concept": "原始概念串",
  "concept_type": "new_metric | new_enum_value | enum_alias",
  "metric_code": "新指标建议代码（完全新指标时填写，如 zcgz.xxx）",
  "metric_name": "新指标中文名",
  "definition": "新指标定义",
  "metric_type": "Atomic",
  "semantic_type": "Amount | Ratio | Enum | Date | Count | String",
  "unit": "单位或 null",
  "value_domain": "新 Enum 指标建议值域代码，否则 null",
  "indexed": false,
  "extraction_hint": "后续抽取提示",
  "axis_metric_code": "已有枚举指标完整代码（枚举新取值/别名时填写）",
  "domain_code": "已有枚举值域代码（枚举新取值/别名时填写）",
  "alias_target": "若为别名，填写已有标准值；否则 null",
  "excerpt": "原文精确片段",
  "confidence": 0.0
}
"""


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
    field_count = len(field_codes)
    return f"""你是一个医保政策分析专家。请从政策文本中提取所有"政策事实"，并从每个事实提取结构化规则。

## 提取字段（来自语义层 published 指标，schema_version={schema.schema_version}）
{fields_desc}

## 实体
{entities_desc}

## 关系
{relations_desc}

## 政策文件
{title}

## 原文
{text}

## 输出格式（硬性要求，逐字遵守）
返回 JSON 数组，每个事实含 fact_text + rules（每条 rule 附 entities 数组）：
[
  {{
    "fact_text": "完整事实描述",
    "rules": [
      {{
        {fields_json_example},
        "entities": [
          {{"name": "统筹基金支付比例", "entity_type": "RATIO", "highlight": "统筹基金支付85%"}}
        ]
      }}
    ],
    "unknown_concepts": []
  }}
]

**每条 rule 对象必须逐一包含上述全部 {field_count} 个字段作为键**，原文未提及的字段必须显式填空字符串 ""；**禁止省略任何字段键，禁止只输出部分字段**。输出前自检：每条 rule 的键数量必须等于 {field_count}（entities 不计入）。

**entities 必须输出**：每条 rule 都要带 `entities` 数组（没有实体时返回 `[]`）。每项含 `name`（实体全称，比例类实体必须带上归属主体，如"统筹基金支付比例"/"大额医疗互助资金支付比例"，不得只写"支付比例"）、`entity_type`、`highlight`（原文精确片段）。`entity_type` 取值：PERSON(人员), ORG(机构), SERVICE(医疗服务), AMOUNT(金额), RATIO(比例), DISEASE(病种), DRUG(药品), DATE(日期), CONDITION(条件), LOCATION(地点)。

{EXTRACTION_QUALITY_GUIDANCE}
{UNKNOWN_CONCEPT_GUIDANCE}
"""
