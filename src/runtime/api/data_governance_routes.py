"""门诊数据治理控制面 API。"""
from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
from typing import Annotated, Callable, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse

from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceConflictError,
    OutpatientGovernanceNotFoundError,
    OutpatientGovernanceStore,
)
from src.data_platform.storage.postgresql.outpatient_store import OutpatientPostgresStore
from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import (
    CdcProbeResponse,
    CdcProbeResult,
    ConnectionProbeResponse,
    ConnectionProbeResult,
    CreateDataSourceRequest,
    DataGovernanceOverviewResponse,
    DataGovernancePrincipal,
    DataSourceListResponse,
    DataSourceListResult,
    DataSourceResponse,
    PostgresTargetResponse,
    RotateDataSourceCredentialRequest,
    SaveSyncJobRequest,
    SyncJobResponse,
    SyncRunListResponse,
    SyncRunListResult,
    UpdateDataSourceRequest,
)
from src.shared.schemas.responses import error_detail
from src.runtime.data_governance.service import (
    CdcNotReadyError,
    CreateDataSourceCommand,
    DataGovernanceService,
    SyncJobInvalidStateError,
)
from src.runtime.discovery.sqlserver_source import _try_connect
from src.security.data_source_credentials import DataSourceCredentialError


router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/data-governance",
    tags=["data-governance"],
)
T = TypeVar("T")


@lru_cache(maxsize=1)
def get_data_governance_service() -> DataGovernanceService:
    """构造生产控制面；密钥缺失时保持端点关闭。"""
    try:
        def connect(source, password):
            connection, _driver = _try_connect({
                "host": source.host,
                "port": source.port,
                "database": source.database,
                "user": source.username,
                "password": password,
            })
            return connection

        return DataGovernanceService(
            OutpatientGovernanceStore(),
            OutpatientPostgresStore(),
            connect,
        )
    except DataSourceCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("DATA_SOURCE_SECRET_UNAVAILABLE", str(exc)),
        ) from exc


def _require_permission(permission: str, authorization: str | None) -> DataGovernancePrincipal:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth = authenticator.validate_signed_token(authorization)
    if not auth.is_success or not auth.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_INVALID", auth.error_message or "登录凭据无效"),
        )
    permitted = authenticator.check_permission(auth, permission)
    if not permitted.is_success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("AUTH_FORBIDDEN", "权限不足"),
        )
    return DataGovernancePrincipal(
        user_id=auth.user_id,
        roles=auth.roles,
        permissions=auth.permissions,
    )


def require_data_governance_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> DataGovernancePrincipal:
    return _require_permission("data_governance:read", authorization)


def require_data_governance_write(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> DataGovernancePrincipal:
    return _require_permission("data_governance:write", authorization)


ReadPrincipal = Annotated[DataGovernancePrincipal, Depends(require_data_governance_read)]
WritePrincipal = Annotated[DataGovernancePrincipal, Depends(require_data_governance_write)]
GovernanceService = Annotated[DataGovernanceService, Depends(get_data_governance_service)]


def _call(action: Callable[[], T]) -> T:
    try:
        return action()
    except OutpatientGovernanceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("DATA_SOURCE_NOT_FOUND", str(exc)),
        ) from exc
    except OutpatientGovernanceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("DATA_SOURCE_CONFLICT", str(exc)),
        ) from exc
    except CdcNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("CDC_NOT_READY", str(exc)),
        ) from exc
    except SyncJobInvalidStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("SYNC_JOB_INVALID_STATE", str(exc)),
        ) from exc
    except DataSourceCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("DATA_SOURCE_SECRET_UNAVAILABLE", str(exc)),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("DATA_GOVERNANCE_UNAVAILABLE", "数据治理服务暂不可用"),
        ) from exc


@router.get("/overview", response_model=DataGovernanceOverviewResponse)
def get_overview(_: ReadPrincipal, service: GovernanceService):
    return DataGovernanceOverviewResponse(result=_call(service.overview))


@router.get("/data-sources", response_model=DataSourceListResponse)
def list_data_sources(_: ReadPrincipal, service: GovernanceService):
    return DataSourceListResponse(result=DataSourceListResult(items=_call(service.list_sources)))


@router.post(
    "/data-sources",
    response_model=DataSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_data_source(
    request: CreateDataSourceRequest,
    principal: WritePrincipal,
    service: GovernanceService,
):
    credential = request.credential
    command = CreateDataSourceCommand(
        **request.model_dump(exclude={"credential"}),
        credential_id=credential.credential_id,
        password=credential.password,
    )
    return DataSourceResponse(
        result=_call(lambda: service.create_source(command, principal.user_id))
    )


@router.patch("/data-sources/{source_id}", response_model=DataSourceResponse)
def update_data_source(
    source_id: str,
    request: UpdateDataSourceRequest,
    principal: WritePrincipal,
    service: GovernanceService,
):
    return DataSourceResponse(result=_call(
        lambda: service.update_source_config(source_id, request, principal.user_id)
    ))


@router.put("/data-sources/{source_id}/credential", response_model=DataSourceResponse)
def rotate_data_source_credential(
    source_id: str,
    request: RotateDataSourceCredentialRequest,
    principal: WritePrincipal,
    service: GovernanceService,
):
    return DataSourceResponse(result=_call(lambda: service.rotate_credential(
        source_id,
        request.credential_id,
        request.password.get_secret_value(),
        request.expected_revision,
        principal.user_id,
    )))


@router.post("/data-sources/{source_id}/test", response_model=ConnectionProbeResponse)
def test_data_source(
    source_id: str,
    _: WritePrincipal,
    service: GovernanceService,
):
    probe = _call(lambda: service.probe_connection(source_id))
    return ConnectionProbeResponse(result=ConnectionProbeResult(
        status=probe.status,
        error_code=probe.error_code,
        safe_message=probe.safe_message,
        checked_at=probe.checked_at,
    ))


@router.get("/data-sources/{source_id}/cdc-script")
def download_cdc_script(
    source_id: str,
    principal: WritePrincipal,
    service: GovernanceService,
):
    path = _call(service.cdc_script_path)
    _call(lambda: service.mark_waiting_dba(source_id, principal.user_id))
    return FileResponse(path, media_type="application/sql", filename=path.name)


@router.post("/data-sources/{source_id}/cdc-check", response_model=CdcProbeResponse)
def check_cdc(
    source_id: str,
    _: WritePrincipal,
    service: GovernanceService,
):
    probe = _call(lambda: service.probe_cdc(source_id))
    return CdcProbeResponse(result=CdcProbeResult.model_validate(asdict(probe)))


@router.get("/postgresql/status", response_model=PostgresTargetResponse)
def get_postgresql_status(_: ReadPrincipal, service: GovernanceService):
    return PostgresTargetResponse(result=_call(service.postgres_target_status))


@router.get("/sync-jobs/{source_id}", response_model=SyncJobResponse)
def get_sync_job(source_id: str, _: ReadPrincipal, service: GovernanceService):
    return SyncJobResponse(result=_call(lambda: service.get_job(source_id)))


@router.put("/sync-jobs/{source_id}", response_model=SyncJobResponse)
def save_sync_job(
    source_id: str,
    request: SaveSyncJobRequest,
    principal: WritePrincipal,
    service: GovernanceService,
):
    return SyncJobResponse(result=_call(
        lambda: service.save_job_config(source_id, request, principal.user_id)
    ))


@router.post("/sync-jobs/{source_id}/start", response_model=SyncJobResponse)
def start_sync_job(source_id: str, principal: WritePrincipal, service: GovernanceService):
    return SyncJobResponse(result=_call(lambda: service.start_job(source_id, principal.user_id)))


@router.post("/sync-jobs/{source_id}/pause", response_model=SyncJobResponse)
def pause_sync_job(source_id: str, principal: WritePrincipal, service: GovernanceService):
    return SyncJobResponse(result=_call(lambda: service.pause_job(source_id, principal.user_id)))


@router.post("/sync-jobs/{source_id}/run-once", response_model=SyncJobResponse)
def run_sync_job_once(source_id: str, principal: WritePrincipal, service: GovernanceService):
    return SyncJobResponse(result=_call(
        lambda: service.request_run_once(source_id, principal.user_id)
    ))


@router.get("/sync-jobs/{source_id}/runs", response_model=SyncRunListResponse)
def list_sync_runs(source_id: str, _: ReadPrincipal, service: GovernanceService):
    return SyncRunListResponse(result=SyncRunListResult(
        items=_call(lambda: service.list_runs(source_id))
    ))
