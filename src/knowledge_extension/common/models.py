from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeExtensionStatus(StrEnum):
    SUCCESS = "success"
    NO_HIT = "no_hit"
    PARTIAL_DEGRADED = "partial_degraded"
    PERMISSION_DENIED = "permission_denied"
    UNAVAILABLE = "unavailable"
    VERSION_MISMATCH = "version_mismatch"
    EVIDENCE_CONFLICT = "evidence_conflict"
    TEMPLATE_MISSING = "template_missing"
    HIGH_RISK_BLOCKED = "high_risk_blocked"


class VisibilityScope(BaseModel):
    roles: set[str] = Field(default_factory=set)
    tenant_ids: set[str] = Field(default_factory=set)
    campus_ids: set[str] = Field(default_factory=set)

    def allows(self, role: str, tenant_id: str | None = None, campus_id: str | None = None) -> bool:
        role_allowed = not self.roles or role in self.roles
        tenant_allowed = not self.tenant_ids or tenant_id in self.tenant_ids
        campus_allowed = not self.campus_ids or campus_id in self.campus_ids
        return role_allowed and tenant_allowed and campus_allowed


class Citation(BaseModel):
    source_id: str
    source_type: str
    title: str
    version: str | None = None
    section: str | None = None
    chunk_id: str | None = None
    evidence: str
    retrieved_at: str | None = None
    score: float | None = None
    internal_locator: str | None = None

    def dedupe_key(self) -> tuple[str, str | None, str | None, str]:
        return (self.source_id, self.version, self.chunk_id, self.evidence)

    def to_public_dict(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True, exclude={"internal_locator"})
        return payload


class Degradation(BaseModel):
    status: KnowledgeExtensionStatus
    reason: str
    user_message: str


class AuditSummary(BaseModel):
    event_type: str
    actor: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)

    def masked_summary(self) -> dict[str, Any]:
        sensitive_keys = {"patient_name", "id_card", "phone", "token", "authorization", "api_key"}
        return {key: "***" if key.lower() in sensitive_keys else value for key, value in self.summary.items()}
