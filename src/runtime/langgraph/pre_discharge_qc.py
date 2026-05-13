import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.emr.in_memory import InMemoryEmrAdapter
from src.adapters.his.in_memory import InMemoryHisAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter
from src.runtime.langgraph.pre_discharge_state import PreDischargeState

_logger = logging.getLogger(__name__)

_emr_adapter = InMemoryEmrAdapter()
_his_adapter = InMemoryHisAdapter()
_pre_audit_adapter = InMemoryPreAuditAdapter()
_drg_adapter = InMemoryDrgDipAdapter()
_mr_adapter = InMemoryMedicalRecordAdapter()

QC_RULES = [
    {"code": "PRE_AUDIT_RISK", "description": "事前审核合规风险评估", "responsible_role": "医保办"},
    {"code": "DRG_LOSS_RISK", "description": "DRG/DIP 亏损风险评估", "responsible_role": "科主任"},
    {"code": "MEDICAL_RECORD_RISK", "description": "病案首页质量风险评估", "responsible_role": "病案室"},
]


def get_patient_summary(state: PreDischargeState) -> dict:
    patient_id = state.get("patient_id", "")
    encounter_id = state.get("encounter_id", "")
    citations = list(state.get("citations", []))

    emr_result = _emr_adapter.query_record_summary(patient_id, encounter_id)
    his_result = _his_adapter.query_orders(patient_id, encounter_id)

    patient_summary = {
        "emr": emr_result.data,
        "his": his_result.data,
    }

    citations.append({
        "source_type": emr_result.source_system,
        "source_id": emr_result.source_record_id or "",
        "summary": "患者病历摘要",
    })
    citations.append({
        "source_type": his_result.source_system,
        "source_id": his_result.source_record_id or "",
        "summary": "患者就诊信息",
    })

    return {
        "patient_summary": patient_summary,
        "citations": citations,
    }


def run_qc_rules(state: PreDischargeState) -> dict:
    patient_id = state.get("patient_id", "")
    encounter_id = state.get("encounter_id", "")
    citations = list(state.get("citations", []))

    pre_audit_result = _pre_audit_adapter.query_audit_result(patient_id, encounter_id)
    drg_result = _drg_adapter.query_group_result(patient_id, encounter_id)
    mr_result = _mr_adapter.query_homepage(patient_id, encounter_id)

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

    citations.append({
        "source_type": pre_audit_result.source_system,
        "source_id": pre_audit_result.source_record_id or "",
        "summary": pre_audit_result.data.get("risk", ""),
    })
    citations.append({
        "source_type": drg_result.source_system,
        "source_id": drg_result.source_record_id or "",
        "summary": drg_result.data.get("risk", ""),
    })
    citations.append({
        "source_type": mr_result.source_system,
        "source_id": mr_result.source_record_id or "",
        "summary": mr_result.data.get("risk", ""),
    })

    return {
        "rule_results": rule_results,
        "quality_issues": quality_issues,
        "citations": citations,
    }


def check_qc_issues(state: PreDischargeState) -> dict:
    quality_issues = state.get("quality_issues", [])
    return {
        "has_issues": len(quality_issues) > 0,
    }


def route_qc_issues(state: PreDischargeState) -> str:
    quality_issues = state.get("quality_issues", [])
    if quality_issues:
        return "has_issues"
    return "no_issues"


def build_qc_report(state: PreDischargeState) -> dict:
    quality_issues = state.get("quality_issues", [])

    if not quality_issues:
        report = "出院前联合质控完成，未发现质控问题。"
    else:
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
        report = "\n".join(report_lines)

    return {
        "qc_recommendation": report,
    }


def human_confirmation_node(state: PreDischargeState) -> dict:
    interrupt({
        "action": "waiting_human_confirmation",
        "workflow_id": state.get("workflow_id"),
        "intent": state.get("intent"),
        "quality_issues": state.get("quality_issues", []),
    })
    return {"requires_confirmation": True}


def build_pre_discharge_qc_graph(checkpointer=None):
    builder = StateGraph(PreDischargeState)
    builder.add_node("get_patient_summary", get_patient_summary)
    builder.add_node("run_qc_rules", run_qc_rules)
    builder.add_node("check_qc_issues", check_qc_issues)
    builder.add_node("build_qc_report", build_qc_report)
    builder.add_node("human_confirmation", human_confirmation_node)

    builder.add_edge(START, "get_patient_summary")
    builder.add_edge("get_patient_summary", "run_qc_rules")
    builder.add_edge("run_qc_rules", "check_qc_issues")

    builder.add_conditional_edges(
        "check_qc_issues",
        route_qc_issues,
        {
            "has_issues": "human_confirmation",
            "no_issues": END,
        },
    )

    builder.add_edge("human_confirmation", "build_qc_report")
    builder.add_edge("build_qc_report", END)

    return builder.compile(checkpointer=checkpointer)


from src.runtime.langgraph.checkpoint import get_checkpointer

pre_discharge_qc_graph = build_pre_discharge_qc_graph(checkpointer=get_checkpointer())
