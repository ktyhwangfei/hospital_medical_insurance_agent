"""异常规则驱动的政策结构治理诊断。"""
from __future__ import annotations

import hashlib
import json

from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    CompilationTraceStore,
)
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    DiscoveryEvidence,
    RuleGovernanceDiagnosis,
    RuleGovernanceIssue,
    RuleGovernanceRuleSnapshot,
    match_database_evidence,
)


def _stable_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _classify(snapshot: RuleGovernanceRuleSnapshot) -> str:
    rule_value = str(snapshot.conditions.get("rule_value") or "")
    fund = str(snapshot.conditions.get("jjgs") or "")
    if (
        ("综合报销比例" in snapshot.subject or "医疗费用报销比例" in rule_value)
        and "大额医疗互助" not in rule_value
    ):
        return "benefit_ratio"
    if (
        "大额医疗互助" in rule_value
        or "大额医疗互助" in fund
        or "大额医疗互助" in snapshot.subject
        or "大额医疗互助" in snapshot.excerpt
    ):
        return "mutual_aid_fund"
    if "综合报销比例" in snapshot.excerpt or "综合待遇" in snapshot.excerpt:
        return "benefit_ratio"
    if "统筹基金" in fund or "统筹基金" in snapshot.excerpt:
        return "pooled_fund"
    return "unknown"


def _issue(
    release_id: str,
    issue_type: str,
    rules: list[RuleGovernanceRuleSnapshot],
    database_fields: list[dict],
) -> RuleGovernanceIssue:
    rule_ids = sorted(rule.rule_id for rule in rules)
    current = "；".join(
        f"{rule.rule_id}: conditions={json.dumps(rule.conditions, ensure_ascii=False, default=str)}, "
        f"result={json.dumps(rule.result, ensure_ascii=False, default=str)}"
        for rule in rules
    )
    settings = {
        "institution_category": {
            "title": "医疗机构类别被误提取为医院等级",
            "problem": "政策区分社区与非社区定点医疗机构，当前结构却使用 hosp_lv 表达医院等级。",
            "missing": "医疗机构类别",
            "values": ["社区卫生服务机构", "其他定点医疗机构"],
            "decision": "add_and_bind",
            "reason": "政策原文明确存在独立机构类别轴，bjyb 中 H_TYPE 表达机构类型，H_LEVEL 仅表达医院等级。",
            "changes": "清除 hosp_lv=一级；新增 institution_category，并绑定医疗机构类别字段。",
        },
        "mutual_aid_fund": {
            "title": "大额医疗互助资金归属纠偏",
            "problem": "该规则表达大额医疗互助资金支付比例，不能归并为统筹基金支付比例。",
            "missing": "基金归属",
            "values": ["大额医疗互助资金"],
            "decision": "repair_extraction",
            "reason": "政策原文明确写明大额医疗互助资金，应保留独立基金分项语义。",
            "changes": "保留大额医疗互助资金支付比例度量；基金来源标记为大额医疗互助资金。",
        },
        "benefit_ratio": {
            "title": "综合待遇比例被误解为基金分项",
            "problem": "综合报销比例是待遇结果，不代表某一个基金来源。",
            "missing": None,
            "values": [],
            "decision": "repair_extraction",
            "reason": "政策原文描述综合待遇结果，没有足够证据指向统筹或互助基金分项。",
            "changes": "保留综合待遇比例度量；清除误加的基金字段。",
        },
        "pooled_fund": {
            "title": "统筹基金分项需要明确归属",
            "problem": "规则表达统筹基金支付，需要与其他基金分项保持独立值域。",
            "missing": "基金归属",
            "values": ["统筹基金"],
            "decision": "supplement_value_mapping",
            "reason": "政策原文明确指向统筹基金，可补充标准值和来源映射。",
            "changes": "补充 fund_attribution=统筹基金，并保留原支付比例度量。",
        },
        "unknown": {
            "title": "未识别的政策结构问题",
            "problem": "当前确定性规则无法识别该政策问题的业务轴。",
            "missing": None,
            "values": [],
            "decision": "needs_review",
            "reason": "缺少可验证的结构模式，需要政策人员补充判断。",
            "changes": "暂不修改结构，记录人工判断。",
        },
    }[issue_type]
    policy_evidence = [DiscoveryEvidence(
        source_ref=f"lineage:{rule.compile_run_id}:{rule.rule_id}",
        excerpt=rule.excerpt,
        doc_id=rule.doc_id,
        unit_id=rule.unit_id,
        extraction_id=rule.extraction_id,
        rule_ids=[rule.rule_id],
    ) for rule in rules]
    database_evidence = match_database_evidence(
        str(settings["missing"] or settings["title"]),
        str(settings["problem"]),
        list(settings["values"]),
        database_fields,
    ) if settings["missing"] else []
    uncertainties = []
    if settings["decision"] == "add_and_bind" and not any(
        item.evidence_grade == "strong" for item in database_evidence
    ):
        uncertainties.append("未找到可直接绑定的数据库强证据")
    return RuleGovernanceIssue(
        issue_id=f"issue_{_stable_hash(release_id, issue_type, *rule_ids)[:16]}",
        issue_type=issue_type,
        title=str(settings["title"]),
        rule_ids=rule_ids,
        current_structure_summary=current,
        problem=str(settings["problem"]),
        missing_concept=settings["missing"],
        candidate_values=list(settings["values"]),
        recommended_decision=settings["decision"],
        recommended_reason=str(settings["reason"]),
        proposed_changes=str(settings["changes"]),
        policy_evidence=policy_evidence,
        database_evidence=database_evidence,
        uncertainties=uncertainties,
    )


def diagnose_rule_governance(
    release_id: str,
    rule_ids: list[str],
    trace_store: CompilationTraceStore,
    database_fields: list[dict],
) -> RuleGovernanceDiagnosis:
    """按规则 lineage 读取 canonical rule，并按独立业务轴拆分问题。"""
    if not release_id.strip():
        raise ValueError("来源 release_id 不能为空")
    normalized_ids = sorted({rule_id.strip() for rule_id in rule_ids if rule_id.strip()})
    if not normalized_ids:
        raise ValueError("至少需要一个 rule_id")

    snapshots: list[RuleGovernanceRuleSnapshot] = []
    for rule_id in normalized_ids:
        trace = trace_store.get_rule_trace_for_release(rule_id, release_id)
        if trace is None or trace.rule is None:
            raise ValueError(f"规则 {rule_id} 在来源版本 {release_id} 中没有可用 lineage")
        snapshots.append(RuleGovernanceRuleSnapshot(
            rule_id=rule_id,
            release_id=release_id,
            compile_run_id=trace.run.run_id,
            extraction_id=trace.run.extraction_id,
            unit_id=trace.run.unit_id,
            doc_id=trace.run.document_id,
            subject=trace.rule.subject,
            conditions=trace.rule.conditions,
            result=trace.rule.result,
            excerpt=str(trace.raw_input.get("source_text") or trace.rule.evidence[0]),
        ))

    grouped: dict[str, list[RuleGovernanceRuleSnapshot]] = {}
    institution_units = {
        snapshot.unit_id for snapshot in snapshots
        if "社区卫生服务机构以外" in snapshot.excerpt
        or "其他定点医疗机构" in snapshot.excerpt
    }
    for snapshot in snapshots:
        issue_type = (
            "institution_category"
            if snapshot.unit_id in institution_units
            else _classify(snapshot)
        )
        key = f"unknown:{snapshot.rule_id}" if issue_type == "unknown" else issue_type
        grouped.setdefault(key, []).append(snapshot)
    items = sorted(
        (_issue(release_id, key.split(":", 1)[0], rules, database_fields)
         for key, rules in grouped.items()),
        key=lambda item: (item.issue_type, item.issue_id),
    )
    payload = json.dumps(
        [rule.model_dump(mode="json") for rule in snapshots],
        ensure_ascii=False,
        sort_keys=True,
    )
    fingerprint = _stable_hash(release_id, payload)
    return RuleGovernanceDiagnosis(
        diagnosis_id=f"diagnosis_{fingerprint[:16]}",
        fingerprint=fingerprint,
        release_id=release_id,
        rules=snapshots,
        items=items,
    )
