"""schema 演化执行器：把指标加/改/删应用到历史 policy_rules（设计文档 §6）。

三策略（§6.2）：
- incremental: 加字段，只提取新字段，已审核字段冻结保护
- full:        改字段语义，整条重提取（无视冻结，旧值失效）
- soft_delete: 删字段，数据保留按 schema_version 忽略

Milvus 硬约束（§6.1）：不支持 partial update → 只能 read-modify-write + upsert 整条。
本模块的 apply_* 是纯函数（dict → dict），不碰 IO，便于单测；read/write/LLM 由
SchemaUpdateExecutor 编排（可注入，见下方）。

[来源: docs/steering/政策知识管线设计.md §6]
"""
from __future__ import annotations

from typing import Any

from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    CORE_DIM_FIELDS, FieldTrace,
)

# 受保护字段：不可被 apply_* 覆写（PK / 向量 / 版本由策略单独管理）
_PROTECTED = {"rule_id", "vector", "schema_version"}


def _set_field(
    entity: dict[str, Any],
    code: str,
    value: Any,
    extracted_at: str,
    schema_version: int,
    confidence: float,
) -> None:
    """写字段：核心维度 → 顶层标量；详情字段 → FieldTrace dict。"""
    if code in _PROTECTED:
        return
    if code in CORE_DIM_FIELDS:
        entity[code] = str(value)
    else:
        entity[code] = FieldTrace(
            value=value, extracted_at=extracted_at,
            schema_version=schema_version, confidence=confidence,
        ).model_dump()


def apply_incremental(
    entity: dict[str, Any],
    extracted_fields: dict[str, Any],
    frozen_field_codes: set[str],
    extracted_at: str,
    schema_version: int,
    confidence: float,
) -> dict[str, Any]:
    """增量策略：用新提取值覆盖非冻结字段；冻结字段保留旧 FieldTrace（冻结保护）。"""
    for code, value in extracted_fields.items():
        if code in frozen_field_codes:
            continue
        _set_field(entity, code, value, extracted_at, schema_version, confidence)
    entity["schema_version"] = schema_version
    return entity


def apply_full(
    entity: dict[str, Any],
    new_rule: dict[str, Any],
    extracted_at: str,
    schema_version: int,
    confidence: float,
) -> dict[str, Any]:
    """全量策略：整条用新提取值覆盖（无视冻结，旧值失效）；rule_id/vector 保留。"""
    for code, value in new_rule.items():
        _set_field(entity, code, value, extracted_at, schema_version, confidence)
    entity["schema_version"] = schema_version
    return entity


def apply_soft_delete(
    entity: dict[str, Any],
    deleted_field_codes: set[str],
    schema_version: int,
) -> dict[str, Any]:
    """软删策略：字段数据保留（历史溯源不丢），仅 bump schema_version。

    实际"忽略"由查询端按当前 schema（不含已删字段）+ entity.schema_version 判断。
    [设计文档 §6.2：数据保留，按 schema_version 忽略]
    """
    entity["schema_version"] = schema_version
    return entity


# ── 批量编排 + read-modify-write（P5.2）────────────────────────

def update_rules(
    entities: list[dict[str, Any]],
    strategy: str,
    *,
    new_values: dict[str, Any] | None = None,
    frozen_field_codes: set[str] | None = None,
    deleted_field_codes: set[str] | None = None,
    extracted_at: str = "",
    schema_version: int = 1,
    confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """对一批 entities 批量应用策略（纯编排，不碰 IO）。"""
    new_values = new_values or {}
    frozen_field_codes = frozen_field_codes or set()
    deleted_field_codes = deleted_field_codes or set()
    for entity in entities:
        if strategy == "incremental":
            apply_incremental(entity, new_values, frozen_field_codes,
                              extracted_at, schema_version, confidence)
        elif strategy == "full":
            apply_full(entity, new_values, extracted_at, schema_version, confidence)
        elif strategy == "soft_delete":
            apply_soft_delete(entity, deleted_field_codes, schema_version)
        # 未知策略：不修改（安全降级）
    return entities


class SchemaUpdateExecutor:
    """编排 schema 演化的 read-modify-write（设计文档 §6.1/§6.3）。

    read/write 均可注入（测试用 mock，生产用 Milvus 实现）。
    LLM 提取（incremental/full 的新值）由调用方以 new_values 传入，
    使本类不直接耦合 ModelGateway，便于单测。
    """

    def __init__(self, reader=None, writer=None):
        self._reader = reader  # callable(doc_id) -> list[entity]
        self._writer = writer  # callable(entities) -> int（写入条数）

    def evolve(
        self,
        doc_id: str,
        strategy: str,
        *,
        new_values: dict[str, Any] | None = None,
        frozen_field_codes: set[str] | None = None,
        deleted_field_codes: set[str] | None = None,
        extracted_at: str = "",
        schema_version: int = 1,
        confidence: float = 0.0,
    ) -> dict[str, Any]:
        """对 doc 下所有 rules 应用策略：read → modify → write。

        Returns: {"processed": 写入条数, "total": 读取条数}
        """
        entities = self._reader(doc_id) if self._reader else []
        update_rules(
            entities, strategy, new_values=new_values,
            frozen_field_codes=frozen_field_codes,
            deleted_field_codes=deleted_field_codes,
            extracted_at=extracted_at, schema_version=schema_version,
            confidence=confidence,
        )
        written = self._writer(entities) if self._writer else 0
        return {"processed": written, "total": len(entities)}
