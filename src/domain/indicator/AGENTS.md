# indicator/ — 指标领域模型

## 概述
语义层领域模型定义，遵循 DDD 分层。纯数据结构（Pydantic / frozen dataclass），无引擎逻辑。

## 结构
```
indicator/
├── __init__.py
├── AGENTS.md
└── models.py    # IndicatorDefinition（Entity）、IndicatorValue（Value Object）、DictionaryEntry（Value Object）
```

## 通用语言字典

| 中文术语 | 英文命名 | DDD 战术分类 | 类型 | 说明 |
|---------|---------|-------------|------|------|
| 指标定义 | `IndicatorDefinition` | **Entity** | Pydantic `BaseModel` | 指标的静态元数据，对应 Excel 政策规则表的一行，由 indicator_id 唯一标识 |
| 指标值 | `IndicatorValue` | **Value Object** | Pydantic `BaseModel` | 指标的运行时取值实例，附置信度和时间戳 |
| 指标上下文 | `IndicatorContext` | **Value Object** | Pydantic `BaseModel` | 某次查询的完整指标快照，含所有已取值和缺失列表 |
| 指标分类 | `IndicatorCategory` | **Value Object** | `StrEnum` | dimension / numeric / condition / meta |
| 加工类型 | `ProcessingType` | **Value Object** | `StrEnum` | 分词 / raw |
| 指标来源 | `IndicatorSource` | **Value Object** | `@dataclass(frozen=True)` | 指标的取值来源类型和参数 |
| 标准化规则 | `NormalizationRule` | **Value Object** | `@dataclass(frozen=True)` | 指标的标准化转换规则 |
| 字典条目 | `DictionaryEntry` | **Value Object** | Pydantic `BaseModel` | 标准化字典的一条记录，含标准值、同义词列表和描述 |

## 关键约定
- IndicatorDefinition 使用 Pydantic BaseModel（类似 domain/skill/models.py 的 Skill），带 field_validator
- IndicatorValue / IndicatorContext 使用 Pydantic BaseModel（DTO，运行时可变）
- IndicatorSource / NormalizationRule 使用 @dataclass(frozen=True)（Value Object，不可变）
- indicator_id 使用 snake_case，与数据模型1的"字段名称"列对齐
- 引擎逻辑在 src/semantic_layer/，不在本包中
