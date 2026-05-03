from typing import Iterator, Protocol

from src.model_service.models import ModelRequest, ModelResponse, StreamChunk


class ModelProviderProtocol(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, request: ModelRequest) -> Iterator[StreamChunk]:
        raise NotImplementedError


class ModelGatewayProtocol(Protocol):
    def generate(self, messages: list, model_type: str, scene: str) -> ModelResponse:
        raise NotImplementedError

    def generate_stream(self, messages: list, model_type: str, scene: str) -> Iterator[StreamChunk]:
        raise NotImplementedError
