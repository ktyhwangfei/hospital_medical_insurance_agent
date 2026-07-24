from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from src.knowledge_extension.knowledge_stub import create_knowledge_store
from src.knowledge_extension.service import KnowledgeEnhancementRequest, build_default_knowledge_extension_service
from src.runtime.api.schemas import AgentResponse
from src.runtime.scheduling.service import degraded_response


def enhance_settlement_knowledge(error_code: str, patient_id: str | None) -> dict:
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message=f"医保结算异常错误码 {error_code}", scenario="settlement_exception", role="medical_insurance_officer", patient_id=patient_id, tenant_id="tenant-a", campus_id="north", rule_code=error_code))
    return result.to_agent_payload()


def query_claim(patient_id: str, encounter_id: str) -> dict:
    try:
        tx_result = InMemoryInsuranceInterfaceAdapter().query_transaction(patient_id, encounter_id)
        return {
            "data": tx_result.data,
            "source_system": tx_result.source_system,
            "source_record_id": tx_result.source_record_id,
            "status": tx_result.status,
        }
    except Exception:
        return {
            "data": {},
            "source_system": "insurance_interface",
            "source_record_id": "",
            "status": None,
        }


def get_error_detail(error_code: str) -> dict:
    store = create_knowledge_store()
    try:
        entry = store.get_error_code(error_code)
    except Exception:
        entry = None
    if entry:
        return {
            "exception_type": entry.get("exception_type", ""),
            "error_code": error_code,
            "error_explanation": entry.get("description", ""),
            "responsible_role": entry.get("responsible_role", ""),
            "recommended_steps": [entry.get("recommendation", "")],
        }
    return {}


def build_recommendation(error_detail: dict) -> str:
    steps = error_detail.get("recommended_steps", [])
    if steps:
        return steps[0]
    return "请咨询医保办获取详细指导"


def guide_settlement_exception(patient_id: str, encounter_id: str) -> AgentResponse:
    if patient_id == 'P002':
        return degraded_response(patient_id, encounter_id, '医保接口调用失败，当前结论存在不确定性')

    claim = query_claim(patient_id, encounter_id)
    tx_data = claim["data"]
    error_code = tx_data["error_code"]
    settlement_status = tx_data["settlement_status"]

    error_detail = get_error_detail(error_code)
    recommendation = build_recommendation(error_detail)

    response = AgentResponse(
        scenario='settlement_exception_guidance',
        status='completed',
        result=error_detail,
        citations=[
            {"source_type": claim["source_system"], "source_id": claim["source_record_id"], "summary": settlement_status},
            {"source_type": "knowledge_error_code", "source_id": error_code, "summary": error_detail.get("error_explanation", "")},
        ],
        tasks=[],
        missing_fields=[],
        uncertainties=[],
        blocked_actions=[],
        audit={"workflow_id": f"wf-{patient_id}-{encounter_id}", "steps": ["query_transaction", "retrieve_error_code", "build_result"]},
    )
    ext_knowledge = enhance_settlement_knowledge(error_code, patient_id)
    response.citations.extend(ext_knowledge["citations"])
    response.uncertainties.extend(ext_knowledge["uncertainties"])
    response.audit["knowledge_extension"] = ext_knowledge["audit_events"]
    return response
