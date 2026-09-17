"""运营问数意图解析：将自然语言映射到 Flow 已发布消费契约的指标码。

核心约束（docs/decisions/2026-08-27-coding-agent-评估.md）：
- LLM 只做「问数意图 → 受治理指标码」的映射；
- 数字永远走 Flow 受控视图 + 确定性门禁（勾稽恒等）；
- 消费契约目录覆盖不了 → 明确返回「暂不支持」，不猜数。

通道说明（2026-09-15 修正）：运营聚合问法无 anchor，不走 SemanticQuery
单笔锚点模型；执行面是 FlowQueryService.query_by_metrics（#42 验收口径：
指标类 → 受控问数 Flow 消费契约）。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.model_service.gateway import ModelGateway
from src.model_service.models import Message


class DataQueryIntent(BaseModel):
    """LLM 解析出的问数意图参数（面向 Flow 消费契约）。"""

    metrics: list[str] = Field(min_length=1, description="消费契约指标码列表")
    dimensions: list[str] = Field(default_factory=list, description="下钻维度编码列表")
    clarification_needed: bool = Field(default=False, description="是否需要澄清")
    clarification_message: str | None = Field(default=None, description="澄清话术")


def _load_flow_contract_catalog() -> list[dict[str, Any]]:
    """已发布 Flow 活跃版本的消费契约指标目录（name + 口径定义）。"""
    from src.data_platform.storage.flow.flow_factory import get_governed_flow_storage
    from src.domain.governed_flow.models import ConsumerNode, DimensionNode, FlowStatus

    storage = get_governed_flow_storage()
    catalog: list[dict[str, Any]] = []
    for flow in storage.list_flows():
        if flow.status is not FlowStatus.PUBLISHED:
            continue
        active = storage.get_active_revision(flow.flow_id)
        if active is None:
            continue
        definition = active.definition
        names = {m.metric_code: m.name for m in definition.metric_outputs}
        calibers = {m.metric_code: m.policy_definition for m in definition.metric_outputs}
        dimensions = [
            d.field_code
            for node in definition.nodes
            if isinstance(node, DimensionNode)
            for d in node.dimensions
        ]
        for node in definition.nodes:
            if not isinstance(node, ConsumerNode):
                continue
            for code in node.consumes:
                catalog.append({
                    "metric_code": code,
                    "metric_name": names.get(code, code),
                    "definition": calibers.get(code, ""),
                    "dimensions": dimensions,
                })
    return catalog


async def parse_data_query_intent(question: str) -> dict[str, Any]:
    """将自然语言问数解析为 Flow 消费契约指标码。

    返回结构（平铺供 Workflow input_mapping 单层引用）：
    metric_codes / metrics / dimensions / clarification_needed / clarification_message
    """
    catalog = _load_flow_contract_catalog()

    if not catalog:
        return {
            "metric_codes": [],
            "metrics": [],
            "dimensions": [],
            "clarification_needed": True,
            "clarification_message": "当前尚未发布可用的运营指标消费契约，无法回答问数问题。",
        }

    catalog_text = "\n".join(
        f"- {item['metric_code']}: {item['metric_name']} | {item['definition']}"
        + (f" | 可下钻维度: {','.join(item['dimensions'])}" if item["dimensions"] else "")
        for item in catalog[:100]  # 控制上下文长度
    )

    prompt = (
        "你是医保运营问数助手。请根据用户问题，从以下已发布消费契约中选择最相关的指标码，"
        "输出 JSON。严禁选择不在目录中的指标。\n\n"
        "输出格式：\n"
        '{"metrics": ["指标码"], "dimensions": ["维度编码"], '
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
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        intent = DataQueryIntent.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        return {
            "metric_codes": [], "metrics": [], "dimensions": [],
            "clarification_needed": True,
            "clarification_message": f"未能理解您的问数意图，请换一种方式提问。详情：{e}",
        }
    except Exception as e:
        # 模型网关未配置或其他故障
        return {
            "metric_codes": [], "metrics": [], "dimensions": [],
            "clarification_needed": True,
            "clarification_message": f"问数意图解析服务暂不可用：{e}",
        }

    if intent.clarification_needed:
        return {
            "metric_codes": [], "metrics": [], "dimensions": [],
            "clarification_needed": True,
            "clarification_message": intent.clarification_message or "请补充您想查询的指标或维度。",
        }

    # 白名单校验：指标码必须在已发布消费契约目录中（不猜数）
    allowed_codes = {item["metric_code"] for item in catalog}
    invalid_metrics = [m for m in intent.metrics if m not in allowed_codes]
    if invalid_metrics:
        return {
            "metric_codes": [], "metrics": [], "dimensions": [],
            "clarification_needed": True,
            "clarification_message": f"以下指标不在已发布目录中，无法查询：{invalid_metrics}",
        }

    return {
        "metric_codes": list(intent.metrics),
        "metrics": list(intent.metrics),
        "dimensions": list(intent.dimensions),
        "clarification_needed": False,
        "clarification_message": None,
    }
