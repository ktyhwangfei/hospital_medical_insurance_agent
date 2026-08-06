"""
LargeAmountSelfPayStrategy — 大额自付解释策略。

负责：大额段支付比例说明、大额自付单一答案、大额与统筹/起付线区分。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base import BaseFeeStrategy

class LargeAmountSelfPayStrategy(BaseFeeStrategy):
    """大额自付解释策略。"""

    fee_item = "large_amount_self_pay"
    fee_label = "大额自付"
    fee_field = "large_amount_self_pay"

    def __init__(self, config_dir: Path):
        super().__init__(config_dir)

    # ── definition ─────────────────────────────────────────────

    def build_definition(self) -> dict:
        cfg = self._load_yaml("definition.yaml")
        return {
            "name": self.fee_label,
            "plain_text": cfg.get("plain_text", "大额医疗互助基金段内按比例由个人承担的金额。"),
            "excludes": cfg.get("excludes", ["起付线", "统筹自付", "目录外自费"]),
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

    # ── answer ─────────────────────────────────────────────────

    def build_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        cfg = self._load_yaml("answer_template.yaml")
        amt = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))
        large_pay = self._fmt_money(getattr(ctx, "large_amount_payment", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        personal = self._fmt_money(getattr(ctx, "personal_total_pay", 0))

        lines = []

        # 结论
        lines.append("【本次结论】")
        lines.append(cfg.get("conclusion", "本次结算中，您的大额自付为 {amount} 元。").replace("{amount}", amt))
        lines.append("")

        # 这是什么钱
        lines.append("【这是什么钱】")
        lines.append(cfg.get("what_is_this", "大额自付是进入大额医疗互助保障段后按比例由个人承担的部分。").replace("{amount}", amt))
        lines.append("")

        # 政策依据
        lines.append(cfg.get("evidence_header", "【本次适用的政策依据】"))
        if evidence:
            lines.append(cfg.get("evidence_intro", "根据已匹配到的政策，本次大额段费用按以下规则执行："))
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
        else:
            lines.append(cfg.get("no_policy", "当前未检索到可引用的大额段政策依据，以下仅基于真实结算字段进行解释，不能作为完整政策依据。"))
            lines.append("")

        # 金额关系
        lines.append(cfg.get("relationship_header", "【本次金额关系】"))
        for item in cfg.get("relationship_items", []):
            field_name = item.get("field", "")
            label = item.get("label", field_name)
            desc = item.get("description", "")
            amt_map = {
                "deductible": deductible,
                "basic_pooling_self_pay": pool_self,
                "basic_pooling_payment": self._fmt_money(getattr(ctx, "basic_pooling_payment", 0)),
                "large_amount_payment": large_pay,
                "large_amount_self_pay": amt,
                "personal_total_pay": personal,
            }
            val = amt_map.get(field_name, "未获取")
            if val != "未获取":
                lines.append(f'- {label} {val} 元：{desc}')
            else:
                lines.append(f'- {label}：未获取')
        lines.append("")

        # 一句话总结
        lines.append("【一句话总结】")
        lines.append(cfg.get("summary", "{amount} 元是本次结算进入大额医疗互助保障段后按比例由您个人承担的部分。").replace("{amount}", amt))

        return "\n".join(lines)

    # ── calculation trace ──────────────────────────────────────

    def build_calculation_trace(self, ctx: Any, evidence: list[dict]) -> dict:
        amt = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))
        large_pay = self._fmt_money(getattr(ctx, "large_amount_payment", 0))
        return {
            "method": "大额自付金额来源于真实结算数据 yb_dyxxzy.dqzfje 字段。大额段费用 = 大额支付 + 大额自付。",
            "steps": [
                {"step_name": "确认结算单号", "description": f'本次结算单号: {getattr(ctx, "settlement_id", "")}'},
                {"step_name": "确认待遇身份", "description": f'人员为 {getattr(ctx, "person_type", "")}，险种 {getattr(ctx, "insurance_type", "")}，{getattr(ctx, "service_type", "")}'},
                {"step_name": "确认大额段入段", "description": "当基本统筹段费用累计达到封顶线后，超出部分自动进入大额医疗互助保障段。"},
                {"step_name": "确认大额自付金额", "description": f'本次大额段费用中，大额支付 {large_pay} 元，大额自付 {amt} 元。大额自付来源于 yb_dyxxzy.dqzfje 字段。'},
            ],
        }

    # ── warnings ───────────────────────────────────────────────

    def build_warnings(self, ctx: Any, policy_status: str) -> list[str]:
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        return [
            "本结果来自真实数据库查询。",
            "大额自付 ≠ 个人总自付。大额自付仅含大额医疗互助保障段个人按比例承担部分。",
            f"大额自付不包含统筹自付（本次统筹自付为 {pool_self} 元）和起付线（本次起付线为 {deductible} 元）。",
            "大额自付是进入大额段后才产生的费用，统筹自付是进入基本统筹段后产生的费用——两者可同时存在但互不包含。",
        ]

    # ── completeness ───────────────────────────────────────────

    def build_completeness(self, ctx: Any, evidence: list[dict]) -> dict:
        has_data = self._has_real_field(ctx, "large_amount_self_pay")
        has_policy = len(evidence) > 0
        if has_data and has_policy:
            level = "full_policy_matched"
            msg = "已匹配到大额段政策支付比例依据。"
        elif has_data:
            level = "real_data_only"
            msg = "已从真实结算数据获取大额自付金额，政策依据未匹配。"
        else:
            level = "incomplete"
            msg = ""
        return {"level": level, "message": msg, "has_real_data": has_data}
