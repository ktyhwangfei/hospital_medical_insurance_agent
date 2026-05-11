import os

_ADAPTER_IMPL_DEFAULTS: dict[str, str] = {
    "insurance_interface": "memory",
    "billing": "memory",
    "his": "memory",
    "emr": "memory",
    "pre_audit": "memory",
    "drg_dip": "memory",
    "medical_record": "memory",
}

_ADAPTER_ENV_VARS: dict[str, str] = {
    "insurance_interface": "ADAPTER_INSURANCE_IMPL",
    "billing": "ADAPTER_BILLING_IMPL",
    "his": "ADAPTER_HIS_IMPL",
    "emr": "ADAPTER_EMR_IMPL",
    "pre_audit": "ADAPTER_PRE_AUDIT_IMPL",
    "drg_dip": "ADAPTER_DRG_DIP_IMPL",
    "medical_record": "ADAPTER_MEDICAL_RECORD_IMPL",
}


def get_adapter_impl(port_name: str) -> str:
    env_var = _ADAPTER_ENV_VARS.get(port_name)
    if env_var:
        value = os.getenv(env_var)
        if value is not None:
            return value
    return _ADAPTER_IMPL_DEFAULTS.get(port_name, "memory")
