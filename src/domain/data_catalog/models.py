"""数据目录领域模型（Issue #38）。

数据资产目录：面向使用者的可发现、可理解、可信任资产视图。
三级资产：源表字段 → 语义对象/指标 → 消费方（skill/页面）。
资产为构建器刷新的快照，无审核状态机；血缘边在刷新时推导并落表
（``data_catalog_lineage_edges``），查询走索引而非全量推导。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CatalogAssetType(StrEnum):
    """数据资产类型（三级资产 + 源表 + 数据模型）。"""

    SOURCE_TABLE = "source_table"  # 源表/投影表/选表直通落地表
    SEMANTIC_OBJECT = "semantic_object"  # 语义对象（如 mzjyxx 门诊交易）
    METRIC = "metric"  # 语义指标（如 mzjyxx.T_FundPay）
    DATA_MODEL = "data_model"  # 数据模型（如 dwd_mz_settlement，V3.0 结构契约层）
    CONSUMER = "consumer"  # 消费方（skill / portal 页面）
    VECTOR_COLLECTION = "vector_collection"  # Milvus 向量集合（政策知识 RAG 资产）


class CatalogAsset(BaseModel):
    """数据资产（Entity）：目录中的一条可检索资产。

    ``asset_key`` 为自然唯一键（``{asset_type}:{业务标识}``），
    构建器按它幂等 upsert；``source_ref`` 携带溯源指针
    （数据集/表名/skill_id/页面路由等），``last_batch_id`` +
    ``semantic_version`` 支撑"溯源到数据批次与语义版本"验收。
    """

    model_config = ConfigDict(frozen=True)

    asset_id: str = Field(min_length=1, max_length=96)
    asset_type: CatalogAssetType
    asset_key: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="")
    owner: str = Field(default="", max_length=64)
    refresh_freq: str = Field(default="", max_length=64)
    tags: list[str] = Field(default_factory=list)
    value_ranges: dict[str, Any] = Field(default_factory=dict)
    sample_summary: dict[str, Any] = Field(default_factory=dict)
    semantic_object_code: str | None = Field(default=None, max_length=128)
    semantic_version: str | None = Field(default=None, max_length=64)
    last_batch_id: str | None = Field(default=None, max_length=64)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class CatalogColumn(BaseModel):
    """资产字段（Entity）：源表/向量集合的列级元数据。

    粒度到列是 DataHub/OpenMetadata 的基本能力；列随资产刷新整体替换，
    ``column_id`` 由 ``{asset_id}:{column_name}`` 确定性派生。
    """

    model_config = ConfigDict(frozen=True)

    column_id: str = Field(min_length=1, max_length=96)
    asset_id: str = Field(min_length=1, max_length=96)
    column_name: str = Field(min_length=1, max_length=256)
    name: str = Field(default="", max_length=256)
    data_type: str = Field(default="", max_length=64)
    field_role: str = Field(default="", max_length=32)
    nullable: bool = True
    value_domain: str | None = Field(default=None, max_length=128)
    ordinal: int = 0


class CatalogLineageEdge(BaseModel):
    """血缘边（Entity）：upstream 资产 → downstream 资产。

    刷新时由构建器从资产快照推导并整体重建落表；``edge_id`` 由
    ``{upstream}|{downstream}|{relation}`` 确定性派生，幂等。
    """

    model_config = ConfigDict(frozen=True)

    edge_id: str = Field(min_length=1, max_length=96)
    upstream_asset_id: str = Field(min_length=1, max_length=96)
    downstream_asset_id: str = Field(min_length=1, max_length=96)
    relation: str = Field(min_length=1, max_length=32)  # feeds / belongs_to / consumed_by
