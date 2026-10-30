"""交易前累计逐交易自证门控（阶段 E）与累计口径开关路径测试。

自证规则（独立于 accumulation_caliber_confirmed 评估开关）：
TB_Year==交易年 且 TA_FeeIn−TB_FeeIn==T_FeeIn、TA_BigPay−TB_BigPay==T_BigPay
两条增量恒等式同时成立（容差 0.005，与探针 probe_accumulation_identity 一致）→
账面 TB_FeeIn/TB_BigPay 按"院内已自证的交易前累计"参战；任一不满足
（TB_Year=2000/0 哨兵、恒等式不成立、负累计）→ 维持 fail-closed。

同时补齐设计文档 :538 点名的开关路径测试（accumulation_caliber_confirmed=True）：
TB_Year 锚点命中/未命中、D16 推导（下界语义）、账面累计注入。

fake conn 路由，无数据库依赖；两目标样例形态（居民 0408 / 职工 000008）
金额取自探针证据 docs/reviews/2026-10-22-accumulation-identity-evidence.md Q4。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.adapters.base.models import AdapterCallStatus
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition import integration, snapshot_service
from src.runtime.policy_qa.fee_decomposition.snapshot_service import (
    decompose_outpatient_trade,
)
from src.tests.unit.runtime.policy_qa.fee_decomposition import (
    test_snapshot_service as helpers,
)

MODE = RoundingMode.HALF_UP

_TRADE_COLS = (*helpers._TRADE_COLS, "TB_Year", "TB_BigPay", "TA_FeeIn", "TA_BigPay")


def _row(cols, **values) -> dict:
    return {c.lower(): values.get(c) for c in cols}


def _employee_row(**overrides) -> dict:
    """职工 000008 形态（2024-11-18，全 0 起）：T_FeeIn=2400，起付 1800，大额 420。"""
    base = dict(
        T_TradeNo="T001", T_TradeDate="2024-11-18", T_HospCode="H001",
        P_FundType="3", T_CureType="11", PN_PersonType="11", P_Birthday="1980-01-01",
        TB_Year=2024, TB_FeeIn="0.00", TA_FeeIn="2400.00",
        TB_BigPay="0.00", TA_BigPay="420.00",
        T_FeeAll="2400.00", T_FeeIn="2400.00", T_FeeOut="0.00", T_FundPay="420.00",
        T_SelfPay2="0.00", T_FirstPay="1800.00", T_BigPay="420.00",
        T_BigSelfPay="180.00", T_BCPay="0.00", T_JCPay="0.00", T_OfficalPay="0.00",
        T_SelfPay1="1980.00", T_SelfPayAll="1980.00", T_PersonCountPay="0.00",
        T_CashPay="1980.00",
        T_HasRefundmented=0, T_PartialReturnFlag="", TR_OraginalTradeNo="",
        T_OraginalTradeNo="",
    )
    base.update(overrides)
    return _row(_TRADE_COLS, **base)


def _resident_row(**overrides) -> dict:
    """居民 0408 形态（2024-04-08）：TB_FeeIn=5159/TA=8354/T=3195；大额 2304.50→3902.00。"""
    base = dict(
        T_TradeNo="T002", T_TradeDate="2024-04-08", T_HospCode="H001",
        P_FundType="91", T_CureType="19", PN_PersonType="14", P_Birthday="1956-03-01",
        TB_Year=2024, TB_FeeIn="5159.00", TA_FeeIn="8354.00",
        TB_BigPay="2304.50", TA_BigPay="3902.00",
        T_FeeAll="3195.00", T_FeeIn="3195.00", T_FeeOut="0.00", T_FundPay="1597.50",
        T_SelfPay2="0.00", T_FirstPay="0.00", T_BigPay="1597.50",
        T_BigSelfPay="1597.50", T_BCPay="0.00", T_JCPay="0.00", T_OfficalPay="0.00",
        T_SelfPay1="1597.50", T_SelfPayAll="1597.50", T_PersonCountPay="0.00",
        T_CashPay="1597.50",
        T_HasRefundmented=0, T_PartialReturnFlag="", TR_OraginalTradeNo="",
        T_OraginalTradeNo="",
    )
    base.update(overrides)
    return _row(_TRADE_COLS, **base)


def _conn(trade_row, fee: str = "2400.00", inst_level: str = "02"):
    item = helpers._item_row(Fee=fee, FeeIn=fee)
    drug = helpers._drug_row()

    def _tuples(row_dicts, cols):
        return [tuple(r[c.lower()] for c in cols) for r in row_dicts]

    routes = {
        "o_FeeItem": (helpers._ITEM_COLS, _tuples([item], helpers._ITEM_COLS)),
        "yb_ypzdml": (helpers._DRUG_COLS, _tuples([drug], helpers._DRUG_COLS)),
        "yb_xzzlfwxm": (helpers._SVC_COLS, []),
        "m_institution": (("HospCode", "H_LEVEL"), [("H001", inst_level)]),
        "o_Trade": (_TRADE_COLS, _tuples([trade_row], _TRADE_COLS)),
    }
    return helpers._Conn(routes)


def _field(result, code: str):
    return helpers._field(result, code)


def _evidence_input(result, ref: str):
    evidence = result.explanation_evidence
    assert evidence is not None, "结果应携带公式输入证据"
    assert ref in evidence.inputs, f"缺少公式输入 {ref}"
    return evidence.inputs[ref]


# ── 逐交易自证门控：主链（accumulation_caliber_confirmed=False）──────────────


def test_employee_self_proven_trade_releases_accumulation_fields() -> None:
    """职工 000008 形态：恒等式成立 → 主链（未开评估口径）起付/大额可核对。"""
    result = decompose_outpatient_trade(
        _conn(_employee_row()), "T001", "H001", MODE,
        profile_resolver=lambda row: ("employee", "outpatient")).result
    assert _field(result, "T_FirstPay").check_status == "matched"
    assert _field(result, "T_FirstPay").calculated_amount == "1800.00"
    assert _field(result, "T_BigPay").check_status == "matched"
    assert _field(result, "T_BigPay").calculated_amount == "420.00"
    # 自证证据：恒等式两侧数值进 citations，跨院口径进 uncertainties
    proof = [c for c in result.citations if c.id == "source.accumulation_self_check"]
    assert proof, "自证成立应记录恒等式证据 citation"
    assert any("2400.00" in v for v in proof[0].values)
    assert any("420.00" in v for v in proof[0].values)
    assert any(u.code == "ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED" for u in result.uncertainties)
    # 公式输入升级为已自证（不再"累计时点或范围未确认"）
    prior = _evidence_input(result, "fact.trade.prior_in_scope_fee")
    assert prior.status == "verified"
    assert prior.value == "0.00"
    assert "自证" in (prior.reason or "")
    fund = _evidence_input(result, "fact.trade.prior_fund_payment")
    assert fund.status == "verified"
    assert fund.value == "0.00"


def test_resident_self_proven_trade_matches_book() -> None:
    """居民 0408 形态：恒等式成立 → 大额 1597.50/起付 0 与账面一致（主链）。"""
    result = decompose_outpatient_trade(
        _conn(_resident_row(), fee="3195.00"), "T002", "H001", MODE,
        profile_resolver=lambda row: ("resident", "outpatient")).result
    assert _field(result, "T_FirstPay").check_status == "matched"
    assert Decimal(_field(result, "T_FirstPay").calculated_amount) == Decimal("0.00")
    big = _field(result, "T_BigPay")
    assert big.check_status == "matched"
    assert big.calculated_amount == "1597.50"
    assert _field(result, "T_SelfPayAll").observed_amount == "1597.50"
    assert any(c.id == "source.accumulation_self_check" for c in result.citations)
    assert any(u.code == "ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED" for u in result.uncertainties)
    prior = _evidence_input(result, "fact.trade.prior_fund_payment")
    assert prior.status == "verified"
    assert prior.value == "2304.50"


def test_identity_broken_trade_stays_fail_closed() -> None:
    """恒等式不成立（TA_FeeIn 多出 46）→ 不落自证路径，维持 fail-closed。"""
    row = _employee_row(TA_FeeIn="2446.00")  # 2446−0 ≠ 2400
    result = decompose_outpatient_trade(
        _conn(row), "T001", "H001", MODE,
        profile_resolver=lambda row: ("employee", "outpatient")).result
    first_pay = _field(result, "T_FirstPay")
    assert first_pay.check_status == "not_verifiable"
    assert first_pay.calculated_amount is None
    assert not [c for c in result.citations if c.id == "source.accumulation_self_check"]
    assert not [u for u in result.uncertainties if u.code == "ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED"]
    prior = _evidence_input(result, "fact.trade.prior_in_scope_fee")
    assert prior.status != "verified"


@pytest.mark.parametrize("sentinel_year", [2000, 0])
def test_sentinel_year_not_self_proven(sentinel_year) -> None:
    """TB_Year=2000/0 哨兵行：即使 TB=0/TA=T 巧合成立也不自证。"""
    row = _employee_row(TB_Year=sentinel_year)
    result = decompose_outpatient_trade(
        _conn(row), "T001", "H001", MODE,
        profile_resolver=lambda row: ("employee", "outpatient")).result
    assert _field(result, "T_FirstPay").check_status == "not_verifiable"
    assert not [c for c in result.citations if c.id == "source.accumulation_self_check"]


def test_negative_prior_accumulation_not_self_proven() -> None:
    """负交易前累计非合法累计形态：恒等式数值上成立也不自证（防护）。"""
    row = _employee_row(TB_FeeIn="-100.00", TA_FeeIn="2300.00")  # 2300−(−100)=2400 恒等式成立
    result = decompose_outpatient_trade(
        _conn(row), "T001", "H001", MODE,
        profile_resolver=lambda row: ("employee", "outpatient")).result
    assert _field(result, "T_FirstPay").check_status == "not_verifiable"
    assert not [c for c in result.citations if c.id == "source.accumulation_self_check"]


@pytest.mark.parametrize("delta,proven", [("0.004", True), ("0.005", False)])
def test_identity_tolerance_matches_probe(delta, proven) -> None:
    """容差与探针一致：|diff| < 0.005 才成立（money 4 位小数）。"""
    row = _employee_row(TA_FeeIn=str(Decimal("2400.00") + Decimal(delta)))
    result = decompose_outpatient_trade(
        _conn(row), "T001", "H001", MODE,
        profile_resolver=lambda row: ("employee", "outpatient")).result
    matched = _field(result, "T_FirstPay").check_status == "matched"
    assert matched is proven


# ── 开关路径（accumulation_caliber_confirmed=True，设计文档 :538 点名）───────


def test_caliber_anchor_hit_uses_book_without_derivation(monkeypatch) -> None:
    """TB_Year==交易年锚点命中：账面累计直接参战，不触发 D16 推导。"""
    monkeypatch.setattr(snapshot_service, "derive_in_hospital_accumulation",
                        lambda *args: pytest.fail("锚点命中不应触发 D16 推导"))
    result = decompose_outpatient_trade(
        _conn(_employee_row()), "T001", "H001", MODE,
        profile_resolver=lambda row: ("employee", "outpatient"),
        accumulation_caliber_confirmed=True).result
    assert _field(result, "T_FirstPay").check_status == "matched"
    assert _field(result, "T_BigPay").calculated_amount == "420.00"
    assert not [u for u in result.uncertainties if u.code == "ACCUMULATION_DERIVED_IN_HOSPITAL"]


def test_caliber_anchor_miss_derives_lower_bound(monkeypatch) -> None:
    """TB_Year=2000 锚点未命中：D16 推导累计只作下界，不升级为已确认口径。"""
    monkeypatch.setattr(
        snapshot_service, "derive_in_hospital_accumulation",
        lambda *args: SimpleNamespace(
            status=AdapterCallStatus.SUCCESS,
            data={"prior_in_scope_fee": Decimal("600.00"),
                  "prior_fund_payment": Decimal("80.00"),
                  "anchor_count": 1, "prior_trade_count": 2}))
    row = _employee_row(T_TradeDate=datetime(2024, 11, 18), TB_Year=2000, TB_FeeIn=None, TB_BigPay=None)
    result = decompose_outpatient_trade(
        _conn(row), "T001", "H001", MODE,
        profile_resolver=lambda row: ("employee", "outpatient"),
        accumulation_caliber_confirmed=True).result
    assert any(u.code == "ACCUMULATION_DERIVED_IN_HOSPITAL" for u in result.uncertainties)
    # 推导累计是下界：依赖累计的字段不升级为已确认核对
    first_pay = _field(result, "T_FirstPay")
    assert first_pay.check_status == "not_verifiable"
    assert first_pay.calculated_amount is None
    prior = _evidence_input(result, "fact.trade.prior_in_scope_fee")
    assert prior.status == "unverified"
    assert prior.value == "600.00"
    assert "下界" in (prior.reason or "")
    fund = _evidence_input(result, "fact.trade.prior_fund_payment")
    assert fund.status == "unverified"
    assert fund.value == "80.00"


def test_caliber_book_prior_big_pay_injection() -> None:
    """账面 TB_BigPay 注入交易前基金累计（锚点命中、恒等式不成立时开关仍生效）。"""
    row = _resident_row(TA_BigPay="3902.51")  # 大额恒等式破 0.01 → 不自证
    result = decompose_outpatient_trade(
        _conn(row, fee="3195.00"), "T002", "H001", MODE,
        profile_resolver=lambda row: ("resident", "outpatient"),
        accumulation_caliber_confirmed=True).result
    # 开关路径行为不变：账面累计参战，大额按 cap−2304.50 核对一致
    big = _field(result, "T_BigPay")
    assert big.check_status == "matched"
    assert big.calculated_amount == "1597.50"
    fund = _evidence_input(result, "fact.trade.prior_fund_payment")
    assert fund.status == "verified"
    assert fund.value == "2304.50"
    # 自证未成立：无自证证据 citation
    assert not [c for c in result.citations if c.id == "source.accumulation_self_check"]


# ── 主链入口（decompose_for_workbench allow_eval_calibers=False）─────────────


class _Provider:
    def __init__(self, conn):
        self._conn = conn

    def _connect(self, _db):
        return self._conn


def test_workbench_main_chain_fail_closed_still_uses_self_proof(monkeypatch) -> None:
    """工作台/policy-qa 主链口径（allow_eval_calibers=False）：自证独立生效。"""
    monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
    monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
    monkeypatch.delenv("FEE_DECOMPOSITION_EVAL_CALIBERS", raising=False)
    outcome = integration.decompose_for_workbench(
        "T001", "outpatient", _Provider(_conn(_employee_row())),
        allow_eval_calibers=False)
    assert outcome.status == "ok"
    assert outcome.caliber == "fail_closed"
    result = outcome.presentation.result
    assert _field(result, "T_FirstPay").check_status == "matched"
    assert _field(result, "T_BigPay").calculated_amount == "420.00"
    assert any(u.code == "ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED" for u in result.uncertainties)
