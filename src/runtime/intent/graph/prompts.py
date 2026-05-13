from src.runtime.intent.models import IntentCandidate


def build_discrimination_prompt(message: str, candidates: list[IntentCandidate]) -> str:
    candidate_lines = []
    for c in candidates:
        kw_str = '、'.join(c.matched_keywords) if c.matched_keywords else '无'
        candidate_lines.append(
            f'- {c.intent_id}（关键词匹配度: {c.score:.2f}，匹配词: {kw_str}）'
        )
    candidates_text = '\n'.join(candidate_lines)

    return (
        '你是医保智能体的意图识别模块。请根据用户消息和候选意图列表，判断最可能的意图。\n\n'
        '候选意图：\n'
        f'{candidates_text}\n\n'
        f'用户消息：{message}\n\n'
        '请返回 JSON（仅返回 JSON，不要其他内容）：\n'
        '{\n'
        '  "intent": "<意图标识>",\n'
        '  "confidence": <0-1的置信度>,\n'
        '  "entities": {},\n'
        '  "citations": ["推理依据"]\n'
        '}'
    )
