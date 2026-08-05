"""
PoolingSelfPayStrategy — 统筹自付解释策略。

负责：统筹段分段比例、退休人员60%折算、统筹自付单一答案。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..base import BaseFeeStrategy
from src.model_service.gateway import ModelGateway
from src.model_service.models import Message
from skills.settlement_explain_skill.fact_builder import FactBuilder
from skills.settlement_explain_skill.output_parser import OutputParser, ParsedOutput

class PoolingSelfPayStrategy(BaseFeeStrategy):
    """统筹自付解释策略。"""

    fee_item = "pooling_self_pay"
    fee_label = "统筹自付"
    fee_field = "basic_pooling_self_pay"

    def __init__(self, config_dir: Path):
        super().__init__(config_dir)

    # ── definition ─────────────────────────────────────────────

    def build_definition(self) -> dict:
        cfg = self._load_yaml("definition.yaml")
        return {
            "name": self.fee_label,
            "plain_text": cfg.get("plain_text", "基本医保统筹段内按政策比例由个人承担的金额。"),
            "excludes": cfg.get("excludes", ["起付线", "大额自付", "目录外自费"]),
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
        # 不缓存：strategy 为单例，缓存会跨请求/跨结算单串答案（生产 bug）
        return self._generate_via_llm(ctx, evidence, policy_status).conclusion

    # ── LLM generation ─────────────────────────────────────────

    def _generate_via_llm(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> ParsedOutput:
        """通过 ModelGateway + FactBuilder + OutputParser 生成 LLM 输出。

        Step 1: 从 evidence 中提取分段比例
        Step 2: 使用 FactBuilder 构建标准化事实 JSON
        Step 3: 加载 prompt_template.yaml 并注入事实 JSON
        Step 4: 调用 ModelGateway.generate()
        Step 5: 使用 OutputParser 解析 LLM 输出
        Step 6: 由 BaseFeeStrategy.execute 的单一出口统一校验

        Returns:
            ParsedOutput (conclusion + office_note)
        """
        import yaml

        # Step 0: dummy 调试模式（MODEL_BASE_URL=dummy）→ 模型只返回固定 mock，
        # 不可作为回答。降级为基于真实结算数据的确定性模板（不写死金额）。
        from src.model_service.gateway import ModelGateway as _GatewayCls
        _gw = _GatewayCls()
        _cfg = getattr(_gw, "_config", None)
        if getattr(_cfg, "base_url", "") == "dummy":
            return self._build_dummy_fallback(ctx, evidence, policy_status)

        # Step 1: 提取分段比例
        segment_ratios = self._extract_segment_ratios(evidence)

        # Step 2: 构建标准化事实
        fact = FactBuilder().build(ctx, evidence, segment_ratios, self.fee_item)
        fact_json = fact.model_dump_json(indent=2)

        # Step 3: 加载 prompt 模板并渲染
        prompt_path = self.config_dir.parent.parent / "prompt_template.yaml"
        with open(prompt_path, encoding="utf-8") as f:
            prompt_cfg = yaml.safe_load(f)

        system_prompt = prompt_cfg["system_prompt"]
        user_prompt = prompt_cfg["user_prompt"].replace("{{ fact_json }}", fact_json)

        # Step 4: 调用 ModelGateway
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]
        response = ModelGateway().generate(
            messages=messages,
            model_type="llm",
            scene="fee_explanation",
        )

        # Step 5: 解析 LLM 输出
        return OutputParser.parse(response.content)

    # ── dummy 调试模式降级 ─────────────────────────────────────

    def _build_dummy_fallback(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> ParsedOutput:
        """dummy 模式（无真实 LLM）下的确定性回答：基于真实结算数据生成。

        不写死金额；分段规则不足时明确说明无法精确还原，并引导咨询医保办。
        """
        amount = self._fmt_money(getattr(ctx, "basic_pooling_self_pay", 0))
        deductible = self._fmt_money(getattr(ctx, "deductible", 0))
        seg = self._extract_segment_ratios(evidence)

        if seg.get("has_complete") and seg.get("retiree"):
            conclusion = (
                f"根据本次结算数据，您的统筹自付金额为 {amount} 元。\n\n"
                "该金额由基本医保统筹段内按政策比例分段计算得出，"
                "并叠加退休人员 60% 自付折算。"
            )
            office_note = (
                f"统筹自付 {amount} 元（来源：yb_zyfdxx.bdtczf）。"
                f"分段依据：职工分段比例 × 退休系数 60%。"
            )
        elif policy_status == "full_policy_matched":
            conclusion = (
                f"根据本次结算数据，您的统筹自付金额为 {amount} 元，"
                f"起付线为 {deductible} 元。"
            )
            office_note = (
                f"统筹自付 {amount} 元（来源：yb_zyfdxx.bdtczf），起付线 {deductible} 元。"
            )
        else:
            conclusion = (
                f"根据本次结算数据，您的统筹自付金额为 {amount} 元。\n\n"
                "当前未检索到完整的分段支付比例政策规则，无法精确还原计算过程。"
                "为避免误导，建议携带结算单前往医院医保办或拨打当地医保局服务热线咨询。"
                "\n\n本回答仅供参考，不作为报销或结算依据。"
            )
            office_note = (
                f"统筹自付 {amount} 元（来源：yb_zyfdxx.bdtczf）；"
                f"政策匹配状态：{policy_status}，分段规则不完整，无法精确还原。"
            )

        return ParsedOutput(conclusion=conclusion, office_note=office_note)

    # ── calculation trace ──────────────────────────────────────

    def build_calculation_trace(self, ctx: Any, evidence: list[dict]) -> dict:
        seg = self._extract_segment_ratios(evidence)
        steps = [
            {"step_name": "确认结算单号", "description": f'本次结算单号: {getattr(ctx, "settlement_id", "")}'},
            {"step_name": "确认待遇身份", "description": f'人员为 {getattr(ctx, "person_type", "")}，险种 {getattr(ctx, "insurance_type", "")}，{getattr(ctx, "service_type", "")}'},
            {"step_name": "确认起付线", "description": f'起付线为 {self._fmt_money(getattr(ctx, "deductible", 0))} 元。起付线以下不计入统筹段。'},
        ]
        if seg.get("has_complete") and seg.get("retiree"):
            for i, e in enumerate(seg["employee"]):
                r = seg["retiree"]
                steps.append({
                    "step_name": f'分段计算 - 第{i + 1}段',
                    "description": f"{e['lower']}{'至' + e['upper'] if e['upper'] != 'inf' else '以上'}：职工自付比例 {e['personal']}%，退休人员系数 {r['ratio']}%，实际 {r['segments'][i]}%。",
                })
        return {"method": "分段比例 × 退休人员优惠系数。结构化政策规则检索自 Milvus policy_rules。", "steps": steps}

    # ── warnings ───────────────────────────────────────────────

    def build_warnings(self, ctx: Any, policy_status: str) -> list[str]:
        large_self = self._fmt_money(getattr(ctx, "large_amount_self_pay", 0))
        return [
            "本结果来自真实数据库查询。",
            "统筹自付 ≠ 患者总自付。统筹自付仅含基本医保统筹段内个人按比例承担部分。",
            f"统筹自付不包含大额自付（本次大额自付为 {large_self} 元）。",
            "不能通过「统筹支付 + 统筹自付 + 起付线」简单倒推医保内费用。",
        ]

    # ── completeness ───────────────────────────────────────────

    def build_completeness(self, ctx: Any, evidence: list[dict]) -> dict:
        seg = self._extract_segment_ratios(evidence)
        has_data = bool(getattr(ctx, "basic_pooling_self_pay", 0))
        has_segs = seg.get("has_complete", False) or len(seg.get("employee", [])) >= 3
        has_retiree = seg.get("retiree") is not None
        if has_data and has_segs and has_retiree:
            level = "full_policy_ratio_matched"
            msg = "已匹配到本次适用的三级医院住院分段支付比例和退休人员折算规则。"
        elif has_data:
            level = "real_data_only"
            msg = "仅有真实结算字段，政策依据未匹配。"
        else:
            level = "incomplete"
            msg = ""
        return {"level": level, "message": msg, "has_real_data": has_data}

    # ── segment extraction (migrated from assembler) ───────────

    def _extract_segment_ratios(self, evidence: list[dict]) -> dict:
        employee_segments = []
        retiree_info = None
        seen_keys = set()
        BAND_PATTERNS = [
            ("起付标准至3万元", "起付标准", "3万元"), ("超过3万元至4万元", "3万元", "4万元"),
            ("超过4万元", "4万元", "inf"), ("4万元以上", "4万元", "inf"),
            ("3万元至4万元", "3万元", "4万元"), ("至3万元", "起付标准", "3万元"),
        ]
        BAND_LABELS_IN_ORDER = [("起付标准", "3万元"), ("3万元", "4万元"), ("4万元", "inf")]

        def _detect_band(text):
            for kw, lo, hi in BAND_PATTERNS:
                if kw in text: return f"{lo}-{hi}"
            return None

        for ev in evidence:
            source = str(ev.get("source_text") or ev.get("policy_title", ""))
            rule_type = str(ev.get("rule_type", ""))
            psn_type = str(ev.get("psn_type", ""))
            rule_tags = ev.get("rule_tags", [])
            rule_value = str(ev.get("rule_value", ""))

            all_matches = re.findall(
                r'(?:统筹基金支付|基金支付)\s*(\d+)%\s*[,，]?\s*职工(?:个人)?支付\s*(\d+)%', source
            )

            if not all_matches:
                retiree_context = " ".join(filter(None, [psn_type, source] + list(rule_tags if isinstance(rule_tags, list) else [])))
                is_retiree = "退休" in retiree_context or "retiree" in rule_value.lower()
                if rule_type == "计算公式" and "60%" in source and is_retiree:
                    retiree_info = {"ratio": 60, "segments": [], "source": source}
                continue

            # Parse segments
            amount_band = str(ev.get("amount_band", ""))
            valid_band = amount_band and amount_band.lower() not in ("nan", "none", "null")
            if valid_band:
                band_key = amount_band.replace(" ", "")
            else:
                band_key = _detect_band(source)

            if len(all_matches) == 1:
                if band_key and band_key not in seen_keys:
                    seen_keys.add(band_key)
                    parts = band_key.split("-") if "-" in (band_key or "") else ["起付标准", "3万元"]
                    employee_segments.append({
                        "lower": parts[0], "upper": parts[1],
                        "fund": int(all_matches[0][0]), "personal": int(all_matches[0][1]), "source": source,
                    })
            else:
                for idx, (fund_str, personal_str) in enumerate(all_matches):
                    if idx < len(BAND_LABELS_IN_ORDER):
                        lo, hi = BAND_LABELS_IN_ORDER[idx]
                        key = f"{lo}-{hi}"
                    else:
                        key = f"unknown-{idx}"
                        lo, hi = f"段{idx + 1}", "inf"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        employee_segments.append({"lower": lo, "upper": hi, "fund": int(fund_str), "personal": int(personal_str), "source": source})

        seg_order = {"起付标准": 0, "3万元": 1, "4万元": 2}
        employee_segments.sort(key=lambda s: seg_order.get(s["lower"], 99))

        has_complete = len(employee_segments) >= 3 and retiree_info is not None
        if retiree_info and employee_segments:
            retiree_info["segments"] = [round(s["personal"] * 60 / 100, 1) for s in employee_segments]
            retiree_info["segments"] = [int(r) if r == int(r) else r for r in retiree_info["segments"]]

        return {"has_complete": has_complete, "employee": employee_segments, "retiree": retiree_info}
