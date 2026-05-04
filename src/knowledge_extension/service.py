from pydantic import BaseModel, Field

from src.knowledge_extension.assets.in_memory import build_default_asset_repository
from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus
from src.knowledge_extension.extension_registry.in_memory import build_default_extension_registry
from src.knowledge_extension.prompt_templates.in_memory import build_default_template_repository
from src.knowledge_extension.prompt_templates.models import TemplateSelectionRequest
from src.knowledge_extension.rag.in_memory import InMemoryHybridRetriever
from src.knowledge_extension.rag.models import RetrievalFilter, RetrievalRequest
from src.knowledge_extension.rule_explanation.in_memory import InMemoryRuleExplainer
from src.knowledge_extension.rule_explanation.models import RuleExplanationRequest, RuleType


class KnowledgeEnhancementRequest(BaseModel):
    message: str
    scenario: str
    role: str
    patient_id: str | None = None
    tenant_id: str | None = None
    campus_id: str | None = None
    rule_code: str | None = None


class KnowledgeEnhancementResult(BaseModel):
    status: KnowledgeExtensionStatus
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)

    def to_agent_payload(self) -> dict[str, list[dict] | list[str]]:
        return {
            "citations": [citation.to_public_dict() for citation in self.citations],
            "uncertainties": self.uncertainties,
            "audit_events": [event.masked_summary() for event in self.audit_events],
        }


class KnowledgeExtensionService:
    def __init__(self, retriever: InMemoryHybridRetriever, explainer: InMemoryRuleExplainer, templates, extensions):
        self.retriever = retriever
        self.explainer = explainer
        self.templates = templates
        self.extensions = extensions

    def enhance(self, request: KnowledgeEnhancementRequest) -> KnowledgeEnhancementResult:
        citations: list[Citation] = []
        uncertainties: list[str] = []
        audits: list[AuditSummary] = []

        template_result = self.templates.select(TemplateSelectionRequest(scenario=request.scenario, role=request.role, output_format="agent_response", language="zh-CN", risk_level="low"))
        uncertainties.extend(template_result.uncertainties)
        audits.extend(template_result.audit_events)

        retrieval = self.retriever.retrieve(RetrievalRequest(query=request.message, filters=RetrievalFilter(role=request.role, tenant_id=request.tenant_id, campus_id=request.campus_id, scenario=request.scenario)))
        citations.extend(retrieval.citations)
        uncertainties.extend(retrieval.uncertainties)
        audits.extend(retrieval.audit_events)

        if request.rule_code:
            rule_type = RuleType.ERROR_CODE if request.scenario == "settlement_exception" else RuleType.DRG_DIP
            explanation = self.explainer.explain(RuleExplanationRequest(rule_type=rule_type, rule_code=request.rule_code, scenario=request.scenario, role=request.role))
            citations.extend(explanation.citations)
            uncertainties.extend(explanation.uncertainties)
            audits.extend(explanation.audit_events)

        deduped = []
        seen = set()
        for citation in citations:
            key = citation.dedupe_key()
            if key not in seen:
                seen.add(key)
                deduped.append(citation)
        status = KnowledgeExtensionStatus.SUCCESS if deduped else KnowledgeExtensionStatus.NO_HIT
        if not deduped and not uncertainties:
            uncertainties.append("未获得可追溯知识依据，建议人工复核")
        return KnowledgeEnhancementResult(status=status, citations=deduped, uncertainties=uncertainties, audit_events=audits)


def build_default_knowledge_extension_service() -> KnowledgeExtensionService:
    assets = build_default_asset_repository()
    return KnowledgeExtensionService(
        retriever=InMemoryHybridRetriever(assets),
        explainer=InMemoryRuleExplainer(),
        templates=build_default_template_repository(),
        extensions=build_default_extension_registry(),
    )
