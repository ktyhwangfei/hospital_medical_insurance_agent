import json
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

import httpx

from src.model_service.exceptions import ModelAuthError, ModelRateLimitError, ModelServerError, ModelTimeoutError
from src.model_service.models import ModelRequest, ModelResponse, StreamChunk, TokenUsage


class OpenAICompatibleProvider:
    _MODEL_LIST_MAX_BYTES = 1024 * 1024
    _MODEL_LIST_MAX_ITEMS = 1000
    _MODEL_ID_MAX_LENGTH = 256

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
        except httpx.TimeoutException:
            raise ModelTimeoutError(
                "Model provider request timed out", model_name=request.model_type
            ) from None
        except httpx.NetworkError:
            raise ModelServerError(
                "Model provider network error", model_name=request.model_type
            ) from None
        except httpx.HTTPError:
            raise ModelServerError(
                "Model provider HTTP error", model_name=request.model_type
            ) from None
        return self._handle_response(response)

    def list_models(self, *, connect_ip: str | None = None) -> list[str]:
        """GET {base_url}/models，返回可用模型 id 列表（字母序）。

        标准 OpenAI 模型列表接口；认证失败/超时复用既有异常类型，
        404/405（端点不支持列表）也归为 ModelServerError 由上层转可读提示。
        """
        try:
            payload = self._read_model_list(connect_ip)
        except httpx.TimeoutException:
            raise ModelTimeoutError("Model list request timed out") from None
        except httpx.NetworkError:
            raise ModelServerError("Model list network error") from None
        except httpx.HTTPError:
            raise ModelServerError("Model list HTTP error") from None
        try:
            data = json.loads(payload)["data"]
            if not isinstance(data, list):
                raise TypeError
            if len(data) > self._MODEL_LIST_MAX_ITEMS:
                raise ModelServerError("Model list returned too many models")
            ids = sorted(
                {
                    item["id"]
                    for item in data
                    if isinstance(item, dict)
                    and isinstance(item.get("id"), str)
                    and item["id"]
                    and len(item["id"]) <= self._MODEL_ID_MAX_LENGTH
                }
            )
        except ModelServerError:
            raise
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            raise ModelServerError("Model list returned invalid payload") from None
        if not ids:
            raise ModelServerError("Model list returned no models")
        return ids

    def _read_model_list(self, connect_ip: str | None) -> bytearray:
        url = f"{self._base_url}/models"
        headers = self._headers()
        extensions = {}
        if connect_ip is not None:
            parsed = urlsplit(url)
            ip_host = f"[{connect_ip}]" if ":" in connect_ip else connect_ip
            netloc = f"{ip_host}:{parsed.port}" if parsed.port else ip_host
            url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
            headers["Host"] = parsed.netloc
            extensions["sni_hostname"] = parsed.hostname or ""
        with httpx.Client(timeout=self._timeout) as client:
            with client.stream(
                "GET", url, headers=headers, extensions=extensions
            ) as response:
                self._check_status(response)
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > self._MODEL_LIST_MAX_BYTES:
                        raise ModelServerError("Model list response too large")
        return payload

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
                        except json.JSONDecodeError:
                            raise ModelServerError(
                                "Model provider returned malformed stream data",
                                model_name=request.model_type,
                            ) from None
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
        except httpx.TimeoutException:
            raise ModelTimeoutError(
                "Model provider request timed out", model_name=request.model_type
            ) from None
        except httpx.NetworkError:
            raise ModelServerError(
                "Model provider network error", model_name=request.model_type
            ) from None
        except httpx.HTTPError:
            raise ModelServerError(
                "Model provider HTTP error", model_name=request.model_type
            ) from None

    def invoke_embedding(self, text: str, model: str) -> ModelResponse:
        payload = {"input": text, "model": model}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/embeddings",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.TimeoutException:
            raise ModelTimeoutError(
                "Model provider request timed out", model_name=model
            ) from None
        except httpx.NetworkError:
            raise ModelServerError(
                "Model provider network error", model_name=model
            ) from None
        except httpx.HTTPError:
            raise ModelServerError(
                "Model provider HTTP error", model_name=model
            ) from None
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
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

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
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            raise ModelServerError(
                "Model provider returned invalid JSON", model_name=""
            ) from None
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
        self._check_status_code(response.status_code)

    def _check_status_code(self, status_code: int) -> None:
        if status_code == 401 or status_code == 403:
            raise ModelAuthError(
                f"Model provider authentication failed (HTTP {status_code})",
                model_name="",
            )
        if status_code == 429:
            raise ModelRateLimitError(
                "Model provider rate limited request (HTTP 429)", model_name=""
            )
        if 400 <= status_code < 500:
            raise ModelServerError(
                f"Model provider rejected request (HTTP {status_code})",
                model_name="",
            )
        if status_code >= 500:
            raise ModelServerError(
                f"Model provider server error (HTTP {status_code})",
                model_name="",
            )
        if not 200 <= status_code < 300:
            raise ModelServerError(
                f"Model provider unexpected response (HTTP {status_code})",
                model_name="",
            )
