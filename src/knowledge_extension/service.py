"""知识扩展服务 stub — 原 assets/rag/prompt_templates 已删除。"""
from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import KnowledgeExtensionStatus


class KnowledgeEnhancementRequest(BaseModel):
    message: str = ""
    scenario: str = ""
    role: str = ""
    patient_id: str | None = None
    tenant_id: str | None = None
    campus_id: str | None = None
    rule_code: str | None = None


class KnowledgeEnhancementResult(BaseModel):
    status: KnowledgeExtensionStatus = KnowledgeExtensionStatus.NO_HIT
    citations: list = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list = Field(default_factory=list)

    def to_agent_payload(self) -> dict:
        return {"citations": [], "uncertainties": self.uncertainties, "audit_events": []}


class KnowledgeExtensionService:
    def enhance(self, request: KnowledgeEnhancementRequest) -> KnowledgeEnhancementResult:
        return KnowledgeEnhancementResult(
            status=KnowledgeExtensionStatus.NO_HIT,
            uncertainties=["知识扩展模块已移除"],
        )


def build_default_knowledge_extension_service() -> KnowledgeExtensionService:
    return KnowledgeExtensionService()
