"""Policy QA API 输入模型。"""

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PreRefundItemInput(BaseModel):
    """门诊部分退费请求中的结构化拟退项目。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fee_detail_id: str = Field(min_length=1)
    refund_quantity: Decimal = Field(gt=0)

    @field_validator("fee_detail_id")
    @classmethod
    def validate_fee_detail_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("fee_detail_id 不能为空")
        return value


@dataclass
class PolicyQARequest:
    """政策问答请求；结算单是必需业务上下文。"""

    question: str
    settlement_id: str
    session_id: str | None = None
    user_id: str = ""
    role: str = ""
    pre_refund_items: list[PreRefundItemInput] | None = None
