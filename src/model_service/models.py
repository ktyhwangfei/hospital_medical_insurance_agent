from dataclasses import dataclass


@dataclass
class Message:
    role: str
    content: str


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class ModelRequest:
    messages: list[Message]
    model_type: str
    scene: str
    temperature: float = 0.7
    max_tokens: int = 2048


@dataclass
class ModelResponse:
    content: str
    model_name: str
    usage: TokenUsage
    finish_reason: str


@dataclass
class StreamChunk:
    content: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
