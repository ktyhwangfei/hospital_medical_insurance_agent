"""快照服务→公开投影→目标裁剪→模型消息，四链路均保留原始条件事实。"""
import json
from types import SimpleNamespace

import pytest

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus
from src.adapters.data_supply import payment_condition_queries
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.api.policy_qa_routes import _public_text
from src.runtime.policy_qa.fee_decomposition.model_explanation import explain_decomposition
from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic


@pytest.mark.parametrize("insurance,special", [("employee", False), ("resident", False), ("employee", True), ("resident", True)])
def test_four_snapshot_services_deliver_condition_context_to_model(monkeypatch, insurance, special):
    def ok(data):
        return AdapterCallResult(status=AdapterCallStatus.SUCCESS, source_system="test", capability="test", data={"row_count": 1, **data})
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_snapshot_service import _service_conn
    if special:
        from src.runtime.policy_qa.fee_decomposition import snapshot_service_special_mz as employee
        from src.runtime.policy_qa.fee_decomposition import snapshot_service_special_mz_resident as resident
        service = employee if insurance == "employee" else resident
        registration = dict(djh="42", fund_type="3" if insurance == "employee" else "91", yllb="12")
        locate = "locate_special_mz_registration" if insurance == "employee" else "locate_special_mz_resident_registration"
        monkeypatch.setattr(service, locate, lambda *a: ok(dict(match_status="unique_match", registration_row=registration)))
        monkeypatch.setattr(service, "load_special_mz_settlement", lambda *a: ok(dict(settlement_row=dict(djh="42", jyrq="2026-04-17", fyfs="0"))))
        monkeypatch.setattr(service, "load_special_mz_fee_items", lambda *a: ok(dict(item_rows=[
            dict(xh="L1", xmdm="D001", xmmc="测试药", zje="33", ybnje="29.7", ybwje="3.3", grziftw="3.3") ])))
        if insurance == "employee":
            monkeypatch.setattr(service, "load_special_institution_level", lambda *a: ok(dict(h_level="02")))
            monkeypatch.setattr(service, "load_special_mz_cycle", lambda *a: ok(dict(cycle_row=None)))
            monkeypatch.setattr(service, "load_special_mz_annual", lambda *a: ok(dict(annual_row=None)))
        else:
            from src.runtime.policy_qa.fee_decomposition import special_catalog_service
            # 目录金额分解缺资料的早退路径仍须交付新增的原始条件事实。
            monkeypatch.setattr(special_catalog_service, "read_special_catalog", lambda *a:
                SimpleNamespace(error="缺金额计算资料"))
        run = service.decompose_special_mz_settlement if insurance == "employee" else service.decompose_special_mz_resident_settlement
        conn = object()
        args = (conn, "42", "H001", RoundingMode.HALF_UP)
        kwargs = dict(profile=(insurance, "outpatient_special"))
    else:
        from src.runtime.policy_qa.fee_decomposition.snapshot_service import decompose_outpatient_trade
        run = decompose_outpatient_trade
        conn = _service_conn()
        args = (conn, "T001", "H001", RoundingMode.HALF_UP)
        kwargs = dict(profile_resolver=lambda _: (insurance, "outpatient"))
    monkeypatch.setattr(payment_condition_queries, "load_payment_condition_rows", lambda *a, **k:
        ok(dict(catalog_available=True, diagnosis_available=True, catalog_rows=[
            dict(line_id="L1", item_code="D001", catalog_code="D001", bz="限无法口服者", recipe_ref="r1")],
            diagnosis_rows=[dict(recipe_ref="r1", diagnosis_code="01", diagnosis_name="1")])))
    outcome = run(*args, **kwargs)
    assert outcome.result.fee_items[0].payment_condition_context.bz == "限无法口服者"
    public = FeeDecompositionPublic.model_validate(to_public_contract_dict(
        outcome.result, summary_text="", summary_source="template", settlement_facts=outcome.facts, sanitize=_public_text))
    calls = []
    def generate(self, **kw):
        calls.append(kw)
        return SimpleNamespace(content="第1行按本单费用记录列示；目录限定无法口服者，现有诊断为占位值，尚不能说明是否符合，也不能据此确定自付原因。")
    monkeypatch.setattr("src.model_service.gateway.ModelGateway.generate", generate)
    monkeypatch.setenv("FEE_EXPLANATION_MODE", "structured")
    explanation = explain_decomposition(public, "第1行为什么自付")
    assert explanation.used_model
    payload = json.loads(calls[0]["messages"][1].content)
    context = payload["decomposition"]["fee_items"][0]["payment_condition_context"]
    assert context["bz"] == "限无法口服者" and context["diagnosis_status"] == "placeholder"
    assert not context["clinical_conditions_verified"]
    assert "source_hash" not in context and "read_at" not in context
