"""
normalize_fee_context.py — 结算上下文标准化

将 SQL Server 返回的原始结算数据标准化为 Milvus 查询所需格式。

输入：SettlementContext 对象（来自 settlement-data MCP）
输出：NormalizedPolicyContext dict

标准化内容：
1. 人员类别：PER_TYPE 1→"退休人员", 2→"在职人员"
2. 医疗类别：添加 "住院-" 前缀（如无）
3. 险种类型：直接透传
4. 医院等级：直接透传，空值默认 "三级医院"
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class NormalizedPolicyContext:
    """标准化后的政策查询上下文。"""
    settlement_id: str = ""
    insu_type: str = ""
    med_type: str = ""
    hosp_lv: str = ""
    psn_type: str = ""
    target_field: str = ""
    target_amount: float = 0.0


_PER_TYPE_MAP = {
    "1": "退休人员",
    "2": "在职人员",
}


_MEDICAL_TYPE_PREFIX = {
    "普通住院": "住院-普通住院",
}


def normalize_person_type(raw: str) -> str:
    """标准化人员类别。"""
    if not raw:
        return "退休人员"  # 默认
    return _PER_TYPE_MAP.get(raw.strip(), raw.strip())


def normalize_med_type(raw: str) -> str:
    """标准化医疗类别。"""
    if not raw:
        return "住院-普通住院"  # 默认
    if raw in _MEDICAL_TYPE_PREFIX:
        return _MEDICAL_TYPE_PREFIX[raw]
    if raw.startswith("住院-") or raw.startswith("门诊-"):
        return raw
    return f"住院-{raw}"


def normalize_fee_context(
    settlement_context: Any,
    target_field: str = "统筹自付",
    target_amount: float = 0.0,
    settlement_id: str = "",
) -> NormalizedPolicyContext:
    """
    将原始 SettlementContext 标准化为 NormalizedPolicyContext。

    Args:
        settlement_context: 来自 settlement-data MCP 的上下文对象。
            需有 person_type, insurance_type, service_type, hospital_level 属性。
        target_field: 目标费用字段中文名
        target_amount: 目标金额
        settlement_id: 结算单号

    Returns:
        NormalizedPolicyContext
    """
    return NormalizedPolicyContext(
        settlement_id=settlement_id or getattr(settlement_context, "settlement_id", ""),
        insu_type=str(getattr(settlement_context, "insurance_type", "") or "城镇职工"),
        med_type=normalize_med_type(
            str(getattr(settlement_context, "service_type", "") or "")
        ),
        hosp_lv=str(getattr(settlement_context, "hospital_level", "") or "三级医院"),
        psn_type=normalize_person_type(
            str(getattr(settlement_context, "person_type", "") or "")
        ),
        target_field=target_field,
        target_amount=target_amount,
    )


# ── 命令行测试 ──────────────────────────────────────────────────

if __name__ == "__main__":
    # 模拟 SettlementContext
    class MockCtx:
        settlement_id = "1671213"
        insurance_type = "城镇职工基本医疗保险"
        service_type = "普通住院"
        hospital_level = "三级医院"
        person_type = "1"

    ctx = MockCtx()
    result = normalize_fee_context(ctx, target_field="统筹自付", settlement_id="1671213")
    print(f"标准化结果: {result}")
    print(f"  psn_type: {result.psn_type}")  # → "退休人员"
    print(f"  med_type: {result.med_type}")    # → "住院-普通住院"
    print("OK")
