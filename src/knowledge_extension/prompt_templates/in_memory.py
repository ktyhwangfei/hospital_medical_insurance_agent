from typing import Any

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.prompt_templates.models import PromptTemplate, TemplateRenderResult, TemplateSelectionRequest, TemplateSelectionResult, TemplateStatus


class InMemoryPromptTemplateRepository:
    def __init__(self, templates: list[PromptTemplate]):
        self._templates = {template.template_id: template for template in templates}

    def select(self, request: TemplateSelectionRequest) -> TemplateSelectionResult:
        candidates = [
            template for template in self._templates.values()
            if template.status is TemplateStatus.PUBLISHED
            and template.scenario == request.scenario
            and template.role in {request.role, "*"}
            and template.output_format == request.output_format
            and template.language == request.language
        ]
        if not candidates:
            return TemplateSelectionResult(status=KnowledgeExtensionStatus.TEMPLATE_MISSING, uncertainties=["未找到匹配提示词模板，已回退确定性响应"], audit_events=[AuditSummary(event_type="template_missing", summary=request.model_dump())])
        selected = sorted(candidates, key=lambda item: (item.role != request.role, item.risk_level != request.risk_level, item.template_id))[0]
        return TemplateSelectionResult(status=KnowledgeExtensionStatus.SUCCESS, template=selected.model_copy(deep=True), audit_events=[AuditSummary(event_type="template_selected", summary={"template_id": selected.template_id})])

    def render(self, template_id: str, variables: dict[str, Any]) -> TemplateRenderResult:
        template = self._templates[template_id]
        missing = sorted(template.required_variables - set(variables.keys()))
        if missing:
            return TemplateRenderResult(status=KnowledgeExtensionStatus.PARTIAL_DEGRADED, uncertainties=[f"模板变量缺失: {', '.join(missing)}"], audit_events=[AuditSummary(event_type="template_render_failed", summary={"template_id": template_id, "missing": missing})])
        prompt = template.content.format(**{key: str(value) for key, value in variables.items()})
        safety = "\n必须保留 citations 或 uncertainties；不得声称已执行高风险业务变更；不得泄露敏感信息。"
        return TemplateRenderResult(status=KnowledgeExtensionStatus.SUCCESS, prompt=prompt + safety, audit_events=[AuditSummary(event_type="template_rendered", summary={"template_id": template_id})])


def build_default_template_repository() -> InMemoryPromptTemplateRepository:
    templates = [
        PromptTemplate(template_id="tpl-settlement-officer", scenario="settlement_exception", role="medical_insurance_officer", output_format="agent_response", language="zh-CN", risk_level="low", version="2026.1", status=TemplateStatus.PUBLISHED, content="针对患者 {patient_id} 的结算异常请求：{message}", required_variables={"patient_id", "message"}),
        PromptTemplate(template_id="tpl-qc-doctor", scenario="pre_discharge_qc", role="doctor", output_format="agent_response", language="zh-CN", risk_level="medium", version="2026.1", status=TemplateStatus.PUBLISHED, content="针对患者 {patient_id} 的出院前质控：{message}", required_variables={"patient_id", "message"}),
    ]
    return InMemoryPromptTemplateRepository(templates)
