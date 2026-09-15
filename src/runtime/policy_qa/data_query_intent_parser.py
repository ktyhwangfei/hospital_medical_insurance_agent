"""运营问数意图解析：将自然语言映射到已发布的语义指标查询参数。

核心约束（来自 docs/decisions/2026-08-27-coding-agent-评估.md）：
- LLM 只做"问数意图 → 受治理指标"的映射；
- 数字永远走固定 SQL + 确定性求值；
- 指标目录覆盖不了 → 明确返回"暂不支持"，不猜数。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.model_service.gateway import ModelGateway
from src.model_service.models import Message
from src.semantic_layer.query_planner import (
    QueryAnchor,
    QueryFilter,
    QueryOrder,
    QueryScope,
    QueryScopeName,
    SemanticQuery,
)
from src.semantic_layer.registry import get_semantic_registry


class DataQueryIntent(BaseModel):
    """LLM 解析出的问数意图参数。"""

    object_code: str = Field(description="业务对象编码，如 outpatient_query")
    entity_code: str = Field(default="outpatient", description="实体编码")
    metrics: list[str] = Field(min_length=1, description="指标编码列表")
    group_by: list[str] = Field(default_factory=list, description="维度编码列表")
    filters: list[dict[str, Any]] = Field(default_factory=list, description="过滤条件")
    query_scope: str = Field(default="whole_settlement", description="查询范围")
    clarification_needed: bool = Field(default=False, description="是否需要澄清")
    clarification_message: str | None = Field(default=None, description="澄清话术")


async def parse_data_query_intent(question: str) -> dict[str, Any]:
    """将自然语言问数解析为语义层查询参数。

    返回结构：
    {
        "semantic_query": SemanticQuery 的 dict,
        "clarification_needed": bool,
        "clarification_message": str | None,
        "matched_metrics": list[str],
    }
    """
    registry = get_semantic_registry()

    # 1. 读取已发布指标目录（运行时锁定最新版本）
    objects = registry.list_objects()
    published_metrics: list[dict[str, Any]] = []
    for obj in objects:
        versions = registry.list_object_versions(obj.object_code)
        if not versions:
            continue
        latest = versions[-1]
        for vm in latest.metrics:
            published_metrics.append(
                {
                    "object_code": obj.object_code,
                    "metric_code": vm.metric_code,
                    "metric_name": vm.name,
                    "definition": vm.definition,
                    "semantic_type": vm.semantic_type,
                }
            )

    if not published_metrics:
        return {
            "semantic_query": None,
            "clarification_needed": True,
            "clarification_message": "当前语义层尚未发布可用指标，无法回答问数问题。",
            "matched_metrics": [],
        }

    # 2. LLM 意图解析：只选 object + metrics + dimensions + filters
    catalog_text = "\n".join(
        f"- {m['metric_code']} ({m['object_code']}): {m['metric_name']} | {m['definition']}"
        for m in published_metrics[:100]  # 控制上下文长度
    )

    prompt = (
        "你是医保运营问数助手。请根据用户问题，从以下已发布语义指标中选择最相关的指标和维度，"
        "输出 JSON。严禁选择不在目录中的指标。\n\n"
        "输出格式：\n"
        '{"object_code": "业务对象编码", "entity_code": "实体编码", '
        '"metrics": ["指标编码"], "group_by": ["维度编码"], '
        '"filters": [{"field_code": "字段", "operator": "eq", "value": "值"}], '
        '"query_scope": "whole_settlement", '
        '"clarification_needed": false, "clarification_message": null}\n\n'
        "如果无法匹配到合适指标，设置 clarification_needed=true 并给出澄清话术。\n\n"
        f"已发布指标目录：\n{catalog_text}\n\n"
        f"用户问题：{question}\n\n"
        "输出 JSON："
    )

    try:
        gateway = ModelGateway()
        response = gateway.generate(
            messages=[Message(role="user", content=prompt)],
            model_type="llm",
            scene="data_query_intent_parse",
            max_tokens=1024,
        )
        raw = (response.content or "").strip()
        # 简单清理可能的 markdown 代码块
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        parsed = json.loads(raw)
        intent = DataQueryIntent.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        return {
            "semantic_query": None,
            "clarification_needed": True,
            "clarification_message": f"未能理解您的问数意图，请换一种方式提问。详情：{e}",
            "matched_metrics": [],
        }
    except Exception as e:
        # 模型网关未配置或其他故障
        return {
            "semantic_query": None,
            "clarification_needed": True,
            "clarification_message": f"问数意图解析服务暂不可用：{e}",
            "matched_metrics": [],
        }

    if intent.clarification_needed:
        return {
            "semantic_query": None,
            "clarification_needed": True,
            "clarification_message": intent.clarification_message or "请补充您想查询的指标或维度。",
            "matched_metrics": [],
        }

    # 3. 白名单校验：metric_code 必须在已发布目录中
    allowed_codes = {m["metric_code"] for m in published_metrics}
    invalid_metrics = [m for m in intent.metrics if m not in allowed_codes]
    if invalid_metrics:
        return {
            "semantic_query": None,
            "clarification_needed": True,
            "clarification_message": f"以下指标不在已发布目录中，无法查询：{invalid_metrics}",
            "matched_metrics": [],
        }

    # 4. 构建 SemanticQuery
    filters = [QueryFilter.model_validate(f) for f in intent.filters]
    valid_query_scopes: set[str] = {"whole_admission", "segment", "whole_settlement", "fee_item"}
    query_scope_value = intent.query_scope if intent.query_scope in valid_query_scopes else "whole_settlement"
    query_scope: QueryScopeName = query_scope_value  # type: ignore[assignment]
    semantic_query = SemanticQuery(
        object_code=intent.object_code,
        scope=QueryScope(
            entity_code=intent.entity_code,
            anchor=QueryAnchor(field_code="entity_code", value=intent.entity_code),
            query_scope=query_scope,
        ),
        metrics=intent.metrics,
        group_by=intent.group_by,
        filters=filters,
        order_by=[QueryOrder(field_code=m) for m in intent.group_by],
        limit=100,
    )
    sq_dict = semantic_query.model_dump(mode="json")

    return {
        "semantic_query": sq_dict,
        # 平铺字段，便于 Workflow input_mapping 单层引用
        "object_code": intent.object_code,
        "entity_code": intent.entity_code,
        "anchor_field": "entity_code",
        "anchor_value": intent.entity_code,
        "metrics": intent.metrics,
        "query_scope": query_scope,
        "clarification_needed": False,
        "clarification_message": None,
        "matched_metrics": intent.metrics,
        "_raw": sq_dict,
    }
