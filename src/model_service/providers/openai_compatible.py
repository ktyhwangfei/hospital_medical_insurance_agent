import json
from typing import Iterator

import httpx

from src.model_service.exceptions import ModelAuthError, ModelRateLimitError, ModelServerError, ModelTimeoutError
from src.model_service.models import ModelRequest, ModelResponse, StreamChunk, TokenUsage

class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def invoke(self, request: ModelRequest) -> ModelResponse:
        payload = self._build_payload(request, stream=False)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"Model provider timeout: {exc}", model_name=request.model_type) from exc
        except httpx.NetworkError as exc:
            raise ModelServerError(f"Model provider network error: {exc}", model_name=request.model_type) from exc
        except httpx.HTTPError as exc:
            raise ModelServerError(f"Model provider http error: {exc}", model_name=request.model_type) from exc
        return self._handle_response(response)

    def invoke_stream(self, request: ModelRequest) -> Iterator[StreamChunk]:
        payload = self._build_payload(request, stream=True)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    if response.status_code >= 400:
                        response.read()
                    self._check_status(response)
                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError as exc:
                            raise ModelServerError(f"Malformed stream JSON: {exc}", model_name=request.model_type) from exc
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        finish_reason = chunk["choices"][0].get("finish_reason")
                        usage = None
                        if "usage" in chunk:
                            usage = TokenUsage(
                                prompt_tokens=chunk["usage"].get("prompt_tokens", 0),
                                completion_tokens=chunk["usage"].get("completion_tokens", 0),
                            )
                        yield StreamChunk(
                            content=content,
                            finish_reason=finish_reason,
                            usage=usage,
                        )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"Model provider timeout: {exc}", model_name=request.model_type) from exc
        except httpx.NetworkError as exc:
            raise ModelServerError(f"Model provider network error: {exc}", model_name=request.model_type) from exc
        except httpx.HTTPError as exc:
            raise ModelServerError(f"Model provider http error: {exc}", model_name=request.model_type) from exc

    def invoke_embedding(self, text: str, model: str) -> ModelResponse:
        payload = {"input": text, "model": model}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/embeddings",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"Model provider timeout: {exc}", model_name=model) from exc
        except httpx.NetworkError as exc:
            raise ModelServerError(f"Model provider network error: {exc}", model_name=model) from exc
        except httpx.HTTPError as exc:
            raise ModelServerError(f"Model provider http error: {exc}", model_name=model) from exc
        self._check_status(response)
        data = response.json()
        embedding = data["data"][0]["embedding"]
        return ModelResponse(
            content=json.dumps(embedding),
            model_name=model,
            usage=TokenUsage(
                prompt_tokens=data["usage"].get("prompt_tokens", 0),
                completion_tokens=0,
            ),
            finish_reason="stop",
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: ModelRequest, stream: bool) -> dict:
        return {
            "model": request.model_type,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }

    def _handle_response(self, response: httpx.Response) -> ModelResponse:
        self._check_status(response)
        data = response.json()
        if "error" in data:
            raise ModelServerError(
                "Model provider returned an error payload",
                model_name="",
            )
        if "choices" in data:
            try:
                choice = data["choices"][0]
                content = self._valid_response_content(choice["message"]["content"])
            except (IndexError, KeyError, TypeError) as exc:
                raise ModelServerError(
                    "Model provider returned an invalid choices payload",
                    model_name="",
                ) from exc
            usage = data.get("usage", {})
            return ModelResponse(
                content=content,
                model_name=data.get("model", ""),
                usage=TokenUsage(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                ),
                finish_reason=choice.get("finish_reason", "stop"),
            )
        for field in ("result", "response", "text"):
            if field in data:
                return ModelResponse(
                    content=self._valid_response_content(data[field]),
                    model_name=data.get("model", ""),
                    usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
                    finish_reason="stop",
                )
        raise ModelServerError(
            "Model provider returned an unsupported response payload",
            model_name="",
        )

    @staticmethod
    def _valid_response_content(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ModelServerError(
                "Model provider returned empty or invalid content",
                model_name="",
            )
        return value

    def _check_status(self, response: httpx.Response) -> None:
        if response.status_code == 401 or response.status_code == 403:
            raise ModelAuthError(f"Auth error: {response.text}", model_name="")
        if response.status_code == 429:
            raise ModelRateLimitError(f"Rate limited: {response.text}", model_name="")
        if response.status_code == 400:
            raise ModelServerError(f"Bad request: {response.text}", model_name="")
        if 400 <= response.status_code < 500 and response.status_code not in (400, 401, 403, 429):
            raise ModelServerError(f"Client error ({response.status_code}): {response.text}", model_name="")
        if response.status_code >= 500:
            raise ModelServerError(f"Server error: {response.text}", model_name="")
