"""费用分解入口集成单元测试（Issue #78 设计 §12/§13，步骤 5）。

覆盖：
- 门控：取整模式未配置/非法、院区码未配置、provider 无连接工厂 → None（fail-closed）；
- profile 解析：仅精确匹配（职工+普通门诊）→ (employee, outpatient)，其余 None；
- 分解调用：连接关闭保证、异常返回 None、profile_resolver 透传；
- 模型润色：数字集合不变才采用（summary_source=model），新增数字/异常/空 → 回退模板。
"""
from __future__ import annotations

from types import SimpleNamespace

from src.adapters.base.models import (
    AdapterCallResult,
    AdapterCallStatus,
    DataQualityStatus,
)
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition import integration
from src.runtime.policy_qa.fee_decomposition.integration import (
    DecompositionPresentation,
    _resolve_profile_from_context,
    _resolve_special_profile_from_context,
    _rounding_mode_from_env,
    maybe_decompose_outpatient,
    maybe_decompose_special_outpatient,
    polish_summary,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
)
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    DecompositionOutcome,
    SettlementFactsItem,
    SettlementFactsView,
)


def _canned_facts() -> SettlementFactsView:
    return SettlementFactsView(
        chain="outpatient", identifier="T001", trade_date="2024-06-01",
        medical_category="11", insurance_type="3", person_type="11",
        hospital_level=None,
        items=[SettlementFactsItem(label="费用总金额", value="100.00")],
        payment_items=[SettlementFactsItem(label="个人账户支付", value="0.00")],
    )


def _canned_result() -> SettlementDecompositionResult:
    return SettlementDecompositionResult(
        settlement_ref="settlement:T001",
        profile=DecompositionProfile(insurance_type="employee", medical_category="outpatient"),
        execution_status="complete",
        reconciliation_status="matched",
        fields=[FieldExplanationModel(
            field_code="T_FeeAll", label="总费用", check_type="detail_aggregation",
            check_status="matched", observed_amount="100.00",
            calculated_amount="100.00", difference="0.00",
            explanation_level="amount_reconciled")],
        coverage=CoverageSummary(
            target_field_count=1, independently_explained_count=0,
            amount_reconciled_count=1, observed_only_count=0),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=True),
    )


def _enable_gate(monkeypatch):
    monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
    monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")


class _FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeProvider:
    def __init__(self, conn):
        self._conn = conn
        self._connect = lambda _db: conn


_EMPLOYEE_CONTEXT = SimpleNamespace(
    insurance_type="城镇职工基本医疗保险", service_type="普通门诊")


class TestGates:
    def test_rounding_mode_unset_disables(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
        assert maybe_decompose_outpatient(object(), "T001", _EMPLOYEE_CONTEXT) is None

    def test_hospital_code_unset_disables(self, monkeypatch):
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        assert maybe_decompose_outpatient(object(), "T001", _EMPLOYEE_CONTEXT) is None

    def test_invalid_rounding_mode_disables(self, monkeypatch):
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "bogus")
        assert _rounding_mode_from_env() is None

    def test_valid_rounding_mode(self, monkeypatch):
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
        assert _rounding_mode_from_env() is RoundingMode.HALF_UP

    def test_provider_without_connect_disables(self, monkeypatch):
        _enable_gate(monkeypatch)
        assert maybe_decompose_outpatient(object(), "T001", _EMPLOYEE_CONTEXT) is None


class TestProfileResolution:
    def test_exact_match(self):
        assert _resolve_profile_from_context(_EMPLOYEE_CONTEXT) == ("employee", "outpatient")

    def test_resident_insurance_matched(self):
        """Issue #80：城乡居民×普通门诊已注册映射到 resident 内核。"""
        ctx = SimpleNamespace(insurance_type="城乡居民基本医疗保险", service_type="普通门诊")
        assert _resolve_profile_from_context(ctx) == ("resident", "outpatient")

    def test_unregistered_insurance_not_matched(self):
        ctx = SimpleNamespace(insurance_type="离休统筹", service_type="普通门诊")
        assert _resolve_profile_from_context(ctx) is None

    def test_special_outpatient_not_matched(self):
        ctx = SimpleNamespace(
            insurance_type="城镇职工基本医疗保险", service_type="门诊特殊疾病")
        assert _resolve_profile_from_context(ctx) is None

    def test_missing_attributes_not_matched(self):
        assert _resolve_profile_from_context(SimpleNamespace()) is None
        assert _resolve_profile_from_context(None) is None


class TestSpecialProfileResolution:
    """门特组合 profile：ESP-CODE-001/002 待码表确认，未登记前恒 None（不升级）。"""

    def test_not_registered_yet(self):
        assert _resolve_special_profile_from_context(None) is None
        assert _resolve_special_profile_from_context(SimpleNamespace()) is None
        ctx = SimpleNamespace(
            insurance_type="城镇职工基本医疗保险", service_type="门诊特殊疾病")
        # 语义层字符串未确认前不得映射（签核后在 _SPECIAL_PROFILE_EXACT_MATCH 登记）
        assert _resolve_special_profile_from_context(ctx) is None


class TestDecomposeCall:
    def test_happy_path_with_profile_resolver(self, monkeypatch):
        _enable_gate(monkeypatch)
        conn = _FakeConn()
        captured = {}

        def fake_decompose(c, trade_no, hospital_code, rounding_mode, profile_resolver=None):
            captured.update(
                trade_no=trade_no, hospital_code=hospital_code,
                rounding_mode=rounding_mode, profile_resolver=profile_resolver)
            return DecompositionOutcome(_canned_result(), _canned_facts())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        monkeypatch.setattr(
            integration, "polish_summary", lambda text: (text, "template"))

        presentation = maybe_decompose_outpatient(
            _FakeProvider(conn), "T001", _EMPLOYEE_CONTEXT)

        assert isinstance(presentation, DecompositionPresentation)
        assert captured["trade_no"] == "T001"
        assert captured["hospital_code"] == "H001"
        assert captured["rounding_mode"] is RoundingMode.HALF_UP
        assert captured["profile_resolver"]({"any": "row"}) == ("employee", "outpatient")
        assert conn.closed is True
        assert "总费用" in presentation.summary_text
        assert presentation.summary_source == "template"
        # 结算事实侧车透传（1.2）
        assert presentation.settlement_facts is not None
        assert presentation.settlement_facts.identifier == "T001"
        assert presentation.settlement_facts.chain == "outpatient"

    def test_unmatched_profile_passes_none_resolver(self, monkeypatch):
        _enable_gate(monkeypatch)
        captured = {}

        def fake_decompose(_c, _t, _h, _r, profile_resolver=None):
            captured["profile_resolver"] = profile_resolver
            return DecompositionOutcome(_canned_result())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        monkeypatch.setattr(
            integration, "polish_summary", lambda text: (text, "template"))
        # 未注册组合（离休统筹）不映射 resolver，内核走 UNSUPPORTED_PROFILE，不猜测
        ctx = SimpleNamespace(insurance_type="离休统筹", service_type="普通门诊")

        assert maybe_decompose_outpatient(_FakeProvider(_FakeConn()), "T001", ctx)
        assert captured["profile_resolver"] is None

    def test_connect_failure_returns_none(self, monkeypatch):
        _enable_gate(monkeypatch)
        provider = SimpleNamespace(
            _connect=lambda _db: (_ for _ in ()).throw(ConnectionError("down")))
        assert maybe_decompose_outpatient(provider, "T001", _EMPLOYEE_CONTEXT) is None

    def test_decompose_failure_returns_none_and_closes_conn(self, monkeypatch):
        _enable_gate(monkeypatch)
        conn = _FakeConn()

        def boom(*_args, **_kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(integration, "decompose_outpatient_trade", boom)
        assert maybe_decompose_outpatient(
            _FakeProvider(conn), "T001", _EMPLOYEE_CONTEXT) is None
        assert conn.closed is True


def _locate_result(match_status: str) -> AdapterCallResult:
    """登记定位桩：仅携带消歧所需的 match_status。"""
    return AdapterCallResult(
        status=AdapterCallStatus.SUCCESS, source_system="test", capability="test",
        data={"match_status": match_status, "registration_row": None, "row_count": 0})


def _locate_failed() -> AdapterCallResult:
    return AdapterCallResult(
        status=AdapterCallStatus.FAILED, source_system="test", capability="test",
        data={}, data_quality=DataQualityStatus.MISSING, message="query failed")


def _stub_locates(monkeypatch, mz: AdapterCallResult,
                  resident_mz: AdapterCallResult | None = None) -> None:
    monkeypatch.setattr(integration, "locate_special_fixed_kidney_registration", lambda *args: _locate_result("not_found"))
    if mz.data.get("match_status") == "unique_match":
        mz = mz.model_copy(update={"data": {**mz.data, "registration_row": {"fund_type": "3", "yllb": "12"}}})
    if resident_mz is not None and resident_mz.data.get("match_status") == "unique_match":
        resident_mz = resident_mz.model_copy(update={"data": {**resident_mz.data, "registration_row": {"fund_type": "93", "yllb": "12"}}})
    monkeypatch.setattr(
        integration, "locate_special_mz_registration", lambda _conn, _djh: mz)
    monkeypatch.setattr(
        integration, "locate_special_mz_resident_registration",
        lambda _conn, _djh: resident_mz or _locate_result("not_found"))


class TestSpecialSuiteRouting:
    """Only employee/resident outpatient suites participate in routing."""

    def test_unsupported_registration_does_not_fall_back(self, monkeypatch):
        _enable_gate(monkeypatch)
        _stub_locates(monkeypatch, _locate_result("not_found"))
        conn = _FakeConn()
        called = []
        monkeypatch.setattr(integration, "decompose_special_mz_settlement",
                            lambda *a, **k: called.append("mz") or DecompositionOutcome(_canned_result()))
        monkeypatch.setattr(integration, "decompose_special_mz_resident_settlement",
                            lambda *a, **k: called.append("resident_mz") or DecompositionOutcome(_canned_result()))
        monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
        presentation = maybe_decompose_special_outpatient(
            _FakeProvider(conn), "604", SimpleNamespace())
        assert presentation.result.execution_status == "unavailable"
        assert presentation.result.uncertainties[0].code == "REGISTRATION_NOT_FOUND"
        assert called == []
        assert conn.closed is True

    def test_mz_unique_routes_to_mz_service(self, monkeypatch):
        _enable_gate(monkeypatch)
        _stub_locates(monkeypatch, _locate_result("unique_match"))
        conn = _FakeConn()
        captured = {}
        def fake_mz(c, djh, hospital_code, rounding_mode, **kwargs):
            captured.update(djh=djh, hospital_code=hospital_code,
                            rounding_mode=rounding_mode, **kwargs)
            return DecompositionOutcome(_canned_result())
        monkeypatch.setattr(integration, "decompose_special_mz_settlement", fake_mz)
        monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
        presentation = maybe_decompose_special_outpatient(
            _FakeProvider(conn), "567", SimpleNamespace())
        assert isinstance(presentation, DecompositionPresentation)
        assert captured["djh"] == "567"
        assert captured["hospital_code"] == "H001"
        assert captured["rounding_mode"] is RoundingMode.HALF_UP
        assert captured["profile"] == ("employee", "outpatient_special")
        assert captured["allow_observed_deductible"] is False
        assert conn.closed is True

    def test_resident_mz_unique_routes_to_resident_service(self, monkeypatch):
        _enable_gate(monkeypatch)
        _stub_locates(monkeypatch, _locate_result("not_found"), _locate_result("unique_match"))
        conn = _FakeConn()
        called = {}
        def fake_resident(c, djh, hospital_code, rounding_mode, **kwargs):
            called["resident_mz"] = (djh, kwargs)
            return DecompositionOutcome(_canned_result())
        monkeypatch.setattr(integration, "decompose_special_mz_resident_settlement", fake_resident)
        monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
        presentation = maybe_decompose_special_outpatient(
            _FakeProvider(conn), "688", SimpleNamespace())
        assert isinstance(presentation, DecompositionPresentation)
        assert called["resident_mz"][0] == "688"
        assert conn.closed is True

    def test_resident_mz_profile_mapped_when_context_confirmed(self, monkeypatch):
        _enable_gate(monkeypatch)
        _stub_locates(monkeypatch, _locate_result("not_found"), _locate_result("unique_match"))
        conn = _FakeConn()
        called = {}
        def fake_resident(c, djh, hospital_code, rounding_mode, **kwargs):
            called["resident_mz"] = (djh, kwargs)
            return DecompositionOutcome(_canned_result())
        monkeypatch.setattr(integration, "decompose_special_mz_resident_settlement", fake_resident)
        monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
        insurance, service = next(iter(integration._SPECIAL_PROFILE_MAP))
        context = SimpleNamespace(insurance_type=insurance, service_type=service)
        presentation = maybe_decompose_special_outpatient(_FakeProvider(conn), "688", context)
        assert isinstance(presentation, DecompositionPresentation)
        assert called["resident_mz"][1]["profile"] == ("resident", "outpatient_special")
        assert conn.closed is True

    def test_both_unique_is_ambiguous(self, monkeypatch):
        _enable_gate(monkeypatch)
        _stub_locates(monkeypatch, _locate_result("unique_match"), _locate_result("unique_match"))
        monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
        presentation = maybe_decompose_special_outpatient(
            _FakeProvider(_FakeConn()), "567", SimpleNamespace())
        assert presentation.result.uncertainties[0].code == "REGISTRATION_AMBIGUOUS"

    def test_within_suite_ambiguous_is_fail_closed(self, monkeypatch):
        _enable_gate(monkeypatch)
        _stub_locates(monkeypatch, _locate_result("ambiguous"))
        monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
        presentation = maybe_decompose_special_outpatient(
            _FakeProvider(_FakeConn()), "567", SimpleNamespace())
        assert presentation.result.uncertainties[0].code == "REGISTRATION_AMBIGUOUS"

    def test_unique_with_ambiguous_alternative_is_fail_closed(self, monkeypatch):
        _enable_gate(monkeypatch)
        monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
        for mz, resident in (("unique_match", "ambiguous"), ("ambiguous", "unique_match")):
            _stub_locates(monkeypatch, _locate_result(mz), _locate_result(resident))
            presentation = maybe_decompose_special_outpatient(
                _FakeProvider(_FakeConn()), "567", SimpleNamespace())
            assert presentation.result.execution_status == "unavailable"
            assert presentation.result.uncertainties[0].code == "REGISTRATION_AMBIGUOUS"

    def test_locate_read_failed_is_fail_closed(self, monkeypatch):
        _enable_gate(monkeypatch)
        _stub_locates(monkeypatch, _locate_failed(), _locate_result("unique_match"))
        monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
        presentation = maybe_decompose_special_outpatient(
            _FakeProvider(_FakeConn()), "567", SimpleNamespace())
        assert presentation.result.uncertainties[0].code == "READ_FAILED"


class TestSpecialDecomposeCall:
    def test_gates_unset_disables_all(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        assert maybe_decompose_special_outpatient(object(), "567", SimpleNamespace()) is None

    def test_provider_without_connect_disables(self, monkeypatch):
        _enable_gate(monkeypatch)
        assert maybe_decompose_special_outpatient(object(), "567", SimpleNamespace()) is None

    def test_connect_failure_returns_none(self, monkeypatch):
        _enable_gate(monkeypatch)
        provider = SimpleNamespace(_connect=lambda _db: (_ for _ in ()).throw(ConnectionError("down")))
        assert maybe_decompose_special_outpatient(provider, "567", SimpleNamespace()) is None


class TestPolishSummary:
    def test_model_unavailable_falls_back_to_template(self, monkeypatch):
        class BrokenGateway:
            def generate(self, **_kwargs):
                raise RuntimeError("model down")

        monkeypatch.setattr(
            "src.model_service.gateway.ModelGateway", BrokenGateway)
        text = "总费用 100.00 元，一致。"
        assert polish_summary(text) == (text, "template")

    def test_model_output_with_same_numbers_does_not_rewrite_financial_summary(self, monkeypatch):
        class OkGateway:
            def generate(self, **_kwargs):
                return SimpleNamespace(content="本次总费用为 100.00 元，核对一致。")

        monkeypatch.setattr("src.model_service.gateway.ModelGateway", OkGateway)
        text, source = polish_summary("总费用 100.00 元，一致。")
        assert source == "template"
        assert text == "总费用 100.00 元，一致。"

    def test_model_output_with_new_number_falls_back(self, monkeypatch):
        class EvilGateway:
            def generate(self, **_kwargs):
                return SimpleNamespace(content="总费用 100.00 元，报销比例 80%。")

        monkeypatch.setattr("src.model_service.gateway.ModelGateway", EvilGateway)
        text = "总费用 100.00 元，一致。"
        assert polish_summary(text) == (text, "template")

    def test_empty_model_output_falls_back(self, monkeypatch):
        class EmptyGateway:
            def generate(self, **_kwargs):
                return SimpleNamespace(content="")

        monkeypatch.setattr("src.model_service.gateway.ModelGateway", EmptyGateway)
        text = "总费用 100.00 元，一致。"
        assert polish_summary(text) == (text, "template")
