from src.data_platform.storage.skill.factory import create_skill_storage
from src.domain.skill.models import Skill, SkillMetadata, SkillStep, ToolOwner
from src.knowledge_extension.mcp_registry.models import McpRiskLevel


def seed_default_skills(skill_storage) -> None:
    skills = [
        Skill(
            skill_id="settlement_exception_guidance",
            name="结算异常导办",
            description="医保结算失败、结算异常相关问题的智能导办。当用户提及结算失败、结算异常、医保结算报错、结算错误时自动触发。",
            owner=ToolOwner.CASHIER,
            steps=[
                SkillStep(step_id="query_transaction", tool_id="query_transaction"),
                SkillStep(step_id="retrieve_error_code", tool_id="retrieve_error_code", depends_on=["query_transaction"]),
                SkillStep(step_id="query_billing_status", tool_id="query_billing_status", depends_on=["query_transaction"]),
                SkillStep(step_id="build_result", tool_id="build_result", depends_on=["retrieve_error_code", "query_billing_status"]),
            ],
            intent_keywords=["结算失败", "结算异常", "医保结算报错", "结算错误"],
            required_roles={"cashier", "medical_office", "information_department"},
            risk_level=McpRiskLevel.LOW,
            license="MIT",
            compatibility="requires insurance_interface adapter",
            allowed_tools=[],
            skill_metadata=SkillMetadata(
                author="hospital-medical-insurance-team",
                version="1.0.0",
                category="workflow-automation",
                tags=["insurance", "settlement", "guidance"],
            ),
        ),
        Skill(
            skill_id="pre_discharge_quality_control",
            name="出院前联合质控",
            description="出院前医保风险检查与质控。当用户提及出院前、医保风险、质控、出院前检查时自动触发。",
            owner=ToolOwner.MEDICAL_OFFICE,
            steps=[
                SkillStep(step_id="query_orders", tool_id="query_orders"),
                SkillStep(step_id="query_insurance_status", tool_id="query_insurance_status"),
                SkillStep(step_id="query_pre_audit", tool_id="query_pre_audit"),
                SkillStep(step_id="query_drg_dip", tool_id="query_drg_dip"),
                SkillStep(step_id="query_medical_record", tool_id="query_medical_record"),
                SkillStep(step_id="retrieve_rule_explanation", tool_id="retrieve_rule_explanation"),
                SkillStep(step_id="build_risk_list", tool_id="build_risk_list", depends_on=["query_orders", "query_insurance_status", "query_pre_audit", "query_drg_dip", "query_medical_record", "retrieve_rule_explanation"]),
                SkillStep(step_id="create_tasks", tool_id="create_tasks", depends_on=["build_risk_list"]),
            ],
            intent_keywords=["出院前", "医保风险", "质控", "出院前检查"],
            required_roles={"medical_office", "medical_record_staff", "clinician"},
            risk_level=McpRiskLevel.LOW,
            license="MIT",
            compatibility="requires his, insurance_interface, pre_audit, drg_dip, medical_record adapters",
            allowed_tools=[],
            skill_metadata=SkillMetadata(
                author="hospital-medical-insurance-team",
                version="1.0.0",
                category="workflow-automation",
                tags=["discharge", "quality-control", "audit"],
            ),
        ),
        Skill(
            skill_id="mcp_tool_invocation",
            name="MCP工具调用",
            description="使用已注册的MCP工具执行操作，如画图、导出文件、调用外部服务。当用户提及画图、画一下、画个、drawio、diagram、图表、架构图、流程图、导出、export、draw时自动触发。",
            owner=ToolOwner.INFORMATION_DEPARTMENT,
            steps=[
                SkillStep(step_id="match_mcp_capability", tool_id="match_mcp_capability"),
                SkillStep(step_id="invoke_mcp_tool", tool_id="invoke_mcp_tool", depends_on=["match_mcp_capability"]),
            ],
            intent_keywords=["画图", "画一下", "画个", "drawio", "diagram", "图表", "架构图", "流程图", "导出", "export", "draw"],
            required_roles={"cashier", "medical_office", "information_department", "medical_record_staff", "clinician"},
            risk_level=McpRiskLevel.MEDIUM,
            license="MIT",
            compatibility="requires mcp_registry adapter",
            allowed_tools=[],
            skill_metadata=SkillMetadata(
                author="hospital-medical-insurance-team",
                version="1.0.0",
                category="mcp-enhancement",
                tags=["mcp", "tools", "invocation"],
            ),
        ),
    ]
    for skill in skills:
        skill_storage.save_skill(skill)


def seed_all() -> None:
    skill_storage = create_skill_storage()
    seed_default_skills(skill_storage)