"""门诊费用分解快照服务单元测试（Issue #78 设计 §15 步骤 1）。

fake conn 路由，无数据库依赖。覆盖：
- 手工行数据 → build_snapshot → 全流程分解（在职社区大额 90% 档走通）；
- 默认 unknown profile 不猜测险种/医疗类别（设计 §6.1 P0）；
- 适配器失败/歧义/未找到降级 unavailable（不抛异常栈）；
- 冲正交易返回 unavailable；
- 读元数据 citations（kind=source_catalog，带来源与哈希）。
"""
from __future__ import annotations

from decimal import Decimal

from src.adapters.data_supply.outpatient_decomposition_queries import build_snapshot
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import (
    decompose_employee_outpatient,
)
from src.runtime.policy_qa.fee_decomposition.snapshot_service import (
    decompose_outpatient_trade,
)

MODE = RoundingMode.HALF_UP

_TRADE_COLS = (
    "T_TradeNo", "T_TradeDate", "T_HospCode", "P_FundType", "T_CureType",
    "PN_PersonType", "P_Birthday", "TB_FeeIn",
    "T_FeeAll", "T_FeeIn", "T_FeeOut", "T_FundPay", "T_SelfPay2", "T_FirstPay",
    "T_BigPay", "T_BigSelfPay", "T_BCPay", "T_JCPay", "T_OfficalPay",
    "T_SelfPay1", "T_SelfPayAll", "T_PersonCountPay", "T_CashPay",
    "T_HasRefundmented", "T_PartialReturnFlag", "TR_OraginalTradeNo", "T_OraginalTradeNo",
)
_ITEM_COLS = (
    "ItemId", "ItemType", "ItemCode", "FeeType", "UnitPrice", "Count",
    "Fee", "FeeIn", "FeeOut", "SelfPay2", "fsrq",
)
_DRUG_COLS = (
    "ypbm", "sxrq", "jzrq", "sflb", "zfbl", "a_ypbs", "a_mzxj",
    "a_xbbl", "ypfl", "bzjg", "zzjssjg",
)
_SVC_COLS = ("xmbm", "sxrq", "jzrq", "sfxmdj", "zfbl", "djxe")


def _row(cols, **values) -> dict:
    return {c.lower(): values.get(c) for c in cols}


def _trade_row(**overrides) -> dict:
    """在职社区样本（2024-06-01）：E=3000，F=1800，B=1200，大额 90%=1080，S=120。"""
    base = dict(
        T_TradeNo="T001", T_TradeDate="2024-06-01", T_HospCode="H001",
        P_FundType="11", T_CureType="11", PN_PersonType="11", P_Birthday="1980-01-01",
        TB_FeeIn="0.00",
        T_FeeAll="3000.00", T_FeeIn="3000.00", T_FeeOut="0.00", T_FundPay="1080.00",
        T_SelfPay2="0.00", T_FirstPay="1800.00", T_BigPay="1080.00",
        T_BigSelfPay="120.00", T_BCPay="0.00", T_JCPay="0.00", T_OfficalPay="0.00",
        T_SelfPay1="1920.00", T_SelfPayAll="1920.00", T_PersonCountPay="0.00",
        T_CashPay="1920.00",
        T_HasRefundmented=0, T_PartialReturnFlag="", TR_OraginalTradeNo="",
        T_OraginalTradeNo="",
    )
    base.update(overrides)
    return _row(_TRADE_COLS, **base)


def _item_row(**overrides) -> dict:
    base = dict(
        ItemId="L1", ItemType="0", ItemCode="D001", FeeType="无自付",
        UnitPrice="100.00", Count="30", Fee="3000.00", FeeIn="3000.00",
        FeeOut="0.00", SelfPay2="0.00", fsrq="2024-05-20",
    )
    base.update(overrides)
    return _row(_ITEM_COLS, **base)


def _drug_row(**overrides) -> dict:
    base = dict(
        ypbm="D001", sxrq="2024-01-01", jzrq="2024-12-31", sflb="无自付",
        zfbl=None, a_ypbs="0", a_mzxj=None, a_xbbl=None, ypfl=None,
        bzjg=None, zzjssjg=None,
    )
    base.update(overrides)
    return _row(_DRUG_COLS, **base)


class _RoutingCursor:
    def __init__(self, routes, fail=False):
        self._routes = routes
        self._fail = fail
        self._active = ((), [])

    def execute(self, sql, params):
        if self._fail:
            raise RuntimeError("db down")
        for fragment, spec in self._routes.items():
            if fragment in sql:
                self._active = spec
                return
        self._active = ((), [])

    @property
    def description(self):
        return [(c,) for c in self._active[0]]

    def fetchall(self):
        return self._active[1]

    def close(self):
        pass


class _Conn:
    def __init__(self, routes, fail=False):
        self._cur = _RoutingCursor(routes, fail)

    def cursor(self):
        return self._cur


def _service_conn(trade_rows=None, item_rows=None, drug_rows=None, inst_rows=None, fail=False):
    def _tuples(row_dicts, cols):
        return [tuple(r[c.lower()] for c in cols) for r in row_dicts]

    routes = {
        "o_FeeItem": (_ITEM_COLS, _tuples(item_rows if item_rows is not None else [_item_row()], _ITEM_COLS)),
        "yb_ypzdml": (_DRUG_COLS, _tuples(drug_rows if drug_rows is not None else [_drug_row()], _DRUG_COLS)),
        "yb_xzzlfwxm": (_SVC_COLS, []),
        "m_institution": (("HospCode", "H_LEVEL"),
                          inst_rows if inst_rows is not None else [("H001", "14")]),
        "o_Trade": (_TRADE_COLS, _tuples(trade_rows if trade_rows is not None else [_trade_row()], _TRADE_COLS)),
    }
    return _Conn(routes, fail)


def _employee_resolver(row):
    """经确认码表映射的 resolver（测试桩）：返回职工+普通门诊。"""
    return ("employee", "outpatient")


def _field(result, code: str):
    for f in result.fields:
        if f.field_code == code:
            return f
    raise AssertionError(f"field {code} not found")


# ── 手工行 → build_snapshot → 全流程分解 ──────────────────────


def test_build_snapshot_full_pipeline_employed_community_90pct() -> None:
    """在职/社区/2024：E=3000，F=1800，B=1200，大额 90%=1080（EOP-RATE-105），S=120。

    年度累计口径由调用方显式断言（is_pre_trade=True），模拟口径已确认场景。
    """
    snapshot, notes = build_snapshot(
        trade_row=_trade_row(),
        item_rows=[_item_row()],
        drug_catalog_rows=[_drug_row()],
        service_catalog_rows=[],
        material_catalog_rows=[],
        institution_h_level="02",
        institution_h_type="04",
        rounding_mode=MODE,
        insurance_type="employee",
        medical_category="outpatient",
        prior_in_scope_fee_is_pre_trade=True,
        prior_fund_payment=Decimal("0.00"),
        prior_fund_payment_is_pre_trade=True,
    )
    result = decompose_employee_outpatient(snapshot)
    assert _field(result, "T_FeeAll").check_status == "matched"
    assert _field(result, "T_FeeIn").calculated_amount == "3000.00"
    assert _field(result, "T_FirstPay").calculated_amount == "1800.00"
    assert _field(result, "T_BigPay").calculated_amount == "1080.00"
    assert _field(result, "T_BigPay").check_status == "matched"
    assert _field(result, "T_BigSelfPay").calculated_amount == "120.00"
    # 在职无退休/军残/公疗：not_applicable 且账面为零不冲突
    assert _field(result, "T_BCPay").check_status == "not_applicable"
    # 结果不外泄出生日期原文（脱敏边界）
    assert "1980-01-01" not in result.model_dump_json()


# ── 服务层：profile 门控与降级 ────────────────────────────────


def test_service_unknown_profile_never_guesses() -> None:
    """默认无 resolver：险种/医疗类别置 unknown，内核 UNSUPPORTED_PROFILE，不猜测职工。"""
    result = decompose_outpatient_trade(_service_conn(), "T001", "H001", MODE)
    assert result.execution_status == "unavailable"
    assert result.profile.insurance_type == "unknown"
    assert result.profile.medical_category == "unknown"
    assert any(u.code == "UNSUPPORTED_PROFILE" for u in result.uncertainties)
    # 读元数据 citation 仍随结果返回
    meta = [c for c in result.citations if c.kind == "source_catalog"]
    assert meta and len(meta[0].value or "") == 64
    assert meta[0].ref.startswith("hospital_record_store#mapping:")


def test_service_adapter_failure_degrades_to_unavailable() -> None:
    result = decompose_outpatient_trade(_service_conn(fail=True), "T001", "H001", MODE)
    assert result.execution_status == "unavailable"
    assert any(u.code == "READ_FAILED" for u in result.uncertainties)
    assert result.fields == []  # 不抛异常栈，空字段结果


def test_service_trade_not_found_and_ambiguous() -> None:
    not_found = decompose_outpatient_trade(_service_conn(trade_rows=[]), "T404", "H001", MODE)
    assert not_found.execution_status == "unavailable"
    assert any(u.code == "TRADE_NOT_FOUND" for u in not_found.uncertainties)

    ambiguous = decompose_outpatient_trade(
        _service_conn(trade_rows=[_trade_row(), _trade_row()]), "T001", "H001", MODE)
    assert ambiguous.execution_status == "unavailable"
    assert any(u.code == "TRADE_AMBIGUOUS" for u in ambiguous.uncertainties)


def test_service_reversal_trade_unavailable() -> None:
    """冲正交易（关联原交易号）：即使 profile 已确认也进入未支持重算状态。"""
    conn = _service_conn(trade_rows=[_trade_row(TR_OraginalTradeNo="T000")])
    result = decompose_outpatient_trade(
        conn, "T001", "H001", MODE, profile_resolver=_employee_resolver)
    assert result.execution_status == "unavailable"
    assert result.profile.insurance_type == "employee"  # resolver 生效
    assert any(u.code == "UNSUPPORTED_REVERSAL_OR_NEGATIVE" for u in result.uncertainties)


def test_service_confirmed_profile_runs_full_decomposition() -> None:
    """resolver 确认职工+门诊：全流程执行，但 TB_FeeIn 口径未确认 → 起付/大额不可核对。

    关键：服务层不伪造口径确认（prior_in_scope_fee_is_pre_trade 默认 False），
    即使观测金额吻合也不升级为独立重算成功（禁止反推）。
    """
    result = decompose_outpatient_trade(
        _service_conn(), "T001", "H001", MODE, profile_resolver=_employee_resolver)
    assert result.execution_status in ("partial", "complete")
    assert _field(result, "T_FeeAll").check_status == "matched"  # 明细汇总核对走通
    first_pay = _field(result, "T_FirstPay")
    assert first_pay.check_status == "not_verifiable"  # 口径未确认，不硬算
    assert first_pay.calculated_amount is None  # 绝不用观测值回填
    # 读元数据 citations：来源 + 内容哈希
    meta = [c for c in result.citations if c.kind == "source_catalog"]
    assert meta and meta[0].value
