"""
知识管理 REST API 路由

提供 28 个端点，覆盖 5 组知识管理 CRUD 操作：
  - Group A: 错误码知识管理 (5)
  - Group B: 规则解释管理 (5)
  - Group C: 知识资产管理 (7)
  - Group D: 申诉模板管理 (5)
  - Group E: 提示词模板管理 (6)
"""
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.config.production import DATABASE_URL
from src.data_platform.storage.knowledge.postgres import PostgresKnowledgeStorage
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.rule.postgres import PostgresRuleStorage
from src.knowledge_extension.knowledge.appeal_postgres import PostgresAppealTemplateStore
from src.knowledge_extension.knowledge.postgres import PostgresKnowledgeStore
from src.knowledge_extension.prompt_templates.postgres import PostgresPromptTemplateStore
from src.runtime.api.schemas import (
    AppealTemplateCreate,
    AppealTemplateUpdate,
    AssetCreate,
    AssetUpdate,
    ChunkCreate,
    ErrorCodeCreate,
    ErrorCodeUpdate,
    PromptTemplateCreate,
    PromptTemplateRenderRequest,
    PromptTemplateUpdate,
    RuleCreate,
    RuleUpdate,
)
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Store instances ──────────────────────────────────────────────────────────

_error_store = PostgresKnowledgeStore()
_rule_store = PostgresRuleStorage()
_asset_store = PostgresKnowledgeStorage()
_appeal_store = PostgresAppealTemplateStore()
_prompt_store = PostgresPromptTemplateStore()

_client: PostgreSQLClient | None = None


def _get_client() -> PostgreSQLClient:
    """获取共享的 PostgreSQL 客户端实例（惰性初始化）"""
    global _client
    if _client is None:
        _client = PostgreSQLClient(DATABASE_URL)
    return _client


# ═══════════════════════════════════════════════════════════════════════════════
# Group A: 错误码知识管理 (error_code_knowledge) — 5 个端点
# ═══════════════════════════════════════════════════════════════════════════════


@router.get('/knowledge/error-codes')
def list_error_codes(
    error_code: str | None = Query(None),
    description: str | None = Query(None),
) -> list[dict[str, Any]]:
    """错误码列表，支持 error_code / description 模糊搜索，按 error_code 排序"""
    codes = _error_store.list_error_codes()
    if error_code:
        codes = [c for c in codes if error_code.lower() in c.get('error_code', '').lower()]
    if description:
        codes = [c for c in codes if description.lower() in c.get('description', '').lower()]
    return codes


@router.post('/knowledge/error-codes', status_code=201)
def create_error_code(request: ErrorCodeCreate) -> dict[str, Any]:
    """创建错误码（ON CONFLICT UPSERT）"""
    client = _get_client()
    sql = """
        INSERT INTO error_code_knowledge (error_code, description, exception_type, responsible_role, recommendation)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (error_code) DO UPDATE SET
            description = EXCLUDED.description,
            exception_type = EXCLUDED.exception_type,
            responsible_role = EXCLUDED.responsible_role,
            recommendation = EXCLUDED.recommendation
    """
    client.execute(sql, (
        request.error_code, request.description, request.exception_type,
        request.responsible_role, request.recommendation,
    ))
    return {
        'error_code': request.error_code,
        'description': request.description,
        'exception_type': request.exception_type,
        'responsible_role': request.responsible_role,
        'recommendation': request.recommendation,
    }


@router.get('/knowledge/error-codes/{error_code}')
def get_error_code(error_code: str) -> dict[str, Any]:
    """获取错误码详情"""
    code = _error_store.get_error_code(error_code)
    if code is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail('ERROR_CODE_NOT_FOUND', '错误码不存在', {'event_type': 'error_code_not_found'}),
        )
    return code


@router.put('/knowledge/error-codes/{error_code}')
def update_error_code(error_code: str, request: ErrorCodeUpdate) -> dict[str, Any]:
    """更新错误码"""
    existing = _error_store.get_error_code(error_code)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail('ERROR_CODE_NOT_FOUND', '错误码不存在', {'event_type': 'error_code_not_found'}),
        )
    client = _get_client()
    sql = """
        UPDATE error_code_knowledge
        SET description = %s, exception_type = %s, responsible_role = %s, recommendation = %s
        WHERE error_code = %s
    """
    client.execute(sql, (
        request.description if request.description is not None else existing.get('description'),
        request.exception_type if request.exception_type is not None else existing.get('exception_type'),
        request.responsible_role if request.responsible_role is not None else existing.get('responsible_role'),
        request.recommendation if request.recommendation is not None else existing.get('recommendation'),
        error_code,
    ))
    return _error_store.get_error_code(error_code) or existing


@router.delete('/knowledge/error-codes/{error_code}')
def delete_error_code(error_code: str) -> dict[str, bool]:
    """删除错误码"""
    existing = _error_store.get_error_code(error_code)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail('ERROR_CODE_NOT_FOUND', '错误码不存在', {'event_type': 'error_code_not_found'}),
        )
    client = _get_client()
    client.execute("DELETE FROM error_code_knowledge WHERE error_code = %s", (error_code,))
    return {'deleted': True}


# ═══════════════════════════════════════════════════════════════════════════════
# Group B: 规则解释管理 (rule_explanations) — 5 个端点
# ═══════════════════════════════════════════════════════════════════════════════


@router.get('/knowledge/rules')
def list_rules(
    scenario: str | None = Query(None),
) -> list[dict[str, Any]]:
    """规则解释列表，支持 ?scenario=xxx 过滤"""
    return _rule_store.list_rules(scenario=scenario)


@router.post('/knowledge/rules', status_code=201)
def create_rule(request: RuleCreate) -> dict[str, Any]:
    """创建规则解释（ON CONFLICT UPSERT）"""
    rule = request.model_dump(exclude_none=True)
    _rule_store.save_rule(rule)
    saved = _rule_store.get_rule(request.rule_id)
    return saved or rule


@router.get('/knowledge/rules/{rule_id}')
def get_rule(rule_id: str) -> dict[str, Any]:
    """获取规则解释详情"""
    rule = _rule_store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail('RULE_NOT_FOUND', '规则不存在', {'event_type': 'rule_not_found'}),
        )
    return rule


@router.put('/knowledge/rules/{rule_id}')
def update_rule(rule_id: str, request: RuleUpdate) -> dict[str, Any]:
    """更新规则解释"""
    existing = _rule_store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail('RULE_NOT_FOUND', '规则不存在', {'event_type': 'rule_not_found'}),
        )
    update_data = {**existing, **request.model_dump(exclude_none=True)}
    _rule_store.save_rule(update_data)
    return _rule_store.get_rule(rule_id) or update_data


@router.delete('/knowledge/rules/{rule_id}')
def delete_rule(rule_id: str) -> dict[str, bool]:
    """删除规则解释"""
    existing = _rule_store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail('RULE_NOT_FOUND', '规则不存在', {'event_type': 'rule_not_found'}),
        )
    client = _get_client()
    client.execute("DELETE FROM rule_explanations WHERE rule_id = %s", (rule_id,))
    return {'deleted': True}


# ═══════════════════════════════════════════════════════════════════════════════
# Group C: 知识资产管理 (knowledge_assets + knowledge_chunks) — 7 个端点
# ═══════════════════════════════════════════════════════════════════════════════


@router.get('/knowledge/assets')
def list_assets(
    asset_type: str | None = Query(None, alias='type'),
    status: str | None = Query(None),
) -> list[dict[str, Any]]:
    """知识资产列表，支持 ?type=xxx&status=xxx 过滤"""
    assets = _asset_store.list_assets(asset_type=asset_type)
    if status:
        assets = [a for a in assets if a.get('status') == status]
    return assets


@router.post('/knowledge/assets', status_code=201)
def create_asset(request: AssetCreate) -> dict[str, Any]:
    """创建知识资产"""
    asset = request.model_dump(exclude_none=True)
    _asset_store.save_asset(asset)
    client = _get_client()
    rows = client.execute(
        "SELECT * FROM knowledge_assets WHERE asset_id = %s", (request.asset_id,),
    )
    return rows[0] if rows else asset


@router.get('/knowledge/assets/{asset_id}')
def get_asset(asset_id: str) -> dict[str, Any]:
    """获取知识资产详情"""
    client = _get_client()
    rows = client.execute(
        "SELECT * FROM knowledge_assets WHERE asset_id = %s", (asset_id,),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=error_detail('ASSET_NOT_FOUND', '知识资产不存在', {'event_type': 'asset_not_found'}),
        )
    return rows[0]


@router.put('/knowledge/assets/{asset_id}')
def update_asset(asset_id: str, request: AssetUpdate) -> dict[str, Any]:
    """更新知识资产"""
    client = _get_client()
    existing_rows = client.execute(
        "SELECT * FROM knowledge_assets WHERE asset_id = %s", (asset_id,),
    )
    if not existing_rows:
        raise HTTPException(
            status_code=404,
            detail=error_detail('ASSET_NOT_FOUND', '知识资产不存在', {'event_type': 'asset_not_found'}),
        )
    existing = existing_rows[0]
    update_data = {**existing, **request.model_dump(exclude_none=True)}
    _asset_store.save_asset(update_data)
    rows = client.execute(
        "SELECT * FROM knowledge_assets WHERE asset_id = %s", (asset_id,),
    )
    return rows[0] if rows else update_data


@router.delete('/knowledge/assets/{asset_id}')
def delete_asset(asset_id: str) -> dict[str, bool]:
    """删除知识资产及其所有切片（CASCADE）"""
    client = _get_client()
    existing = client.execute(
        "SELECT asset_id FROM knowledge_assets WHERE asset_id = %s", (asset_id,),
    )
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=error_detail('ASSET_NOT_FOUND', '知识资产不存在', {'event_type': 'asset_not_found'}),
        )
    client.execute("DELETE FROM knowledge_chunks WHERE asset_id = %s", (asset_id,))
    client.execute("DELETE FROM knowledge_assets WHERE asset_id = %s", (asset_id,))
    return {'deleted': True}


@router.get('/knowledge/assets/{asset_id}/chunks')
def list_asset_chunks(asset_id: str) -> list[dict[str, Any]]:
    """获取资产的所有切片"""
    return _asset_store.list_chunks(asset_id)


@router.post('/knowledge/assets/{asset_id}/chunks', status_code=201)
def create_asset_chunk(asset_id: str, request: ChunkCreate) -> dict[str, Any]:
    """创建知识切片（关联指定资产，触发向量化逻辑）"""
    chunk = request.model_dump(exclude_none=True)
    chunk['asset_id'] = asset_id
    _asset_store.save_chunk(chunk)
    client = _get_client()
    rows = client.execute(
        "SELECT * FROM knowledge_chunks WHERE chunk_id = %s", (request.chunk_id,),
    )
    return rows[0] if rows else chunk


# ═══════════════════════════════════════════════════════════════════════════════
# Group D: 申诉模板管理 (appeal_templates) — 5 个端点
# ═══════════════════════════════════════════════════════════════════════════════


@router.get('/knowledge/appeal-templates')
def list_appeal_templates(
    template_type: str | None = Query(None, alias='type'),
) -> list[dict[str, Any]]:
    """申诉模板列表，支持 ?type=xxx 过滤"""
    templates = _appeal_store.list_templates(enabled_only=False)
    if template_type:
        templates = [t for t in templates if t.get('template_type') == template_type]
    return templates


@router.post('/knowledge/appeal-templates', status_code=201)
def create_appeal_template(request: AppealTemplateCreate) -> dict[str, Any]:
    """创建申诉模板"""
    client = _get_client()
    sql = """
        INSERT INTO appeal_templates (template_id, template_name, template_type, denial_reason_pattern, content, required_evidence, applicable_scenarios, enabled)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (template_id) DO UPDATE SET
            template_name = EXCLUDED.template_name,
            content = EXCLUDED.content
    """
    client.execute(sql, (
        request.template_id, request.template_name, request.template_type,
        request.denial_reason_pattern, request.content,
        json.dumps(request.required_evidence or []),
        json.dumps(request.applicable_scenarios or []),
        request.enabled if request.enabled is not None else True,
    ))
    rows = client.execute(
        "SELECT * FROM appeal_templates WHERE template_id = %s", (request.template_id,),
    )
    return rows[0] if rows else request.model_dump()


@router.get('/knowledge/appeal-templates/{template_id}')
def get_appeal_template(template_id: str) -> dict[str, Any]:
    """获取申诉模板详情"""
    client = _get_client()
    rows = client.execute(
        "SELECT * FROM appeal_templates WHERE template_id = %s", (template_id,),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=error_detail('APPEAL_TEMPLATE_NOT_FOUND', '申诉模板不存在', {'event_type': 'appeal_template_not_found'}),
        )
    return rows[0]


@router.put('/knowledge/appeal-templates/{template_id}')
def update_appeal_template(template_id: str, request: AppealTemplateUpdate) -> dict[str, Any]:
    """更新申诉模板"""
    client = _get_client()
    existing_rows = client.execute(
        "SELECT * FROM appeal_templates WHERE template_id = %s", (template_id,),
    )
    if not existing_rows:
        raise HTTPException(
            status_code=404,
            detail=error_detail('APPEAL_TEMPLATE_NOT_FOUND', '申诉模板不存在', {'event_type': 'appeal_template_not_found'}),
        )
    existing = existing_rows[0]

    sql = """
        UPDATE appeal_templates SET
            template_name = %s, template_type = %s, denial_reason_pattern = %s,
            content = %s, required_evidence = %s, applicable_scenarios = %s,
            enabled = %s, updated_at = CURRENT_TIMESTAMP
        WHERE template_id = %s
    """
    client.execute(sql, (
        request.template_name if request.template_name is not None else existing.get('template_name'),
        request.template_type if request.template_type is not None else existing.get('template_type'),
        request.denial_reason_pattern if request.denial_reason_pattern is not None else existing.get('denial_reason_pattern'),
        request.content if request.content is not None else existing.get('content'),
        json.dumps(request.required_evidence) if request.required_evidence is not None else existing.get('required_evidence'),
        json.dumps(request.applicable_scenarios) if request.applicable_scenarios is not None else existing.get('applicable_scenarios'),
        request.enabled if request.enabled is not None else existing.get('enabled'),
        template_id,
    ))
    rows = client.execute(
        "SELECT * FROM appeal_templates WHERE template_id = %s", (template_id,),
    )
    return rows[0] if rows else existing


@router.delete('/knowledge/appeal-templates/{template_id}')
def delete_appeal_template(template_id: str) -> dict[str, bool]:
    """删除申诉模板"""
    client = _get_client()
    existing = client.execute(
        "SELECT template_id FROM appeal_templates WHERE template_id = %s", (template_id,),
    )
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=error_detail('APPEAL_TEMPLATE_NOT_FOUND', '申诉模板不存在', {'event_type': 'appeal_template_not_found'}),
        )
    client.execute("DELETE FROM appeal_templates WHERE template_id = %s", (template_id,))
    return {'deleted': True}


# ═══════════════════════════════════════════════════════════════════════════════
# Group E: 提示词模板管理 (prompt_templates) — 6 个端点
# ═══════════════════════════════════════════════════════════════════════════════


@router.get('/knowledge/prompt-templates')
def list_prompt_templates(
    scenario: str | None = Query(None),
    role: str | None = Query(None),
) -> list[dict[str, Any]]:
    """提示词模板列表，支持 ?scenario=xxx&role=xxx 过滤"""
    client = _get_client()
    sql = "SELECT * FROM prompt_templates WHERE 1=1"
    params: list[Any] = []
    if scenario:
        sql += " AND scenario = %s"
        params.append(scenario)
    if role:
        sql += " AND role = %s"
        params.append(role)
    sql += " ORDER BY template_id"
    return client.execute(sql, tuple(params))


@router.post('/knowledge/prompt-templates', status_code=201)
def create_prompt_template(request: PromptTemplateCreate) -> dict[str, Any]:
    """创建提示词模板"""
    client = _get_client()
    sql = """
        INSERT INTO prompt_templates (template_id, template_name, template_type, scenario, role, system_prompt, user_prompt_template, variables, output_format, enabled)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (template_id) DO UPDATE SET
            template_name = EXCLUDED.template_name,
            system_prompt = EXCLUDED.system_prompt
    """
    client.execute(sql, (
        request.template_id, request.template_name, request.template_type,
        request.scenario, request.role, request.system_prompt,
        request.user_prompt_template,
        json.dumps(request.variables or []),
        json.dumps(request.output_format or {}),
        request.enabled if request.enabled is not None else True,
    ))
    rows = client.execute(
        "SELECT * FROM prompt_templates WHERE template_id = %s", (request.template_id,),
    )
    return rows[0] if rows else request.model_dump()


@router.get('/knowledge/prompt-templates/{template_id}')
def get_prompt_template(template_id: str) -> dict[str, Any]:
    """获取提示词模板详情"""
    client = _get_client()
    rows = client.execute(
        "SELECT * FROM prompt_templates WHERE template_id = %s", (template_id,),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=error_detail('PROMPT_TEMPLATE_NOT_FOUND', '提示词模板不存在', {'event_type': 'prompt_template_not_found'}),
        )
    return rows[0]


@router.put('/knowledge/prompt-templates/{template_id}')
def update_prompt_template(template_id: str, request: PromptTemplateUpdate) -> dict[str, Any]:
    """更新提示词模板"""
    client = _get_client()
    existing_rows = client.execute(
        "SELECT * FROM prompt_templates WHERE template_id = %s", (template_id,),
    )
    if not existing_rows:
        raise HTTPException(
            status_code=404,
            detail=error_detail('PROMPT_TEMPLATE_NOT_FOUND', '提示词模板不存在', {'event_type': 'prompt_template_not_found'}),
        )
    existing = existing_rows[0]

    sql = """
        UPDATE prompt_templates SET
            template_name = %s, template_type = %s, scenario = %s, role = %s,
            system_prompt = %s, user_prompt_template = %s, variables = %s,
            output_format = %s, enabled = %s, updated_at = CURRENT_TIMESTAMP
        WHERE template_id = %s
    """
    client.execute(sql, (
        request.template_name if request.template_name is not None else existing.get('template_name'),
        request.template_type if request.template_type is not None else existing.get('template_type'),
        request.scenario if request.scenario is not None else existing.get('scenario'),
        request.role if request.role is not None else existing.get('role'),
        request.system_prompt if request.system_prompt is not None else existing.get('system_prompt'),
        request.user_prompt_template if request.user_prompt_template is not None else existing.get('user_prompt_template'),
        json.dumps(request.variables) if request.variables is not None else existing.get('variables'),
        json.dumps(request.output_format) if request.output_format is not None else existing.get('output_format'),
        request.enabled if request.enabled is not None else existing.get('enabled'),
        template_id,
    ))
    rows = client.execute(
        "SELECT * FROM prompt_templates WHERE template_id = %s", (template_id,),
    )
    return rows[0] if rows else existing


@router.delete('/knowledge/prompt-templates/{template_id}')
def delete_prompt_template(template_id: str) -> dict[str, bool]:
    """删除提示词模板"""
    client = _get_client()
    existing = client.execute(
        "SELECT template_id FROM prompt_templates WHERE template_id = %s", (template_id,),
    )
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=error_detail('PROMPT_TEMPLATE_NOT_FOUND', '提示词模板不存在', {'event_type': 'prompt_template_not_found'}),
        )
    client.execute("DELETE FROM prompt_templates WHERE template_id = %s", (template_id,))
    return {'deleted': True}


@router.post('/knowledge/prompt-templates/render')
def render_prompt_template(request: PromptTemplateRenderRequest) -> dict[str, Any]:
    """渲染提示词模板变量（不写数据库）"""
    client = _get_client()
    rows = client.execute(
        "SELECT * FROM prompt_templates WHERE template_id = %s", (request.template_id,),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=error_detail('PROMPT_TEMPLATE_NOT_FOUND', '提示词模板不存在', {'event_type': 'prompt_template_not_found'}),
        )
    template = rows[0]
    content = template.get('system_prompt', '') or template.get('user_prompt_template', '')
    rendered = content
    for key, value in request.variables.items():
        rendered = rendered.replace('{{' + key + '}}', value)
    return {
        'template_id': request.template_id,
        'rendered': rendered,
        'variables_used': list(request.variables.keys()),
    }
