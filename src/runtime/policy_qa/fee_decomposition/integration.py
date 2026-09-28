"""费用分解接入 policy-qa 入口的门控与表述层（Issue #78 设计 §12/§13/§15 步骤 5）。

门控（任一不满足即返回 None，绝不影响主问答链路）：
- `FEE_DECOMPOSITION_ROUNDING_MODE`：取整模式显式配置，无默认（EOP-RND-001 待确认，
  未配置或取值非法 = 功能关闭，fail-closed）；
- `FEE_DECOMPOSITION_HOSPITAL_CODE`：源系统（o_Trade 院区列）取值，用于交易定位；
  与部署级 `PLATFORM_HOSPITAL_CODE` 是不同口径，未配置 = 功能关闭；
- 数据供给连接可用（复用结算 provider 的连接工厂，bjybdb 库）。

险种/医疗类别解析：只接受语义层已解析字符串的精确匹配（城镇职工基本医疗保险 +
普通门诊），其余一律 unknown → 内核走 UNSUPPORTED_PROFILE，不猜测（设计 §6.1 P0）。

模型表述（设计 §12）：模型只做语言润色；校验润色后数字集合 ⊆ 模板数字集合，
越界/异常/模型不可用一律回退确定性模板（summary_source 记录实际来源）。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.public_view import render_summary
from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult
from src.runtime.policy_qa.fee_decomposition.snapshot_service import (
    decompose_outpatient_trade,
)
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special import (
    decompose_outpatient_special_settlement,
)

logger = logging.getLogger(__name__)

_ROUNDING_ENV = "FEE_DECOMPOSITION_ROUNDING_MODE"
_HOSPITAL_ENV = "FEE_DECOMPOSITION_HOSPITAL_CODE"

#: 险种/医疗类别精确匹配表（语义层已解析字符串；其余值一律不映射，不猜测）
_PROFILE_EXACT_MATCH = ("城镇职工基本医疗保险", "普通门诊")

#: 门特组合精确匹配表（Issue #78 第二流程）。ESP-CODE-001/002 实测待码表确认，
#: 语义层字符串未确认前不注册匹配 → resolver 返回 None → 内核 UNSUPPORTED_PROFILE/unavailable，
#: 签核后在此登记即可放行（不改流程代码）。
_SPECIAL_PROFILE_EXACT_MATCH: tuple[tuple[str, str], ...] = ()

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class DecompositionPresentation:
    """分解结果 + 表述文本（summary_source ∈ template/model，供公开契约标注）。"""

    result: SettlementDecompositionResult
    summary_text: str
    summary_source: str


def _rounding_mode_from_env() -> RoundingMode | None:
    """取整模式显式门控：未配置/取值非法 → None（功能关闭），无默认模式。"""
    raw = os.getenv(_ROUNDING_ENV, "").strip()
    if not raw:
        return None
    try:
        return RoundingMode(raw)
    except ValueError:
        logger.warning("[FEE-DECOMP] %s=%r 非法，费用分解关闭", _ROUNDING_ENV, raw)
        return None


def _resolve_profile_from_context(context: Any) -> tuple[str, str] | None:
    """语义层已解析的险种/医疗类别字符串 → 标准组合；仅精确匹配，其余 None。"""
    insurance = str(getattr(context, "insurance_type", None) or "").strip()
    category = str(getattr(context, "service_type", None) or "").strip()
    if (insurance, category) == _PROFILE_EXACT_MATCH:
        return ("employee", "outpatient")
    return None


def _resolve_special_profile_from_context(context: Any) -> tuple[str, str] | None:
    """门特组合的险种/类别精确匹配（ESP-CODE-001/002 待码表确认，未注册前恒 None）。"""
    insurance = str(getattr(context, "insurance_type", None) or "").strip()
    category = str(getattr(context, "service_type", None) or "").strip()
    if (insurance, category) in _SPECIAL_PROFILE_EXACT_MATCH:
        return ("employee", "outpatient_special")
    return None


def polish_summary(summary_text: str) -> tuple[str, str]:
    """模型润色（设计 §12）：仅语言组织；数字集合越界或模型不可用回退模板。

    返回 (文本, 来源)；来源为 "model" 时保证润色文本的数字集合 ⊆ 模板数字集合。
    """
    if not summary_text.strip():
        return summary_text, "template"
    try:
        from src.model_service.gateway import ModelGateway
        from src.model_service.models import Message

        prompt = (
            "以下是一段医保门诊费用分解的确定性说明。请仅做语言润色：\n"
            "1. 不得改变、新增或删除任何数字与结论；\n"
            "2. 不得把'部分解释/暂不可用/暂不能核对'改写为确定已解释；\n"
            "3. 不得补充原文没有的规则或比例。\n\n"
            f"原文：\n{summary_text}\n\n润色后："
        )
        gateway = ModelGateway()
        response = gateway.generate(
            messages=[Message(role="user", content=prompt)],
            model_type="llm",
            scene="policy_qa_fee_decomposition",
            max_tokens=2048,
        )
        polished = (response.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — 模型不可用回退模板，不阻塞主链路
        logger.warning("[FEE-DECOMP] 模型润色失败，使用确定性模板: %s", exc)
        return summary_text, "template"
    if not polished:
        return summary_text, "template"
    template_numbers = set(_NUMBER_PATTERN.findall(summary_text))
    polished_numbers = set(_NUMBER_PATTERN.findall(polished))
    if not polished_numbers <= template_numbers:
        logger.warning("[FEE-DECOMP] 模型润色引入新数字，回退确定性模板")
        return summary_text, "template"
    return polished, "model"


def maybe_decompose_outpatient(
    provider: Any,
    trade_no: str,
    routing_context: Any,
) -> DecompositionPresentation | None:
    """门诊交易号 → 费用分解表述。任何门控不满足或异常都返回 None，不抛异常。"""
    rounding_mode = _rounding_mode_from_env()
    hospital_code = os.getenv(_HOSPITAL_ENV, "").strip()
    if rounding_mode is None or not hospital_code:
        return None
    # 复用结算 provider 的数据供给连接工厂（同一组合根，bjybdb 库）
    connect = getattr(provider, "_connect", None)
    if connect is None:
        return None
    resolved = _resolve_profile_from_context(routing_context)
    profile_resolver = (lambda _row: resolved) if resolved is not None else None
    conn = None
    try:
        conn = connect("bjybdb")
        result = decompose_outpatient_trade(
            conn,
            trade_no,
            hospital_code,
            rounding_mode,
            profile_resolver=profile_resolver,
        )
    except Exception as exc:  # noqa: BLE001 — 分解失败不影响主问答链路
        logger.warning("[FEE-DECOMP] 费用分解失败，本次不附带分解结果: %s", exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    summary_text, summary_source = polish_summary(render_summary(result))
    return DecompositionPresentation(
        result=result, summary_text=summary_text, summary_source=summary_source)


def maybe_decompose_special_outpatient(
    provider: Any,
    djh: str,
    routing_context: Any,
    *,
    cycle_context_override: Any = None,
    allow_observed_deductible: bool = False,
) -> DecompositionPresentation | None:
    """门特登记号（djh）→ 费用分解表述（Issue #78 第二流程）。

    门控与 maybe_decompose_outpatient 一致；profile 仅接受显式确认的险种×类别
    精确匹配（ESP-CODE-001/002 待码表确认，未注册 → None → UNSUPPORTED_PROFILE/unavailable）。
    cycle_context_override/allow_observed_deductible 为评估口径开关，生产默认不注入。
    """
    rounding_mode = _rounding_mode_from_env()
    hospital_code = os.getenv(_HOSPITAL_ENV, "").strip()
    if rounding_mode is None or not hospital_code:
        return None
    connect = getattr(provider, "_connect", None)
    if connect is None:
        return None
    profile = _resolve_special_profile_from_context(routing_context)
    conn = None
    try:
        conn = connect("bjybdb")
        result = decompose_outpatient_special_settlement(
            conn,
            djh,
            hospital_code,
            rounding_mode,
            profile=profile,
            cycle_context_override=cycle_context_override,
            allow_observed_deductible=allow_observed_deductible,
        )
    except Exception as exc:  # noqa: BLE001 — 分解失败不影响主问答链路
        logger.warning("[FEE-DECOMP] 门特费用分解失败，本次不附带分解结果: %s", exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    summary_text, summary_source = polish_summary(render_summary(result))
    return DecompositionPresentation(
        result=result, summary_text=summary_text, summary_source=summary_source)
