"""验证所有适配器端口（Protocol）定义正确，且与现有 InMemory 实现兼容。"""

from src.adapters.billing.in_memory import InMemoryBillingAdapter
from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.emr.in_memory import InMemoryEmrAdapter
from src.adapters.his.in_memory import InMemoryHisAdapter
from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.ports.billing import BillingPort
from src.adapters.ports.drg_dip import DrgDipPort
from src.adapters.ports.emr import EmrPort
from src.adapters.ports.his import HisPort
from src.adapters.ports.insurance_interface import InsuranceInterfacePort
from src.adapters.ports.medical_record import MedicalRecordPort
from src.adapters.ports.pre_audit import PreAuditPort
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter


class TestPortContracts:
    """验证所有 Port 协议可以被对应的 InMemory 适配器满足。"""

    def test_insurance_interface_port(self):
        adapter = InMemoryInsuranceInterfaceAdapter()
        assert isinstance(adapter, InsuranceInterfacePort)
        result = adapter.query_transaction("P001", "E001")
        assert result.status.value == "success"

    def test_billing_port(self):
        adapter = InMemoryBillingAdapter()
        assert isinstance(adapter, BillingPort)
        result = adapter.query_billing_status("P001", "E001")
        assert result.status.value == "success"

    def test_billing_port_exposes_partial_refund_preview(self):
        assert hasattr(BillingPort, "preview_partial_refund")

    def test_his_port(self):
        adapter = InMemoryHisAdapter()
        assert isinstance(adapter, HisPort)
        result = adapter.query_orders("P001", "E001")
        assert result.status.value == "success"

    def test_emr_port(self):
        adapter = InMemoryEmrAdapter()
        assert isinstance(adapter, EmrPort)
        result = adapter.query_record_summary("P001", "E001")
        assert result.status.value == "success"

    def test_pre_audit_port(self):
        adapter = InMemoryPreAuditAdapter()
        assert isinstance(adapter, PreAuditPort)
        result = adapter.query_audit_result("P001", "E001")
        assert result.status.value == "success"

    def test_drg_dip_port(self):
        adapter = InMemoryDrgDipAdapter()
        assert isinstance(adapter, DrgDipPort)
        result = adapter.query_group_result("P001", "E001")
        assert result.status.value == "success"

    def test_medical_record_port(self):
        adapter = InMemoryMedicalRecordAdapter()
        assert isinstance(adapter, MedicalRecordPort)
        result = adapter.query_homepage("P001", "E001")
        assert result.status.value == "success"


class TestPortImports:
    """验证所有 Port 可以从 __init__.py 正常导出。"""

    def test_all_ports_exported(self):
        from src.adapters.ports import (
            BillingPort as BP,
            DrgDipPort as DP,
            EmrPort as EP,
            HisPort as HP,
            InsuranceInterfacePort as IP,
            MedicalRecordPort as MP,
            PreAuditPort as PP,
        )
        assert BP is BillingPort
        assert DP is DrgDipPort
        assert EP is EmrPort
        assert HP is HisPort
        assert IP is InsuranceInterfacePort
        assert MP is MedicalRecordPort
        assert PP is PreAuditPort
