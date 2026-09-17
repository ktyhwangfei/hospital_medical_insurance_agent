"""数据模型建模 API — 数据治理中心 · 数据建模阶段（架构设计 V3.0 §4）。

前缀 /api/v1/medical-insurance-ai-agent/data-governance/models；
权限复用数据治理 data_governance:read/write；
错误码：404 DATA_MODEL_NOT_FOUND / 409 DATA_MODEL_CONFLICT / 422 DATA_MODEL_STATE_INVALID。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.data_platform.storage.data_model.data_model_factory import get_data_model_storage
from src.domain.data_model.models import (
    DataModel,
    DataModelConflictError,
    DataModelMapping,
    DataModelNotFoundError,
    DataModelStateInvalidError,
)
from src.runtime.api.data_governance_routes import (
    require_data_governance_read,
    require_data_governance_write,
)
from src.runtime.data_governance.modeling.service import DataModelingService
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/data-governance/models",
    tags=["data-modeling"],
)


def get_data_modeling_service() -> DataModelingService:
    """依赖注入 seam：API 测试 override 此函数注入内存存储。"""
    return DataModelingService(get_data_model_storage())


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DataModelNotFoundError):
        return HTTPException(status_code=404, detail=error_detail(
            "DATA_MODEL_NOT_FOUND", str(exc), {},
        ))
    if isinstance(exc, DataModelConflictError):
        return HTTPException(status_code=409, detail=error_detail(
            "DATA_MODEL_CONFLICT", str(exc), {},
        ))
    if isinstance(exc, DataModelStateInvalidError):
        return HTTPException(status_code=422, detail=error_detail(
            "DATA_MODEL_STATE_INVALID", str(exc), {},
        ))
    logger.exception("data modeling api unexpected error")
    return HTTPException(status_code=500, detail=error_detail(
        "DATA_MODEL_STATE_INVALID", f"未预期错误: {exc}", {},
    ))


ModelingService = DataModelingService


@router.get("")
def list_models(
    _: object = Depends(require_data_governance_read),
    service: ModelingService = Depends(get_data_modeling_service),
) -> list[DataModel]:
    return service.list_models()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_model(
    model: DataModel,
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> DataModel:
    try:
        return service.create_model(model)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/{model_code}")
def get_model(
    model_code: str,
    _: object = Depends(require_data_governance_read),
    service: ModelingService = Depends(get_data_modeling_service),
) -> DataModel:
    try:
        return service.get_model(model_code)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/{model_code}")
def update_model(
    model_code: str,
    model: DataModel,
    expected_revision: int = Query(..., ge=1),
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> DataModel:
    try:
        return service.update_model(model_code, model, expected_revision)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/{model_code}")
def delete_model(
    model_code: str,
    expected_revision: int = Query(..., ge=1),
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> dict:
    try:
        service.delete_model(model_code, expected_revision)
        return {"deleted": model_code}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{model_code}/submit-review")
def submit_model_review(
    model_code: str,
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> DataModel:
    try:
        return service.submit_review(model_code)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{model_code}/publish")
def publish_model(
    model_code: str,
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> DataModel:
    try:
        return service.publish_model(model_code)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{model_code}/deprecate")
def deprecate_model(
    model_code: str,
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> DataModel:
    try:
        return service.deprecate_model(model_code)
    except Exception as exc:
        raise _http_error(exc) from exc


# ── 多源映射 ────────────────────────────────────────────────────────

@router.get("/{model_code}/mappings")
def list_mappings(
    model_code: str,
    _: object = Depends(require_data_governance_read),
    service: ModelingService = Depends(get_data_modeling_service),
) -> list[DataModelMapping]:
    try:
        return service.list_mappings(model_code)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/{model_code}/mappings")
def save_mapping(
    model_code: str,
    mapping: DataModelMapping,
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> DataModelMapping:
    try:
        if mapping.model_code != model_code:
            raise DataModelStateInvalidError("model_code 路径与载荷不一致")
        return service.save_mapping(mapping)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{model_code}/mappings/{field_code}/{source_id}/confirm")
def confirm_mapping(
    model_code: str,
    field_code: str,
    source_id: str,
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> DataModelMapping:
    try:
        return service.confirm_mapping(model_code, field_code, source_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/{model_code}/mappings/{field_code}/{source_id}")
def delete_mapping(
    model_code: str,
    field_code: str,
    source_id: str,
    expected_revision: int = Query(..., ge=1),
    _: object = Depends(require_data_governance_write),
    service: ModelingService = Depends(get_data_modeling_service),
) -> dict:
    try:
        service.delete_mapping(model_code, field_code, source_id, expected_revision)
        return {"deleted": f"{model_code}.{field_code}@{source_id}"}
    except Exception as exc:
        raise _http_error(exc) from exc
