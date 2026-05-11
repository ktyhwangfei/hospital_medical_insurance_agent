from dataclasses import dataclass


@dataclass(frozen=True)
class AuditResult:
    """事前审核结果：包含风险等级、规则命中详情和合规评分。"""

    audit_id: str
    patient_id: str
    encounter_id: str
    risk_level: str  # "high", "medium", "low"
    findings: tuple["RiskFlag", ...]
    compliance_score: float
    audit_time: str


@dataclass(frozen=True)
class RiskFlag:
    """风险标记：单条规则触发的风险信号。"""

    flag_id: str
    rule_id: str
    severity: str
    description: str
    evidence: str


@dataclass(frozen=True)
class RuleHit:
    """规则命中：记录被触发的审核规则信息。"""

    rule_id: str
    rule_name: str
    category: str
    matched_condition: str


@dataclass(frozen=True)
class ComplianceScore:
    """合规评分：多维度的合规性量化评分。"""

    overall: float
    coding_accuracy: float
    documentation_completeness: float
    billing_accuracy: float
