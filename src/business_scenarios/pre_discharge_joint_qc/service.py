from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.emr.in_memory import InMemoryEmrAdapter
from src.adapters.his.in_memory import InMemoryHisAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter
from src.knowledge_extension.mcp_registry.demo_tools import build_demo_mcp_tool_service
from src.knowledge_extension.service import KnowledgeEnhancementRequest, build_default_knowledge_extension_service
from src.runtime.api.schemas import AgentResponse

QC_RULES = [
    {"code": "PRE_AUDIT_RISK", "description": "事前审核合规风险评估", "responsible_role": "医保办"},
    {"code": "DRG_LOSS_RISK", "description": "DRG/DIP 亏损风险评估", "responsible_role": "科主任"},
    {"code": "MEDICAL_RECORD_RISK", "description": "病案首页质量风险评估", "responsible_role": "病案室"},
]


def enhance_qc_knowledge(patient_id: str | None) -> dict:
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="出院前联合质控 DRG DIP 病案风险", scenario="pre_discharge_qc", role="doctor", patient_id=patient_id, rule_code="DRG_LOSS_RISK"))
    return result.to_agent_payload()


def get_patient_summary(patient_id: str, encounter_id: str) -> dict:
    emr_adapter = InMemoryEmrAdapter()
    his_adapter = InMemoryHisAdapter()
    emr_result = emr_adapter.query_record_summary(patient_id, encounter_id)
    his_result = his_adapter.query_orders(patient_id, encounter_id)
    return {
        "emr": emr_result.data,
        "his": his_result.data,
        "emr_source": emr_result.source_system,
        "emr_source_id": emr_result.source_record_id or "",
        "his_source": his_result.source_system,
        "his_source_id": his_result.source_record_id or "",
    }


def run_qc_rules(patient_id: str, encounter_id: str) -> dict:
    pre_audit_adapter = InMemoryPreAuditAdapter()
    drg_adapter = InMemoryDrgDipAdapter()
    mr_adapter = InMemoryMedicalRecordAdapter()
    pre_audit_result = pre_audit_adapter.query_audit_result(patient_id, encounter_id)
    drg_result = drg_adapter.query_group_result(patient_id, encounter_id)
    mr_result = mr_adapter.query_homepage(patient_id, encounter_id)
    rule_results = [
        {
            "rule": QC_RULES[0]["code"],
            "description": QC_RULES[0]["description"],
            "risk": pre_audit_result.data.get("risk", ""),
            "risk_level": pre_audit_result.data.get("risk_level", "medium"),
            "responsible_role": QC_RULES[0]["responsible_role"],
            "source_system": pre_audit_result.source_system,
        },
        {
            "rule": QC_RULES[1]["code"],
            "description": QC_RULES[1]["description"],
            "risk": drg_result.data.get("risk", ""),
            "risk_level": drg_result.data.get("risk_level", "medium"),
            "responsible_role": QC_RULES[1]["responsible_role"],
            "source_system": drg_result.source_system,
        },
        {
            "rule": QC_RULES[2]["code"],
            "description": QC_RULES[2]["description"],
            "risk": mr_result.data.get("risk", ""),
            "risk_level": mr_result.data.get("risk_level", "medium"),
            "responsible_role": QC_RULES[2]["responsible_role"],
            "source_system": mr_result.source_system,
        },
    ]
    quality_issues = [r for r in rule_results if r.get("risk")]
    return {
        "rule_results": rule_results,
        "quality_issues": quality_issues,
        "pre_audit_source": pre_audit_result.source_system,
        "pre_audit_source_id": pre_audit_result.source_record_id or "",
        "drg_source": drg_result.source_system,
        "drg_source_id": drg_result.source_record_id or "",
        "mr_source": mr_result.source_system,
        "mr_source_id": mr_result.source_record_id or "",
    }


def build_qc_report(quality_issues: list) -> str:
    if not quality_issues:
        return "出院前联合质控完成，未发现质控问题。"
    issue_lines = []
    for i, issue in enumerate(quality_issues, 1):
        rule = issue.get("rule", "")
        risk = issue.get("risk", "")
        role = issue.get("responsible_role", "")
        issue_lines.append(f"{i}. [{rule}] {risk}（责任方：{role}）")
    report_lines = [
        f"出院前联合质控完成，发现 {len(quality_issues)} 个质控问题：",
    ]
    report_lines.extend(issue_lines)
    report_lines.append("")
    report_lines.append("建议联系相关责任方进行整改。")
    return "\n".join(report_lines)


def run_pre_discharge_qc(patient_id: str, encounter_id: str) -> AgentResponse:
    qc = run_qc_rules(patient_id, encounter_id)
    quality_issues = qc["quality_issues"]
    rule_results = qc["rule_results"]
    report = build_qc_report(quality_issues)
    risks = [
        {
            "risk_type": risk["risk"],
            "rule": risk["rule"],
            "risk_level": risk["risk_level"],
            "responsible_role": risk["responsible_role"],
            "recommendation": risk.get("recommendation", risk.get("description", "请相关责任方复核")),
        }
        for risk in rule_results
    ]
    tasks = [
        {"task_id": f"task-qc-{idx}", "task_type": "rectification", "status": "pending", "responsible_role": risk["responsible_role"], "description": risk["recommendation"]}
        for idx, risk in enumerate(risks, start=1)
    ]
    response = AgentResponse(
        scenario="pre_discharge_quality_control",
        status="completed",
        result={"risks": risks, "qc_recommendation": report},
        citations=[
            {"source_type": qc["pre_audit_source"], "source_id": qc["pre_audit_source_id"], "summary": rule_results[0].get("risk", "")},
            {"source_type": qc["drg_source"], "source_id": qc["drg_source_id"], "summary": rule_results[1].get("risk", "")},
            {"source_type": qc["mr_source"], "source_id": qc["mr_source_id"], "summary": rule_results[2].get("risk", "")},
        ],
        tasks=tasks,
        missing_fields=[],
        uncertainties=[],
        blocked_actions=[],
        audit={"workflow_id": f"wf-qc-{patient_id}-{encounter_id}", "steps": ["query_pre_audit", "query_drg_dip", "query_medical_record", "create_tasks"]},
    )
    mcp_insight = build_demo_mcp_tool_service().invoke_for_scenario(
        scenario="pre_discharge_quality_control",
        role="medical_office",
        tool_name="get_pre_discharge_checklist",
        arguments={"patient_id": patient_id, "encounter_id": encounter_id},
    )
    response.result["mcp_insights"] = [mcp_insight]
    response.citations.extend(mcp_insight["citations"])
    response.audit["mcp_tool_invocations"] = mcp_insight["audit_events"]
    knowledge = enhance_qc_knowledge(patient_id)
    response.citations.extend(knowledge["citations"])
    response.uncertainties.extend(knowledge["uncertainties"])
    response.audit["knowledge_extension"] = knowledge["audit_events"]
    return response
