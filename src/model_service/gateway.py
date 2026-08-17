from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Iterator

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
    ) -> ModelResponse:
        governed = resolve_governed_route(scene, model_type)
        if governed is None:
            model_name, fallbacks = self._router.resolve(scene, model_type)
            chain: list[tuple[str, RuntimeModelProfile | None]] = [
                (name, None) for name in [model_name, *fallbacks]
            ]
        else:
            chain = [
                (profile.model_name, profile)
                for profile in [governed.primary, *governed.fallbacks]
            ]
        failures = []
        overall_start = time.time()  # 记录总耗时用于 all-failed 事件
        
        # 调试模式: 如果配置了特殊的 dummy LLM，直接返回以绕过 API 报错
        if governed is None and self._config.base_url == "dummy":
            # 按 scene 返回不同结构的示例数据
            if scene == "fee_explanation":
                content = (
                    "【本次结论】\n"
                    "[CONCLUSION]\n"
                    "本次结算中，您的统筹自付为 4,962.67 元。"
                    "这笔费用是基本医保统筹段内按政策比例需要您个人承担的部分，"
                    "不包含起付线、大额自付和医保外费用。\n\n"
                    "[OFFICE_NOTE]\n"
                    "本次解释基于费用项 [统筹自付]，数据来源为结算记录，"
                    "仅供参考，不作为报销凭证。\n"
                )
            elif "结算周期" in messages[-1].content or "90天" in messages[-1].content:
                content = (
                    "===PATIENT===\n"
                    "根据本次结算数据，住院治疗满 90 天将按医保政策进入新的结算周期。"
                    "周期切换后起付线重新计算，超出部分的费用按对应政策比例报销。\n"
                    "===PATIENT_END===\n"
                    "===OFFICE===\n"
                    "匹配规则：住院 90 天结算周期（period_rule）。"
                    "数据来源：结算记录 + 政策规则检索。\n"
                    "===OFFICE_END===\n"
                )
            else:
                content = (
                    "===PATIENT===\n"
                    "根据本次结算数据，您的统筹自付金额为 4,962.67 元，"
                    "这是基本医保统筹段内按政策比例需要您个人承担的部分，"
                    "不包含起付线、大额自付和医保外费用。\n"
                    "===PATIENT_END===\n"
                    "===OFFICE===\n"
                    "本次结算统筹自付 4,962.67 元（来源：yb_zyfdxx.bdtczf），"
                    "为统筹段按政策比例自付部分，已匹配相关政策规则。\n"
                    "===OFFICE_END===\n"
                )

            return ModelResponse(
                content=content,
                model_name="dummy_llm",
                usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                finish_reason="stop"
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
                        prompt_summary=_truncate_content(messages[-1].content if messages else ""),
                        response_summary=_truncate_content(result.content),
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
                        prompt_summary=_truncate_content(messages[-1].content if messages else ""),
                        response_summary="",
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
                    logger.warning("model_retry", extra={"model_name": current_model, "scene": scene, "attempt": attempt + 1, "error": str(e)})
                    if attempt < self._config.max_retries - 1:
                        continue
                    failures.append({"model_name": current_model, "error_type": type(e).__name__, "error_message": str(e)})
                    model_failed = True
                    break

            # 记录单模型失败事件（当前模型所有重试耗尽）
            if model_failed:
                _record_llm_event(
                    model_name=current_model,
                    scene=scene,
                    prompt_summary=_truncate_content(messages[-1].content if messages else ""),
                    response_summary="",
                    latency_ms=int((time.time() - overall_start) * 1000),
                    status="failed",
                    error_message=f"Model {current_model} exhausted after {self._config.max_retries} attempts",
                )

        # 所有模型均失败，记录汇总事件后抛出
        cumulative_ms = int((time.time() - overall_start) * 1000)
        _record_llm_event(
            model_name="(all_failed)",
            scene=scene,
            prompt_summary=_truncate_content(messages[-1].content if messages else ""),
            response_summary="",
            latency_ms=cumulative_ms,
            status="failed",
            error_message=f"All models in fallback chain [{', '.join(f['model_name'] for f in failures)}] failed after {cumulative_ms}ms",
        )
        raise ModelExhaustedError("All models in fallback chain failed", failures=failures)

    def generate_stream(self, messages: list[Message], model_type: str, scene: str) -> Iterator[StreamChunk]:
        governed = resolve_governed_route(scene, model_type)
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
                # 记录基础设施事件
                _record_llm_event(
                    model_name=model_name,
                    scene=scene,
                    prompt_summary=_truncate_content(messages[-1].content if messages else ""),
                    response_summary=f"(stream, {total_chunks} chunks)",
                    latency_ms=latency_ms,
                    status="completed",
                )
                return
            except Exception as e:
                latency_ms = int((time.time() - start) * 1000)
                logger.error("model_stream_interrupted", extra={"model_name": model_name, "scene": scene, "total_chunks": total_chunks, "latency_ms": latency_ms, "error": str(e)})
                # 记录基础设施事件（失败）
                _record_llm_event(
                    model_name=model_name,
                    scene=scene,
                    prompt_summary=_truncate_content(messages[-1].content if messages else ""),
                    response_summary="",
                    latency_ms=latency_ms,
                    status="failed",
                    error_message=str(e),
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
