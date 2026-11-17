"""筛查规则分类器与执行器单元测试 — issue #86 规则管理。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.screening_rules.classifier import (
    build_candidate_rule,
    classify_checklist,
    classify_clause,
    split_checklist_items,
)
from src.domain.screening_rules.executor import FeeLine, execute_rule
from src.domain.screening_rules.models import (
    FindingType,
    RuleClass,
    RuleStatus,
    ScreeningRule,
)

NOW = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
DOC = "国家定点医疗机构违法违规使用医疗保障基金典型问题清单（2025版）"
THYROID_CLAUSE = "开展甲状腺癌扩大根治术，重复收取甲状腺癌根治术和（或）淋巴结清扫术费用"


class TestSplitChecklistItems:
    def test_splits_lines_and_extracts_ref(self):
        text = "1. 开展甲状腺癌扩大根治术，重复收取甲状腺癌根治术费用\n\n2、超限定支付范围收费\n"
        items = split_checklist_items(text)
        assert len(items) == 2
        assert items[0][0] == "1"
        assert items[1][0] == "2"
        assert "甲状腺癌" in items[0][1]

    def test_falls_back_to_line_number(self):
        items = split_checklist_items("没有序号的条款\n")
        assert items[0][0] == "1"


class TestClassifyClause:
    def test_cocharge_is_executable(self):
        rule_class, gap = classify_clause(THYROID_CLAUSE)
        assert rule_class is RuleClass.EXECUTABLE
        assert gap is None

    def test_missing_material_is_not_executable(self):
        rule_class, gap = classify_clause("对存在基因突变的患者超说明书用药")
        assert rule_class is RuleClass.NOT_EXECUTABLE
        assert gap and ("基因" in gap or "突变" in gap)

    def test_line_of_therapy_is_not_executable(self):
        rule_class, _ = classify_clause("二线用药未提供一线治疗失败证据")
        assert rule_class is RuleClass.NOT_EXECUTABLE

    def test_mapping_gap_is_written(self):
        rule_class, gap = classify_clause("限三级医疗机构使用的项目超范围收费")
        assert rule_class is RuleClass.NEEDS_MAPPING
        assert gap and "映射" in gap

    def test_unknown_shape_defaults_to_needs_mapping(self):
        rule_class, gap = classify_clause("某条无法结构化的条款")
        assert rule_class is RuleClass.NEEDS_MAPPING
        assert gap  # 差一层映射必须写清缺什么


class TestBuildCandidateRule:
    def test_candidate_carries_source_clause(self):
        rule = build_candidate_rule(
            THYROID_CLAUSE, source_doc=DOC, source_item_ref="1", now=NOW
        )
        assert rule is not None
        assert rule.source_clause == THYROID_CLAUSE  # 必须带原条款
        assert rule.source_doc == DOC
        assert rule.status is RuleStatus.CANDIDATE  # 未批准不得跑数
        assert rule.condition_spec is not None
        assert rule.condition_spec["kind"] == "cocharge"
        assert rule.condition_spec["anchor_item_contains"] == "甲状腺癌扩大根治术"
        assert "甲状腺癌根治术" in rule.condition_spec["conflict_items_contain"]
        assert "淋巴结清扫术" in rule.condition_spec["conflict_items_contain"]

    def test_not_executable_yields_no_candidate(self):
        rule = build_candidate_rule(
            "对存在基因突变的患者超说明书用药", source_doc=DOC, source_item_ref="2", now=NOW
        )
        assert rule is None


class TestClassifyChecklist:
    def test_end_to_end(self):
        content = f"1. {THYROID_CLAUSE}\n2. 对存在基因突变的患者超说明书用药\n"
        items, rules = classify_checklist(content, source_doc=DOC, now=NOW)
        assert len(items) == 2
        assert items[0].rule_class is RuleClass.EXECUTABLE
        assert items[0].candidate_rule_id == rules[0].rule_id
        assert items[1].rule_class is RuleClass.NOT_EXECUTABLE
        assert items[1].candidate_rule_id is None
        assert len(rules) == 1


def _rule(status: RuleStatus = RuleStatus.APPROVED) -> ScreeningRule:
    rule = build_candidate_rule(
        THYROID_CLAUSE, source_doc=DOC, source_item_ref="1", now=NOW
    )
    assert rule is not None
    return rule.model_copy(update={"status": status})


class TestExecuteRule:
    def test_hit_when_anchor_and_conflict_cocharged(self):
        lines = [
            FeeLine("T1", "1:1", "A1", "甲状腺癌扩大根治术", 5000.0),
            FeeLine("T1", "1:2", "A2", "甲状腺癌根治术", 3000.0),
            FeeLine("T1", "1:3", "A3", "淋巴结清扫术", 2000.0),
            FeeLine("T2", "2:1", "A1", "甲状腺癌扩大根治术", 5000.0),  # 无冲突项 → 不命中
        ]
        findings = execute_rule(_rule(), lines, run_id="run-1", now=NOW)
        assert len(findings) == 2
        assert all(f.finding_type is FindingType.MISMATCH for f in findings)
        assert all(f.settlement_key == "T1" for f in findings)
        assert all(f.evidence_clause == THYROID_CLAUSE for f in findings)
        # 每条命中都能对上费用行与原条款
        assert {f.item_name for f in findings} == {"甲状腺癌根治术", "淋巴结清扫术"}
        # 主疑点 = 自身（同批次无其他规则时）
        assert all(f.primary_finding_id == f.finding_id for f in findings)

    def test_no_hit_still_succeeds_with_zero(self):
        lines = [FeeLine("T2", "2:1", "A1", "甲状腺癌扩大根治术", 5000.0)]
        findings = execute_rule(_rule(), lines, run_id="run-1", now=NOW)
        assert findings == []

    def test_anchor_substring_guard(self):
        """「甲状腺癌根治术」是「甲状腺癌扩大根治术」的子串风险：anchor 行不得再被计为冲突行。"""
        lines = [
            FeeLine("T1", "1:1", "A1", "甲状腺癌扩大根治术", 5000.0),
        ]
        findings = execute_rule(_rule(), lines, run_id="run-1", now=NOW)
        assert findings == []

    def test_unapproved_rule_refused(self):
        with pytest.raises(ValueError, match="未批准"):
            execute_rule(_rule(RuleStatus.CANDIDATE), [], run_id="run-1", now=NOW)

    def test_rule_without_source_clause_refused(self):
        rule = _rule().model_copy(update={"source_clause": " "})
        with pytest.raises(ValueError, match="原条款"):
            execute_rule(rule, [], run_id="run-1", now=NOW)

    def test_cross_rule_amount_dedup(self):
        """同一费用行只计一次金额：第二条规则命中同一费用行时指向主疑点。"""
        other = build_candidate_rule(
            "开展甲状腺癌扩大根治术，重复收取淋巴结清扫术费用",
            source_doc=DOC, source_item_ref="2", now=NOW,
        )
        assert other is not None
        other = other.model_copy(update={"status": RuleStatus.APPROVED})
        lines = [
            FeeLine("T1", "1:1", "A1", "甲状腺癌扩大根治术", 5000.0),
            FeeLine("T1", "1:3", "A3", "淋巴结清扫术", 2000.0),
        ]
        seen: dict[tuple[str, str], str] = {}
        first = execute_rule(_rule(), lines, run_id="run-1", now=NOW, seen_fee_lines=seen)
        second = execute_rule(other, lines, run_id="run-1", now=NOW, seen_fee_lines=seen)
        primary = [f for f in first if f.fee_line_id == "1:3"][0]
        secondary = [f for f in second if f.fee_line_id == "1:3"][0]
        assert primary.primary_finding_id == primary.finding_id
        assert secondary.primary_finding_id == primary.finding_id


# ── drug_age_indication（两库知识点：药品限适应症+年龄分支）──

from src.domain.screening_rules.executor import SettlementContext

FACTOR8_CLAUSE = "注射用重组人凝血因子Ⅷ：限儿童甲(A)型血友病；成人甲(A)型血友病限出血时使用。"
FACTOR8_SPEC = {
    "kind": "drug_age_indication",
    "drug_name_contains": "凝血因子Ⅷ",
    "diagnosis_contains": ["血友病A", "甲型血友病"],
    "child_max_age": 18,
    "adult_requires_diagnosis_contains": ["出血"],
}


def _factor8_rule(status: RuleStatus = RuleStatus.APPROVED) -> ScreeningRule:
    return ScreeningRule(
        rule_id="sr_factor8",
        source_doc="国家医保智能监管“两库”规则和知识点（第十三批）",
        source_clause=FACTOR8_CLAUSE,
        title="注射用重组人凝血因子Ⅷ限儿童甲(A)型血友病；成人限出血时使用",
        condition_text="门诊使用该药时：儿童甲型血友病不受限；成人需诊断中同时出现甲型血友病与出血",
        rule_class=RuleClass.EXECUTABLE,
        condition_spec=FACTOR8_SPEC,
        created_at=NOW,
        updated_at=NOW,
        status=status,
    )


def _ctx(settlement: str, age_years: float | None, diagnoses: tuple[str, ...]) -> SettlementContext:
    from datetime import timedelta
    if age_years is None:
        return SettlementContext(settlement_key=settlement, trade_date=NOW, birthday=None, diagnoses=diagnoses)
    return SettlementContext(
        settlement_key=settlement,
        trade_date=NOW,
        birthday=NOW - timedelta(days=int(age_years * 365.25)),
        sex="1",
        diagnoses=diagnoses,
    )


class TestDrugAgeIndication:
    def test_adult_with_bleeding_compliant_no_finding(self):
        """成人 + 甲型血友病 + 出血诊断 → 符合条件，不命中。"""
        lines = [FeeLine("T1", "1:1", "D1", "人凝血因子Ⅷ", 2990.0)]
        ctx = {"T1": _ctx("T1", 48, ("血友病A型", "下消化道出血"))}
        findings = execute_rule(_factor8_rule(), lines, run_id="r", now=NOW, settlement_contexts=ctx)
        assert findings == []

    def test_child_with_hemophilia_compliant(self):
        lines = [FeeLine("T2", "2:1", "D1", "人凝血因子Ⅷ", 2990.0)]
        ctx = {"T2": _ctx("T2", 8, ("血友病A型",))}
        assert execute_rule(_factor8_rule(), lines, run_id="r", now=NOW, settlement_contexts=ctx) == []

    def test_adult_without_bleeding_is_mismatch(self):
        lines = [FeeLine("T3", "3:1", "D1", "人凝血因子Ⅷ", 2990.0)]
        ctx = {"T3": _ctx("T3", 40, ("血友病A型",))}
        findings = execute_rule(_factor8_rule(), lines, run_id="r", now=NOW, settlement_contexts=ctx)
        assert len(findings) == 1
        assert findings[0].finding_type is FindingType.MISMATCH
        assert findings[0].evidence_clause == FACTOR8_CLAUSE

    def test_diagnosis_without_indication_is_mismatch(self):
        lines = [FeeLine("T4", "4:1", "D1", "人凝血因子Ⅷ", 2990.0)]
        ctx = {"T4": _ctx("T4", 30, ("上呼吸道感染",))}
        findings = execute_rule(_factor8_rule(), lines, run_id="r", now=NOW, settlement_contexts=ctx)
        assert len(findings) == 1
        assert findings[0].finding_type is FindingType.MISMATCH

    def test_placeholder_diagnosis_is_insufficient_material(self):
        """诊断是占位值（'1'）→ 材料不足，不编造依据。"""
        lines = [FeeLine("T5", "5:1", "D1", "罗沙司他胶囊", 400.0)]
        rule = _factor8_rule().model_copy(update={
            "condition_spec": {
                "kind": "drug_age_indication",
                "drug_name_contains": "罗沙司他",
                "diagnosis_contains": ["贫血"],
                "child_max_age": 18,
                "adult_requires_diagnosis_contains": [],
            },
        })
        ctx = {"T5": _ctx("T5", 50, ("1",))}
        findings = execute_rule(rule, lines, run_id="r", now=NOW, settlement_contexts=ctx)
        assert len(findings) == 1
        assert findings[0].finding_type is FindingType.INSUFFICIENT_MATERIAL

    def test_missing_birthday_is_insufficient_material(self):
        lines = [FeeLine("T6", "6:1", "D1", "人凝血因子Ⅷ", 2990.0)]
        ctx = {"T6": _ctx("T6", None, ("血友病A型",))}
        findings = execute_rule(_factor8_rule(), lines, run_id="r", now=NOW, settlement_contexts=ctx)
        assert len(findings) == 1
        assert findings[0].finding_type is FindingType.INSUFFICIENT_MATERIAL
