"""按结算日和支付项目展示完整候选，不用账面金额挑选比例。"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.insurance.fee_decomposition import BranchOutcome, DecompositionSnapshot, OutpatientSpecialSnapshot, PersonKind, SpecialPersonProfile, InstitutionProfile
from src.runtime.policy_qa.fee_decomposition.explanation_evidence import (
    CandidateCheck, ExplanationEvidence, FormulaInput, RuleCandidate, RuleChoiceGroup, input_id,
)

if TYPE_CHECKING:
    from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult

_WORDS = {"employed": "在职", "retired": "退休", "unknown": "未确认", "lt70": "未满70岁",
          "ge70": "已满70岁", "community": "社区", "other": "非社区", "normal": "普通退休",
          "prepaid": "预提退休", "first": "年度首周期", "subsequent": "第二及以后周期",
          "level_1_and_below": "一级及以下", "level_2_and_above": "二级及以上", "True": "是", "False": "否"}

#: 规则来源确认状态的唯一口径：本模块输入验证与 public_view 结论分级共用。
#: 含"待"字的状态（待确认/文档明确-待官方核证/实测待码表确认/待业务签核）一律不在其中；
#: 「官方转录已核实」正式文件出处待补，保守不计入。
CONFIRMED_RULE_STATUSES = frozenset({"文档明确", "官方已核实", "已核实"})


def _word(value) -> str | None:
    if value is None or str(value) == "unknown":
        return None
    return _WORDS.get(str(value), str(value))


def build_rule_choices(result: SettlementDecompositionResult,
                       snapshot: DecompositionSnapshot | OutpatientSpecialSnapshot,
                       evidence: ExplanationEvidence) -> list[RuleChoiceGroup]:
    from src.runtime.policy_qa.fee_decomposition import params_employee_outpatient as e
    from src.runtime.policy_qa.fee_decomposition import params_employee_outpatient_special as s
    from src.runtime.policy_qa.fee_decomposition import params_resident_outpatient as r
    from src.runtime.policy_qa.fee_decomposition import params_resident_outpatient_special as q
    from src.runtime.policy_qa.fee_decomposition.employee_outpatient import classify_person, classify_institution
    from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import _classify_institution, _classify_person

    special = isinstance(snapshot, OutpatientSpecialSnapshot)
    resident = snapshot.insurance_type == "resident"
    module = q if resident and special else r if resident else s if special else e
    person = snapshot.person
    code = person.cblb if isinstance(person, SpecialPersonProfile) else person.person_type_code
    kind = (_classify_person(code) if special else classify_person(code))[0]
    inst = snapshot.institution
    h_type = inst.h_type if isinstance(inst, InstitutionProfile) else None
    institution_kind = None if special else classify_institution(inst.h_level, h_type)[0]
    level = (q.institution_level_from_h_level(inst.h_level) if resident else _classify_institution(inst.h_level)[0]) if special else None
    tier = None if special else r.classify_institution_tier(inst.h_level)
    age = evidence.inputs["fact.person.age"].value
    age_band = None if age is None else "ge70" if int(age) >= 70 else "lt70"
    selected = {o.ref.removeprefix("rule.").split(".")[0]
                for calc in result.calculations for o in calc.operands if o.ref.startswith("rule.")}
    touched = selected | {ref.removeprefix("rule.").split(".")[0] for b in result.branches for ref in b.rule_refs}

    def family(p):
        # 自付分段、退休折算与基金支付分开，合计展示不进此集合。
        prefix = "-".join(p.rule_id.split("-")[:2])
        if p.rule_id == "ESP-RATE-113":
            return prefix + "-factor"
        return prefix + ("-" + p.supplement_segment if getattr(p, "supplement_segment", None) else "")

    touched_families = {family(p) for p in module.PARAMS if p.rule_id in touched}
    groups = defaultdict(list)
    for p in module.PARAMS:
        if family(p) not in touched_families or p.payment_level == "合计展示":
            continue
        if p.value is None or not p.unit.startswith(("%", "元")):
            continue
        # 只隐藏能证明在本单日期无效的版本，日期缺证仍可见并明确待核实。
        if p.effective_date and p.effective_date > evidence.settlement_date:
            continue
        if p.expiry_date and p.expiry_date < evidence.settlement_date:
            continue
        groups[family(p)].append(p)

    output = []
    for key, params in groups.items():
        group_id = "rules-" + key
        rows = []
        group_inputs = set()
        for p in params:
            checks = []

            def check(name, actual, expected, ref):
                actual, expected = _word(actual), _word(expected)
                if name == "住院口径机构档":
                    labels = {"1": "一级及未评级档", "2": "二级档", "3": "三级档"}
                    actual = labels.get(actual, actual) if actual is not None else None
                    expected = labels.get(expected, expected) if expected is not None else None
                ident = input_id(ref)
                status = evidence.inputs.get(ref)
                outcome = "unknown" if actual is None or (status and status.status != "verified") else "met" if actual == expected else "unmet"
                checks.append(CandidateCheck(name=name, actual=actual, expected=expected or "未确认", outcome=outcome, input_ref=ident))
                group_inputs.add(ident)

            if p.person_kind is not None:
                # 门特在职档是退休折算的基础，患者退休不应将该基础档排除。
                actual_kind = PersonKind.EMPLOYED if special and key == "ESP-RATE" and kind != PersonKind.UNKNOWN else kind
                check("比例基础档" if special and key == "ESP-RATE" else "人员身份", actual_kind, p.person_kind, "fact.person.person_type_code")
            if getattr(p, "age_band", None) is not None:
                check("年龄档", age_band, p.age_band, "fact.person.age")
            if getattr(p, "institution_kind", None) is not None:
                check("机构类别", institution_kind, p.institution_kind, "fact.institution.h_type" if h_type is not None else "fact.institution.h_level")
            if getattr(p, "institution_tier", None) is not None:
                check("机构等级档", tier, p.institution_tier, "fact.institution.h_level")
                if snapshot.institution.h_level and checks[-1].actual:
                    checks[-1].actual = f"{checks[-1].actual}（本单机构等级代码 {snapshot.institution.h_level}）"
            if getattr(p, "institution_level", None) is not None:
                check("住院口径机构档", level, p.institution_level, "fact.institution.h_level")
            if getattr(p, "retirement_category", None) is not None:
                check("退休补助类别", person.retirement_category, p.retirement_category, "fact.person.retirement_category")
            if getattr(p, "cycle_position", None) is not None:
                check("周期位置", snapshot.cycle.cycle_position if special else None, p.cycle_position, "fact.cycle.position")
            if p.rule_id in ("EOP-RSUP-001", "EOP-RSUP-002"):
                check("退休补助类别", person.retirement_category, "normal" if p.rule_id.endswith("001") else "prepaid", "fact.person.retirement_category")
            if p.rule_id.startswith(("EOP-RSUP-", "ESP-RSUP-")) and p.unit.startswith("%"):
                check("退休资格", kind, PersonKind.RETIRED, "fact.person.person_type_code")
            if p.rule_id.startswith(("EOP-DVET-", "ESP-DVET-")) and p.rule_id[-3:] in ("001", "002", "003", "004"):
                grade = person.military_grade if isinstance(person, SpecialPersonProfile) else person.military_disability_grade
                check("军残等级", grade, "5-6" if p.rule_id.endswith(("001", "003")) else "1-4", "fact.person.military_grade")
                eligible_value = evidence.inputs["fact.person.military_eligible"].value
                check("军残资格", eligible_value, "True", "fact.person.military_eligible")
            if p.rule_id.startswith(("EOP-PMED-", "ESP-PMED-")):
                check("公疗资格", evidence.inputs["fact.person.public_eligible"].value, "True", "fact.person.public_eligible")
                if p.rule_id in ("EOP-PMED-001", "EOP-PMED-002"):
                    check("人员身份", kind, PersonKind.RETIRED if p.rule_id.endswith("001") else PersonKind.EMPLOYED, "fact.person.person_type_code")
            # 居民门特参数复用基类，选择维度在原选择器中以规则 ID 显式映射。
            if p.rule_id.startswith("RSP-RATE-"):
                expected_level = {"RSP-RATE-001": "3", "RSP-RATE-002": "2", "RSP-RATE-003": "1"}[p.rule_id]
                check("住院口径机构档", level, expected_level, "fact.institution.h_level")
            if p.rule_id.startswith("RSP-DED-"):
                n = int(p.rule_id.rsplit("-", 1)[1])
                expected_level = "3" if n < 100 else "2" if n in (101, 103) else "1"
                student = code in q.STUDENT_CHILD_PERSON_TYPE_CODES if code is not None else None
                check("人员档", None if student is None else "学生儿童" if student else "老年或无业", "学生儿童" if n in (3, 103, 104) else "老年或无业", "fact.person.person_type_code")
                check("住院口径机构档", level, expected_level, "fact.institution.h_level")
                if n in (1, 2, 101, 102):
                    check("周期位置", snapshot.cycle.cycle_position if isinstance(snapshot, OutpatientSpecialSnapshot) else None, "subsequent" if n == 2 else "first", "fact.cycle.position")
            if p.segment:
                segment_name = {"base": "基础段", "excess_20k": "基金年度累计超2万元段", "seg1": "起付至1万元", "seg2": "1万至3万元", "seg3": "3万至4万元", "seg4": "4万元至封顶"}.get(p.segment, p.segment)
                segment_branch = next((b for b in result.branches if b.step_id in (f"pool.segment.{p.segment}.intersection", f"big_pay.segment.{p.segment}.intersection")), None)
                if segment_branch and segment_branch.condition:
                    actual = f"本笔与此段交集 {segment_branch.condition.actual_value} 元"
                else:
                    # 不写“见分段基数”：直接给出本笔进入该段的基数。
                    base = next((c.result for c in result.calculations
                                 if c.calculation_id in ("calc.deductible.copay_base", "calc.big_pay.capped")), None)
                    actual = f"本笔基数 {base} 元" if base else "本笔基数未取得"
                checks.append(CandidateCheck(name="费用分段", actual=actual, expected=segment_name or "未确认",
                    outcome="met" if not segment_branch or segment_branch.outcome == "true" else "unmet"))
            if key.startswith("ROP-CAP") and p.value is not None:
                prior = snapshot.accumulation.prior_fund_payment
                pay = next((c.result for c in result.calculations
                            if c.calculation_id == "calc.big_pay.capped"), None)
                if prior is not None and pay is not None:
                    room = max(p.value - prior, 0)
                    capped = prior + Decimal(pay) > p.value
                    checks.append(CandidateCheck(
                        name="年度封顶额度", expected=f"{p.value} 元",
                        actual=(f"交易前已支付 {prior} 元，剩余额度 {room} 元；本次支付 {pay} 元"
                                + ("，已按剩余额度封顶" if capped else "，未触及上限")),
                        outcome="met"))
            eligible = e.select_param((p,), evidence.settlement_date)
            if eligible.outcome.value != "true":
                checks.append(CandidateCheck(name="参数可用性", actual=p.confirmation_status,
                                            expected="日期与确认状态满足计算门控", outcome="unknown"))
            unmet = [c for c in checks if c.outcome == "unmet"]
            unknown = [c for c in checks if c.outcome == "unknown"]
            # 无结构化维度的其他补助，只陈列原条件和采用记录，不能猜排除原因。
            if not checks:
                checks.append(CandidateCheck(name="适用条件", actual=None, expected=p.applies_to, outcome="unknown"))
                unknown = checks
            status = "excluded" if unmet else "unknown" if unknown else "selected" if p.rule_id in selected else "eligible"
            reason = "；".join(f"{c.name}：本单{c.actual or '未取得'}，要求{c.expected}" for c in (unmet or unknown))
            if not reason:
                not_entered = any(p.rule_id in b.rule_refs and b.outcome in (BranchOutcome.FALSE, BranchOutcome.NOT_APPLICABLE)
                                  for b in result.branches)
                reason = ("本单未进入该待遇分支，未产生本档计算记录" if status == "eligible" and not_entered
                          else "本次计算已采用，条件符合当前参数口径" if status == "selected"
                          else "条件符合，未产生本档计算记录")
            row = RuleCandidate(rule_id=p.rule_id, name=p.name, value=str(p.value) if p.value is not None else p.value_text,
                                unit=p.unit, version=p.version, effective_from=str(p.effective_date) if p.effective_date else None,
                                effective_to=str(p.expiry_date) if p.expiry_date else "尚未终止" if p.expiry_open_ended else None,
                                source=p.source, confirmation_status=p.confirmation_status, status=status, reason=reason, checks=checks)
            rows.append(row)
            ref = "rule." + p.rule_id
            evidence.inputs[ref] = FormulaInput(
                input_id=input_id(ref), name=p.name, value=str(p.ratio if p.ratio is not None else p.value) if p.value is not None else p.value_text,
                status="verified" if status in ("selected", "eligible") and p.confirmation_status in CONFIRMED_RULE_STATUSES else "unverified",
                source=f"{p.source} · {p.version}", rule_group_ref=group_id, rule_id=p.rule_id,
                reason=None if status in ("selected", "eligible") and p.confirmation_status in CONFIRMED_RULE_STATUSES else p.confirmation_status + "；" + reason)
            if p.rule_id in ("EOP-RATE-301", "EOP-RATE-302"):
                from src.runtime.policy_qa.fee_decomposition.big_pay import _EXCESS_FUND_THRESHOLD
                threshold_ref = ref + ".threshold"
                evidence.inputs[threshold_ref] = FormulaInput(input_id=input_id(threshold_ref), name="基金年度累计支付分界",
                    value=str(_EXCESS_FUND_THRESHOLD), source=f"{p.source} · {p.version}", rule_group_ref=group_id,
                    status="unverified", reason=p.confirmation_status)
                group_inputs.add(input_id("fact.trade.prior_fund_payment"))
        # 同段多条同时成立才冲突；跨费用段同时适用是正常分段计算。
        buckets = defaultdict(list)
        for row, param in zip(rows, params):
            if row.status in ("selected", "eligible"):
                buckets[getattr(param, "segment", None)].append(row)
        for bucket in buckets.values():
            if len(bucket) > 1:
                for row in bucket:
                    row.status, row.reason = "conflict", "同一费用段多条候选同时满足，不能任取一条"
                    evidence.inputs["rule." + row.rule_id].status = "conflict"
        ids = {p.rule_id for p in params}
        calc_refs = [c.calculation_id for c in result.calculations if any(o.ref.removeprefix("rule.").split(".")[0] in ids for o in c.operands)]
        # 兜底标题：payment_level 为 None/"不适用"（无支付层次）时只用 category，
        # 否则"起付线 · 不适用"会被误读为本单起付规则不适用。
        fallback_title = (params[0].category if params[0].payment_level in (None, "不适用")
                          else f"{params[0].category} · {params[0].payment_level}")
        title = {"ESP-RATE": "统筹分段 · 在职自付基础比例（退休另行折算）", "ESP-RATE-factor": "退休自付折算系数",
                 "EOP-RATE": "大额基金支付比例", "ESP-LGP": "大额互助基金支付比例",
                 "ROP-RATE": "居民门诊基金支付比例", "RSP-RATE": "居民门特基金支付比例"}.get(key, fallback_title)
        output.append(RuleChoiceGroup(group_id=group_id, title=title,
                                      calculation_refs=calc_refs, input_refs=sorted(group_inputs), candidates=rows))
    if special and isinstance(snapshot, OutpatientSpecialSnapshot):
        output.extend(_secondary_choices(result, snapshot, evidence))
    return output


def _secondary_choices(result, snapshot: OutpatientSpecialSnapshot, evidence: ExplanationEvidence) -> list[RuleChoiceGroup]:
    from decimal import Decimal
    from src.runtime.policy_qa.fee_decomposition.params_secondary_coverage import (
        EFFECTIVE_DATE, BIG_ILL_DEDUCTIBLE, BIG_ILL_FIRST_BAND, BIG_ILL_RATES, ASSISTED_RATE_INCREMENT,
        SPECIAL_AID_POLICIES, DB_SOURCE, AID_SOURCE,
    )
    if snapshot.settle_date < EFFECTIVE_DATE or not any(b.module_id == "secondary_coverage" for b in result.branches):
        return []
    code = snapshot.person.civil_type
    known = code == "0" or code in SPECIAL_AID_POLICIES
    assisted = code in SPECIAL_AID_POLICIES
    groups = []
    for kind in ("db", "aid"):
        group_id = "rules-secondary-" + kind
        rows = []
        if kind == "db":
            specs = [(f"DB-{band}-{int(enhanced)}", f"{'救助对象' if enhanced else '非救助对象'} · 第{band+1}段", str((BIG_ILL_RATES[band] + (ASSISTED_RATE_INCREMENT if enhanced else 0)) * 100),
                      "救助对象" if enhanced else "非救助对象", "起付以上前5万元" if band == 0 else "超过首段5万元", assisted == enhanced)
                     for band in (0, 1) for enhanced in (False, True)]
        else:
            specs = [(f"AID-{identity}", f"救助身份代码 {identity} · {'无封顶' if cap is None else str(cap)+'元封顶'}", str(rate * 100),
                      identity, "基本医保及大病后的剩余合规自付", code == identity)
                     for identity, (rate, cap) in SPECIAL_AID_POLICIES.items()]
        for ident, name, value, expected, band, matches in specs:
            actual = ("救助对象" if assisted else "非救助对象") if kind == "db" and known else code
            check = CandidateCheck(name="救助身份", actual=actual, expected=expected,
                outcome="unknown" if not known else "met" if matches else "unmet", input_ref=input_id("fact.person.civil_type"))
            executed = any(any(o.ref.startswith("rule.SC-DB-") if kind == "db" else o.ref.startswith("rule.SC-MAF-") for o in c.operands) for c in result.calculations)
            status = "unknown" if not known else ("selected" if executed else "eligible") if matches else "excluded"
            rows.append(RuleCandidate(rule_id=ident, name=name, value=value, unit="%", version="2023-01-01",
                effective_from="2023-01-01", effective_to="尚未终止", source=DB_SOURCE if kind == "db" else AID_SOURCE,
                confirmation_status="用户补充规则，待业务签核", status=status,
                reason="身份条件符合；实际进入的费用段见交集基数" if status in ("selected", "eligible") else "救助身份不同" if status == "excluded" else "救助身份未确认，不能默认普通比例",
                checks=[check, CandidateCheck(name="费用段", actual="逐段交集", expected=band, outcome="met")]))
        refs = [c.calculation_id for c in result.calculations if any(o.ref.startswith("rule.SC-DB-") if kind == "db" else o.ref.startswith("rule.SC-MAF-") for o in c.operands)]
        groups.append(RuleChoiceGroup(group_id=group_id, title="二次大病保险比例" if kind == "db" else "医疗救助比例",
            calculation_refs=refs, input_refs=[input_id("fact.person.civil_type")], candidates=rows))
    values = {
        "rule.SC-DB-001.base_deductible": ("大病基础起付标准", BIG_ILL_DEDUCTIBLE),
        "rule.SC-DB-001.band_width": ("大病首段费用宽度", BIG_ILL_FIRST_BAND),
        "rule.SC-DB-001.db_first_rate": ("大病首段基础比例", BIG_ILL_RATES[0]),
        "rule.SC-DB-001.db_second_rate": ("大病第二段基础比例", BIG_ILL_RATES[1]),
        "rule.SC-DB-002.divisor": ("救助身份起付除数", Decimal("2") if assisted else Decimal("1")),
        "rule.SC-DB-002.increment": ("救助身份比例加成", ASSISTED_RATE_INCREMENT if assisted else Decimal("0")),
    }
    if assisted:
        assert code is not None
        values["rule.SC-MAF-001"] = ("本次救助比例", SPECIAL_AID_POLICIES[code][0])
        cap = SPECIAL_AID_POLICIES[code][1]
        if cap is not None:
            values["rule.SC-MAF-001.cap"] = ("本身份救助年度封顶", cap)
    for ref, (name, value) in values.items():
        evidence.inputs[ref] = FormulaInput(input_id=input_id(ref), name=name, value=str(value), status="unverified",
            source="2023年起二次保障参数（用户补充规则）", reason="规则仍待业务签核" if known else "救助身份未确认",
            rule_group_ref="rules-secondary-aid" if "MAF" in ref else "rules-secondary-db")
    return groups
