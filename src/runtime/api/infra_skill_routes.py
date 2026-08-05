import logging
import time
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.version_factory import get_skill_version_storage
from src.data_platform.storage.skill.version_ports import SkillVersionConflictError

logger = logging.getLogger(__name__)
from src.runtime.api.schemas import (
    FieldMappingItem,
    FieldMappingResponse,
    InfraSkillCatalogResponse,
    InfraSkillOverviewItem,
    InfraSkillOverviewResponse,
    InfraSkillDetailResponse,
    InfraSkillFilesStructure,
    InfraSkillItem,
    SkillExecuteTestRequest,
    SkillExecuteTestResponse,
    SkillRefreshResponse,
    SkillRouteTestRequest,
    SkillRouteTestResponse,
    SkillVersionResponse,
    SkillVersionSyncRequest,
)
from src.runtime.skill_management.version_service import (
    SkillNotFoundError,
    SkillVersionService,
)
from src.shared.schemas.responses import error_detail
from src.skill_infra.artifact import SkillArtifactError
from src.skill_infra.skill_loader import get_loader, refresh_loader
from src.skill_infra.skill_router import get_assembler
from src.skill_infra.unified_router import route_question_ranked

router = APIRouter()


def get_skill_version_service() -> SkillVersionService:
    return SkillVersionService(
        storage=get_skill_version_storage(),
        loader=get_loader(),
        skills_root=SKILLS_DIR,
    )


SkillVersionServiceDependency = Annotated[
    SkillVersionService, Depends(get_skill_version_service)
]


@router.get("/infra-skills", response_model=list[InfraSkillItem])
def list_infra_skills(
    business_action: str = Query(default="", description="按业务动作筛选（explain/query/guide/verify/compare/evaluate/analyze）"),
    business_object: str = Query(default="", description="按业务对象筛选（settlement/benefit/policy/directory/...）"),
) -> list[InfraSkillItem]:
    loader = get_loader()
    skills = loader.get_all()
    result = []
    for s_id, s in skills.items():
        if business_action and s.business_action != business_action:
            continue
        if business_object and s.business_object != business_object:
            continue
        result.append(
            InfraSkillItem(
                skill_id=s.skill_id,
                skill_name=s.skill_name,
                business_action=s.business_action,
                business_object=s.business_object,
                include_keywords=s.include_keywords,
                excluded_intents=s.excluded_intents,
            )
        )
    return result


@router.get("/infra-skills/catalog", response_model=InfraSkillCatalogResponse)
def list_infra_skill_catalog(
    service: SkillVersionServiceDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    business_action: str = Query(default=""),
    business_object: str = Query(default=""),
    artifact_status: str = Query(default=""),
    query: str = Query(default="", max_length=128),
) -> InfraSkillCatalogResponse:
    catalog = service.list_catalog(
        page=page,
        page_size=page_size,
        business_action=business_action,
        business_object=business_object,
        artifact_status=artifact_status,
        query=query,
    )
    return InfraSkillCatalogResponse.model_validate(catalog.model_dump())


def _list_files_in_dir(base_dir: Path, sub_dir: str) -> list[str]:
    target_dir = base_dir / sub_dir
    if not target_dir.exists() or not target_dir.is_dir():
        return []
    
    files = []
    for item in target_dir.iterdir():
        if item.name.startswith("__"):
            continue
        if item.is_dir():
            files.append(f"{item.name}/")
        else:
            files.append(item.name)
    return sorted(files)


def _read_field_mapping(skill_dir: Path) -> FieldMappingResponse | None:
    """读取技能包的 field_mapping.yaml，返回结构化字段映射数据。"""
    field_mapping_path = skill_dir / "field_mapping.yaml"
    if not field_mapping_path.exists():
        return None

    try:
        raw = yaml.safe_load(field_mapping_path.read_text(encoding="utf-8"))
        if not raw:
            return None

        target_field = raw.get("target_field", {})

        settlement_fields: dict[str, FieldMappingItem] = {}
        raw_settlement = raw.get("settlement_fields", {})
        if isinstance(raw_settlement, dict):
            for field_name, field_data in raw_settlement.items():
                if isinstance(field_data, dict):
                    settlement_fields[field_name] = FieldMappingItem(
                        label=field_data.get("label", ""),
                        description=field_data.get("description", ""),
                        db_source=field_data.get("db_source", ""),
                    )

        defaults = raw.get("defaults", {})

        return FieldMappingResponse(
            target_field=target_field,
            settlement_fields=settlement_fields,
            defaults=defaults,
        )
    except Exception:
        logger.exception("Failed to parse field_mapping.yaml for skill: %s", skill_dir.name)
        return None


@router.get("/infra-skills/overview", response_model=InfraSkillOverviewResponse)
def get_infra_skills_overview_early() -> InfraSkillOverviewResponse:
    return get_infra_skills_overview()


@router.get("/infra-skills/{skill_id}", response_model=InfraSkillDetailResponse)
def get_infra_skill_details(skill_id: str) -> InfraSkillDetailResponse:
    loader = get_loader()
    skill = loader.get(skill_id)
    if not skill:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_NOT_FOUND", "未找到该 Skill 包", {"skill_id": skill_id}),
        )

    skill_dir = Path(SKILLS_DIR) / skill_id
    readme_content = ""
    readme_path = skill_dir / "SKILL.md"
    if readme_path.exists():
        readme_content = readme_path.read_text(encoding="utf-8")

    files_struct = InfraSkillFilesStructure(
        agents=_list_files_in_dir(skill_dir, "agents"),
        schemas=_list_files_in_dir(skill_dir, "schemas"),
        templates=_list_files_in_dir(skill_dir, "templates"),
        scripts=_list_files_in_dir(skill_dir, "scripts"),
        references=_list_files_in_dir(skill_dir, "references"),
        tests=_list_files_in_dir(skill_dir, "tests"),
        strategies=_list_files_in_dir(skill_dir, "strategies"),
    )

    # 读取 field_mapping.yaml（语义层字段映射）
    field_mapping = _read_field_mapping(skill_dir)

    return InfraSkillDetailResponse(
        skill_id=skill.skill_id,
        skill_name=skill.skill_name,
        business_action=skill.business_action,
        business_object=skill.business_object,
        include_keywords=skill.include_keywords,
        excluded_intents=skill.excluded_intents,
        manifest=skill.manifest,
        readme=readme_content,
        files_structure=files_struct,
        field_mapping=field_mapping,
    )


@router.get(
    "/infra-skills/{skill_id}/versions",
    response_model=list[SkillVersionResponse],
)
def list_infra_skill_versions(
    skill_id: str,
    service: SkillVersionServiceDependency,
) -> list[SkillVersionResponse]:
    return [
        SkillVersionResponse.model_validate(version.model_dump())
        for version in service.list_versions(skill_id)
    ]


@router.get(
    "/infra-skills/{skill_id}/versions/{version_id}",
    response_model=SkillVersionResponse,
)
def get_infra_skill_version(
    skill_id: str,
    version_id: str,
    service: SkillVersionServiceDependency,
) -> SkillVersionResponse:
    try:
        version = service.get_version(skill_id, version_id)
    except SkillNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "SKILL_VERSION_NOT_FOUND",
                str(exc),
                {"skill_id": skill_id, "version_id": version_id},
            ),
        ) from exc
    return SkillVersionResponse.model_validate(version.model_dump())


@router.post(
    "/infra-skills/{skill_id}/versions/sync",
    response_model=SkillVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def sync_infra_skill_version(
    skill_id: str,
    request: SkillVersionSyncRequest,
    service: SkillVersionServiceDependency,
) -> SkillVersionResponse:
    try:
        version = service.sync_version(
            skill_id,
            source_commit=request.source_commit,
            created_by=request.created_by,
        )
    except SkillNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "SKILL_NOT_FOUND", str(exc), {"skill_id": skill_id}
            ),
        ) from exc
    except SkillVersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "SKILL_VERSION_CONFLICT", str(exc), {"skill_id": skill_id}
            ),
        ) from exc
    except (SkillArtifactError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=error_detail(
                "SKILL_VERSION_INVALID", str(exc), {"skill_id": skill_id}
            ),
        ) from exc
    return SkillVersionResponse.model_validate(version.model_dump())


@router.post("/infra-skills/route-test", response_model=SkillRouteTestResponse)
def test_infra_skill_routing(request: SkillRouteTestRequest) -> SkillRouteTestResponse:
    matches = route_question_ranked(request.question, min_confidence=0.0)
    top = matches[0] if matches else None
    return SkillRouteTestResponse(
        question=request.question,
        matched_skill_id=top.skill_id if top else None,
        confidence=top.confidence if top else 0.0,
        match_method=top.match_method if top else "none",
        matched_keywords=top.matched_keywords if top else [],
        candidates=[match.to_dict() for match in matches[:5]],
    )


def _safe_input_summary(request: SkillExecuteTestRequest) -> dict[str, object]:
    """只返回调试所需的非敏感上下文摘要，不回显原始患者数据。"""
    context = request.context or {}
    return {
        "context_keys": sorted(context.keys()),
        "patient_id": context.get("patient_id"),
        "encounter_id": context.get("encounter_id"),
        "target_fee_item": request.target_fee_item,
    }


def _result_diagnostics(result: object) -> tuple[list[str], list[dict], list[str], list[dict]]:
    if not isinstance(result, dict):
        return [], [], [], []
    return (
        list(result.get("warnings", []) or []),
        list(result.get("citations", []) or []),
        list(result.get("uncertainties", []) or []),
        list(result.get("trace", []) or []),
    )


@router.post("/infra-skills/{skill_id}/test", response_model=SkillExecuteTestResponse)
def test_infra_skill_execution(
    skill_id: str, request: SkillExecuteTestRequest
) -> SkillExecuteTestResponse:
    assembler = get_assembler(skill_id)
    if not assembler:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_NOT_FOUND", "未找到该 Skill 包", {"skill_id": skill_id}),
        )

    try:
        # Check if the assembler expects 'target_fee_item' or just standard kwargs
        # This is a generic test execution wrapper, we pass available args.
        # It's assumed the assembler handles these inputs or ignores unknown kwargs.
        
        # Policy Fee Explanation specific signature:
        # execute(self, context, evidence, status, target_fee_item=None)
        
        import inspect
        from types import SimpleNamespace
        sig = inspect.signature(assembler.execute)
        kwargs = {}
        # 将 dict 转为 SimpleNamespace 以支持 getattr 访问
        ctx_obj = SimpleNamespace(**request.context) if request.context else SimpleNamespace()
        if "settlement_context" in sig.parameters or "context" in sig.parameters:
            kwargs["settlement_context"] = ctx_obj
        if "policy_evidence" in sig.parameters or "evidence" in sig.parameters:
            kwargs["policy_evidence"] = request.evidence
        if "policy_status" in sig.parameters or "status" in sig.parameters:
            kwargs["policy_status"] = request.status
        if "target_fee_item" in sig.parameters and request.target_fee_item:
            kwargs["target_fee_item"] = request.target_fee_item

        started = time.perf_counter()
        result = assembler.execute(**kwargs)
        warnings, citations, uncertainties, trace = _result_diagnostics(result)
        
        return SkillExecuteTestResponse(
            skill_id=skill_id,
            status="success",
            result=result,
            warnings=warnings,
            citations=citations,
            uncertainties=uncertainties,
            trace=trace,
            input_summary=_safe_input_summary(request),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_detail("SKILL_EXECUTION_FAILED", str(e), {"skill_id": skill_id}),
        )


@router.get("/infra-skills/overview", response_model=InfraSkillOverviewResponse)
def get_infra_skills_overview() -> InfraSkillOverviewResponse:
    """返回管理页面使用的 Skill 健康摘要。"""
    loader = get_loader()
    items: list[InfraSkillOverviewItem] = []
    for skill_id, skill in loader.get_all().items():
        skill_dir = Path(SKILLS_DIR) / skill_id
        manifest_path = skill_dir / "skill_manifest.yaml"
        warnings: list[str] = []
        manifest_valid = manifest_path.exists()
        if not manifest_valid:
            warnings.append("缺少 skill_manifest.yaml")
        field_mapping_configured = (skill_dir / "field_mapping.yaml").exists()
        metric_count = sum(
            len(declaration.get("metrics", []))
            for declaration in (skill.manifest.get("needed_objects", []) or [])
            if isinstance(declaration, dict)
        )
        items.append(InfraSkillOverviewItem(
            skill_id=skill_id,
            skill_name=skill.skill_name,
            business_action=skill.business_action,
            business_object=skill.business_object,
            manifest_valid=manifest_valid,
            field_mapping_configured=field_mapping_configured,
            metric_count=metric_count,
            warnings=warnings,
        ))
    return InfraSkillOverviewResponse(skill_count=len(items), skills=items)


@router.post("/infra-skills/refresh", response_model=SkillRefreshResponse)
def refresh_infra_skills() -> SkillRefreshResponse:
    """热重载：重新扫描 skills/ 目录，发现新增或移除的 skill 包。

    无需重启服务即可加载新创建的 skill 目录。
    """
    try:
        new_registry = refresh_loader()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_detail("SKILL_REFRESH_FAILED", str(e), {}),
        )

    skills = []
    for s_id, s in new_registry.items():
        skills.append(
            InfraSkillItem(
                skill_id=s.skill_id,
                skill_name=s.skill_name,
                include_keywords=s.include_keywords,
                excluded_intents=s.excluded_intents,
            )
        )

    return SkillRefreshResponse(
        skill_count=len(skills),
        skills=skills,
        message=f"热重载完成，已发现 {len(skills)} 个 skill",
    )
