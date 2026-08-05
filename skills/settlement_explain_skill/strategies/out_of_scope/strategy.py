"""
OutOfScopeStrategy — 医保外费用解释策略。

医保外费用是概念驱动的解释策略。由于结算上下文中可能没有直接的
"out_of_scope" 字段，策略侧重解释"什么是医保外费用"以及
"为什么医保不报销这些"，而非具体金额计算。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base import BaseFeeStrategy

class OutOfScopeStrategy(BaseFeeStrategy):
    """医保外费用解释策略。"""

    fee_item = "out_of_scope"
    fee_label = "医保外费用"
    fee_field = "out_of_scope"

    def __init__(self, config_dir: Path):
        super().__init__(config_dir)

    # ── definition ─────────────────────────────────────────────

    def build_definition(self) -> dict:
        cfg = self._load_yaml("definition.yaml")
        return {
            "name": self.fee_label,
            "plain_text": cfg.get(
                "plain_text",
                "不在医保报销目录范围内的费用，需患者全额自费。包括：目录外药品（丙类药）、自费耗材、特需服务、美容整形等非治疗性项目、超出医保限价的费用等。",
            ),
            "excludes": cfg.get("excludes", [
                "统筹自付", "起付线", "大额自付", "乙类先行自付",
            ]),
        }

    # ── policy queries ─────────────────────────────────────────

    def build_policy_queries(self) -> list[Any]:
        """返回 YAML 定义的结构化政策查询计划（向后兼容）。"""
        from src.runtime.policy_qa.structured_policy_retriever import (
            StructuredPolicyQuery,
        )
        cfg = self._load_yaml("policy_queries.yaml")
        queries = []
        for q in cfg.get("queries", []):
            queries.append(
                StructuredPolicyQuery(
                    query_name=q["query_name"],
                    required=q.get("required", True),
                    filters=q.get("filters", {}),
                    text_must_include_any=q.get("text_must_include_any", []),
                    text_must_include_all=q.get("text_must_include_all", []),
                    psn_type_allow_all=q.get("psn_type_allow_all", False),
                )
            )
        return queries

    # ── answer ─────────────────────────────────────────────────

    def build_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        cfg = self._load_yaml("answer_template.yaml")

        # out_of_scope 字段可能不存在结算上下文，尝试安全获取
        amount_raw = getattr(ctx, "out_of_scope", None)
        target_amt = self._fmt_money(amount_raw) if amount_raw is not None else None

        # 金额关系辅助
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        large_self = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))
        personal = self._fmt_money(getattr(ctx, "personal_total_pay", 0))

        lines = []

        # 【本次结论】
        lines.append(cfg.get("conclusion_header", "【本次结论】"))
        if target_amt is not None:
            lines.append(
                cfg.get(
                    "conclusion_with_amount",
                    '本次结算中，您有 {amount} 元属于医保外费用（不在医保报销目录范围内的费用），需由您全额自费。',
                ).replace("{amount}", target_amt)
            )
        else:
            lines.append(
                cfg.get(
                    "conclusion_without_amount",
                    "本次结算涉及医保外费用——不在医保报销目录范围内的费用，需由患者全额自费。",
                )
            )
        lines.append("")

        # 【什么是医保外费用】
        lines.append(cfg.get("what_is_header", "【什么是医保外费用】"))
        lines.append(
            cfg.get(
                "what_is_template",
                "医保外费用，是指不属于医保三大目录范围内的费用。",
            )
        )
        lines.append("")

        # 【为什么医保不报销这些】
        lines.append(cfg.get("why_header", "【为什么医保不报销这些】"))
        lines.append(
            cfg.get(
                "why_template",
                "医保基金遵循'保基本'原则，三大目录外的费用不属于报销范围。",
            )
        )
        lines.append("")

        # 【政策依据】
        lines.append(cfg.get("evidence_header", "【政策依据】"))
        if evidence:
            lines.append(
                cfg.get(
                    "evidence_intro",
                    "根据已匹配到的医保目录范围政策：",
                )
            )
            lines.append("")
            for idx, ev in enumerate(evidence):
                excerpt = self._clean_policy_excerpt(
                    str(ev.get("source_text", ""))
                )
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
            lines.append(
                cfg.get(
                    "no_policy",
                    "当前未检索到医保目录范围的专项政策依据，以下内容基于医保通用规则进行解释。",
                )
            )
        lines.append("")

        # 【本次金额关系】
        lines.append(cfg.get("relationship_header", "【本次金额关系】"))
        for item in cfg.get("relationship_items", []):
            field_name = item.get("field", "")
            label = item.get("label", field_name)
            desc = item.get("description", "")
            amt_map = {
                "basic_pooling_self_pay": pool_self,
                "deductible": deductible,
                "large_amount_self_pay": large_self,
                "personal_total_pay": personal,
            }
            val = amt_map.get(field_name, "未获取")
            if val != "未获取":
                lines.append(f'- {label} {val} 元：{desc}')
            else:
                lines.append(f'- {label}：{desc}')
        lines.append("")

        # 【一句话总结】
        lines.append(cfg.get("summary_header", "【一句话总结】"))
        summary_tpl = cfg.get(
            "summary_template",
            "医保外费用与统筹自付、起付线、大额自付不同。"  # noqa: E501
            "统筹自付、起付线、大额自付都属于'医保目录内的费用按政策由个人承担的部分'；"
            "而医保外费用是'根本不在医保目录内、需全额自费的费用'。",
        )
        target_val = target_amt if target_amt else "医保外费用"
        lines.append(
            summary_tpl.replace("{amount}", target_val)
        )

        return "\n".join(lines)

    # ── calculation trace ──────────────────────────────────────

    def build_calculation_trace(self, ctx: Any, evidence: list[dict]) -> dict:
        amount_raw = getattr(ctx, "out_of_scope", None)
        target_amt = (
            self._fmt_money(amount_raw) if amount_raw is not None else "未获取"
        )

        steps = [
            {
                "step_name": "确认结算单号",
                "description": f'本次结算单号: {getattr(ctx, "settlement_id", "")}',
            },
            {
                "step_name": "确认待遇身份",
                "description": (
                    f'人员为 {getattr(ctx, "person_type", "")}，'
                    f'险种 {getattr(ctx, "insurance_type", "")}，'
                    f'{getattr(ctx, "service_type", "")}'
                ),
            },
            {
                "step_name": "区分目录内与目录外费用",
                "description": (
                    "医保三大目录（药品、诊疗项目、医疗服务设施）划定了报销范围。"
                    "目录内费用进入统筹计算流程（起付线→统筹段→大额段），"
                    "目录外费用（医保外费用）不纳入任何统筹计算，全额由患者自费。"
                ),
            },
        ]

        if amount_raw is not None:
            steps.append(
                {
                    "step_name": "确认医保外费用金额",
                    "description": (
                        f"本次医保外费用为 {target_amt} 元，"
                        "该金额来源于结算数据字段。"
                    ),
                }
            )
        else:
            steps.append(
                {
                    "step_name": "医保外费用金额",
                    "description": (
                        "当前结算上下文中未获取到独立的'医保外费用'字段，"
                        "解释侧重于概念说明而非具体金额。"
                    ),
                }
            )

        return {
            "method": (
                "医保外费用不参与统筹报销计算，为概念性解释。"
                "政策规则检索自 Milvus policy_rules。"
            ),
            "steps": steps,
        }

    # ── warnings ───────────────────────────────────────────────

    def build_warnings(self, ctx: Any, policy_status: str) -> list[str]:
        warnings = [
            "本结果来自真实数据库查询。",
            "医保外费用需患者全额自费，与统筹自付、起付线、大额自付的性质完全不同。",
            "医保外费用不纳入任何医保报销计算流程。",
        ]

        # 如果 out_of_scope 字段不存在，添加提示
        if getattr(ctx, "out_of_scope", None) is None:
            warnings.append(
                "当前结算数据未提供独立的医保外费用金额字段，"
                "解释基于概念而非具体金额。"
            )

        return warnings

    # ── completeness ───────────────────────────────────────────

    def build_completeness(self, ctx: Any, evidence: list[dict]) -> dict:
        has_amount = bool(getattr(ctx, "out_of_scope", 0))
        has_policy = len(evidence) > 0

        if has_amount and has_policy:
            level = "full_policy_matched"
            msg = "已获取医保外费用金额并匹配相关目录范围政策依据。"
        elif has_amount:
            level = "real_data_only"
            msg = "已从真实结算数据获取医保外费用金额，政策依据未匹配。"
        elif has_policy:
            level = "policy_only"
            msg = (
                "未获取独立的医保外费用金额字段，但有目录范围政策依据，"
                "仅提供概念性解释。"
            )
        else:
            level = "incomplete"
            msg = (
                "既无独立医保外费用金额字段，也未匹配到政策依据，"
                "解释基于通用医保规则。"
            )

        return {
            "level": level,
            "message": msg,
            "has_real_data": has_amount,
        }
