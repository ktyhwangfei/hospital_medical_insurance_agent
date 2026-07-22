"""
StrategyRegistry — 费用项 → Strategy 注册表。

新增费用项时只需在此注册，assembler 自动分发。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseFeeStrategy


# ── 延迟导入避免循环依赖 ──────────────────────────────────────

def _get_pooling_self_pay_strategy() -> BaseFeeStrategy:
    from .pooling_self_pay.strategy import PoolingSelfPayStrategy
    return PoolingSelfPayStrategy(
        Path(__file__).parent / "pooling_self_pay"
    )


def _get_deductible_strategy() -> BaseFeeStrategy:
    from .deductible.strategy import DeductibleStrategy
    return DeductibleStrategy(
        Path(__file__).parent / "deductible"
    )


def _get_large_amount_strategy() -> BaseFeeStrategy:
    from .large_amount_self_pay.strategy import LargeAmountSelfPayStrategy
    return LargeAmountSelfPayStrategy(
        Path(__file__).parent / "large_amount_self_pay"
    )


def _get_out_of_scope_strategy() -> BaseFeeStrategy:
    from .out_of_scope.strategy import OutOfScopeStrategy
    return OutOfScopeStrategy(
        Path(__file__).parent / "out_of_scope"
    )


def _get_pooling_payment_strategy() -> BaseFeeStrategy:
    from .pooling_payment.strategy import PoolingPaymentStrategy
    return PoolingPaymentStrategy(
        Path(__file__).parent / "pooling_payment"
    )


def _get_personal_total_pay_strategy() -> BaseFeeStrategy:
    from .personal_total_pay.strategy import PersonalTotalPayStrategy
    return PersonalTotalPayStrategy(
        Path(__file__).parent / "personal_total_pay"
    )


# ── 注册表 ─────────────────────────────────────────────────────

_STRATEGY_REGISTRY: dict[str, Any] = {}
_INSTANCE_CACHE: dict[str, BaseFeeStrategy] = {}


def _init_registry():
    if _STRATEGY_REGISTRY:
        return
    _STRATEGY_REGISTRY.update({
        "pooling_self_pay": _get_pooling_self_pay_strategy,
        "deductible": _get_deductible_strategy,
        "large_amount_self_pay": _get_large_amount_strategy,
        "out_of_scope": _get_out_of_scope_strategy,
        "pooling_payment": _get_pooling_payment_strategy,
        "personal_total_pay": _get_personal_total_pay_strategy,
    })


def get_strategy(target_fee_item: str) -> BaseFeeStrategy:
    """根据 target_fee_item 获取对应 Strategy 实例（带缓存）。"""
    _init_registry()
    if target_fee_item not in _INSTANCE_CACHE:
        factory = _STRATEGY_REGISTRY.get(target_fee_item)
        if factory is None:
            factory = _STRATEGY_REGISTRY["pooling_self_pay"]
        _INSTANCE_CACHE[target_fee_item] = factory()
    return _INSTANCE_CACHE[target_fee_item]


def list_strategies() -> list[str]:
    """列出所有已注册的费用项策略。"""
    _init_registry()
    return list(_STRATEGY_REGISTRY.keys())
