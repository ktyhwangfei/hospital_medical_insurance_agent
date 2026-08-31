"""门诊部分项目预退费分析候选 Skill 组装器。"""

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.adapters.billing.models import PartialRefundItemRequest, PartialRefundPreview
from src.runtime.policy_qa.public_contract import (
    PolicyQACalculationStep,
    PolicyQACaseContext,
    PolicyCitation,
    PolicyQADefinition,
)


class PreRefundSkillResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    calculation_steps: list[PolicyQACalculationStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    definition: PolicyQADefinition
    source_citations: list[PolicyCitation] = Field(default_factory=list)
    case_context: PolicyQACaseContext | None = None
    can_answer: bool
    partial_answer: bool = False
    verified_external_result: bool
    policy_status: str = "no_policy_matched"


class OutpatientPreRefundAnalysisAssembler:
    """校验并解释院端门诊部分退费预结算结果。"""

    def __init__(self) -> None:
        template_path = Path(__file__).parent / "templates" / "analysis.yaml"
        self._template = yaml.safe_load(template_path.read_text(encoding="utf-8"))

    def execute(
        self,
        original_trade_no: str,
        requested_items: tuple[PartialRefundItemRequest, ...],
        preview: PartialRefundPreview,
    ) -> PreRefundSkillResult:
        definition = PolicyQADefinition(**self._template["definition"])
        source = self._source_citation(preview)
        if preview.original_trade_no != original_trade_no:
            return self._unavailable("院端预结算响应与门诊原交易号不一致。", definition)
        if source is None:
            return self._unavailable("院端预结算结果缺少可追溯来源。", definition)

        if not preview.accepted:
            answer = self._template["official_rejection"].format(
                response_code=preview.response_code,
                response_message=preview.response_message,
            )
            return PreRefundSkillResult(
                answer=answer,
                warnings=[self._template["advisory_warning"]],
                definition=definition,
                source_citations=[source],
                can_answer=True,
                verified_external_result=True,
            )

        validation_error = self._validate_accepted(requested_items, preview)
        if validation_error:
            return self._unavailable(validation_error, definition)

        before = preview.before
        after = preview.after
        assert before is not None and after is not None

        total_delta = before.total_amount - after.total_amount
        fund_delta = before.fund_amount - after.fund_amount
        personal_delta = before.personal_amount - after.personal_amount
        direction = "no_change"
        if personal_delta > 0:
            direction = "refund"
        elif personal_delta < 0:
            direction = "supplement"
        answer = self._template[direction].format(
            total_delta=self._money(total_delta),
            fund_delta=self._money(fund_delta),
            personal_delta=self._money(abs(personal_delta)),
        )

        # 公开计算步骤只保留业务含义和金额，不暴露院端内部字段。
        steps = [
            PolicyQACalculationStep(
                step_name=self._template["steps"]["total"],
                description="原交易总金额减预结算后总金额",
                result=f"{self._money(before.total_amount)} - {self._money(after.total_amount)} = {self._money(total_delta)} 元",
            ),
            PolicyQACalculationStep(
                step_name=self._template["steps"]["fund"],
                description="原基金支付减预结算后基金支付",
                result=f"{self._money(before.fund_amount)} - {self._money(after.fund_amount)} = {self._money(fund_delta)} 元",
            ),
            PolicyQACalculationStep(
                step_name=self._template["steps"]["personal"],
                description="原个人支付减预结算后个人支付",
                result=f"{self._money(before.personal_amount)} - {self._money(after.personal_amount)} = {self._money(personal_delta)} 元",
            ),
        ]
        return PreRefundSkillResult(
            answer=answer,
            calculation_steps=steps,
            warnings=[self._template["advisory_warning"]],
            definition=definition,
            source_citations=[source],
            case_context=PolicyQACaseContext(
                basic_pooling_payment=float(after.fund_amount),
                personal_total_pay=float(after.personal_amount),
                total_amount=float(after.total_amount),
            ),
            can_answer=True,
            verified_external_result=True,
        )

    def _validate_accepted(
        self,
        requested_items: tuple[PartialRefundItemRequest, ...],
        preview: PartialRefundPreview,
    ) -> str | None:
        if preview.before is None or preview.after is None:
            return "院端预结算未返回完整的结算前后金额。"

        returned_by_id = {item.fee_detail_id: item for item in preview.items}
        if len(returned_by_id) != len(preview.items):
            return "院端预结算返回了重复的费用明细。"
        if set(returned_by_id) != {item.fee_detail_id for item in requested_items}:
            return "院端预结算返回的费用明细与请求不一致。"
        for requested in requested_items:
            returned = returned_by_id[requested.fee_detail_id]
            if returned.refund_quantity != requested.refund_quantity:
                return "院端预结算返回的拟退数量与请求不一致。"
            if requested.refund_quantity > returned.refundable_quantity:
                return "拟退数量超过院端返回的可退数量。"
            if returned.refund_amount < 0:
                return "院端预结算返回了无效的退费金额。"

        before = preview.before
        after = preview.after
        total_delta = before.total_amount - after.total_amount
        fund_delta = before.fund_amount - after.fund_amount
        personal_delta = before.personal_amount - after.personal_amount
        item_total = sum((item.refund_amount for item in preview.items), Decimal("0"))
        if total_delta != item_total or total_delta != fund_delta + personal_delta:
            return "院端预结算金额未通过一致性校验。"
        return None

    @staticmethod
    def _source_citation(preview: PartialRefundPreview) -> PolicyCitation | None:
        if not preview.source_system.strip() or not preview.source_reference.strip():
            return None
        return PolicyCitation(
            title=f"{preview.source_system}预结算",
            excerpt=f"预结算凭证：{preview.source_reference}；响应码：{preview.response_code}",
        )

    @staticmethod
    def _money(value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01')):.2f}"

    def _unavailable(
        self,
        reason: str,
        definition: PolicyQADefinition,
    ) -> PreRefundSkillResult:
        return PreRefundSkillResult(
            answer=self._template["unavailable"],
            warnings=[reason],
            definition=definition,
            can_answer=False,
            verified_external_result=False,
        )


def load() -> OutpatientPreRefundAnalysisAssembler:
    return OutpatientPreRefundAnalysisAssembler()
