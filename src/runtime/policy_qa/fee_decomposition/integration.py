"""费用分解接入 policy-qa 入口的门控与表述层（Issue #78 设计 §12/§13/§15 步骤 5）。

门控（任一不满足即返回 None，绝不影响主问答链路）：
- `FEE_DECOMPOSITION_ROUNDING_MODE`：取整模式显式配置，无默认（EOP-RND-001 待确认，
  未配置或取值非法 = 功能关闭，fail-closed）；
- `FEE_DECOMPOSITION_HOSPITAL_CODE`：源系统（o_Trade 院区列）取值，用于交易定位；
  与部署级 `PLATFORM_HOSPITAL_CODE` 是不同口径，未配置 = 功能关闭；
- 数据供给连接可用（复用结算 provider 的连接工厂，bjybdb 库）。

险种/医疗类别解析：只接受语义层已解析字符串的精确匹配（`_PROFILE_MAP`：城镇职工
基本医疗保险/城乡居民基本医疗保险 + 普通门诊），其余一律 unknown → 内核走
UNSUPPORTED_PROFILE，不猜测（设计 §6.1 P0）。

门特由唯一登记的原始险种、医疗类别确认，已确认问答上下文冲突时停止分发。
公开表述使用确定性模板，保留核对状态与不确定性，避免模型改变结论。
"""
from __future__ import annotations

import logging
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import has_kidney_code, locate_special_fixed_kidney_registration
from src.adapters.data_supply.outpatient_special_mz_queries import (
    EMPLOYEE_FUND_TYPE,
    RESIDENT_FUND_TYPE_CODES,
    locate_special_mz_registration,
    locate_special_mz_resident_registration,
)
from src.adapters.data_supply.record_query_mappings import (
    DEFAULT_RECORD_QUERY_MAPPING,
    RecordQueryMapping,
)
from src.adapters.data_supply.settlement_record_queries import _k
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.public_view import render_summary
from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    DecompositionOutcome,
    SettlementFactsView,
)
from src.runtime.policy_qa.fee_decomposition.snapshot_service import (
    decompose_outpatient_trade,
)
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_mz import (
    _unavailable_result,
    decompose_special_mz_settlement,
)
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_mz_resident import (
    decompose_special_mz_resident_settlement,
)
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_fixed_kidney import decompose_special_fixed_kidney_settlement

logger = logging.getLogger(__name__)

_ROUNDING_ENV = "FEE_DECOMPOSITION_ROUNDING_MODE"
_HOSPITAL_ENV = "FEE_DECOMPOSITION_HOSPITAL_CODE"

#: 险种/医疗类别精确匹配表（语义层已解析字符串 → 标准组合；其余值一律不映射，不猜测）。
#: Issue #80 新增居民门诊组合；居民与职工目录划分规则相同（ROP-CAT-000），
#: 待遇参数独立（params_resident_outpatient，ROP-* 系列）。
_PROFILE_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("城镇职工基本医疗保险", "普通门诊"): ("employee", "outpatient"),
    ("城乡居民基本医疗保险", "普通门诊"): ("resident", "outpatient"),
}

#: 门特组合精确匹配表（语义层已解析字符串 → 标准组合；其余值一律不映射，不猜测）。
#: 职工门特 ESP-CODE-001/002 实测待码表确认，签核前不注册（恒走 UNSUPPORTED_PROFILE）。
#: 居民门特（Issue #81）注册城乡居民×门诊特殊病 → resident+outpatient_special；
#: 类别字符串与语义层码表解析一致（yb_zdxm flid=300：'12'=门诊特殊病）。
_SPECIAL_PROFILE_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("城乡居民基本医疗保险", "门诊特殊病"): ("resident", "outpatient_special"),
    ("城镇职工基本医疗保险", "门诊特殊病"): ("employee", "outpatient_special"),
}



@dataclass(frozen=True)
class DecompositionPresentation:
    """分解结果 + 表述文本（summary_source ∈ template/model，供公开契约标注）。

    settlement_facts 为结算事实侧车（方案 §53：事实区独立于算法，unavailable
    早退路径同样携带；原始行未取到时为 None）。
    """

    result: SettlementDecompositionResult
    summary_text: str
    summary_source: str
    settlement_facts: SettlementFactsView | None = None


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
    return _PROFILE_MAP.get((insurance, category))


def _resolve_special_profile_from_context(context: Any) -> tuple[str, str] | None:
    """门特组合的险种/类别精确匹配（职工 ESP-CODE-001/002 待码表确认未注册；
    居民门特 Issue #81 已注册 → ("resident","outpatient_special")）。"""
    insurance = str(getattr(context, "insurance_type", None) or "").strip()
    category = str(getattr(context, "service_type", None) or "").strip()
    return _SPECIAL_PROFILE_MAP.get((insurance, category))


def polish_summary(summary_text: str) -> tuple[str, str]:
    """金额、字段关系及不确定性由确定性模板固定，模型不得重写结论。"""
    return summary_text, "template"


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
        outcome = decompose_outpatient_trade(
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
    summary_text, summary_source = polish_summary(render_summary(outcome.result))
    return DecompositionPresentation(
        result=outcome.result, summary_text=summary_text, summary_source=summary_source,
        settlement_facts=outcome.facts)


def _resolve_special_suite(conn: Any, djh: str) -> tuple[str, tuple[str, str] | None]:
    """仅由唯一登记的原始险种/类别判定profile，任一歧义或读取失败不分发。"""
    matches = {"mz": locate_special_mz_registration(conn, djh),
               "kidney_mz": locate_special_fixed_kidney_registration(conn, djh),
               "resident_mz": locate_special_mz_resident_registration(conn, djh)}
    if any(result.status != AdapterCallStatus.SUCCESS for result in matches.values()):
        return "read_failed", None
    statuses = {suite: result.data["match_status"] for suite, result in matches.items()}
    if "ambiguous" in statuses.values():
        return "ambiguous", None
    hits = [suite for suite, status in statuses.items() if status == "unique_match"]
    if all(status == "not_found" for status in statuses.values()):
        return "none", None
    if len(hits) != 1 or any(status not in ("unique_match", "not_found") for status in statuses.values()):
        return "ambiguous", None
    suite = hits[0]
    row = matches[suite].data.get("registration_row") or {}
    fund, category = str(row.get("fund_type") or "").strip(), str(row.get("yllb") or "").strip()
    if category != "12":
        return "profile_unavailable", None
    if suite == "mz" and fund == "3" and not has_kidney_code(row):
        return suite, ("employee", "outpatient_special")
    if suite == "kidney_mz" and fund == "3" and has_kidney_code(row):
        return suite, ("employee", "outpatient_special")
    if suite == "resident_mz" and fund in ("91", "92", "93"):
        return suite, ("resident", "outpatient_special")
    return "profile_unavailable", None


def _decompose_special_core(
    conn: Any,
    djh: str,
    hospital_code: str,
    rounding_mode: RoundingMode,
    profile: tuple[str, str] | None,
    *,
    allow_observed_deductible: bool = False,
) -> tuple[DecompositionOutcome, tuple[str, str] | None]:
    """门特分解核心分发：登记消歧 → 套表内核。返回 (结果+事实侧车, 实际使用的 profile)。

    仅定位 yllb=12 的 mz 套表，按职工/居民险种分发；多命中、歧义、未命中或读取失败
    均 unavailable。policy-qa 主链与费用分解工作台共用（主链传问答上下文 profile，
    工作台传 None 完全由登记事实确认）。登记/结算行未取到的早退 facts=None。
    """
    suite, source_profile = _resolve_special_suite(conn, djh)
    if source_profile is not None:
        if profile is not None and profile != source_profile:
            return DecompositionOutcome(_unavailable_result(
                djh, "PROFILE_CONTEXT_CONFLICT",
                "登记事实与已确认问答上下文的险种不一致，不做费用分解")), source_profile
        profile = source_profile
    if suite == "mz":
        outcome = decompose_special_mz_settlement(
            conn, djh, hospital_code, rounding_mode,
            profile=profile, allow_observed_deductible=allow_observed_deductible)
    elif suite == "kidney_mz":
        outcome = decompose_special_fixed_kidney_settlement(
            conn, djh, hospital_code, rounding_mode, profile=profile)
    elif suite == "resident_mz":
        # 居民门特：唯一登记原始码确认 profile；问答上下文缺失不抹掉来源事实。
        outcome = decompose_special_mz_resident_settlement(
            conn, djh, hospital_code, rounding_mode, profile=profile)
    elif suite == "none":
        outcome = DecompositionOutcome(_unavailable_result(
            djh, "REGISTRATION_NOT_FOUND",
            "登记号未命中职工/居民门特门诊套表登记（yllb=12），不做费用分解"))
    elif suite == "profile_unavailable":
        outcome = DecompositionOutcome(_unavailable_result(
            djh, "UNSUPPORTED_PROFILE",
            "唯一登记缺少可确认的险种或医疗类别，不做费用分解"))
    elif suite == "ambiguous":
        outcome = DecompositionOutcome(_unavailable_result(
            djh, "REGISTRATION_AMBIGUOUS",
            "登记号门特登记歧义（双套表同时命中或表内多条登记），不猜测套表，"
            "不做费用分解"))
    else:  # read_failed
        outcome = DecompositionOutcome(_unavailable_result(
            djh, "READ_FAILED", "门特登记定位查询失败，无法判定套表，不做费用分解"))
    return outcome, profile


def maybe_decompose_special_outpatient(
    provider: Any,
    djh: str,
    routing_context: Any,
    *,
    allow_observed_deductible: bool = False,
) -> DecompositionPresentation | None:
    """门特登记号（djh）→ 职工/居民门诊套表费用分解表述。

    门控与普通门诊一致；profile 仅接受显式确认的险种×类别精确匹配。
    仅定位 yllb=12 的 mz 套表，按职工/居民险种分发；多命中、歧义、未命中或读取失败均 unavailable。
    allow_observed_deductible 仅供职工 mz 评估链路显式开启，生产默认 False。
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
        outcome, _used_profile = _decompose_special_core(
            conn, djh, hospital_code, rounding_mode, profile,
            allow_observed_deductible=allow_observed_deductible)
    except Exception as exc:  # noqa: BLE001 — 分解失败不影响主问答链路
        logger.warning("[FEE-DECOMP] 门特费用分解失败，本次不附带分解结果: %s", exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    summary_text, summary_source = polish_summary(render_summary(outcome.result))
    return DecompositionPresentation(
        result=outcome.result, summary_text=summary_text, summary_source=summary_source,
        settlement_facts=outcome.facts)


# ── 费用分解工作台入口（Issue #78 四链路页面可用化 Phase 1）──────────────────
#
# 与 policy-qa 主链的差异：
# - 门控不满足返回结构化 not_configured（含缺失 env 名），而非静默 None；
# - profile 不经问答上下文：普通门诊按唯一交易行的险种码（o_Trade P_FundType，
#   回放脚本 SQL 同款口径）确定性映射；门特复用 _resolve_special_suite 登记消歧；
# - FEE_DECOMPOSITION_EVAL_CALIBERS=1 时普通门诊路径启用回放验证过的候选口径
#   （accumulation_caliber_confirmed / derive_eligibility_from_codes，决策记录
#   D3-D8，待业务签核）。该入口同时服务工作台与 policy-qa 结算解释：
#   policy-qa 显式传 allow_eval_calibers=False 保持生产 fail-closed；
#   实际采用口径写入 outcome.caliber（eval_calibers / fail_closed）。

_EVAL_CALIBERS_ENV = "FEE_DECOMPOSITION_EVAL_CALIBERS"


@dataclass(frozen=True)
class WorkbenchDecompositionOutcome:
    """工作台单笔分解出口：not_configured 显式报因（含缺失配置项），ok 携带表述与 profile。"""

    status: str  # "ok" | "not_configured"
    chain: str  # 实际分发链路："outpatient" | "special"
    presentation: DecompositionPresentation | None = None
    profile: tuple[str, str] | None = None
    missing_env: tuple[str, ...] = ()
    message: str = ""
    # 本次采用的累计/资格口径："eval_calibers"=回放候选口径（D3-D8，待签核）；
    # "fail_closed"=生产默认（累计未确认不硬算）。两个入口都必须显式记录。
    caliber: str = "fail_closed"


def _looks_like_outpatient_trade_no(identifier: str) -> bool:
    """与 policy_qa 主链同款规则：≥15 位纯字母数字 → 普通门诊交易号，否则 → 门特登记号 djh。"""
    return re.fullmatch(r"[A-Za-z0-9]{15,}", identifier or "") is not None


def _eval_calibers_enabled() -> bool:
    """评估候选口径开关（回放验证口径复现），默认关闭。

    工作台入口按此环境变量取值；policy-qa 结算解释显式传 allow_eval_calibers=False，
    不受本变量影响，并在 outcome.caliber 记录本次实际采用的口径。
    """
    return os.getenv(_EVAL_CALIBERS_ENV, "").strip() == "1"


def _resolve_outpatient_profile_from_record(
    trade_row: Mapping[str, Any],
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> tuple[str, str] | None:
    """普通门诊险种确定性解析：唯一交易行的险种码 → 标准组合。

    口径与回放脚本 SQL 筛选用列一致（o_Trade P_FundType：3=职工、91/92/93=居民，
    与 _resolve_special_suite 先例相同）；缺失/空/未知码 → None（内核走
    UNSUPPORTED_PROFILE，fail-closed 不猜测）。多行歧义由上游
    locate_outpatient_trade 拦为 TRADE_AMBIGUOUS，本函数只见唯一交易行。
    """
    fund_type = str(trade_row.get(_k(mapping, "op_fund_type")) or "").strip()
    if fund_type == EMPLOYEE_FUND_TYPE:
        return ("employee", "outpatient")
    if fund_type in RESIDENT_FUND_TYPE_CODES:
        return ("resident", "outpatient")
    return None


def decompose_for_workbench(
    identifier: str,
    chain_hint: str,
    provider: Any,
    *,
    allow_eval_calibers: bool | None = None,
) -> WorkbenchDecompositionOutcome:
    """费用分解工作台单笔入口：显式门控报因 + 链路识别 + 确定性分解。

    - chain_hint ∈ {"auto","outpatient","special"}；auto 按 _looks_like_outpatient_trade_no
      同款规则识别（≥15 位纯字母数字 → 普通门诊交易号，否则 → 门特登记号 djh）；
    - 门控（取整模式/院区码/连接工厂）不满足 → not_configured + 缺失项，不查库；
    - 分解异常 → unavailable 表述（诚实降级），不抛异常栈给调用方；连接保证关闭；
    - allow_eval_calibers：None=读 FEE_DECOMPOSITION_EVAL_CALIBERS（工作台入口），
      显式 False=生产问答主链强制 fail-closed。两者都在 outcome.caliber 记录。
    """
    if chain_hint == "auto":
        chain = "outpatient" if _looks_like_outpatient_trade_no(identifier) else "special"
    elif chain_hint in ("outpatient", "special"):
        chain = chain_hint
    else:
        raise ValueError(f"chain_hint 必须是 auto/outpatient/special，收到 {chain_hint!r}")

    rounding_mode = _rounding_mode_from_env()
    hospital_code = os.getenv(_HOSPITAL_ENV, "").strip()
    missing: list[str] = []
    if rounding_mode is None:
        missing.append(_ROUNDING_ENV)
    if not hospital_code:
        missing.append(_HOSPITAL_ENV)
    if missing:
        return WorkbenchDecompositionOutcome(
            status="not_configured", chain=chain, missing_env=tuple(missing),
            message="费用分解未启用，缺少配置项：" + "、".join(missing))
    assert rounding_mode is not None  # 配置门控已通过，显式收窄供两个内核共用的类型。
    connect = getattr(provider, "_connect", None)
    if connect is None:
        return WorkbenchDecompositionOutcome(
            status="not_configured", chain=chain,
            message="结算数据 provider 无数据供给连接工厂（_connect），费用分解不可用")

    eval_calibers = _eval_calibers_enabled() if allow_eval_calibers is None else allow_eval_calibers
    conn = None
    profile: tuple[str, str] | None = None
    try:
        conn = connect("bjybdb")
        if chain == "outpatient":
            # profile 由唯一交易行的险种码确定性解析；resolver 回调时记录供 meta 回传
            resolved: list[tuple[str, str] | None] = []

            def _record_resolver(trade_row: Mapping[str, Any]) -> tuple[str, str] | None:
                resolved_profile = _resolve_outpatient_profile_from_record(trade_row)
                resolved.append(resolved_profile)
                return resolved_profile

            outcome = decompose_outpatient_trade(
                conn,
                identifier,
                hospital_code,
                rounding_mode,
                profile_resolver=_record_resolver,
                # 候选口径（决策记录 D3-D8，待签核）：仅 EVAL_CALIBERS=1 时开启，默认 False
                accumulation_caliber_confirmed=eval_calibers,
                derive_eligibility_from_codes=eval_calibers,
            )
            profile = resolved[0] if resolved else None
        else:
            outcome, profile = _decompose_special_core(
                conn, identifier, hospital_code, rounding_mode, None)
    except Exception as exc:  # noqa: BLE001 — 诚实降级：异常转 unavailable，不抛栈
        logger.warning("[FEE-DECOMP] 工作台费用分解失败: %s", exc)
        outcome = DecompositionOutcome(_unavailable_result(
            identifier, "DECOMPOSITION_FAILED", "费用分解执行异常，暂不可用"))
        profile = None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    summary_text, summary_source = polish_summary(render_summary(outcome.result))
    # 候选口径显式留痕：结果里附一条内部引用（公开来源投影会按类别过滤，不冒充政策依据）。
    caliber = "eval_calibers" if eval_calibers else "fail_closed"
    if eval_calibers:
        from src.runtime.policy_qa.fee_decomposition.result import CitationModel
        outcome = DecompositionOutcome(
            outcome.result.model_copy(update={"citations": [
                *outcome.result.citations,
                CitationModel(id="caliber.eval_calibers", kind="caliber",
                              ref="FEE_DECOMPOSITION_EVAL_CALIBERS=1",
                              value="回放验证候选口径（D3-D8，待业务签核）")]}),
            outcome.facts)
    return WorkbenchDecompositionOutcome(
        status="ok", chain=chain,
        presentation=DecompositionPresentation(
            outcome.result, summary_text, summary_source,
            settlement_facts=outcome.facts),
        profile=profile, caliber=caliber)


# ── 会话级共享分解实例缓存（阶段 A：面板↔聊天同源）────────────────────────
#
# 键 (session_id, settlement_id) → 主链 fail-closed 口径的分解出口。
# policy-qa 主流命中即复用；GET /policy-qa/sessions/{id}/decomposition 同款口径
# 未命中时计算并写入。两侧由此共享同一运行实例；聊天对 summary 的模型回写只
# 作用于该消息的公开投影（dataclass replace 产生新对象），不回写共享实例。
# 容量有界（LRU 淘汰最久未用）；policy-qa 流在 executor 线程执行，读写加锁。

_SESSION_CACHE_CAPACITY = 64
_session_decomposition_cache: OrderedDict[tuple[str, str], WorkbenchDecompositionOutcome] = OrderedDict()
_session_decomposition_lock = threading.Lock()


def get_cached_session_decomposition(
    session_id: str, settlement_id: str,
) -> WorkbenchDecompositionOutcome | None:
    """读会话级共享实例；命中即刷新为最近使用。"""
    key = (session_id, settlement_id)
    with _session_decomposition_lock:
        outcome = _session_decomposition_cache.get(key)
        if outcome is not None:
            _session_decomposition_cache.move_to_end(key)
        return outcome


def cache_session_decomposition(
    session_id: str, settlement_id: str, outcome: WorkbenchDecompositionOutcome,
) -> None:
    """写会话级共享实例；超容量淘汰最久未用条目。"""
    key = (session_id, settlement_id)
    with _session_decomposition_lock:
        _session_decomposition_cache[key] = outcome
        _session_decomposition_cache.move_to_end(key)
        while len(_session_decomposition_cache) > _SESSION_CACHE_CAPACITY:
            _session_decomposition_cache.popitem(last=False)


def clear_session_decomposition_cache() -> None:
    """清空缓存（测试隔离用）。"""
    with _session_decomposition_lock:
        _session_decomposition_cache.clear()
