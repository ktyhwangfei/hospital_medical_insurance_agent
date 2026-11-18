"""种子规则与基线值域映射（Issue #85 Slice 1 手工基线）。

规则来自 bjyb 目录 bz 原文的人工翻译（设计 V2.0 §5）；映射为 default 作用域基线，
院区差异后续按 hospital 作用域覆盖，不改本文件规则。
规则及映射均保留草稿/未审核状态，正式启用前需核实政策版本、价格口径及临床映射。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.directory_compliance.models import (
    ComplianceRule,
    ConditionGroup,
    MappingScope,
    MappingTargetType,
    PriceCapSpec,
    RestrictionConditionType,
    RuleCondition,
    ValueDomain,
    ValueDomainMapping,
)

# ── 基线值域映射（default 作用域）────────────────────────────────

BASELINE_MAPPINGS: tuple[ValueDomainMapping, ...] = (
    # dg.peptic_ulcer_bleeding：消化性溃疡出血 → ICD-10 前缀集（人工初稿待审核）
    *(
        ValueDomainMapping(
            mapping_id=f"map-dg-pub-icd-{prefix.replace('.', '')}",
            domain=ValueDomain.DIAGNOSIS,
            concept_code="dg.peptic_ulcer_bleeding",
            scope=MappingScope.DEFAULT,
            target_type=MappingTargetType.ICD_PREFIX,
            target_value=prefix,
            source="manual",
        )
        for prefix in ("K25.0", "K25.4", "K26.0", "K26.4", "K27.0", "K27.4", "K28.0", "K28.4")
    ),
    # dg.unable_oral_intake：无法口服 → 诊断名/病历中的证据性表述
    *(
        ValueDomainMapping(
            mapping_id=f"map-dg-uoi-name-{i}",
            domain=ValueDomain.DIAGNOSIS,
            concept_code="dg.unable_oral_intake",
            scope=MappingScope.DEFAULT,
            target_type=MappingTargetType.NAME_PATTERN,
            target_value=pattern,
            source="manual",
        )
        for i, pattern in enumerate(("吞咽困难", "禁食", "鼻饲", "无法口服"), 1)
    ),
    # dg.stress_ulcer_prophylaxis_critical（预防重症患者应激性溃疡出血）：
    # 故意不提供映射——门诊数据无可靠的重症状态数据源，执行引擎 fail-closed 判 unverifiable。
)

# ── 种子规则（bz → 规则 AST）────────────────────────────────────

RULE_ILAPRAZOLE = ComplianceRule(
    rule_id="rule-XA02BCA084B001010100453-20240320",
    item_code="XA02BCA084B001010100453",
    item_name="注射用艾普拉唑钠",
    catalog_source="bjyb.yb_ypzdml",
    catalog_effective_from=date(2024, 3, 20),
    catalog_effective_to=date(2050, 12, 31),
    condition_groups=(
        ConditionGroup(conditions=(
            RuleCondition(
                condition_type=RestrictionConditionType.DISEASE,
                concept_code="dg.stress_ulcer_prophylaxis_critical",
                source_span="预防重症患者应激性溃疡出血",
            ),
            RuleCondition(
                condition_type=RestrictionConditionType.DISEASE,
                concept_code="dg.peptic_ulcer_bleeding",
                source_span="消化性溃疡出血",
            ),
        )),
        ConditionGroup(conditions=(
            RuleCondition(
                condition_type=RestrictionConditionType.PRICE_CAP,
                concept_code="unit.vial_10mg",
                source_span="支付标准不得高于：63.00元(10mg/支)",
                price_cap=PriceCapSpec(amount=Decimal("63.00"), unit="支", strength_text="10mg"),
            ),
        )),
    ),
    source_bz="限：1.预防重症患者应激性溃疡出血；2.消化性溃疡出血。支付标准不得高于：63.00元(10mg/支)",
)

RULE_CARBAZOCHROME = ComplianceRule(
    rule_id="rule-XB02BXK018B001010201504-20240601",
    item_code="XB02BXK018B001010201504",
    item_name="注射用卡络磺钠",
    catalog_source="bjyb.yb_ypzdml",
    catalog_effective_from=date(2024, 6, 1),
    catalog_effective_to=date(2050, 12, 31),
    condition_groups=(
        ConditionGroup(conditions=(
            RuleCondition(
                condition_type=RestrictionConditionType.DISEASE,
                concept_code="dg.unable_oral_intake",
                source_span="限无法口服卡络磺钠（肾上腺色腙）的患者",
            ),
        )),
    ),
    source_bz="限无法口服卡络磺钠（肾上腺色腙）的患者",
)

SEED_RULES: tuple[ComplianceRule, ...] = (RULE_ILAPRAZOLE, RULE_CARBAZOCHROME)
