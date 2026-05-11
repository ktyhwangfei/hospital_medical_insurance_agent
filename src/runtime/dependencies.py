from src.adapters.ports import (
    BillingPort,
    DrgDipPort,
    EmrPort,
    HisPort,
    InsuranceInterfacePort,
    MedicalRecordPort,
    PreAuditPort,
)
from src.config.adapters import get_adapter_impl


_insurance_adapter: InsuranceInterfacePort | None = None
_billing_adapter: BillingPort | None = None
_his_adapter: HisPort | None = None
_emr_adapter: EmrPort | None = None
_pre_audit_adapter: PreAuditPort | None = None
_drg_dip_adapter: DrgDipPort | None = None
_medical_record_adapter: MedicalRecordPort | None = None


def get_insurance_adapter() -> InsuranceInterfacePort:
    global _insurance_adapter
    if _insurance_adapter is not None:
        return _insurance_adapter
    impl = get_adapter_impl("insurance_interface")
    if impl == "memory":
        from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
        _insurance_adapter = InMemoryInsuranceInterfaceAdapter()
        return _insurance_adapter
    raise ValueError(f"Unknown insurance_interface implementation: {impl}")


def get_billing_adapter() -> BillingPort:
    global _billing_adapter
    if _billing_adapter is not None:
        return _billing_adapter
    impl = get_adapter_impl("billing")
    if impl == "memory":
        from src.adapters.billing.in_memory import InMemoryBillingAdapter
        _billing_adapter = InMemoryBillingAdapter()
        return _billing_adapter
    raise ValueError(f"Unknown billing implementation: {impl}")


def get_his_adapter() -> HisPort:
    global _his_adapter
    if _his_adapter is not None:
        return _his_adapter
    impl = get_adapter_impl("his")
    if impl == "memory":
        from src.adapters.his.in_memory import InMemoryHisAdapter
        _his_adapter = InMemoryHisAdapter()
        return _his_adapter
    raise ValueError(f"Unknown his implementation: {impl}")


def get_emr_adapter() -> EmrPort:
    global _emr_adapter
    if _emr_adapter is not None:
        return _emr_adapter
    impl = get_adapter_impl("emr")
    if impl == "memory":
        from src.adapters.emr.in_memory import InMemoryEmrAdapter
        _emr_adapter = InMemoryEmrAdapter()
        return _emr_adapter
    raise ValueError(f"Unknown emr implementation: {impl}")


def get_pre_audit_adapter() -> PreAuditPort:
    global _pre_audit_adapter
    if _pre_audit_adapter is not None:
        return _pre_audit_adapter
    impl = get_adapter_impl("pre_audit")
    if impl == "memory":
        from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter
        _pre_audit_adapter = InMemoryPreAuditAdapter()
        return _pre_audit_adapter
    raise ValueError(f"Unknown pre_audit implementation: {impl}")


def get_drg_dip_adapter() -> DrgDipPort:
    global _drg_dip_adapter
    if _drg_dip_adapter is not None:
        return _drg_dip_adapter
    impl = get_adapter_impl("drg_dip")
    if impl == "memory":
        from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
        _drg_dip_adapter = InMemoryDrgDipAdapter()
        return _drg_dip_adapter
    raise ValueError(f"Unknown drg_dip implementation: {impl}")


def _reset_adapters() -> None:
    """Reset all adapter singletons (for testing only)."""
    global _insurance_adapter, _billing_adapter, _his_adapter, _emr_adapter
    global _pre_audit_adapter, _drg_dip_adapter, _medical_record_adapter
    _insurance_adapter = None
    _billing_adapter = None
    _his_adapter = None
    _emr_adapter = None
    _pre_audit_adapter = None
    _drg_dip_adapter = None
    _medical_record_adapter = None


def get_medical_record_adapter() -> MedicalRecordPort:
    global _medical_record_adapter
    if _medical_record_adapter is not None:
        return _medical_record_adapter
    impl = get_adapter_impl("medical_record")
    if impl == "memory":
        from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
        _medical_record_adapter = InMemoryMedicalRecordAdapter()
        return _medical_record_adapter
    raise ValueError(f"Unknown medical_record implementation: {impl}")
