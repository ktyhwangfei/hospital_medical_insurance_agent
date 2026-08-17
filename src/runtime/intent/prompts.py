from src.runtime.intent.registry import IntentEntry
from src.model_service.governance_runtime import render_governed_prompt


INTENT_CLASSIFICATION_PROMPT_TEMPLATE = (
    '你是医保智能体的意图识别模块。请分析用户消息，返回 JSON。\n\n'
    '可用意图：\n'
    '{intents_text}\n\n'
    '用户消息：{message}\n\n'
    '返回格式（仅返回 JSON，不要其他内容）：\n'
    '{{"intent": "<意图标识>", "confidence": <0-1>, "entities": {{}}, '
    '"citations": ["LLM意图推理"]}}'
)


def build_intent_prompt(message: str, registry: list[IntentEntry]) -> str:
    intent_lines = []
    for entry in registry:
        examples = '、'.join(entry.examples)
        intent_lines.append(
            f'- {entry.intent_id}: {entry.description}（示例：{examples}）'
        )
    intents_text = '\n'.join(intent_lines)

    rendered = render_governed_prompt(
        "intent.classify",
        variables={"intents_text": intents_text, "message": message},
        fallback_system="",
        fallback_user=INTENT_CLASSIFICATION_PROMPT_TEMPLATE,
    )
    return "\n\n".join(
        filter(None, [rendered.rendered_system_prompt, rendered.rendered_user_prompt])
    )
