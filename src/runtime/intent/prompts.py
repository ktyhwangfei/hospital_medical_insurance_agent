from src.runtime.intent.registry import IntentEntry


def build_intent_prompt(message: str, registry: list[IntentEntry]) -> str:
    intent_lines = []
    for entry in registry:
        examples = '、'.join(entry.examples)
        intent_lines.append(
            f'- {entry.intent_id}: {entry.description}（示例：{examples}）'
        )
    intents_text = '\n'.join(intent_lines)

    return (
        '你是医保智能体的意图识别模块。请分析用户消息，返回 JSON。\n\n'
        '可用意图：\n'
        f'{intents_text}\n\n'
        f'用户消息：{message}\n\n'
        '返回格式（仅返回 JSON，不要其他内容）：\n'
        '{"intent": "<意图标识>", "confidence": <0-1>, "entities": {}, '
        '"citations": ["LLM意图推理"]}'
    )
