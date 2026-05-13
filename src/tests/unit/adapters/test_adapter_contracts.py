from src.adapters.base.models import AdapterCallContext, AdapterCallResult, AdapterCallStatus, AdapterError, DataQualityStatus
from src.adapters.base.service import adapter_citation, failed_result, successful_result
from src.adapters.billing.in_memory import InMemoryBillingAdapter
from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.emr.in_memory import InMemoryEmrAdapter
from src.adapters.his.in_memory import InMemoryHisAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter
from src.shared.schemas.contracts import Citation


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

    assert result.status == AdapterCallStatus.SUCCESS
    assert result.data_quality == DataQualityStatus.COMPLETE
    assert isinstance(citation, Citation)
    assert citation.source_type == "insurance_interface"
    assert citation.source_id == "P001:E001"


def test_failed_adapter_result_has_error_and_preserves_input():
    context = AdapterCallContext(workflow_id="wf-001", step_id="query_emr", user_id="U001", role="doctor", input_summary={"patient_id": "P001"})
    result = failed_result(context=context, source_system="emr", capability="query_record_summary", error_type="timeout", message="病历系统超时")

    assert result.status == AdapterCallStatus.FAILED
    assert result.error_type == "timeout"
    assert result.message == "病历系统超时"
    assert result.input_summary == {"patient_id": "P001"}


def test_adapter_error_carries_type_and_source():
    error = AdapterError("connection refused", error_type="network", source_system="his")

    assert str(error) == "connection refused"
    assert error.error_type == "network"
    assert error.source_system == "his"


def test_adapter_citation_falls_back_to_capability_when_no_record_id():
    context = AdapterCallContext()
    result = failed_result(context=context, source_system="emr", capability="query_record_summary", error_type="timeout", message="超时")

    citation = adapter_citation(result)

    assert citation.source_id == "query_record_summary"
    assert citation.summary == "超时"


def test_adapter_citation_falls_back_to_capability_when_no_message():
    context = AdapterCallContext()
    result = successful_result(
        context=context,
        source_system="insurance_interface",
        source_record_id="P001:E001",
        capability="query_transaction",
        data={"status": "ok"},
    )

    citation = adapter_citation(result)

    assert citation.summary == "query_transaction"


def test_in_memory_adapters_return_adapter_call_result():
    adapters = [
        InMemoryBillingAdapter().query_billing_status("P001", "E001"),
        InMemoryDrgDipAdapter().query_group_result("P001", "E001"),
        InMemoryEmrAdapter().query_record_summary("P001", "E001"),
        InMemoryHisAdapter().query_orders("P001", "E001"),
        InMemoryMedicalRecordAdapter().query_homepage("P001", "E001"),
        InMemoryPreAuditAdapter().query_audit_result("P001", "E001"),
    ]

    assert all(isinstance(result, AdapterCallResult) for result in adapters)
    assert {result.status for result in adapters} == {AdapterCallStatus.SUCCESS}
