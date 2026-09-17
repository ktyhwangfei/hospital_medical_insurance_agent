"""院区隔离接缝测试：语义绑定不得跨院区使用（fail-closed）。"""

from __future__ import annotations

import pytest

from src.semantic_layer.guard import HospitalScopeViolationError, assert_hospital_scope
from src.semantic_layer.models import SemanticDataset


def _dataset(code: str, hospital_code: str = "") -> SemanticDataset:
    return SemanticDataset(
        dataset_code=code,
        object_code="obj_demo",
        datasource_id="bjybdb",
        hospital_code=hospital_code,
        table_name="t_demo",
        name=code,
    )


def test_platform_default_binding_allowed_everywhere() -> None:
    assert_hospital_scope([_dataset("ds_common")])


def test_hospital_binding_allowed_in_own_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_HOSPITAL_CODE", "HOSP-A")
    assert_hospital_scope([_dataset("ds_a", "HOSP-A")])


def test_hospital_binding_rejected_in_other_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_HOSPITAL_CODE", "HOSP-B")
    with pytest.raises(HospitalScopeViolationError) as excinfo:
        assert_hospital_scope([_dataset("ds_a", "HOSP-A")])
    assert "HOSP-A" in str(excinfo.value) and "HOSP-B" in str(excinfo.value)
