from dataclasses import dataclass


@dataclass(frozen=True)
class DrgGroupResult:
    """DRG 分组结果：疾病诊断相关分组的核心产出。"""

    drg_code: str
    drg_name: str
    weight: float
    payment_rate: float
    expected_cost: float
    actual_cost: float
    profit_loss: float


@dataclass(frozen=True)
class DipGroupResult:
    """DIP 分组结果：按病种分值付费的分组信息。"""

    dip_code: str
    dip_name: str
    payment_standard: float
    actual_cost: float


@dataclass(frozen=True)
class PaymentRate:
    """支付费率：医保支付相关的费率标准。"""

    rate_type: str
    rate_value: float
    effective_date: str


@dataclass(frozen=True)
class ProfitLoss:
    """盈亏分析：按病种的成本盈亏计算结果。"""

    amount: float
    percentage: float
    category: str  # "profit", "loss", "break_even"
