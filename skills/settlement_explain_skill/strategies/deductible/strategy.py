"""
DeductibleStrategy — 起付线解释策略。

负责：起付线定义、起付线政策查询、单一答案。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base import BaseFeeStrategy

class DeductibleStrategy(BaseFeeStrategy):
    """起付线解释策略。"""

    fee_item = "deductible"
    fee_label = "起付线"
    fee_field = "deductible"

    def __init__(self, config_dir: Path):
        super().__init__(config_dir)

    def build_definition(self) -> dict:
        cfg = self._load_yaml("definition.yaml")
        return {
            "name": self.fee_label,
            "plain_text": cfg.get("plain_text", "医保开始报销前需先由个人承担的固定金额。"),
            "excludes": cfg.get("excludes", []),
        }

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

    def build_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        cfg = self._load_yaml("answer_template.yaml")
        amt = self._fmt_money(getattr(ctx, "deductible", 0))

        lines = []
        lines.append("【本次结论】")
        lines.append(cfg.get("conclusion", "本次结算中，您的起付线为 {amount} 元。").replace("{amount}", amt))
        lines.append("")

        lines.append("【这是什么钱】")
        lines.append(cfg.get("what_is_this", "起付线是医保报销的门槛金额。只有超过起付线的部分，医保才开始按比例报销。").replace("{amount}", amt))
        lines.append("")

        lines.append("【政策依据】")
        if evidence:
            for idx, ev in enumerate(evidence):
                excerpt = self._clean_policy_excerpt(str(ev.get("source_text", "")))
                if not excerpt: continue
                reason = str(ev.get("applied_reason", "本次结算适用本规则。"))
                lines.append(f"政策依据 {idx + 1}：")
                lines.append(f'"{excerpt}"')
                lines.append(f"本次适用原因：{reason}")
                lines.append("")
        else:
            lines.append(cfg.get("no_policy", "当前未查到起付线政策依据，金额来源于真实结算数据。"))
        lines.append("")

        lines.append("【一句话总结】")
        lines.append(cfg.get("summary", "{amount} 元是本次住院的起付线金额。起付线以下是个人全额承担的部分，与统筹自付、大额自付互不包含。").replace("{amount}", amt))

        return "\n".join(lines)

    def build_calculation_trace(self, ctx: Any, evidence: list[dict]) -> dict:
        amt = self._fmt_money(getattr(ctx, "deductible", 0))
        return {
            "method": "起付线金额来源于真实结算数据 yb_dyxxzy.bcqfje 字段。",
            "steps": [
                {"step_name": "确认结算单号", "description": f'结算单号: {getattr(ctx, "settlement_id", "")}'},
                {"step_name": "确认起付线金额", "description": f"本次起付线为 {amt} 元，来源于 yb_dyxxzy.bcqfje 字段。"},
                {"step_name": "起付线与统筹自付的区别", "description": "起付线是报销前的固定自付金额，统筹自付是进入统筹段后按比例自付。两者互不包含。"},
            ],
        }

    def build_warnings(self, ctx: Any, policy_status: str) -> list[str]:
        return [
            "本结果来自真实数据库查询。",
            "起付线是医保开始报销前的固定自付金额，不同于统筹自付（按比例自付）。",
        ]

    def build_completeness(self, ctx: Any, evidence: list[dict]) -> dict:
        has_data = bool(getattr(ctx, "deductible", 0))
        has_policy = len(evidence) > 0
        if has_data and has_policy:
            level = "full_policy_matched"
            msg = "已匹配起付线政策依据。"
        elif has_data:
            level = "real_data_only"
            msg = "已从真实结算数据获取起付线金额，政策依据未匹配。"
        else:
            level = "incomplete"
            msg = ""
        return {"level": level, "message": msg, "has_real_data": has_data}
