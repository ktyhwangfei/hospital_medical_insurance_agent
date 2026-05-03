from src.runtime.intent.parser import parse_intent


def detect_intent(message: str) -> str:
    result = parse_intent(message)
    return result.intent
