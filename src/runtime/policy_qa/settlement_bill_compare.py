"""两张结算单费用分解的模型解释（Issue #87）。

门诊 / 门诊特殊病不在住院语义模型内，既有 `settlement_compare_skill` 只能
解释住院单。这里把两张结算单的 `/bill` 费用构成与费用明细结构化后交给
ModelGateway 生成解释，硬约束在提示词中声明：

- 两张单逐单陈述，金额不加总、不出「总共该付」；
- 只陈述账面差异，不作合规判定、不讨论监管疑点；
- 未提供政策依据时不解释政策原因，如实建议医保办核实。
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from src.runtime.policy_qa.settlement_data_provider import SettlementBill

logger = logging.getLogger(__name__)

# 单张结算单喂给模型的明细上限（住院明细可达数千行，取金额绝对值最大的前 N 条）
MAX_PROMPT_FEE_ITEMS = 60

SYSTEM_RULES = """你是院端医保费用解释助手。请只依据下面两张结算单的费用分解数据回答用户问题。

硬性要求：
1. 两张单分别陈述；每笔金额都必须标明属于哪张结算单。禁止把两张单的金额相加，禁止给出「总共该付/合计应承担」等汇总结论。
2. 只使用给定数据中的金额和收费项目，不得编造数字、比例、政策条款或项目；数据没有覆盖的内容明确写「现有数据不足以判断」。
3. 只描述账面差异，不判断结算是否合规，不讨论监管疑点，不使用「违规/异常/可疑」等定性结论。
4. 不解释政策原因（如起付累计、基金分段、报销比例），除非下文明确给出了政策依据；没有依据时只说明差异落在哪些费用构成项上，并建议向医保办核实政策原因。
5. 回答使用中文，按以下小节组织；没有内容的小节省略：
   【个人支付差异】两张单各自的个人支付金额，差额方向与金额，并指出差异来自哪些构成项。
   【费用构成差异】逐项列出两张单都有、且金额不同的构成项（旧值 → 新值）；个人支付总金额/现金/账户已在上一节呈现，不重复。
   【相同收费项目】两张单中相同收费项目的数量、单价、金额差异（不要用「明细条数」表述）。
   【说明】数据口径与限制（如明细缺失、明细截断、未附政策依据）。
6. 如果用户问题与费用分解无关，或数据不足以回答，直接说明原因，不要臆测。"""


class SettlementBillCompareItem(BaseModel):
    settlement_id: str
    service_type: str = ""


class SettlementBillCompareRequest(BaseModel):
    items: list[SettlementBillCompareItem] = Field(default_factory=list)
    question: str = ""


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _bill_payload(bill: SettlementBill) -> tuple[dict, list[str]]:
    """单张结算单 → 提示词结构化数据；返回 (payload, 数据限制说明)。"""
    notes: list[str] = []
    fields = [
        {"项目": field.label, "金额": field.amount if field.amount is not None else "缺失"}
        for field in bill.fields
    ]
    items = sorted(
        bill.fee_items,
        key=lambda item: abs(_to_decimal(item.total_amount) or Decimal("0")),
        reverse=True,
    )
    if bill.fee_items_state == "missing":
        notes.append(f"结算单 {bill.settlement_id} 的费用明细缺失，未做项目级对比。")
        item_rows: list[dict] = []
    else:
        truncated = len(items) > MAX_PROMPT_FEE_ITEMS
        if truncated:
            notes.append(
                f"结算单 {bill.settlement_id} 共 {len(items)} 条费用明细，"
                f"仅提供金额绝对值最大的前 {MAX_PROMPT_FEE_ITEMS} 条。"
            )
        item_rows = [
            {
                "项目编码": item.item_code,
                "项目名称": item.item_name,
                "类别": item.item_type,
                "数量": item.quantity,
                "单价": item.unit_price,
                "金额": item.total_amount,
                "医保内": item.insurance_inner,
                "医保外": item.insurance_outer,
            }
            for item in items[:MAX_PROMPT_FEE_ITEMS]
        ]
    payload = {
        "结算单": bill.settlement_id,
        "结算类型": bill.service_type or "未知",
        "结算日期": bill.settlement_date or "未知",
        "费用构成": fields,
        "费用明细": item_rows,
        "明细条数": len(bill.fee_items) if bill.fee_items_state != "missing" else 0,
    }
    return payload, notes


def build_bill_compare_prompt(question: str, bills: list[SettlementBill]) -> tuple[str, list[str]]:
    """构造模型提示词；返回 (prompt, 数据限制说明)。"""
    payloads: list[dict] = []
    notes: list[str] = []
    for bill in bills:
        payload, bill_notes = _bill_payload(bill)
        payloads.append(payload)
        notes.extend(bill_notes)
    data_json = json.dumps(payloads, ensure_ascii=False, indent=2)
    prompt = (
        f"{SYSTEM_RULES}\n\n"
        f"用户问题：{question or '请解释这两张结算单的费用差异。'}\n\n"
        f"两张结算单的费用分解数据（JSON，按结算日期从早到晚排列）：\n{data_json}\n\n"
        "回答："
    )
    return prompt, notes


def generate_bill_compare_answer(
    question: str,
    bills: list[SettlementBill],
    gateway=None,
) -> str:
    """调用统一模型网关生成两单费用对比解释；异常由调用方处理。"""
    from src.model_service.gateway import ModelGateway
    from src.model_service.models import Message

    prompt, _notes = build_bill_compare_prompt(question, bills)
    model_gateway = gateway or ModelGateway()
    response = model_gateway.generate(
        messages=[Message(role="user", content=prompt)],
        model_type="llm",
        scene="settlement_compare_answer",
        max_tokens=1200,
    )
    return (response.content or "").strip()


def bill_compare_data_notes(bills: list[SettlementBill]) -> list[str]:
    """给公开结果附加的数据限制说明（明细缺失/截断）。"""
    notes: list[str] = []
    for bill in bills:
        if bill.fee_items_state == "missing":
            notes.append(f"结算单 {bill.settlement_id} 的费用明细缺失，未做项目级对比。")
        elif len(bill.fee_items) > MAX_PROMPT_FEE_ITEMS:
            notes.append(
                f"结算单 {bill.settlement_id} 共 {len(bill.fee_items)} 条费用明细，"
                f"模型仅参考金额绝对值最大的前 {MAX_PROMPT_FEE_ITEMS} 条。"
            )
    return notes
