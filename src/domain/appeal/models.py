from dataclasses import dataclass


@dataclass(frozen=True)
class DenialRecord:
    """拒付记录：医保拒付的原始记录信息。"""

    denial_id: str
    claim_id: str
    denial_reason: str
    denial_amount: float
    denial_date: str
    appeal_deadline: str


@dataclass(frozen=True)
class AppealCase:
    """申诉案件：基于拒付发起的申诉全流程信息。"""

    appeal_id: str
    denial_id: str
    status: str  # "draft", "submitted", "under_review", "approved", "rejected"
    submit_date: str | None
    evidence: tuple["Evidence", ...]
    materials: tuple["AppealMaterial", ...]


@dataclass(frozen=True)
class Evidence:
    """证据材料：支撑申诉的各类证据项。"""

    evidence_id: str
    type: str  # "clinical", "coding", "policy"
    description: str
    source: str


@dataclass(frozen=True)
class AppealMaterial:
    """申诉附件：申诉时提交的具体材料文件。"""

    material_id: str
    type: str
    content: str
    created_at: str
