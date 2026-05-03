from src.adapters.base.models import AdapterCallContext, AdapterCallResult, DataQualityStatus
from src.adapters.base.service import adapter_citation, failed_result, successful_result


def test_successful_adapter_result_contains_source_and_citation():
    context = AdapterCallContext(workflow_id="wf-001", step_id="query_transaction", user_id="U001", role="medical_office")
    result = successful_result(
        context=context,
        source_system="insurance_interface",
        source_record_id="P001:E001",
        capability="query_transaction",
        data={"settlement_status": "failed"},
    )

    citation = adapter_citation(result)

    assert result.status == "success"
    assert result.data_quality == DataQualityStatus.COMPLETE
    assert citation["source_type"] == "insurance_interface"
    assert citation["source_id"] == "P001:E001"


def test_failed_adapter_result_has_error_and_no_sensitive_input():
    context = AdapterCallContext(workflow_id="wf-001", step_id="query_emr", user_id="U001", role="doctor", input_summary={"patient_id": "P001"})
    result = failed_result(context=context, source_system="emr", capability="query_record_summary", error_type="timeout", message="病历系统超时")

    assert result.status == "failed"
    assert result.error_type == "timeout"
    assert result.message == "病历系统超时"
    assert "name" not in result.input_summary
