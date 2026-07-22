"""
PoolingPaymentStrategy — 统筹支付解释策略。

负责：统筹基金支付比例解读、统筹支付定义、患者/医保办视角。
统筹支付即基本医保统筹基金按政策比例为患者支付的金额。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..base import BaseFeeStrategy


class PoolingPaymentStrategy(BaseFeeStrategy):
    """统筹支付解释策略。"""

    fee_item = "pooling_payment"
    fee_label = "统筹支付"
    fee_field = "basic_pooling_payment"

    def __init__(self, config_dir: Path):
        super().__init__(config_dir)

    # ── definition ─────────────────────────────────────────────

    def build_definition(self) -> dict:
        cfg = self._load_yaml("definition.yaml")
        return {
            "name": self.fee_label,
            "plain_text": cfg.get(
                "plain_text",
                "基本医保统筹基金按政策比例为患者支付的金额。",
            ),
            "excludes": cfg.get(
                "excludes",
                ["起付线", "统筹自付", "大额自付", "目录外自费"],
            ),
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

    def _build_dynamic_policy_queries(self) -> list[Any] | None:
        """当 IndicatorContext 可用时，使用语义层动态构建统筹支付政策查询。"""
        from ..semantic_utils import build_structured_query_from_context

        ctx = self._indicator_context
        if ctx is None:
            return None

        # 查询 1：分段支付比例（动态维度 + 固定 rule_type）
        query1 = build_structured_query_from_context(
            ctx,
            query_name="employee_inpatient_tertiary_segment_ratio",
            text_must_include_any=[
                "起付标准至3万元",
                "超过3万元至4万元",
                "超过4万元",
            ],
            psn_type_allow_all=True,
        )
        if query1 is not None:
            query1.filters["rule_type"] = "支付比例"

        # 查询 2：退休人员优惠（可选）
        query2 = build_structured_query_from_context(
            ctx,
            query_name="retiree_personal_ratio_formula",
            text_must_include_all=["退休人员", "个人支付比例", "60%"],
            required=False,
        )
        if query2 is not None:
            query2.filters["rule_type"] = "计算公式"

        return [q for q in [query1, query2] if q is not None]

    # ── patient answer ─────────────────────────────────────────

    def build_patient_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        cfg = self._load_yaml("patient_template.yaml")
        seg = self._extract_fund_ratios(evidence)
        emp = seg.get("employee", [])
        ret = seg.get("retiree")
        has_complete = seg.get("has_complete", False)

        target_amt = self._fmt_money(getattr(ctx, "basic_pooling_payment", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        large_pay = self._fmt_money(getattr(ctx, "large_amount_payment", 0))
        large_self = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))
        personal = self._fmt_money(getattr(ctx, "personal_total_pay", 0))
        inner = self._fmt_money(getattr(ctx, "medical_insurance_inner_amount", 0))

        lines = []

        # 结论
        lines.append(cfg.get("conclusion_header", "【本次结论】"))
        conclusion_tpl = cfg.get(
            "conclusion_template",
            '本次结算中，您的"{fee_label}"为 {amount} 元。',
        )
        lines.append(
            conclusion_tpl.replace("{fee_label}", self.fee_label).replace(
                "{amount}", target_amt
            )
        )
        lines.append("")

        # 这是什么钱
        lines.append(cfg.get("what_is_this_header", "【这是什么钱】"))
        what_tpl = cfg.get(
            "what_is_this_template",
            "统筹支付是基本医保统筹基金已经为您支付的金额，不是您个人出的钱。",
        )
        lines.append(what_tpl.replace("{amount}", target_amt))
        lines.append("")

        # 政策依据
        lines.append(cfg.get("evidence_header", "【本次适用的政策依据】"))
        if evidence:
            evidence_intro = cfg.get(
                "evidence_intro",
                "根据已匹配到的政策，本次统筹基金按以下规则计算：",
            )
            lines.append(evidence_intro)
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
        elif policy_status == "no_policy_matched":
            lines.append(
                "当前未检索到可引用政策依据，本页仅说明真实结算字段含义，"
                "不能作为完整政策解释。"
            )
        else:
            lines.append("当前已匹配部分政策依据，以下解释可能不完整。")
        lines.append("")

        # 政策比例如何决定统筹支付
        lines.append(
            cfg.get("ratio_header", "【政策比例如何决定统筹支付】")
        )
        if has_complete:
            tertiary_intro = cfg.get(
                "tertiary_intro",
                "根据已匹配到的政策规则，三级医院住院费用按以下分段，"
                "统筹基金按比例支付：",
            )
            lines.append(tertiary_intro)
            lines.append("")
            segment_item = cfg.get(
                "segment_item",
                "{idx}. {lower} {upper}的部分：统筹基金支付 {fund}%",
            )
            for i, e in enumerate(emp):
                upper_text = (
                    "以上" if e["upper"] == "inf" else f'至 {e["upper"]}'
                )
                lines.append(
                    segment_item.format(
                        idx=i + 1,
                        lower=e["lower"],
                        upper=upper_text,
                        fund=e["fund"],
                    )
                )
            lines.append("")

            # 如果匹配到退休人员信息，展示退休优惠后的基金支付比例
            if ret:
                retiree_intro = cfg.get(
                    "retiree_intro",
                    "\n您本次属于退休人员，政策规定退休人员个人支付比例为"
                    "在职职工个人支付比例的60%。\n"
                    "这意味着基金实际支付比例更高，具体为：",
                )
                lines.append(retiree_intro)
                lines.append("")
                retiree_seg_item = cfg.get(
                    "retiree_segment_item",
                    "{idx}. {lower} {upper}部分："
                    "统筹基金支付 {adj_fund}%（退休优惠后）",
                )
                for i, e in enumerate(emp):
                    upper_text = (
                        "以上" if e["upper"] == "inf" else f'至 {e["upper"]}'
                    )
                    adj_fund = 100 - round(e["personal"] * 60 / 100, 1)
                    adj_fund = int(adj_fund) if adj_fund == int(adj_fund) else adj_fund
                    lines.append(
                        retiree_seg_item.format(
                            idx=i + 1,
                            lower=e["lower"],
                            upper=upper_text,
                            adj_fund=adj_fund,
                        )
                    )
                lines.append("")
                retiree_conclusion = cfg.get(
                    "retiree_conclusion",
                    "\n因此，{amount} 元是统筹基金按三级医院住院分段支付比例"
                    "（退休优惠后）为您实际支付的金额，"
                    "并非系统随意生成。",
                )
                lines.append(
                    retiree_conclusion.replace("{amount}", target_amt)
                )
            else:
                lines.append(
                    "您本次的统筹支付金额就是按上述分段比例，"
                    "由统筹基金为您实际支付的金额。"
                )
            lines.append("")
        else:
            ratio_unavailable = cfg.get(
                "ratio_unavailable",
                "当前未检索到可引用的分段比例政策依据，"
                "统筹支付金额来源于真实结算数据。",
            )
            lines.append(ratio_unavailable)
            lines.append("")

        # 金额关系
        lines.append(
            cfg.get("relationship_header", "【本次金额关系】")
        )
        for item in cfg.get("relationship_items", []):
            field_name = item.get("field", "")
            label = item.get("label", field_name)
            desc = item.get("description", "")
            amt_map = {
                "deductible": deductible,
                "basic_pooling_self_pay": pool_self,
                "basic_pooling_payment": target_amt,
                "large_amount_payment": large_pay,
                "large_amount_self_pay": large_self,
                "personal_total_pay": personal,
                "medical_insurance_inner_amount": inner,
            }
            val = amt_map.get(field_name)
            if val and val != "未获取":
                lines.append(f'- {label} {val} 元：{desc}')
            else:
                lines.append(f'- {label}：未获取')
        lines.append("")

        # 一句话总结
        lines.append(cfg.get("summary_header", "【一句话总结】"))
        summary_tpl = cfg.get(
            "summary_template",
            '{amount} 元是"基本医保统筹基金按政策比例为本次住院支付的金额"，'
            "统筹支付越高说明医保报销越多，不是患者需要额外出的钱。",
        )
        lines.append(summary_tpl.replace("{amount}", target_amt))

        if not has_complete:
            lines.append("")
            lines.append(
                cfg.get(
                    "incomplete_footer",
                    "当前金额来源于真实结算数据，"
                    "若要逐段复算还需要分段金额明细。",
                )
            )

        return "\n".join(lines)

    # ── office answer ──────────────────────────────────────────

    def build_office_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        target_amt = self._fmt_money(getattr(ctx, "basic_pooling_payment", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        inner = self._fmt_money(getattr(ctx, "medical_insurance_inner_amount", 0))
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        large_pay = self._fmt_money(getattr(ctx, "large_amount_payment", 0))
        large_self = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))
        personal = self._fmt_money(getattr(ctx, "personal_total_pay", 0))

        lines = [
            f'本次解释对象为"{self.fee_label}"，金额为 {target_amt} 元。',
            "",
            "一、结算上下文",
            f'- 参保体系：{getattr(ctx, "insurance_type", "") or "未获取"}',
            f'- 人员类别：{getattr(ctx, "person_type", "") or "未获取"}',
            f'- 医疗类别：{getattr(ctx, "service_type", "") or "未获取"}',
            f'- 医院等级：{getattr(ctx, "hospital_level", "") or "未查询"}',
            f"- 起付线：{deductible} 元",
            f"- 医保内费用：{inner} 元",
            f"- 基本统筹支付：{target_amt} 元",
            f"- 基本统筹自付：{pool_self} 元",
            f"- 大额支付：{large_pay} 元",
            f"- 大额自付：{large_self} 元",
            f"- 个人总支付：{personal} 元",
            "",
            "二、金额口径说明",
            f"{target_amt} 元是结算系统根据起付线扣减、统筹段归集、"
            "分段比例计算和封顶线控制后，写入基本统筹支付字段的结果。",
            "统筹支付是统筹基金为患者支付的金额，不是患者个人出的钱。",
            "统筹支付 = 医保内费用 - 起付线 - 统筹自付 - 大额自付"
            "（进入大额段前），但该公式仅为口径关系，"
            "实际由结算系统逐段计算生成。",
        ]
        return "\n".join(lines)

    # ── calculation trace ──────────────────────────────────────

    def build_calculation_trace(
        self, ctx: Any, evidence: list[dict]
    ) -> dict:
        seg = self._extract_fund_ratios(evidence)
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
                "step_name": "确认起付线及统筹段归集",
                "description": (
                    f'起付线为 {self._fmt_money(getattr(ctx, "deductible", 0))} 元。'
                    "起付线以上合规费用进入统筹段。"
                ),
            },
        ]
        if seg.get("has_complete"):
            for i, e in enumerate(seg.get("employee", [])):
                upper_text = (
                    "以上" if e["upper"] == "inf" else f'至 {e["upper"]}'
                )
                steps.append(
                    {
                        "step_name": f"分段支付比例 - 第{i + 1}段",
                        "description": (
                            f"{e['lower']} {upper_text}："
                            f"统筹基金支付 {e['fund']}%。"
                        ),
                    }
                )
            ret = seg.get("retiree")
            if ret:
                steps.append(
                    {
                        "step_name": "退休人员优惠调整",
                        "description": (
                            "退休人员个人支付比例为职工个人支付比例的60%，"
                            "基金实际支付比例相应提高。"
                        ),
                    }
                )
        steps.append(
            {
                "step_name": "统筹支付金额确认",
                "description": (
                    f"基本统筹支付为 "
                    f'{self._fmt_money(getattr(ctx, "basic_pooling_payment", 0))}'
                    " 元，来源于结算系统真实数据。"
                ),
            }
        )
        return {
            "method": "统筹基金按分段比例支付。政策规则检索自 Milvus policy_rules。",
            "steps": steps,
        }

    # ── warnings ───────────────────────────────────────────────

    def build_warnings(self, ctx: Any, policy_status: str) -> list[str]:
        pool_self = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        return [
            "本结果来自真实数据库查询。",
            (
                "统筹支付是基本医保统筹基金支付的金额，"
                "不是患者个人承担的部分。"
            ),
            (
                "统筹支付不等于医保内费用全额。医保内费用中还包含起付线、"
                f"统筹自付（本次统筹自付为 {pool_self} 元）、"
                "大额自付等个人负担部分。"
            ),
            "不能通过「医保内费用 - 统筹支付」简单计算患者个人自付金额。",
        ]

    # ── completeness ───────────────────────────────────────────

    def build_completeness(
        self, ctx: Any, evidence: list[dict]
    ) -> dict:
        seg = self._extract_fund_ratios(evidence)
        has_data = bool(getattr(ctx, "basic_pooling_payment", 0))
        has_segs = seg.get("has_complete", False)
        if has_data and has_segs:
            level = "full_policy_ratio_matched"
            msg = "已匹配到本次适用的三级医院住院分段支付比例。"
        elif has_data:
            level = "real_data_only"
            msg = "仅有真实结算字段，政策依据未匹配。"
        else:
            level = "incomplete"
            msg = ""
        return {
            "level": level,
            "message": msg,
            "has_real_data": has_data,
        }

    # ── fund ratio extraction ──────────────────────────────────

    def _extract_fund_ratios(self, evidence: list[dict]) -> dict:
        """
        从政策证据中提取统筹基金支付分段比例。

        解析政策文本中形如
        '统筹基金支付 85%，职工个人支付 15%' 的规则，
        并识别退休人员信息。
        """
        employee_segments = []
        retiree_info = None
        seen_keys: set[str] = set()

        BAND_PATTERNS = [
            ("起付标准至3万元", "起付标准", "3万元"),
            ("超过3万元至4万元", "3万元", "4万元"),
            ("超过4万元", "4万元", "inf"),
            ("4万元以上", "4万元", "inf"),
            ("3万元至4万元", "3万元", "4万元"),
            ("至3万元", "起付标准", "3万元"),
        ]
        BAND_LABELS_IN_ORDER = [
            ("起付标准", "3万元"),
            ("3万元", "4万元"),
            ("4万元", "inf"),
        ]

        def _detect_band(text: str):
            for kw, lo, hi in BAND_PATTERNS:
                if kw in text:
                    return f"{lo}-{hi}"
            return None

        for ev in evidence:
            source = str(
                ev.get("source_text") or ev.get("policy_title", "")
            )
            rule_type = str(ev.get("rule_type", ""))
            psn_type = str(ev.get("psn_type", ""))
            rule_tags = ev.get("rule_tags", [])
            rule_value = str(ev.get("rule_value", ""))

            amount_band = (
                str(ev.get("amount_band", ""))
                if ev.get("amount_band")
                else ""
            )
            valid_band = (
                bool(amount_band)
                and amount_band.lower() not in ("nan", "none", "null")
            )

            if valid_band:
                band_key = amount_band.replace(" ", "")
            else:
                band_key = _detect_band(source)

            # 提取分段比例
            all_matches = re.findall(
                r"(?:统筹基金支付|基金支付)\s*(\d+)%\s*[,，]?\s*"
                r"职工(?:个人)?支付\s*(\d+)%",
                source,
            )

            if not all_matches:
                # 检查退休人员信息
                retiree_context = " ".join(
                    filter(
                        None,
                        [psn_type, source]
                        + (
                            list(rule_tags)
                            if isinstance(rule_tags, list)
                            else []
                        ),
                    )
                )
                is_retiree = "退休" in retiree_context or "retiree" in rule_value.lower()
                if (
                    rule_type == "计算公式"
                    and "60%" in source
                    and is_retiree
                ):
                    retiree_info = {
                        "ratio": 60,
                        "segments": [],
                        "source": source,
                    }
                continue

            # 解析分段
            if len(all_matches) == 1:
                if band_key and band_key not in seen_keys:
                    seen_keys.add(band_key)
                    parts = (
                        band_key.split("-")
                        if "-" in (band_key or "")
                        else ["起付标准", "3万元"]
                    )
                    employee_segments.append(
                        {
                            "lower": parts[0],
                            "upper": parts[1],
                            "fund": int(all_matches[0][0]),
                            "personal": int(all_matches[0][1]),
                        }
                    )
            else:
                for idx, (fund_str, personal_str) in enumerate(
                    all_matches
                ):
                    if idx < len(BAND_LABELS_IN_ORDER):
                        lo, hi = BAND_LABELS_IN_ORDER[idx]
                        key = f"{lo}-{hi}"
                    else:
                        key = f"unknown-{idx}"
                        lo, hi = f"段{idx + 1}", "inf"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        employee_segments.append(
                            {
                                "lower": lo,
                                "upper": hi,
                                "fund": int(fund_str),
                                "personal": int(personal_str),
                            }
                        )

        seg_order = {"起付标准": 0, "3万元": 1, "4万元": 2}
        employee_segments.sort(
            key=lambda s: seg_order.get(s["lower"], 99)
        )

        # 为退休人员计算调整后各段比例
        if retiree_info and employee_segments:
            retiree_info["segments"] = [
                round(s["personal"] * 60 / 100, 1)
                for s in employee_segments
            ]
            retiree_info["segments"] = [
                int(r) if r == int(r) else r
                for r in retiree_info["segments"]
            ]

        # 统筹支付只要有分段比例即可认为完整，退休信息是补充
        has_complete = len(employee_segments) >= 3

        return {
            "has_complete": has_complete,
            "employee": employee_segments,
            "retiree": retiree_info,
        }
