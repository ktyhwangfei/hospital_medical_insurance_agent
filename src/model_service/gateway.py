from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Iterator

from src.config.model_service import ModelServiceConfig
from src.model_service.exceptions import (
    ModelAuthError,
    ModelConfigError,
    ModelExhaustedError,
    ModelRateLimitError,
    ModelServerError,
    ModelTimeoutError,
)
from src.model_service.models import Message, ModelRequest, ModelResponse, StreamChunk
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider
from src.model_service.router import ModelRouter

if TYPE_CHECKING:
    from src.model_service.governance_runtime import RuntimeModelProfile, RuntimeModelRoute

logger = logging.getLogger(__name__)

# 基础设施事件记录（延迟导入避免循环依赖）
def _truncate_content(content: str, max_len: int = 500) -> str:
    """截断 prompt/response 内容用于事件记录"""
    if not content:
        return ""
    if len(content) <= max_len:
        return content
    return content[:max_len] + "..."

def _audit_content_summary(content: str, scene: str) -> str:
    """AI 编写场景只记录内容哈希，其他场景保持原有截断摘要。"""
    if scene == "skill_authoring":
        digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
    return _truncate_content(content)


def _audit_error_summary(error: Exception, scene: str) -> str:
    """AI 编写场景只暴露异常类型与正文哈希，不改变原异常对象。"""
    if scene == "skill_authoring":
        digest = hashlib.sha256(str(error).encode("utf-8")).hexdigest()
        return f"{type(error).__name__}:sha256:{digest}"
    return str(error)


def _record_llm_event(
    model_name: str,
    scene: str,
    prompt_summary: str,
    response_summary: str,
    token_usage: dict | None = None,
    latency_ms: float = 0,
    status: str = "completed",
    error_message: str | None = None,
) -> None:
    """记录 LLM 调用事件。如果已有 workflow 上下文（被 step_task 追踪），跳过以避免重复。"""
    try:
        from src.runtime.infra_event.context import infra_context
        ctx = infra_context()
        # ★ 优化：有 workflow_id 说明已被 step_task 记录，跳过避免重复
        if ctx.workflow_id:
            return
        from src.runtime.infra_event.recorder import record_llm_call
        record_llm_call(
            model_name=model_name,
            scene=scene,
            prompt_summary=prompt_summary,
            response_summary=response_summary,
            token_usage=token_usage,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
        )
    except Exception:
        pass  # 事件记录失败不抛出，不影响主流程

RATE_LIMIT_DELAY = 10


def resolve_governed_route(scene: str, model_type: str) -> RuntimeModelRoute | None:
    # 延迟导入，避免存储协议加载模型包时循环导入。
    from src.model_service.governance_runtime import resolve_governed_route as resolve

    return resolve(scene, model_type)


class ModelGateway:
    def __init__(self, router: ModelRouter | None = None):
        self._router = router or ModelRouter()
        self._config = ModelServiceConfig()

    def generate(
        self,
        messages: list[Message],
        model_type: str,
        scene: str,
        max_tokens: int | None = None,
        model_override: str | None = None,
    ) -> ModelResponse:
        try:
            governed = resolve_governed_route(scene, model_type)
        except Exception:
            # 治理解析失败（如缺 MASTER_KEY / 存储不可用）降级 .env 直连配置，
            # 语义与 governed=None 一致；无直连配置时由下方 ModelConfigError 硬拦。
            logger.warning("治理路由解析失败，降级环境配置 scene=%s type=%s", scene, model_type, exc_info=True)
            governed = None
        if model_override:
            # model_override 非空时绕过治理与 router 直接用指定模型，并关闭 fallback
            # （用户显式选了某模型，失败应明确报错而非偷偷换模型）。
            chain: list[tuple[str, RuntimeModelProfile | None]] = [(model_override, None)]
        elif governed is None:
            model_name, fallbacks = self._router.resolve(scene, model_type)
            chain = [
                (name, None) for name in [model_name, *fallbacks]
            ]
        else:
            chain = [
                (profile.model_name, profile)
                for profile in [governed.primary, *governed.fallbacks]
            ]
        failures = []
        overall_start = time.time()  # 记录总耗时用于 all-failed 事件
        
        # 未配置真实模型（无 MODEL_BASE_URL/MODEL_API_KEY 且无已发布治理路由）时
        # 必须明确报错，绝不返回 dummy 示例假数据（Issue #19：假规则入库事故）。
        if governed is None and self._config.base_url == "dummy":
            raise ModelConfigError(
                "模型服务未配置：请在工作区根目录 .env 设置 MODEL_BASE_URL 与 "
                "MODEL_API_KEY（或发布模型治理路由）后重启；系统已禁用 dummy 假数据模式"
            )

        for current_model, profile in chain:
            params = (
                {
                    "temperature": profile.temperature,
                    "max_tokens": profile.max_tokens,
                }
                if profile is not None
                else self._router.get_model_params(current_model)
            )
            request = ModelRequest(
                messages=messages,
                model_type=current_model,
                scene=scene,
                temperature=params["temperature"],
                # 调用方可传 max_tokens 覆盖 router 默认（长文档提取需更大输出空间）
                max_tokens=(
                    params["max_tokens"]
                    if profile is not None or max_tokens is None
                    else max_tokens
                ),
            )

            model_failed = False
            for attempt in range(self._config.max_retries):
                try:
                    start = time.time()
                    result = (
                        self._call_provider(request, current_model, profile)
                        if profile is not None
                        else self._call_provider(request, current_model)
                    )
                    if not str(result.model_name or "").strip():
                        result = replace(result, model_name=current_model)
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
                    # 记录基础设施事件（成功）
                    _record_llm_event(
                        model_name=current_model,
                        scene=scene,
                        prompt_summary=_audit_content_summary(
                            messages[-1].content if messages else "", scene
                        ),
                        response_summary=_audit_content_summary(result.content, scene),
                        token_usage=result.usage,
                        latency_ms=latency_ms,
                        status="completed",
                    )
                    return result
                except ModelAuthError:
                    logger.error("model_auth_error", extra={"model_name": current_model, "scene": scene})
                    # 记录失败事件（认证错误直接抛出，不重试）
                    _record_llm_event(
                        model_name=current_model,
                        scene=scene,
                        prompt_summary=_audit_content_summary(
                            messages[-1].content if messages else "", scene
                        ),
                        response_summary=_audit_content_summary("", scene),
                        latency_ms=int((time.time() - overall_start) * 1000),
                        status="failed",
                        error_message=f"Auth error for {current_model}",
                    )
                    raise
                except ModelRateLimitError:
                    logger.warning("model_rate_limit", extra={"model_name": current_model, "scene": scene, "attempt": attempt + 1})
                    if attempt < self._config.max_retries - 1:
                        time.sleep(RATE_LIMIT_DELAY)
                        continue
                    failures.append({"model_name": current_model, "error_type": "rate_limit", "error_message": "rate limited"})
                    model_failed = True
                    break
                except (ModelTimeoutError, ModelServerError) as e:
                    logger.warning("model_retry", extra={"model_name": current_model, "scene": scene, "attempt": attempt + 1, "error": _audit_error_summary(e, scene)})
                    if attempt < self._config.max_retries - 1:
                        continue
                    failures.append({"model_name": current_model, "error_type": type(e).__name__, "error_message": _audit_error_summary(e, scene)})
                    model_failed = True
                    break

            # 记录单模型失败事件（当前模型所有重试耗尽）
            if model_failed:
                _record_llm_event(
                    model_name=current_model,
                    scene=scene,
                    prompt_summary=_audit_content_summary(
                        messages[-1].content if messages else "", scene
                    ),
                    response_summary=_audit_content_summary("", scene),
                    latency_ms=int((time.time() - overall_start) * 1000),
                    status="failed",
                    error_message=f"Model {current_model} exhausted after {self._config.max_retries} attempts",
                )

        # 所有模型均失败，记录汇总事件后抛出
        cumulative_ms = int((time.time() - overall_start) * 1000)
        _record_llm_event(
            model_name="(all_failed)",
            scene=scene,
            prompt_summary=_audit_content_summary(
                messages[-1].content if messages else "", scene
            ),
            response_summary=_audit_content_summary("", scene),
            latency_ms=cumulative_ms,
            status="failed",
            error_message=f"All models in fallback chain [{', '.join(f['model_name'] for f in failures)}] failed after {cumulative_ms}ms",
        )
        raise ModelExhaustedError("All models in fallback chain failed", failures=failures)

    def generate_stream(self, messages: list[Message], model_type: str, scene: str) -> Iterator[StreamChunk]:
        try:
            governed = resolve_governed_route(scene, model_type)
        except Exception:
            logger.warning("治理路由解析失败，降级环境配置 scene=%s type=%s", scene, model_type, exc_info=True)
            governed = None
        if governed is None:
            model_name, _ = self._router.resolve(scene, model_type)
            targets: list[tuple[str, RuntimeModelProfile | None]] = [(model_name, None)]
        else:
            targets = [
                (profile.model_name, profile)
                for profile in [governed.primary, *governed.fallbacks]
            ]

        for index, (model_name, profile) in enumerate(targets):
            params = (
                {
                    "temperature": profile.temperature,
                    "max_tokens": profile.max_tokens,
                }
                if profile is not None
                else self._router.get_model_params(model_name)
            )
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
                provider = (
                    self._get_provider(model_name, profile)
                    if profile is not None
                    else self._get_provider(model_name)
                )
                for chunk in provider.invoke_stream(request):
                    total_chunks += 1
                    yield chunk
                latency_ms = int((time.time() - start) * 1000)
                logger.info("model_stream_success", extra={"model_name": model_name, "scene": scene, "total_chunks": total_chunks, "latency_ms": latency_ms})
                # 记录基础设施事件（成功）
                _record_llm_event(
                    model_name=model_name,
                    scene=scene,
                    prompt_summary=_audit_content_summary(
                        messages[-1].content if messages else "", scene
                    ),
                    response_summary=_audit_content_summary(
                        f"(stream, {total_chunks} chunks)", scene
                    ),
                    latency_ms=latency_ms,
                    status="completed",
                )
                return
            except Exception as e:
                latency_ms = int((time.time() - start) * 1000)
                logger.error("model_stream_interrupted", extra={"model_name": model_name, "scene": scene, "total_chunks": total_chunks, "latency_ms": latency_ms, "error": _audit_error_summary(e, scene)})
                # 记录基础设施事件（失败）
                _record_llm_event(
                    model_name=model_name,
                    scene=scene,
                    prompt_summary=_audit_content_summary(
                        messages[-1].content if messages else "", scene
                    ),
                    response_summary=_audit_content_summary("", scene),
                    latency_ms=latency_ms,
                    status="failed",
                    error_message=_audit_error_summary(e, scene),
                )
                retryable = isinstance(
                    e, (ModelRateLimitError, ModelTimeoutError, ModelServerError)
                )
                if (
                    governed is not None
                    and total_chunks == 0
                    and retryable
                    and index < len(targets) - 1
                ):
                    continue
                raise

    def _call_provider(
        self,
        request: ModelRequest,
        model_name: str,
        runtime_profile: RuntimeModelProfile | None = None,
    ) -> ModelResponse:
        provider = (
            self._get_provider(model_name, runtime_profile)
            if runtime_profile is not None
            else self._get_provider(model_name)
        )
        return provider.invoke(request)

    def _get_provider(
        self,
        model_name: str,
        runtime_profile: RuntimeModelProfile | None = None,
    ) -> OpenAICompatibleProvider:
        if runtime_profile is not None:
            return OpenAICompatibleProvider(
                base_url=runtime_profile.base_url,
                api_key=runtime_profile.api_key.get_secret_value(),
                timeout=runtime_profile.timeout_seconds,
            )
        return OpenAICompatibleProvider(
            base_url=self._config.base_url,
            api_key=self._config.api_key,
            timeout=self._config.default_timeout,
        )
