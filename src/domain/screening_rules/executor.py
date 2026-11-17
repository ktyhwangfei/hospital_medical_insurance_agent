"""筛查规则执行器（纯函数）— issue #86。

输入：一批结算的费用行（settlement_key 分组）；输出：疑点命中列表。

证据纪律：
- 每条命中的 evidence_clause 必须等于规则原条款，引不出原条款的规则不执行；
- 同一费用行只计一次金额：同批次内首个命中该费用行的疑点为主疑点
  （primary_finding_id = 自身 finding_id），后续命中同一费用行的疑点
  primary_finding_id 指向主疑点；
- 命中只是疑点（mismatch 明显对不上），不做违规判定；
- 诊断/年龄等材料缺失时记 insufficient_material，不编造依据。

支持的条件类型（condition_spec.kind）：
- ``cocharge``：同一次结算中项目 A 与项目 B 同时收费（项目组合内涵比较）；
- ``drug_age_indication``：药品限适应症 + 年龄分支——按结算时年龄
  （T_TradeDate - P_Birthday）与诊断判定是否符合限定支付条件；
  诊断或出生日期缺失时记 insufficient_material。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from src.domain.screening_rules.models import (
    FindingType,
    RuleStatus,
    ScreeningFinding,
    ScreeningRule,
    VerifyStatus,
    new_finding_id,
)


@dataclass(frozen=True)
class FeeLine:
    """一次结算下的一条费用行（来自 bjyb o_FeeItem / mz_fee_item）。"""

    settlement_key: str  # = o_Trade.T_TradeNo
    fee_line_id: str
    item_code: str | None
    item_name: str
    amount: float | None


@dataclass(frozen=True)
class SettlementContext:
    """一次结算的就诊级上下文（o_Trade 人员字段 + o_Diagnose 诊断）。"""

    settlement_key: str
    trade_date: datetime | None = None
    birthday: datetime | None = None  # o_Trade.P_Birthday
    sex: str | None = None  # o_Trade.P_Sex（1=男 2=女）
    diagnoses: tuple[str, ...] = ()  # o_Diagnose.DiagnoseName 列表

    @property
    def age_at_trade(self) -> float | None:
        """就诊时年龄（岁）；出生日期或就诊日期缺失时返回 None。"""
        if self.birthday is None or self.trade_date is None:
            return None
        return (self.trade_date - self.birthday).days / 365.25


# 占位/无效诊断：本地 o_Diagnose 存在 '1'、'11'、'诊断名称测试123' 等测试残留
_PLACEHOLDER_DIAGNOSIS = {"1", "11", "", "无", "内科", "眼科"}


def _is_placeholder_diagnosis(name: str) -> bool:
    text = (name or "").strip()
    return text in _PLACEHOLDER_DIAGNOSIS or text.startswith("诊断名称测试")


def _make_finding(
    rule: ScreeningRule,
    line: FeeLine,
    *,
    run_id: str,
    finding_type: FindingType,
    evidence_facts: dict,
    seen: dict[tuple[str, str], str],
    now: datetime,
) -> ScreeningFinding:
    """构造疑点：evidence_clause 恒等于规则原条款；同一费用行只计一次金额。"""
    finding_id = new_finding_id()
    dedup_key = (line.settlement_key, line.fee_line_id)
    primary_id = seen.get(dedup_key, finding_id)
    seen.setdefault(dedup_key, finding_id)
    return ScreeningFinding(
        finding_id=finding_id,
        run_id=run_id,
        rule_id=rule.rule_id,
        settlement_key=line.settlement_key,
        fee_line_id=line.fee_line_id,
        item_code=line.item_code,
        item_name=line.item_name,
        amount=line.amount,
        finding_type=finding_type,
        primary_finding_id=primary_id,
        evidence_clause=rule.source_clause,
        evidence_facts={**evidence_facts, "dedup": "primary" if primary_id == finding_id else "secondary"},
        verify_status=VerifyStatus.PENDING,
        created_at=now,
    )


def _execute_cocharge(
    rule: ScreeningRule,
    by_settlement: dict[str, list[FeeLine]],
    *,
    run_id: str,
    spec: dict,
    seen: dict[tuple[str, str], str],
    now: datetime,
) -> list[ScreeningFinding]:
    anchor = str(spec["anchor_item_contains"])
    conflicts = [str(item) for item in spec["conflict_items_contain"]]
    findings: list[ScreeningFinding] = []
    for settlement_key, lines in by_settlement.items():
        anchor_lines = [line for line in lines if anchor in line.item_name]
        if not anchor_lines:
            continue
        for line in lines:
            if any(line is anchor_line for anchor_line in anchor_lines):
                continue
            if not any(conflict in line.item_name for conflict in conflicts):
                continue
            findings.append(
                _make_finding(
                    rule, line, run_id=run_id, finding_type=FindingType.MISMATCH,
                    evidence_facts={
                        "anchor_items": [
                            {
                                "fee_line_id": a.fee_line_id,
                                "item_code": a.item_code,
                                "item_name": a.item_name,
                                "amount": a.amount,
                            }
                            for a in anchor_lines
                        ],
                        "conflict_item": {
                            "fee_line_id": line.fee_line_id,
                            "item_code": line.item_code,
                            "item_name": line.item_name,
                            "amount": line.amount,
                        },
                    },
                    seen=seen, now=now,
                )
            )
    return findings


def _execute_drug_age_indication(
    rule: ScreeningRule,
    by_settlement: dict[str, list[FeeLine]],
    contexts: dict[str, SettlementContext],
    *,
    run_id: str,
    spec: dict,
    seen: dict[tuple[str, str], str],
    now: datetime,
) -> list[ScreeningFinding]:
    """药品限适应症 + 年龄分支。

    spec 字段：
    - drug_name_contains：药品名包含词（命中费用行）；
    - diagnosis_contains：限定适应症诊断关键词列表（任一命中即算有适应症）；
    - child_max_age：儿童年龄上限（岁），儿童不受 adult_requires 限制；
    - adult_requires_diagnosis_contains：成人额外要求的诊断关键词（如出血）。

    判定（只产疑点，不做合规结论）：
    - 诊断全部缺失/占位 → insufficient_material（材料不足）；
    - 有真实诊断但无适应症诊断 → mismatch（明显对不上）；
    - 成人、有适应症、但缺成人限定条件诊断 → mismatch；
    - 出生日期缺失导致年龄不可算 → insufficient_material。
    """
    drug = str(spec["drug_name_contains"])
    dx_keywords = [str(k) for k in spec["diagnosis_contains"]]
    child_max_age = float(spec.get("child_max_age", 14))
    adult_extra = [str(k) for k in (spec.get("adult_requires_diagnosis_contains") or [])]

    findings: list[ScreeningFinding] = []
    for settlement_key, lines in by_settlement.items():
        ctx = contexts.get(settlement_key, SettlementContext(settlement_key=settlement_key))
        real_dx = [d for d in ctx.diagnoses if not _is_placeholder_diagnosis(d)]
        age = ctx.age_at_trade
        has_indication = any(kw in d for kw in dx_keywords for d in real_dx)
        has_adult_extra = any(kw in d for kw in adult_extra for d in real_dx) if adult_extra else True
        is_child = age is not None and age <= child_max_age
        for line in lines:
            if drug not in line.item_name:
                continue
            base_facts = {
                "diagnoses": list(ctx.diagnoses),
                "age_at_trade": round(age, 1) if age is not None else None,
                "sex": ctx.sex,
                "rule_expectation": {
                    "diagnosis_contains": dx_keywords,
                    "child_max_age": child_max_age,
                    "adult_requires_diagnosis_contains": adult_extra,
                },
            }
            if not real_dx:
                # 诊断材料缺失/占位：不编造依据
                findings.append(_make_finding(
                    rule, line, run_id=run_id,
                    finding_type=FindingType.INSUFFICIENT_MATERIAL,
                    evidence_facts={**base_facts, "reason": "诊断缺失或为占位值，无法核对适应症"},
                    seen=seen, now=now,
                ))
            elif not has_indication:
                findings.append(_make_finding(
                    rule, line, run_id=run_id,
                    finding_type=FindingType.MISMATCH,
                    evidence_facts={**base_facts, "reason": "诊断中未见限定适应症"},
                    seen=seen, now=now,
                ))
            elif age is None:
                findings.append(_make_finding(
                    rule, line, run_id=run_id,
                    finding_type=FindingType.INSUFFICIENT_MATERIAL,
                    evidence_facts={**base_facts, "reason": "出生日期缺失，无法计算就诊年龄"},
                    seen=seen, now=now,
                ))
            elif not is_child and adult_extra and not has_adult_extra:
                findings.append(_make_finding(
                    rule, line, run_id=run_id,
                    finding_type=FindingType.MISMATCH,
                    evidence_facts={**base_facts, "reason": "成人使用但诊断中未见限定条件（如出血）"},
                    seen=seen, now=now,
                ))
    return findings


def execute_rule(
    rule: ScreeningRule,
    fee_lines: Iterable[FeeLine],
    *,
    run_id: str,
    now: datetime,
    seen_fee_lines: dict[tuple[str, str], str] | None = None,
    settlement_contexts: dict[str, SettlementContext] | None = None,
) -> list[ScreeningFinding]:
    """对一条已批准规则执行筛查。

    ``seen_fee_lines``：批次内已命中费用行 → 主疑点 finding_id 的映射，
    跨规则共享，保证同一费用只计一次金额（只一条主疑点）。
    ``settlement_contexts``：drug_age_indication 类规则需要的就诊级上下文。
    """
    if rule.status is not RuleStatus.APPROVED:
        raise ValueError(f"规则未批准，禁止执行: {rule.rule_id}")
    if not rule.source_clause.strip():
        raise ValueError(f"规则缺少原条款，禁止执行: {rule.rule_id}")
    spec = rule.condition_spec or {}
    kind = spec.get("kind")
    seen = seen_fee_lines if seen_fee_lines is not None else {}

    by_settlement: dict[str, list[FeeLine]] = {}
    for line in fee_lines:
        by_settlement.setdefault(line.settlement_key, []).append(line)

    if kind == "cocharge":
        return _execute_cocharge(rule, by_settlement, run_id=run_id, spec=spec, seen=seen, now=now)
    if kind == "drug_age_indication":
        return _execute_drug_age_indication(
            rule, by_settlement, settlement_contexts or {},
            run_id=run_id, spec=spec, seen=seen, now=now,
        )
    raise ValueError(f"不支持的条件类型: {kind!r}（规则 {rule.rule_id}）")
