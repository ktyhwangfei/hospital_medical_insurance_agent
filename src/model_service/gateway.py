import logging
import time
from typing import Iterator

from src.config.model_service import ModelServiceConfig
from src.model_service.exceptions import (
    ModelAuthError,
    ModelExhaustedError,
    ModelRateLimitError,
    ModelServerError,
    ModelTimeoutError,
)
from src.model_service.models import Message, ModelRequest, ModelResponse, StreamChunk
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider
from src.model_service.router import ModelRouter

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 10


class ModelGateway:
    def __init__(self, router: ModelRouter | None = None):
        self._router = router or ModelRouter()
        self._config = ModelServiceConfig()

    def generate(self, messages: list[Message], model_type: str, scene: str) -> ModelResponse:
        model_name, fallbacks = self._router.resolve(scene, model_type)
        chain = [model_name] + fallbacks
        failures = []

        for current_model in chain:
            params = self._router.get_model_params(current_model)
            request = ModelRequest(
                messages=messages,
                model_type=current_model,
                scene=scene,
                temperature=params["temperature"],
                max_tokens=params["max_tokens"],
            )

            for attempt in range(self._config.max_retries):
                try:
                    start = time.time()
                    result = self._call_provider(request, current_model)
                    latency_ms = int((time.time() - start) * 1000)
                    logger.info(
                        "model_call_success",
                        extra={
                            "model_name": current_model,
                            "scene": scene,
                            "latency_ms": latency_ms,
                            "token_usage": result.usage,
                        },
                    )
                    return result
                except ModelAuthError:
                    logger.error("model_auth_error", extra={"model_name": current_model, "scene": scene})
                    raise
                except ModelRateLimitError:
                    logger.warning("model_rate_limit", extra={"model_name": current_model, "scene": scene, "attempt": attempt + 1})
                    if attempt < self._config.max_retries - 1:
                        time.sleep(RATE_LIMIT_DELAY)
                        continue
                    failures.append({"model_name": current_model, "error_type": "rate_limit", "error_message": "rate limited"})
                    break
                except (ModelTimeoutError, ModelServerError) as e:
                    logger.warning("model_retry", extra={"model_name": current_model, "scene": scene, "attempt": attempt + 1, "error": str(e)})
                    if attempt < self._config.max_retries - 1:
                        continue
                    failures.append({"model_name": current_model, "error_type": type(e).__name__, "error_message": str(e)})
                    break

        raise ModelExhaustedError("All models in fallback chain failed", failures=failures)

    def generate_stream(self, messages: list[Message], model_type: str, scene: str) -> Iterator[StreamChunk]:
        model_name, _ = self._router.resolve(scene, model_type)
        params = self._router.get_model_params(model_name)
        request = ModelRequest(
            messages=messages,
            model_type=model_name,
            scene=scene,
            temperature=params["temperature"],
            max_tokens=params["max_tokens"],
        )

        start = time.time()
        total_chunks = 0
        try:
            provider = self._get_provider(model_name)
            for chunk in provider.invoke_stream(request):
                total_chunks += 1
                yield chunk
            latency_ms = int((time.time() - start) * 1000)
            logger.info("model_stream_success", extra={"model_name": model_name, "scene": scene, "total_chunks": total_chunks, "latency_ms": latency_ms})
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            logger.error("model_stream_interrupted", extra={"model_name": model_name, "scene": scene, "total_chunks": total_chunks, "latency_ms": latency_ms, "error": str(e)})
            raise

    def _call_provider(self, request: ModelRequest, model_name: str) -> ModelResponse:
        provider = self._get_provider(model_name)
        return provider.invoke(request)

    def _get_provider(self, model_name: str) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            base_url=self._config.base_url,
            api_key=self._config.api_key,
            timeout=self._config.default_timeout,
        )
