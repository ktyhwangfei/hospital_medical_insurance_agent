"""
PersonalTotalPayStrategy — 个人总支付解释策略。

个人总支付是患者在本次住院中个人承担的全部费用总和。
组成：个人总支付 ≈ 起付线 + 统筹自付 + 大额自付 + 目录外自费（如有）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.domain.indicator.models import MetricFormula
from src.semantic_layer.formula_evaluator import FormulaEvaluator

from ..base import BaseFeeStrategy

class PersonalTotalPayStrategy(BaseFeeStrategy):
    """个人总支付解释策略。"""

    fee_item = "personal_total_pay"
    fee_label = "个人总支付"
    fee_field = "personal_total_pay"

    def __init__(self, config_dir: Path):
        super().__init__(config_dir)

    # ── definition ─────────────────────────────────────────────

    def build_definition(self) -> dict:
        cfg = self._load_yaml("definition.yaml")
        return {
            "name": self.fee_label,
            "plain_text": cfg.get("plain_text", "患者在本次住院中个人承担的全部费用总和。个人总支付 = 起付线 + 统筹自付 + 大额自付 + 目录外自费 + 先行自付（如有）。这是患者最终需要自掏腰包的全部金额。"),
            "excludes": cfg.get("excludes", ["统筹支付", "大额支付", "医保内费用"]),
        }

    # ── policy queries ─────────────────────────────────────────

    def build_policy_queries(self) -> list[Any]:
        """返回 YAML 定义的结构化政策查询计划（向后兼容）。"""
        from src.runtime.policy_qa.structured_policy_retriever import StructuredPolicyQuery
        cfg = self._load_yaml("policy_queries.yaml")
        queries = []
        for q in cfg.get("queries", []):
            queries.append(StructuredPolicyQuery(
                query_name=q["query_name"],
                required=q.get("required", True),
                filters=q.get("filters", {}),
                text_must_include_any=q.get("text_must_include_any", []),
                text_must_include_all=q.get("text_must_include_all", []),
                psn_type_allow_all=q.get("psn_type_allow_all", False),
            ))
        return queries

    # ── patient answer ─────────────────────────────────────────

    def build_patient_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        cfg = self._load_yaml("patient_template.yaml")

        amt = self._fmt_money(getattr(ctx, "personal_total_pay", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        large_self = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))
        pool_pay = self._fmt_money(getattr(ctx, "basic_pooling_payment", 0))
        large_pay = self._fmt_money(getattr(ctx, "large_amount_payment", 0))

        lines = []

        # 本次结论
        lines.append(cfg.get("conclusion_header", "【本次结论】"))
        lines.append(cfg.get("conclusion_template", '本次结算中，您的"个人总支付"为 {amount} 元。').replace("{amount}", amt))
        lines.append("")

        # 费用构成
        lines.append(cfg.get("composition_header", "【费用构成】"))
        lines.append(cfg.get("composition_intro", "个人总支付不是单一费用项目，而是多个费用来源的总和。"))
        lines.append("")
        table_body = cfg.get("composition_table_body", "起付线 {deductible} 元\n+ 统筹自付 {pooling_self_pay} 元\n+ 大额自付 {large_self} 元\n= 个人总支付 {personal_total_pay} 元")
        table_body = table_body.replace("{deductible}", deductible)
        table_body = table_body.replace("{pooling_self_pay}", pool_self)
        table_body = table_body.replace("{large_self}", large_self)
        table_body = table_body.replace("{personal_total_pay}", amt)
        for line in table_body.split("\n"):
            lines.append(line.strip())
        lines.append("")
        note = cfg.get("composition_note", "注：如存在目录外自费、先行自付等其他个人负担项，也已包含在个人总支付中。")
        lines.append(note)
        lines.append("")

        # 什么是个人总支付
        lines.append(cfg.get("what_is_this_header", "【什么是个人总支付】"))
        lines.append(cfg.get("what_is_this_template", "这是本次住院全部需要您自己承担的钱，包含多个不同来源：起付线（报销门槛）、统筹自付（统筹段按比例自付）、大额自付（大额段按比例自付）以及目录外自费等其他个人负担。个人总支付不等于统筹自付，统筹自付只是个人总支付的一部分。"))
        lines.append("")

        # 政策依据
        lines.append(cfg.get("evidence_header", "【政策依据】"))
        if evidence:
            lines.append(cfg.get("evidence_intro", "个人总支付是结算系统的综合计算结果，以下为本次适用的相关政策依据："))
            lines.append("")
            for idx, ev in enumerate(evidence):
                excerpt = self._clean_policy_excerpt(str(ev.get("source_text", "")))
                if not excerpt:
                    continue
                reason = str(ev.get("applied_reason", "本次结算适用本规则。"))
                lines.append(f"政策依据 {idx + 1}：")
                lines.append("政策原文摘录：")
                lines.append(f'"{excerpt}"')
                lines.append("本次适用原因：")
                lines.append(reason)
                lines.append("")
        elif policy_status == "no_policy_matched":
            lines.append("当前未检索到可引用政策依据，本页仅说明真实结算字段含义，不能作为完整政策解释。")
        else:
            lines.append("当前已匹配部分政策依据，以下解释可能不完整。")
        lines.append("")

        # 一句话总结
        lines.append(cfg.get("summary_header", "【一句话总结】"))
        summary_tpl = cfg.get("summary_template", '{amount} 元是您本次住院的"个人总支付"，包含起付线、统筹自付、大额自付等全部个人负担项。个人总支付不等于统筹自付，统筹自付只是其中一部分，两者不可混淆。')
        lines.append(summary_tpl.replace("{amount}", amt))

        return "\n".join(lines)

    # ── office answer ──────────────────────────────────────────

    def build_office_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        amt = self._fmt_money(getattr(ctx, "personal_total_pay", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        large_self = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))
        pool_pay = self._fmt_money(getattr(ctx, "basic_pooling_payment", 0))
        large_pay = self._fmt_money(getattr(ctx, "large_amount_payment", 0))

        lines = [
            f'本次解释对象为"{self.fee_label}"，金额为 {amt} 元。',
            "",
            "一、结算上下文",
            f'- 参保体系：{getattr(ctx, "insurance_type", "") or "未获取"}',
            f'- 人员类别：{getattr(ctx, "person_type", "") or "未获取"}',
            f'- 医疗类别：{getattr(ctx, "service_type", "") or "未获取"}',
            f'- 医院等级：{getattr(ctx, "hospital_level", "") or "未获取"}',
            f"- 起付线：{deductible} 元",
            f"- 统筹自付：{pool_self} 元",
            f"- 大额自付：{large_self} 元",
            f"- 统筹支付：{pool_pay} 元",
            f"- 大额支付：{large_pay} 元",
            "",
            "二、个人总支付构成分析",
            f"个人总支付 {amt} 元由以下费用项目构成：",
            f"  起付线 {deductible} 元（来源：yb_dyxxzy.bcqfje）",
            f"+ 统筹自付 {pool_self} 元（来源：yb_zyfdxx.bdtczf）",
            f"+ 大额自付 {large_self} 元（来源：yb_zyfdxx.bddegwyzf）",
            f"+ 其他个人负担项（来源：结算系统综合计算）",
            f"= 个人总支付 {amt} 元（来源：yb_zyfdxx.bdgryf）",
            "",
            "三、金额口径说明",
            "个人总支付是结算系统的汇总字段，等于所有个人负担类项目的总和。",
            "个人总支付 ≠ 统筹自付。统筹自付仅含基本统筹段按比例自付部分。",
            "个人总支付包含起付线、统筹自付、大额自付以及目录外自费（如有）。",
        ]
        return "\n".join(lines)

    # ── calculation trace ──────────────────────────────────────

    def build_calculation_trace(self, ctx: Any, evidence: list[dict]) -> dict:
        amt = self._fmt_money(getattr(ctx, "personal_total_pay", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        large_self = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))

        # 使用 FormulaEvaluator 验证费用组成是否一致
        evaluator = FormulaEvaluator()
        raw_amt = getattr(ctx, "personal_total_pay", 0) or 0
        raw_deductible = getattr(ctx, "deductible", 0) or 0
        raw_pool_self = getattr(ctx, "basic_pooling_self_pay", 0) or 0
        raw_large_self = getattr(ctx, "large_amount_self_pay", 0) or 0

        try:
            formula = MetricFormula(
                expression="personal_total_pay - (deductible + pooling_self_pay + large_amount_self_pay)",
                dependencies=["personal_total_pay", "deductible", "pooling_self_pay", "large_amount_self_pay"],
            )
            difference = evaluator.evaluate(formula, {
                "personal_total_pay": raw_amt,
                "deductible": raw_deductible,
                "pooling_self_pay": raw_pool_self,
                "large_amount_self_pay": raw_large_self,
            })
        except (ValueError, TypeError):
            difference = float("inf")

        steps: list[dict] = [
            {"step_name": "确认结算单号", "description": f'结算单号: {getattr(ctx, "settlement_id", "")}'},
            {"step_name": "确认起付线", "description": f"起付线为 {deductible} 元，来源于 yb_dyxxzy.bcqfje。"},
            {"step_name": "确认统筹自付", "description": f"统筹自付为 {pool_self} 元，来源于 yb_zyfdxx.bdtczf。"},
            {"step_name": "确认大额自付", "description": f"大额自付为 {large_self} 元，来源于 yb_zyfdxx.bddegwyzf。"},
            {"step_name": "汇总个人总支付", "description": f"个人总支付 = 起付线 {deductible} + 统筹自付 {pool_self} + 大额自付 {large_self} + 其他 = {amt} 元（来源于 yb_zyfdxx.bdgryf）。"},
        ]

        # 如果差值超过 1 元，添加差异警告
        if difference != float("inf") and abs(difference) > 1:
            steps.append({
                "step_name": "费用组成校验",
                "description": (
                    f"注意：起付线 + 统筹自付 + 大额自付 = "
                    f"{self._fmt_money(raw_deductible + raw_pool_self + raw_large_self)} 元，"
                    f"与个人总支付 {amt} 元相差 {self._fmt_money(abs(difference))} 元，"
                    f"表明存在其他个人负担项（如目录外自费、先行自付等）或存在舍入差异。"
                ),
            })
        elif difference != float("inf"):
            steps.append({
                "step_name": "费用组成校验",
                "description": (
                    f"个人总支付 {amt} 元与起付线 + 统筹自付 + 大额自付之和一致，费用组成完整。"
                ),
            })

        steps.append(
            {"step_name": "关键提醒", "description": "个人总支付是汇总字段，不等于统筹自付。统筹自付只是个人总支付的一部分。"},
        )

        return {
            "method": "个人总支付 = 起付线 + 统筹自付 + 大额自付 + 其他个人负担。金额来源于真实结算数据 yb_zyfdxx.bdgryf 字段。",
            "steps": steps,
        }

    # ── warnings ───────────────────────────────────────────────

    def build_warnings(self, ctx: Any, policy_status: str) -> list[str]:
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        return [
            "本结果来自真实数据库查询。",
            f"个人总支付不等于统筹自付（本次统筹自付为 {pool_self} 元）。统筹自付只是个人总支付的组成部分之一。",
            "个人总支付是汇总字段，包含起付线、统筹自付、大额自付、目录外自费等多个个人负担项。",
            "不能将个人总支付等同于「患者需要自费的部分」——统筹支付和大额支付已由医保基金承担，不在个人总支付内。",
        ]

    # ── completeness ───────────────────────────────────────────

    def build_completeness(self, ctx: Any, evidence: list[dict]) -> dict:
        has_data = bool(getattr(ctx, "personal_total_pay", 0))
        has_components = (
            bool(getattr(ctx, "deductible", 0))
            or bool(getattr(ctx, "basic_pooling_self_pay", 0))
            or bool(getattr(ctx, "large_amount_self_pay", 0))
        )
        has_policy = len(evidence) > 0

        if has_data and has_components and has_policy:
            level = "full_policy_matched"
            msg = "已匹配政策依据，已获取个人总支付及其构成字段的完整数据。"
        elif has_data and has_components:
            level = "real_data_only"
            msg = "已获取个人总支付及其构成字段的真实结算数据，政策依据未匹配。"
        elif has_data:
            level = "partial_data"
            msg = "已有个人总支付金额，但构成字段数据不完整。"
        else:
            level = "incomplete"
            msg = ""
        return {"level": level, "message": msg, "has_real_data": has_data}
