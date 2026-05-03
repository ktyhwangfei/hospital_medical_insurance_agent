from enum import Enum


class ModelType(str, Enum):
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    OCR = "ocr"


ROUTING_TABLE = {
    ("settlement_exception_guidance", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",
    ("pre_discharge_quality_control", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",
    ("intent_recognition", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",
    ("default", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",
    ("default", ModelType.EMBEDDING): "text-embedding-3-small",
}

FALLBACK_CHAINS = {
    "deepseek-ai/DeepSeek-V3.2": ["deepseek-ai/DeepSeek-V4-Flash"],
    "text-embedding-3-small": [],
}

MODEL_PARAMS = {
    "deepseek-ai/DeepSeek-V3.2": {"temperature": 0.1, "max_tokens": 512},
    "deepseek-ai/DeepSeek-V4-Flash": {"temperature": 0.5, "max_tokens": 1024},
}
