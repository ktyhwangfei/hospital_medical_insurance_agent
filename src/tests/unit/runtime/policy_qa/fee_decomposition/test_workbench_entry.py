"""费用分解工作台入口单元测试（Issue #78 四链路页面可用化 Phase 1）。

覆盖：
- 普通门诊 profile 确定性映射：交易行险种码（o_Trade P_FundType，回放脚本 SQL 同款口径）
  3→职工、91/92/93→居民、未知码/缺失/空 → None（fail-closed 不猜测）；
- 门控报因：缺取整模式/缺院区码/取整非法/provider 无连接工厂 → not_configured 且
  携带缺失 env 名（与主链静默 None 不同，工作台必须显式报因）；
- auto 链路识别：≥15 位纯字母数字 → outpatient，否则 → special（与主链同款规则）；
- FEE_DECOMPOSITION_EVAL_CALIBERS 开关在工作台普通门诊路径透传候选口径；
  policy-qa 主链显式 fail-closed，并以 outcome.caliber 记录本次采用口径；
- 门特路径复用 _resolve_special_suite 消歧并回传实际 profile；
- 分解异常 → unavailable 表述（诚实降级），连接保证关闭。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition import integration
from src.runtime.policy_qa.fee_decomposition.integration import (
    DecompositionPresentation,
    _resolve_outpatient_profile_from_record,
    decompose_for_workbench,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
)
from src.runtime.policy_qa.fee_decomposition.settlement_facts import DecompositionOutcome


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


class TestOutpatientProfileFromRecord:
    """普通门诊 profile：唯一交易行的险种码确定性映射（多行歧义由上游
    locate_outpatient_trade 拦为 TRADE_AMBIGUOUS，本函数只见唯一行）。"""

    def test_employee_fund_type(self):
        assert _resolve_outpatient_profile_from_record({"p_fundtype": "3"}) == (
            "employee", "outpatient")

    @pytest.mark.parametrize("fund", ["91", "92", "93"])
    def test_resident_fund_types(self, fund):
        assert _resolve_outpatient_profile_from_record({"p_fundtype": fund}) == (
            "resident", "outpatient")

    def test_unknown_code_not_guessed(self):
        assert _resolve_outpatient_profile_from_record({"p_fundtype": "7"}) is None

    def test_missing_column(self):
        assert _resolve_outpatient_profile_from_record({}) is None

    def test_blank_value(self):
        assert _resolve_outpatient_profile_from_record({"p_fundtype": "  "}) is None

    def test_none_value(self):
        assert _resolve_outpatient_profile_from_record({"p_fundtype": None}) is None


class TestWorkbenchGateReporting:
    """门控不满足 → not_configured 结构化报因（含缺失 env 名），绝不静默。"""

    def test_missing_rounding_mode_reports_env(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
        outcome = decompose_for_workbench("T001", "outpatient", _FakeProvider(_FakeConn()))
        assert outcome.status == "not_configured"
        assert outcome.missing_env == ("FEE_DECOMPOSITION_ROUNDING_MODE",)
        assert "FEE_DECOMPOSITION_ROUNDING_MODE" in outcome.message
        assert outcome.presentation is None

    def test_missing_hospital_code_reports_env(self, monkeypatch):
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        outcome = decompose_for_workbench("T001", "outpatient", _FakeProvider(_FakeConn()))
        assert outcome.status == "not_configured"
        assert outcome.missing_env == ("FEE_DECOMPOSITION_HOSPITAL_CODE",)

    def test_invalid_rounding_mode_reports_env(self, monkeypatch):
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "bogus")
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
        outcome = decompose_for_workbench("T001", "outpatient", _FakeProvider(_FakeConn()))
        assert outcome.status == "not_configured"
        assert "FEE_DECOMPOSITION_ROUNDING_MODE" in outcome.missing_env

    def test_both_missing_reports_both(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        outcome = decompose_for_workbench("T001", "outpatient", _FakeProvider(_FakeConn()))
        assert outcome.status == "not_configured"
        assert set(outcome.missing_env) == {
            "FEE_DECOMPOSITION_ROUNDING_MODE", "FEE_DECOMPOSITION_HOSPITAL_CODE"}

    def test_provider_without_connect_reports_not_configured(self, monkeypatch):
        _enable_gate(monkeypatch)
        outcome = decompose_for_workbench("T001", "outpatient", object())
        assert outcome.status == "not_configured"
        assert "_connect" in outcome.message


class TestAutoChainDetection:
    """auto 识别与主链 _looks_like_outpatient_trade_no 同款规则；门控未配置时
    也可从 not_configured 结果读出识别结论（识别先于门控，不消耗连接）。"""

    def test_long_alnum_is_outpatient(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        outcome = decompose_for_workbench("011100030X240311000031", "auto", object())
        assert outcome.chain == "outpatient"

    def test_short_digits_is_special(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        outcome = decompose_for_workbench("604", "auto", object())
        assert outcome.chain == "special"

    def test_explicit_hint_not_overridden(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        # 显式 special 即使标识符形似交易号也不改判
        assert decompose_for_workbench("011100030X240311000031", "special", object()).chain == "special"
        assert decompose_for_workbench("604", "outpatient", object()).chain == "outpatient"

    def test_invalid_chain_hint_rejected(self, monkeypatch):
        _enable_gate(monkeypatch)
        with pytest.raises(ValueError):
            decompose_for_workbench("T001", "inpatient", _FakeProvider(_FakeConn()))


class TestWorkbenchOutpatientPath:
    def test_profile_from_trade_row_and_calibers_default_off(self, monkeypatch):
        _enable_gate(monkeypatch)
        monkeypatch.delenv("FEE_DECOMPOSITION_EVAL_CALIBERS", raising=False)
        conn = _FakeConn()
        captured = {}

        def fake_decompose(_conn, trade_no, hospital_code, rounding_mode,
                           profile_resolver=None, accumulation_caliber_confirmed=False,
                           derive_eligibility_from_codes=False):
            captured.update(
                trade_no=trade_no, hospital_code=hospital_code,
                rounding_mode=rounding_mode,
                accumulation=accumulation_caliber_confirmed,
                eligibility=derive_eligibility_from_codes,
                resolved=profile_resolver({"p_fundtype": "3"}) if profile_resolver else None,
            )
            return DecompositionOutcome(_canned_result())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        outcome = decompose_for_workbench("T001", "outpatient", _FakeProvider(conn))

        assert outcome.status == "ok"
        assert outcome.chain == "outpatient"
        assert outcome.profile == ("employee", "outpatient")
        assert captured["trade_no"] == "T001"
        assert captured["hospital_code"] == "H001"
        assert captured["rounding_mode"] is RoundingMode.HALF_UP
        # 默认不开候选口径（fail-closed；回放验证口径仅 EVAL_CALIBERS=1 时启用）
        assert captured["accumulation"] is False
        assert captured["eligibility"] is False
        assert outcome.caliber == "fail_closed"
        assert isinstance(outcome.presentation, DecompositionPresentation)
        assert outcome.presentation.result.execution_status == "complete"
        assert conn.closed is True

    def test_eval_calibers_env_enables_candidate_calibers(self, monkeypatch):
        _enable_gate(monkeypatch)
        monkeypatch.setenv("FEE_DECOMPOSITION_EVAL_CALIBERS", "1")
        captured = {}

        def fake_decompose(_conn, _trade_no, _hospital_code, _rounding_mode,
                           profile_resolver=None, accumulation_caliber_confirmed=False,
                           derive_eligibility_from_codes=False):
            captured.update(
                accumulation=accumulation_caliber_confirmed,
                eligibility=derive_eligibility_from_codes,
                resolved=profile_resolver({"p_fundtype": "92"}) if profile_resolver else None,
            )
            return DecompositionOutcome(_canned_result())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        outcome = decompose_for_workbench(
            "011100030X240311000032", "auto", _FakeProvider(_FakeConn()))

        assert captured["accumulation"] is True
        assert captured["eligibility"] is True
        assert outcome.caliber == "eval_calibers"
        assert outcome.profile == ("resident", "outpatient")

    def test_explicit_fail_closed_ignores_eval_env(self, monkeypatch):
        """policy-qa 主链显式 fail-closed：即使环境变量开着也不用候选口径。"""
        _enable_gate(monkeypatch)
        monkeypatch.setenv("FEE_DECOMPOSITION_EVAL_CALIBERS", "1")
        captured = {}

        def fake_decompose(_conn, _trade_no, _hospital_code, _rounding_mode,
                           profile_resolver=None, accumulation_caliber_confirmed=False,
                           derive_eligibility_from_codes=False):
            captured.update(accumulation=accumulation_caliber_confirmed,
                            eligibility=derive_eligibility_from_codes)
            return DecompositionOutcome(_canned_result())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        outcome = decompose_for_workbench("T001", "outpatient", _FakeProvider(_FakeConn()),
                                          allow_eval_calibers=False)

        assert captured == {"accumulation": False, "eligibility": False}
        assert outcome.caliber == "fail_closed"

    def test_unknown_fund_type_profile_stays_none(self, monkeypatch):
        _enable_gate(monkeypatch)

        def fake_decompose(_conn, _t, _h, _r, profile_resolver=None, **_kwargs):
            assert profile_resolver({"p_fundtype": "7"}) is None
            return DecompositionOutcome(_canned_result())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        # 交易行险种码缺失：resolver 不被调用时 profile 仍为 None（内核 UNSUPPORTED_PROFILE）
        outcome = decompose_for_workbench("T001", "outpatient", _FakeProvider(_FakeConn()))
        assert outcome.profile is None

    def test_decompose_exception_degrades_to_unavailable(self, monkeypatch):
        _enable_gate(monkeypatch)
        conn = _FakeConn()

        def boom(*_args, **_kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(integration, "decompose_outpatient_trade", boom)
        outcome = decompose_for_workbench("T001", "outpatient", _FakeProvider(conn))

        # 诚实降级：不抛栈，返回 unavailable + uncertainties
        assert outcome.status == "ok"
        assert outcome.presentation is not None
        assert outcome.presentation.result.execution_status == "unavailable"
        assert outcome.presentation.result.uncertainties[0].code == "DECOMPOSITION_FAILED"
        assert conn.closed is True


def _locate_result(match_status: str, row: dict | None = None) -> AdapterCallResult:
    return AdapterCallResult(
        status=AdapterCallStatus.SUCCESS, source_system="test", capability="test",
        data={"match_status": match_status, "registration_row": row,
              "row_count": 1 if match_status == "unique_match" else 0})


class TestWorkbenchSpecialPath:
    def test_special_dispatches_and_returns_profile(self, monkeypatch):
        _enable_gate(monkeypatch)
        monkeypatch.setattr(
            integration, "locate_special_mz_registration",
            lambda _c, _d: _locate_result("unique_match", {"fund_type": "3", "yllb": "12"}))
        monkeypatch.setattr(
            integration, "locate_special_mz_resident_registration",
            lambda _c, _d: _locate_result("not_found"))
        monkeypatch.setattr(
            integration, "locate_special_fixed_kidney_registration",
            lambda _c, _d: _locate_result("not_found"))
        conn = _FakeConn()
        captured = {}

        def fake_mz(_conn, djh, hospital_code, rounding_mode, **kwargs):
            captured.update(djh=djh, **kwargs)
            return DecompositionOutcome(_canned_result())

        monkeypatch.setattr(integration, "decompose_special_mz_settlement", fake_mz)
        outcome = decompose_for_workbench("604", "auto", _FakeProvider(conn))

        assert outcome.status == "ok"
        assert outcome.chain == "special"
        assert outcome.profile == ("employee", "outpatient_special")
        assert captured["djh"] == "604"
        assert captured["allow_observed_deductible"] is False
        assert conn.closed is True

    def test_special_registration_not_found_is_unavailable(self, monkeypatch):
        _enable_gate(monkeypatch)
        monkeypatch.setattr(
            integration, "locate_special_mz_registration",
            lambda _c, _d: _locate_result("not_found"))
        monkeypatch.setattr(
            integration, "locate_special_mz_resident_registration",
            lambda _c, _d: _locate_result("not_found"))
        monkeypatch.setattr(
            integration, "locate_special_fixed_kidney_registration",
            lambda _c, _d: _locate_result("not_found"))
        outcome = decompose_for_workbench("999999", "special", _FakeProvider(_FakeConn()))
        assert outcome.status == "ok"
        assert outcome.profile is None
        assert outcome.presentation.result.execution_status == "unavailable"
        assert outcome.presentation.result.uncertainties[0].code == "REGISTRATION_NOT_FOUND"

    def test_special_exception_degrades_to_unavailable(self, monkeypatch):
        _enable_gate(monkeypatch)

        def boom(*_args, **_kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(integration, "locate_special_mz_registration", boom)
        monkeypatch.setattr(integration, "locate_special_mz_resident_registration", boom)
        monkeypatch.setattr(integration, "locate_special_fixed_kidney_registration", boom)
        outcome = decompose_for_workbench("604", "special", _FakeProvider(_FakeConn()))
        assert outcome.status == "ok"
        assert outcome.presentation.result.execution_status == "unavailable"
        assert outcome.presentation.result.uncertainties[0].code == "DECOMPOSITION_FAILED"


class TestExistingEntriesUnchanged:
    """主链既有入口行为不回归：门控不满足仍静默 None（不因工作台报因而改变）。"""

    def test_maybe_decompose_outpatient_still_silent_none(self, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        ctx = SimpleNamespace(insurance_type="城镇职工基本医疗保险", service_type="普通门诊")
        assert integration.maybe_decompose_outpatient(object(), "T001", ctx) is None
