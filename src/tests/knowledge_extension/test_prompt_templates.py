from src.knowledge_extension.prompt_templates.in_memory import build_default_template_repository
from src.knowledge_extension.prompt_templates.models import TemplateSelectionRequest


def test_selects_role_specific_template():
    repo = build_default_template_repository()
    result = repo.select(TemplateSelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", output_format="agent_response", language="zh-CN", risk_level="low"))

    assert result.status.value == "success"
    assert result.template is not None
    assert result.template.requires_citations is True


def test_missing_template_degrades_safely():
    repo = build_default_template_repository()
    result = repo.select(TemplateSelectionRequest(scenario="unknown", role="doctor", output_format="agent_response", language="zh-CN", risk_level="low"))

    assert result.status.value == "template_missing"
    assert result.uncertainties


def test_render_rejects_missing_required_variable():
    repo = build_default_template_repository()
    selected = repo.select(TemplateSelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", output_format="agent_response", language="zh-CN", risk_level="low"))

    rendered = repo.render(selected.template.template_id, {"message": "请解释异常"})

    assert rendered.status.value == "partial_degraded"
    assert "patient_id" in rendered.uncertainties[0]
