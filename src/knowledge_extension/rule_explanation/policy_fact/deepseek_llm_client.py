from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError

load_dotenv()

logger = logging.getLogger(__name__)


class DeepSeekLLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.getenv("MODEL_API_KEY")
        self.base_url = base_url or os.getenv("MODEL_BASE_URL")
        self.model = model or os.getenv("MODEL")

        if not self.api_key:
            raise RuntimeError("未配置 MODEL_API_KEY。请先设置环境变量 MODEL_API_KEY。")

        if not self.base_url:
            raise RuntimeError("未配置 MODEL_BASE_URL。请先设置环境变量 MODEL_BASE_URL。")

        if not self.model:
            raise RuntimeError("未配置 MODEL。请先设置环境变量 MODEL。")

        logger.info(
            "[DeepSeekLLMClient] 初始化 base_url=%s, model=%s",
            self.base_url,
            self.model,
        )

        timeout = httpx.Timeout(
            connect=20.0,   # 建立连接最多 20 秒
            read=120.0,     # 等模型返回最多 120 秒
            write=30.0,
            pool=20.0,
        )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
            max_retries=0,  # 先关闭 SDK 内部重试，避免看起来像“卡死”
        )

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> Any:
        logger.info(
            "[chat_json] 请求开始 model=%s, system_len=%s, user_len=%s",
            self.model,
            len(system_prompt or ""),
            len(user_prompt or ""),
        )

        start = time.time()

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt+"""
                        输出约束：
                        1. 只返回 JSON。
                        2. 不要复制政策原文全文。
                        3. evidence_text 每条不超过 80 字。
                        4. explanation 每条不超过 80 字。
                        5. atomic_rules 最多 8 条。
                        6. composite_rule.description 不超过 120 字。
                        7. 所有字符串字段必须简短。
                        8. 不要输出推理过程、不要输出 Markdown。
                     """},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
                max_tokens=8192,
            )
            choice = response.choices[0]
            content = choice.message.content
            finish_reason = choice.finish_reason

            logger.info(
                "[chat_json] finish_reason=%s, content_len=%s",
                finish_reason,
                len(content or ""),
            )

            if finish_reason == "length":
                raise RuntimeError(
                    f"LLM输出被截断：finish_reason=length, content_len={len(content or '')}"
                )

            logger.info(
                "[chat_json] 请求完成 cost=%.2fs",
                time.time() - start,
            )

        except APITimeoutError as e:
            logger.exception("[chat_json] 请求超时 cost=%.2fs", time.time() - start)
            raise RuntimeError(f"LLM请求超时: {repr(e)}") from e

        except APIConnectionError as e:
            logger.exception("[chat_json] 连接失败 cost=%.2fs", time.time() - start)
            raise RuntimeError(f"LLM连接失败，请检查网络、代理、base_url: {repr(e)}") from e

        except APIStatusError as e:
            logger.exception(
                "[chat_json] API状态错误 status_code=%s, response=%s",
                e.status_code,
                e.response.text if e.response else None,
            )
            raise RuntimeError(
                f"LLM API返回错误: status_code={e.status_code}, body={e.response.text if e.response else None}"
            ) from e

        except Exception as e:
            logger.exception("[chat_json] 未知异常 cost=%.2fs", time.time() - start)
            raise RuntimeError(f"LLM调用未知异常: {repr(e)}") from e

        content = response.choices[0].message.content

        logger.info(
            "[chat_json] 返回内容长度 content_len=%s",
            len(content or ""),
        )

        return self._parse_json_content(content)

    @staticmethod
    def _parse_json_content(content: Any) -> Any:
        if isinstance(content, dict):
            return content

        if content is None:
            raise ValueError("LLM 返回内容为空")

        text = str(content).strip()

        if text.startswith("```json"):
            text = text.replace("```json", "", 1).strip()
        if text.startswith("```"):
            text = text.replace("```", "", 1).strip()
        if text.endswith("```"):
            text = text[:-3].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("[chat_json] JSON解析失败，原始内容前1000字符：%s", text[:1000])
            raise ValueError(f"LLM返回内容不是合法JSON: {repr(e)}") from e