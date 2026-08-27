"""
strategy.py — CompareStrategy：结算差异的确定性归因匹配 + 对比答案组装。

归因规则全部来自 attribution_rules.yaml（业务逻辑不硬编码）。
本模块只做：规则加载 → 条件求值 → 优先级裁决 → 兜底。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ...diff_engine import NUMERIC_FIELDS, FieldDiff, coerce_number, get_field_value

STRATEGY_DIR = Path(__file__).parent

_BASELINE_PREFIX = "baseline."
_RATIO_OPS = ("ratio_gt", "ratio_lt")


@dataclass(frozen=True)
class Attribution:
    """单条差异归因结果（Value Object）。"""

    rule_id: str
    name: str
    field: str
    settlement_id: str
    attribution: str
    baseline_value: float | str | None
    current_value: float | str | None
    policy_topic: str
    is_fallback: bool = False


def load_attribution_config(path: Path | None = None) -> dict[str, Any]:
    """加载归因规则配置。"""
    rules_path = path or (STRATEGY_DIR / "attribution_rules.yaml")
    return yaml.safe_load(rules_path.read_text(encoding="utf-8"))


def _compare_values(left: Any, op: str, right: Any) -> bool:
    """通用比较：双方可数值化时按数值比，否则按字符串比。"""
    left_num, right_num = coerce_number(left), coerce_number(right)
    if left_num is not None and right_num is not None:
        left, right = left_num, right_num
    else:
        left, right = str(left or ""), str(right or "")
    match op:
        case "eq":
            return left == right
        case "ne":
            return left != right
        case "gt":
            return left > right
        case "gte":
            return left >= right
        case "lt":
            return left < right
        case "lte":
            return left <= right
        case _:
            return False


def _eval_condition(cond: dict[str, Any], baseline: Any, current: Any) -> bool:
    """求值单条归因条件（语义见 attribution_rules.yaml 头部注释）。"""
    field = cond["field"]
    op = cond["op"]

    if field.startswith(_BASELINE_PREFIX):
        # baseline.<field>：取基准单字段，必须与字面量 value 比
        left = get_field_value(baseline, field[len(_BASELINE_PREFIX):])
        return _compare_values(left, op, cond["value"])

    if op in _RATIO_OPS:
        # 比值比较：对比单 / 基准单 与 value 比；基准为 0 或不可数值化时不命中
        cur = coerce_number(get_field_value(current, field))
        base = coerce_number(get_field_value(baseline, field))
        if cur is None or base is None or base == 0:
            return False
        ratio = cur / base
        return ratio > cond["value"] if op == "ratio_gt" else ratio < cond["value"]

    left = get_field_value(current, field)
    right = cond["value"] if "value" in cond else get_field_value(baseline, field)
    return _compare_values(left, op, right)


def _rule_matches(rule: dict[str, Any], diff: FieldDiff, baseline: Any, current: Any) -> bool:
    """规则适用字段包含差异字段，且 when.all 全部满足。"""
    if diff.field not in rule.get("applies_to", []):
        return False
    conditions = rule.get("when", {}).get("all", [])
    return all(_eval_condition(c, baseline, current) for c in conditions)


def match_attribution(
    diff: FieldDiff,
    baseline: Any,
    current: Any,
    settlement_id: str,
    config: dict[str, Any],
) -> tuple[Attribution, list[str]]:
    """对单个字段差异匹配归因规则。

    Returns:
        (Attribution, warnings)：命中多条时取 priority 最高者，其余进 warnings；
        未命中时返回 fallback 归因（is_fallback=True）。
    """
    hits = [r for r in config.get("rules", []) if _rule_matches(r, diff, baseline, current)]
    if hits:
        hits.sort(key=lambda r: r.get("priority", 0), reverse=True)
        picked = hits[0]
        warnings = []
        if len(hits) > 1:
            others = "、".join(r["name"] for r in hits[1:])
            warnings.append(
                f"字段「{diff.label}」命中多条归因规则，取最高优先级「{picked['name']}」（其余：{others}）"
            )
        return (
            Attribution(
                rule_id=picked["rule_id"],
                name=picked["name"],
                field=diff.field,
                settlement_id=settlement_id,
                attribution=picked["attribution"],
                baseline_value=diff.baseline_value,
                current_value=diff.current_value,
                policy_topic=picked.get("policy_topic", ""),
            ),
            warnings,
        )

    fallback = config.get("fallback", {})
    return (
        Attribution(
            rule_id="fallback",
            name=fallback.get("name", "费用构成变化"),
            field=diff.field,
            settlement_id=settlement_id,
            attribution=fallback.get("attribution", "差异由费用构成变化导致"),
            baseline_value=diff.baseline_value,
            current_value=diff.current_value,
            policy_topic="",
            is_fallback=True,
        ),
        [],
    )


# ── 对比策略 ────────────────────────────────────────────────────


class CompareStrategy:
    """结算对比策略：归因匹配 + 政策查询计划 + 确定性模板渲染。

    配置驱动：definition.yaml（费用项映射）、attribution_rules.yaml（归因规则）、
    policy_queries.yaml（归因政策查询）、answer_template.yaml（文案片段）。
    """

    def __init__(self, strategy_dir: Path | None = None):
        self._dir = strategy_dir or STRATEGY_DIR
        self.attribution_config = load_attribution_config(self._dir / "attribution_rules.yaml")
        self._definition = yaml.safe_load((self._dir / "definition.yaml").read_text(encoding="utf-8"))
        self._policy_queries = yaml.safe_load((self._dir / "policy_queries.yaml").read_text(encoding="utf-8"))
        self._tpl = yaml.safe_load((self._dir / "answer_template.yaml").read_text(encoding="utf-8"))

    def build_definition(self) -> dict:
        """返回对比定义（名称 + 说明）。"""
        return dict(self._definition.get("definition", {}))

    def fee_item_fields(self, target_fee_item: str | None) -> list[str] | None:
        """target_fee_item → 收窄后的对比字段；None/未知项 → 全字段对比。"""
        if not target_fee_item:
            return None
        item = self._definition.get("fee_items", {}).get(target_fee_item)
        return [item["field"]] if item else None

    def fee_item_known(self, target_fee_item: str) -> bool:
        return target_fee_item in self._definition.get("fee_items", {})

    def attribute_diffs(
        self,
        baseline: Any,
        current: Any,
        diffs: list[FieldDiff],
        settlement_id: str,
    ) -> tuple[list[Attribution], list[str]]:
        """对一张对比单的全部差异逐项归因。"""
        attributions: list[Attribution] = []
        warnings: list[str] = []
        for diff in diffs:
            attribution, warns = match_attribution(
                diff, baseline, current, settlement_id, self.attribution_config
            )
            attributions.append(attribution)
            warnings.extend(warns)
        return attributions, warnings

    def build_policy_queries(self, topics: list[str]) -> list[Any]:
        """按归因主题生成结构化政策查询计划（供产品层执行检索取 citations）。"""
        # skills 引用 src.* 是既有约定（见 settlement_explain_skill/strategies）
        from src.runtime.policy_qa.structured_policy_retriever import StructuredPolicyQuery

        queries: list[Any] = []
        topic_defs = self._policy_queries.get("topics", {})
        for topic in topics:
            for q in topic_defs.get(topic, []):
                queries.append(StructuredPolicyQuery(
                    query_name=q["query_name"],
                    required=q.get("required", False),
                    filters=dict(q.get("filters", {})),
                    text_must_include_any=list(q.get("text_must_include_any", [])),
                    text_must_include_all=list(q.get("text_must_include_all", [])),
                ))
        return queries

    # ── 答案渲染（确定性拼接，文案全部来自 answer_template.yaml）──

    def _format_value(self, field: str, value: float | str | None) -> str:
        """数值字段格式化为金额，类别字段原样输出。"""
        num = coerce_number(value)
        if field in NUMERIC_FIELDS and num is not None:
            return self._tpl["money"].format(amount=num)
        return str(value if value is not None else "")

    def _format_delta(self, diff: FieldDiff) -> str:
        if diff.delta is None:
            return ""
        key = "delta_up" if diff.delta > 0 else "delta_down"
        return self._tpl[key].format(amount=f"{abs(diff.delta):.2f}")

    def build_answer(
        self,
        baseline_id: str,
        compared: list[Any],
        evidence_by_topic: dict[str, list[dict]] | None = None,
    ) -> str:
        """渲染对比答案。

        Args:
            baseline_id: 基准结算单号
            compared: ComparedSettlement 列表（含 diffs + attributions）
            evidence_by_topic: 归因主题 → 政策证据列表（产品层检索供给）
        """
        tpl = self._tpl
        evidence_by_topic = evidence_by_topic or {}
        lines: list[str] = [tpl["header"].format(baseline_id=baseline_id)]
        uncertainty_items: list[str] = []

        for item in compared:
            lines.append("")
            lines.append(tpl["settlement_header"].format(settlement_id=item.settlement_id))
            if not item.diffs:
                lines.append(tpl["no_diff"])
                continue
            for diff, attribution in zip(item.diffs, item.attributions):
                baseline_text = self._format_value(diff.field, diff.baseline_value)
                current_text = self._format_value(diff.field, diff.current_value)
                delta_text = self._format_delta(diff)
                row_key = "row_with_delta" if delta_text else "row"
                lines.append(tpl[row_key].format(
                    label=diff.label,
                    baseline_text=baseline_text,
                    current_text=current_text,
                    delta_text=delta_text,
                ))
                lines.append(tpl["reason"].format(attribution=attribution.attribution))
                if attribution.is_fallback:
                    uncertainty_items.append(f"{item.settlement_id} 的{diff.label}")

        # 政策依据区块：按归因主题列出来源
        if evidence_by_topic:
            lines.append("")
            lines.append(tpl["evidence_header"])
            for topic, evidences in evidence_by_topic.items():
                for ev in evidences:
                    source = str(ev.get("source_text") or ev.get("applied_reason") or "")[:80]
                    if source:
                        lines.append(tpl["evidence_row"].format(topic=topic, source=source))

        if uncertainty_items:
            lines.append("")
            lines.append(tpl["uncertainty_note"].format(items="；".join(uncertainty_items)))

        return "\n".join(lines)

    def build_cannot_answer(self, reason: str) -> str:
        return self._tpl["cannot_answer"].format(reason=reason)
