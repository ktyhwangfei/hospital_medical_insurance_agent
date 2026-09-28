"""费用分解入口集成单元测试（Issue #78 设计 §12/§13，步骤 5）。

覆盖：
- 门控：取整模式未配置/非法、院区码未配置、provider 无连接工厂 → None（fail-closed）；
- profile 解析：仅精确匹配（职工+普通门诊）→ (employee, outpatient)，其余 None；
- 分解调用：连接关闭保证、异常返回 None、profile_resolver 透传；
- 模型润色：数字集合不变才采用（summary_source=model），新增数字/异常/空 → 回退模板。
"""
from __future__ import annotations

from types import SimpleNamespace

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

    def test_resident_insurance_not_matched(self):
        ctx = SimpleNamespace(insurance_type="城乡居民基本医疗保险", service_type="普通门诊")
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
            return _canned_result()

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

    def test_unmatched_profile_passes_none_resolver(self, monkeypatch):
        _enable_gate(monkeypatch)
        captured = {}

        def fake_decompose(_c, _t, _h, _r, profile_resolver=None):
            captured["profile_resolver"] = profile_resolver
            return _canned_result()

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        monkeypatch.setattr(
            integration, "polish_summary", lambda text: (text, "template"))
        ctx = SimpleNamespace(insurance_type="城乡居民基本医疗保险", service_type="普通门诊")

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


class TestSpecialDecomposeCall:
    """门特（第二流程）integration 入口：门控一致、profile 解析透传、连接关闭保证。"""

    def test_gates_unset_disables_all(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        assert maybe_decompose_special_outpatient(
            object(), "604", SimpleNamespace()) is None

    def test_provider_without_connect_disables(self, monkeypatch):
        _enable_gate(monkeypatch)
        assert maybe_decompose_special_outpatient(
            object(), "604", SimpleNamespace()) is None

    def test_happy_path_passes_profile_and_closes_conn(self, monkeypatch):
        _enable_gate(monkeypatch)
        conn = _FakeConn()
        captured = {}

        def fake_decompose(c, djh, hospital_code, rounding_mode,
                           profile=None, cycle_context_override=None,
                           allow_observed_deductible=False):
            captured.update(
                djh=djh, hospital_code=hospital_code,
                rounding_mode=rounding_mode, profile=profile,
                cycle_context_override=cycle_context_override,
                allow_observed_deductible=allow_observed_deductible)
            return _canned_result()

        monkeypatch.setattr(
            integration, "decompose_outpatient_special_settlement", fake_decompose)
        monkeypatch.setattr(
            integration, "polish_summary", lambda text: (text, "template"))

        ctx = SimpleNamespace(
            insurance_type="城镇职工基本医疗保险", service_type="门诊特殊疾病")
        presentation = maybe_decompose_special_outpatient(
            _FakeProvider(conn), "604", ctx)

        assert isinstance(presentation, DecompositionPresentation)
        assert captured["djh"] == "604"
        assert captured["hospital_code"] == "H001"
        assert captured["rounding_mode"] is RoundingMode.HALF_UP
        # ESP-CODE-001/002 未登记：profile 保持 None（fail-closed，不猜测职工门特）
        assert captured["profile"] is None
        assert captured["cycle_context_override"] is None
        assert captured["allow_observed_deductible"] is False
        assert conn.closed is True

    def test_connect_failure_returns_none(self, monkeypatch):
        _enable_gate(monkeypatch)
        provider = SimpleNamespace(
            _connect=lambda _db: (_ for _ in ()).throw(ConnectionError("down")))
        assert maybe_decompose_special_outpatient(
            provider, "707", SimpleNamespace()) is None


class TestPolishSummary:
    def test_model_unavailable_falls_back_to_template(self, monkeypatch):
        class BrokenGateway:
            def generate(self, **_kwargs):
                raise RuntimeError("model down")

        monkeypatch.setattr(
            "src.model_service.gateway.ModelGateway", BrokenGateway)
        text = "总费用 100.00 元，一致。"
        assert polish_summary(text) == (text, "template")

    def test_model_output_with_same_numbers_is_used(self, monkeypatch):
        class OkGateway:
            def generate(self, **_kwargs):
                return SimpleNamespace(content="本次总费用为 100.00 元，核对一致。")

        monkeypatch.setattr("src.model_service.gateway.ModelGateway", OkGateway)
        text, source = polish_summary("总费用 100.00 元，一致。")
        assert source == "model"
        assert "100.00" in text

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
