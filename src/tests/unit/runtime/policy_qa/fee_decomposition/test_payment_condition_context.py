import json
from types import SimpleNamespace

import pytest

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus
from src.adapters.data_supply import payment_condition_queries as queries
from src.runtime.policy_qa.fee_decomposition.payment_condition_context import (
    attach_payment_condition_context, build_payment_condition_context)
from src.runtime.policy_qa.fee_decomposition.model_explanation import build_model_input, explain_decomposition
from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic


def make_result():
    return SettlementDecompositionResult.model_validate(dict(
        settlement_ref="settlement:test", profile=dict(insurance_type="employee", medical_category="outpatient"),
        execution_status="partial", reconciliation_status="not_verifiable", fields=[],
        coverage=dict(target_field_count=0, independently_explained_count=0, amount_reconciled_count=0, observed_only_count=0),
        answer_constraints=dict(may_claim_full_explanation=False),
        fee_items=[dict(line_id="1", item_code="DRUG", item_name="测试药", total_fee="33", observed_in_scope="29.7", observed_out_scope="3.3")]))


def row(**overrides):
    return {"line_id": "1", "item_code": "DRUG", "catalog_code": "DRUG", "recipe_ref": "r1",
            "bz": "限胃肠镜检查和腹部影像学检查", "catalog_source": "药品目录",
            "effective_from": "2026-01-01", "effective_to": "2026-12-31",
            "fee_date": "2026-04-17", "date_basis": "settlement_date_fallback",
            "specification": "30ml", "unit": "瓶", "usage": "口服", **overrides}


def build(source=None, diagnoses=None, **overrides):
    kwargs = dict(catalog_available=True, diagnosis_available=True, ambiguous=False,
                  hospital_level="02", hospital_level_name="三级", source_hash="hash", read_at="time")
    kwargs.update(overrides)
    return build_payment_condition_context(source if source is not None else row(), diagnoses or [], **kwargs)


def test_only_same_prescription_diagnoses_are_associated_when_recipe_known():
    context = build(diagnoses=[
        {"recipe_ref": "r1", "diagnosis_code": "R19.4", "diagnosis_name": "大便习惯改变"},
        {"recipe_ref": "r2", "diagnosis_code": "K27.4", "diagnosis_name": "其他处方诊断"}])
    assert len(context.diagnoses) == 1
    assert context.diagnoses[0].association == "same_prescription"
    assert context.diagnoses[0].name == "大便习惯改变"
    assert context.hospital_level_name == "三级"
    assert context.symptoms is None
    assert context.symptoms_status == "not_available_in_current_source"
    assert context.clinical_conditions_verified is False


def test_missing_recipe_is_labeled_same_settlement_not_same_drug():
    context = build(row(recipe_ref=None), [{"recipe_ref": "r2", "diagnosis_name": "诊断"}])
    assert context.diagnoses[0].association == "same_settlement"


def test_placeholder_is_visible_as_placeholder_not_noncompliance():
    context = build(diagnoses=[{"recipe_ref": "r1", "diagnosis_code": "01", "diagnosis_name": "1"}])
    assert context.diagnosis_status == "placeholder"
    assert context.diagnoses[0].is_placeholder
    assert not context.clinical_conditions_verified


def test_catalog_failure_keeps_available_bill_diagnoses_without_claiming_prescription_link():
    context = build({}, [{"recipe_ref": "r1", "diagnosis_code": "K27.4", "diagnosis_name": "消化性溃疡出血"}],
                    catalog_available=False)
    assert context.catalog_status == "unavailable" and context.bz is None
    assert context.diagnosis_status == "recorded"
    assert context.diagnoses[0].association == "same_settlement"


@pytest.mark.parametrize("source,kwargs,status", [
    (row(bz=None), {}, "unique"),
    (row(catalog_code=None, bz="不能使用的旧文本"), {}, "not_found"),
    (row(), {"ambiguous": True}, "ambiguous"),
    (row(), {"catalog_available": False}, "unavailable"),
])
def test_empty_ambiguous_or_unavailable_note_is_not_borrowed(source, kwargs, status):
    context = build(source, **kwargs)
    assert context.catalog_status == status
    assert context.bz is None


def test_attachment_does_not_change_money_and_ambiguous_rows_do_not_pick_first(monkeypatch):
    original = make_result()
    data = dict(catalog_rows=[row(), row(bz="第二条冲突备注")], diagnosis_rows=[],
                catalog_available=True, diagnosis_available=True)
    monkeypatch.setattr(queries, "load_payment_condition_rows", lambda *a, **k:
        AdapterCallResult(status=AdapterCallStatus.SUCCESS, source_system="test", capability="test", data=data))
    result = attach_payment_condition_context(original, object(), "bill", special=False,
        hospital_level="02", hospital_level_name="三级")
    context = result.fee_items[0].payment_condition_context
    assert context.catalog_status == "ambiguous" and context.bz is None
    assert result.model_dump(exclude={"fee_items": {"__all__": {"payment_condition_context"}}}) == original.model_dump()


def test_unverified_line_keeps_context_through_projection_and_actual_model_messages(monkeypatch):
    original = make_result()
    original.fee_items[0].payment_condition_context = build(diagnoses=[
        {"recipe_ref": "r1", "diagnosis_code": "R19.4", "diagnosis_name": "大便习惯改变"}])
    from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation
    original.fee_items.append(FeeItemExplanation(line_id="2", item_name="电子胃镜检查", item_type="诊疗项目", total_fee="410"))
    from src.runtime.api.policy_qa_routes import _public_text
    public = FeeDecompositionPublic.model_validate(to_public_contract_dict(
        original, summary_text="", summary_source="template", sanitize=_public_text))
    payload = build_model_input(public, "第1行测试药为什么有自付")
    assert not payload.decomposition.fee_items[0].explainable
    assert payload.decomposition.fee_items[0].payment_condition_context.bz == row()["bz"]
    captured = []
    def generate(self, **kwargs):
        captured.append(kwargs)
        return SimpleNamespace(content="第1行测试药原单费用33元。目录限定用于相关检查；本处方有大便习惯改变记录，仍需核对检查用途，不能由此确定本次自付原因。")
    monkeypatch.setattr("src.model_service.gateway.ModelGateway.generate", generate)
    monkeypatch.setenv("FEE_EXPLANATION_MODE", "structured")
    result = explain_decomposition(public, "第1行测试药为什么有自付")
    assert result.used_model
    data = json.loads(captured[0]["messages"][1].content)
    context = data["decomposition"]["fee_items"][0]["payment_condition_context"]
    assert context["bz"] == row()["bz"]
    assert context["diagnoses"][0]["name"] == "大便习惯改变"
    assert context["hospital_level_name"] == "三级" and context["symptoms"] is None
    assert len(data["decomposition"]["fee_items"]) == 1
    assert data["billed_items"][1]["item_name"] == "电子胃镜检查"
    assert data["billed_items"][1]["association"] == "same_settlement_charge_only"
    assert "410" not in json.dumps(data["billed_items"])
    assert "不是已核实的临床条件" in captured[0]["messages"][0].content
