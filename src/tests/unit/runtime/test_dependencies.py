"""Tests for runtime dependency injection."""
import os

import pytest

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
from src.runtime.dependencies import (
    _reset_adapters,
    get_billing_adapter,
    get_drg_dip_adapter,
    get_emr_adapter,
    get_his_adapter,
    get_insurance_adapter,
    get_medical_record_adapter,
    get_pre_audit_adapter,
)


class TestAdapterDependencies:

    def test_get_insurance_adapter_returns_valid_instance(self):
        adapter = get_insurance_adapter()
        assert isinstance(adapter, InsuranceInterfacePort)
        result = adapter.query_transaction("P001", "E001")
        assert result is not None

    def test_get_billing_adapter_returns_valid_instance(self):
        adapter = get_billing_adapter()
        assert isinstance(adapter, BillingPort)
        result = adapter.query_billing_status("P001", "E001")
        assert result is not None

    def test_get_his_adapter_returns_valid_instance(self):
        adapter = get_his_adapter()
        assert isinstance(adapter, HisPort)
        result = adapter.query_orders("P001", "E001")
        assert result is not None

    def test_get_emr_adapter_returns_valid_instance(self):
        adapter = get_emr_adapter()
        assert isinstance(adapter, EmrPort)
        result = adapter.query_record_summary("P001", "E001")
        assert result is not None

    def test_get_pre_audit_adapter_returns_valid_instance(self):
        adapter = get_pre_audit_adapter()
        assert isinstance(adapter, PreAuditPort)
        result = adapter.query_audit_result("P001", "E001")
        assert result is not None

    def test_get_drg_dip_adapter_returns_valid_instance(self):
        adapter = get_drg_dip_adapter()
        assert isinstance(adapter, DrgDipPort)
        result = adapter.query_group_result("P001", "E001")
        assert result is not None

    def test_get_medical_record_adapter_returns_valid_instance(self):
        adapter = get_medical_record_adapter()
        assert isinstance(adapter, MedicalRecordPort)
        result = adapter.query_homepage("P001", "E001")
        assert result is not None

    def test_adapters_are_singletons(self):
        a1 = get_insurance_adapter()
        a2 = get_insurance_adapter()
        assert a1 is a2

    def test_adapter_impl_defaults_to_memory(self):
        assert get_adapter_impl("insurance_interface") == "memory"


class TestAdapterConfiguration:

    def test_env_override_insurance_adapter(self):
        os.environ["ADAPTER_INSURANCE_IMPL"] = "custom"
        try:
            assert get_adapter_impl("insurance_interface") == "custom"
        finally:
            os.environ.pop("ADAPTER_INSURANCE_IMPL", None)
        # After env var is popped, default should be restored
        assert get_adapter_impl("insurance_interface") == "memory"

    def test_all_ports_have_memory_default(self):
        for port_name in [
            "insurance_interface",
            "billing",
            "his",
            "emr",
            "pre_audit",
            "drg_dip",
            "medical_record",
        ]:
            assert get_adapter_impl(port_name) == "memory", f"{port_name} should default to memory"

    def test_unknown_port_defaults_to_memory(self):
        assert get_adapter_impl("nonexistent_port") == "memory"

    def test_unknown_impl_raises_value_error(self):
        _reset_adapters()
        os.environ["ADAPTER_INSURANCE_IMPL"] = "nonexistent"
        try:
            with pytest.raises(ValueError, match="Unknown insurance_interface implementation"):
                get_insurance_adapter()
        finally:
            os.environ.pop("ADAPTER_INSURANCE_IMPL", None)
