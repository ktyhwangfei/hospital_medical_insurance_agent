"""数据模型（Data Model）领域模型 — 架构设计 V3.0 §4。

定位：数据模型是可信数据的**结构契约**——粒度 + 字段 + 角色 + 多源标准化映射，
介于 ODS 与语义层之间的独立一层。语义指标经 model_field_ref 绑定模型字段；
治理 Flow 以数据模型为物化输出契约（Slice 2）。

边界（冻结）：
- 数据模型只描述结构，不含业务口径（口径在语义层指标定义）；
- 映射只描述「物理列 → 模型字段」的标准化规则，不含加工编排（编排在 Flow）；
- 状态机：draft → published → deprecated（终态），published 模型不可删只可退役。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

_CODE_RE = r"^[a-z][a-z0-9_]{1,63}$"


class DataModelLayer(StrEnum):
    """数仓分层白名单。"""

    ODS = "ods"
    DWD = "dwd"
    DWS = "dws"
    ADS = "ads"


class DataModelStatus(StrEnum):
    """状态机：draft → pending_review → published → deprecated（终态）。"""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class ModelFieldRole(StrEnum):
    """模型字段角色白名单（与语义层 field_role 口径一致）。"""

    IDENTIFIER = "identifier"
    DIMENSION = "dimension"
    FACT = "fact"
    DATETIME = "datetime"


class MappingStatus(StrEnum):
    """映射确认流：draft（系统/录入候选）→ confirmed（人工确认生效）。"""

    DRAFT = "draft"
    CONFIRMED = "confirmed"


class DataModelNotFoundError(ValueError):
    """模型或映射不存在。"""


class DataModelConflictError(ValueError):
    """乐观锁冲突 / 唯一约束冲突。"""


class DataModelStateInvalidError(ValueError):
    """状态机非法流转或结构不满足发布门槛。"""


class DataModelField(BaseModel):
    """数据模型字段（值对象）。"""

    field_code: str = Field(pattern=_CODE_RE)
    name: str = Field(min_length=1, max_length=128)
    data_type: str = Field(min_length=1, max_length=64)
    field_role: ModelFieldRole
    value_domain: Optional[str] = None
    # DWS 派生字段：expression + dependencies（与语义层派生指标同构，AST 安全渲染在编译期）
    expression: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)


class DataModel(BaseModel):
    """数据模型（聚合根）。fields 随模型文档整体编辑（与 Flow nodes 同模式）。"""

    model_code: str = Field(pattern=_CODE_RE)
    name: str = Field(min_length=1, max_length=128)
    layer: DataModelLayer
    grain: str = Field(min_length=1, max_length=128)
    entity_code: str = Field(min_length=1, max_length=64)
    status: DataModelStatus = DataModelStatus.DRAFT
    owner: str = Field(min_length=1, max_length=128)
    description: str = ""
    fields: list[DataModelField] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    content_hash: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @model_validator(mode="after")
    def _validate_structure(self) -> "DataModel":
        codes = [f.field_code for f in self.fields]
        if len(codes) != len(set(codes)):
            raise DataModelStateInvalidError("字段编码重复")
        known = set(codes)
        identifiers = [f for f in self.fields if f.field_role is ModelFieldRole.IDENTIFIER]
        if self.fields and self.grain not in {f.field_code for f in identifiers}:
            raise DataModelStateInvalidError(
                f"粒度字段 '{self.grain}' 必须声明为 identifier 角色字段"
            )
        for field in self.fields:
            unknown = [d for d in field.dependencies if d not in known]
            if unknown:
                raise DataModelStateInvalidError(
                    f"字段 '{field.field_code}' 的依赖未在模型内声明: {unknown}"
                )
            if field.expression and field.field_role is not ModelFieldRole.FACT:
                raise DataModelStateInvalidError("派生表达式仅允许 fact 角色字段")
        return self


class DataModelMapping(BaseModel):
    """多源映射（实体）：一个模型字段 ← 某数据源的物理列。

    transform_rule 为空 = 直通；值域码表映射/单位换算等标准化规则显式声明。
    """

    model_code: str = Field(pattern=_CODE_RE)
    field_code: str = Field(pattern=_CODE_RE)
    source_id: str = Field(min_length=1, max_length=64)
    physical_table: str = Field(min_length=1, max_length=128)
    physical_column: str = Field(min_length=1, max_length=128)
    transform_rule: Optional[str] = None
    status: MappingStatus = MappingStatus.DRAFT
    revision: int = Field(default=1, ge=1)
    updated_at: Optional[str] = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_model_content_hash(model: DataModel) -> str:
    """结构内容哈希：物化产物锁定的证据锚点（Slice 2 复用）。"""
    payload = model.model_dump(
        mode="json",
        exclude={"revision", "content_hash", "created_at", "updated_at"},
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def validate_for_publish(model: DataModel) -> None:
    """发布门槛：字段非空、粒度合法的 identifier 存在。

    纯维度/登记类模型（如诊断、病人登记）无 fact 字段属合法形态，
    不强制；消费侧需要度量时由语义层指标绑定校验。"""
    if not model.fields:
        raise DataModelStateInvalidError("发布门槛：模型字段不能为空")
    identifiers = [f for f in model.fields if f.field_role is ModelFieldRole.IDENTIFIER]
    if not identifiers:
        raise DataModelStateInvalidError("发布门槛：至少声明一个 identifier 字段")
