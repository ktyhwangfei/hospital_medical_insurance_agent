from src.business_scenarios.pre_discharge_joint_qc.service import (
    build_qc_report,
    get_patient_summary,
    run_qc_rules,
)


def get_patient_summary_node(state: dict) -> dict:
    patient_id = state.get("patient_id", "")
    encounter_id = state.get("encounter_id", "")
    citations = list(state.get("citations", []))
    summary = get_patient_summary(patient_id, encounter_id)
    citations.append({
        "source_type": summary["emr_source"],
        "source_id": summary["emr_source_id"],
        "summary": "患者病历摘要",
    })
    citations.append({
        "source_type": summary["his_source"],
        "source_id": summary["his_source_id"],
        "summary": "患者就诊信息",
    })
    return {
        "patient_summary": {"emr": summary["emr"], "his": summary["his"]},
        "citations": citations,
    }


def run_qc_rules_node(state: dict) -> dict:
    patient_id = state.get("patient_id", "")
    encounter_id = state.get("encounter_id", "")
    citations = list(state.get("citations", []))
    qc = run_qc_rules(patient_id, encounter_id)
    for result in qc["rule_results"]:
        citations.append({
            "source_type": result["source_system"],
            "source_id": "",
            "summary": result.get("risk", ""),
        })
    return {
        "rule_results": qc["rule_results"],
        "quality_issues": qc["quality_issues"],
        "citations": citations,
    }


def build_qc_report_node(state: dict) -> dict:
    quality_issues = state.get("quality_issues", [])
    qc_recommendation = build_qc_report(quality_issues)
    return {"qc_recommendation": qc_recommendation}
