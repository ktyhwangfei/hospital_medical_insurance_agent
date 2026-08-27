"""
assembler.py — 结算对比装配器（轻量调度器）。

不包含归因/渲染逻辑。流程：输入校验 → diff_contexts 逐对 diff →
CompareStrategy 归因 + 模板渲染 → 组装 CompareSkillResult。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .comparison_context import ComparedSettlement
from .diff_engine import diff_contexts
from .strategies.compare.strategy import CompareStrategy


@dataclass
class CompareSkillResult:
    """结算对比技能的标准输出结果（字段与 explain skill SkillResult 对齐）。"""

    answer: str
    calculation_trace: dict
    warnings: list[str] = field(default_factory=list)
    definition: dict = field(default_factory=dict)
    policy_status: str = "no_policy_matched"
    policy_status_message: str = ""
    target_fee_item: str | None = None
    target_field: str = ""
    can_answer: bool = True
    partial_answer: bool = False
    diff_items: list[dict] = field(default_factory=list)
    attributions: list[dict] = field(default_factory=list)


class SettlementCompareAssembler:
    """结算对比装配器。

    输入 2~N 个 SettlementContext（首个为基准），输出逐项差异 + 归因的
    模板化对比解释。政策证据由产品层检索后经 policy_evidence_by_topic 注入。
    """

    MAX_SETTLEMENTS = 5

    _STATUS_MESSAGES = {
        "full_policy_matched": "已匹配完整政策依据。",
        "partial_policy_matched": "仅匹配部分政策依据，对比解释可能不完整。",
        "no_policy_matched": "未匹配政策依据，仅展示真实结算字段对比，不能作为完整政策解释。",
    }

    def __init__(self, strategy: CompareStrategy | None = None):
        self._strategy = strategy or CompareStrategy()

    def build_policy_queries(self, topics: list[str]) -> list[Any]:
        """按归因主题返回结构化政策查询计划（供产品层检索 citations）。"""
        return self._strategy.build_policy_queries(topics)

    def execute(
        self,
        settlement_contexts: list[Any],
        policy_evidence_by_id: dict[str, list[dict]] | None = None,
        policy_status: str = "no_policy_matched",
        target_fee_item: str | None = None,
        policy_evidence_by_topic: dict[str, list[dict]] | None = None,
    ) -> CompareSkillResult:
        """主入口：对比 2~N 张结算单。

        Args:
            settlement_contexts: SettlementContext 列表，首个为基准
            policy_evidence_by_id: 各结算单的政策证据（保留参数）
            policy_status: 政策匹配状态（产品层聚合后传入）
            target_fee_item: 可选，收窄对比到单个费用项
            policy_evidence_by_topic: 归因主题 → 政策证据列表，
                产品层按 build_policy_queries 检索后注入，用于答案中的政策依据区块
        """
        warnings: list[str] = []
        definition = self._strategy.build_definition()

        # ── 输入校验 ─────────────────────────────────────────
        contexts = [c for c in settlement_contexts if c is not None]
        if len(contexts) > self.MAX_SETTLEMENTS:
            contexts = contexts[: self.MAX_SETTLEMENTS]
            warnings.append(f"结算单数量超过上限 {self.MAX_SETTLEMENTS}，仅对比前 {self.MAX_SETTLEMENTS} 张")
        if len(contexts) < 2:
            return CompareSkillResult(
                answer=self._strategy.build_cannot_answer("至少需要两张不同的结算单才能对比"),
                calculation_trace={},
                warnings=warnings,
                definition=definition,
                policy_status=policy_status,
                target_fee_item=target_fee_item,
                can_answer=False,
            )

        # ── target_fee_item 收窄 ─────────────────────────────
        if target_fee_item and not self._strategy.fee_item_known(target_fee_item):
            warnings.append(f"费用项 {target_fee_item} 暂不支持单独对比，已退化为全字段对比")
            target_fee_item = None
        fields = self._strategy.fee_item_fields(target_fee_item)

        # ── 逐对 diff + 归因 ─────────────────────────────────
        baseline = contexts[0]
        baseline_id = str(getattr(baseline, "settlement_id", "") or "")
        compared: list[ComparedSettlement] = []
        for ctx in contexts[1:]:
            settlement_id = str(getattr(ctx, "settlement_id", "") or "")
            diffs = diff_contexts(baseline, ctx, fields)
            attributions, attr_warnings = self._strategy.attribute_diffs(
                baseline, ctx, diffs, settlement_id
            )
            warnings.extend(attr_warnings)
            compared.append(ComparedSettlement(
                settlement_id=settlement_id,
                context=ctx,
                diffs=diffs,
                attributions=attributions,
            ))

        # ── 可答性判断 ───────────────────────────────────────
        # 存在 fallback 归因（未命中规则）→ partial；diff 为空也是合法答案（无差异）
        partial = any(a.is_fallback for c in compared for a in c.attributions)

        # ── 渲染 ─────────────────────────────────────────────
        answer = self._strategy.build_answer(baseline_id, compared, policy_evidence_by_topic)

        # ── 组装输出 ─────────────────────────────────────────
        diff_items = [
            {**asdict(diff), "settlement_id": c.settlement_id}
            for c in compared
            for diff in c.diffs
        ]
        attribution_dicts = [asdict(a) for c in compared for a in c.attributions]
        target_field = (fields[0] if fields else "")
        # calculation_trace.steps：与 _public_result_from_internal_payload 的
        # 公开计算步骤白名单（step_name/description/result/note）对齐
        steps = [
            {
                "step_name": "字段比对",
                "description": f"{c.settlement_id} · {diff.label}",
                "result": f"基准 {diff.baseline_value} → 本次 {diff.current_value}",
                "note": attr.attribution,
            }
            for c in compared
            for diff, attr in zip(c.diffs, c.attributions)
        ]

        return CompareSkillResult(
            answer=answer,
            calculation_trace={
                "baseline_settlement_id": baseline_id,
                "diff_items": diff_items,
                "attributions": attribution_dicts,
                "steps": steps,
            },
            warnings=warnings,
            definition=definition,
            policy_status=policy_status,
            policy_status_message=self._STATUS_MESSAGES.get(policy_status, ""),
            target_fee_item=target_fee_item,
            target_field=target_field,
            can_answer=True,
            partial_answer=partial,
            diff_items=diff_items,
            attributions=attribution_dicts,
        )


# ── 动态加载入口 ────────────────────────────────────────────────

def load() -> SettlementCompareAssembler:
    """SkillLoader 入口。"""
    return SettlementCompareAssembler()
