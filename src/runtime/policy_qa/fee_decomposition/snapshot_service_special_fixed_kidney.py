"""职工门特肾/肝肾移植抗排异定额独立快照服务。"""
from typing import Any

from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.settlement_facts import DecompositionOutcome
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_mz import decompose_special_mz_settlement


def decompose_special_fixed_kidney_settlement(conn: Any, djh: str, hospital_code: str,
        rounding_mode: RoundingMode, *, profile: tuple[str, str] | None = None,
        allow_observed_deductible: bool = False) -> DecompositionOutcome:
    outcome = decompose_special_mz_settlement(conn, djh, hospital_code, rounding_mode,
        profile=profile, allow_observed_deductible=allow_observed_deductible, _kidney_fixed=True)
    # 事实侧车透传；仅覆盖算法版本标识
    return DecompositionOutcome(
        outcome.result.model_copy(update={"algorithm_version": "employee_special_fixed_kidney_v1"}),
        outcome.facts)
