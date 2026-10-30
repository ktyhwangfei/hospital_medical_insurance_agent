"""结算事实侧车（settlement_facts）单元测试（Issue #78 费用解释改造，方案 §53）。

覆盖：
- build_outpatient_facts / build_special_mz_facts：列映射、标签顺序、金额原样透传；
- 零值不吞（Decimal("0.00")/int 0 是 falsy，必须显式 is None 判断）；
- 缺失列 → value=None（前端显示"未返回"），不转零；
- 四个 decompose_* 入口改返回 DecompositionOutcome：unavailable 早退路径
  只要原始行已取到就携带 facts（事实区独立于算法）；原始行未取到 → facts=None。
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from src.adapters.base.models import AdapterCallStatus
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    DecompositionOutcome,
    SettlementFactsView,
    build_outpatient_facts,
    build_special_mz_facts,
)
from src.tests.unit.runtime.policy_qa.fee_decomposition import (
    test_snapshot_service as helpers,
)

MODE = RoundingMode.HALF_UP


def _item(view: SettlementFactsView, label: str, *, payment: bool = False):
    group = view.payment_items if payment else view.items
    for item in group:
        if item.label == label:
            return item
    raise AssertionError(f"结算事实缺少条目: {label}")


def _trade_row_full() -> dict:
    """o_Trade 行（_fetch_all 小写物理键口径）。"""
    return {
        "t_tradeno": "T001", "t_tradedate": "2024-06-01", "t_hospcode": "H001",
        "p_fundtype": "3", "t_curetype": "11", "pn_persontype": "11",
        "t_feeall": Decimal("3000.00"), "t_feein": "3000.00", "t_feeout": "0.00",
        "t_selfpay1": "1920.00", "t_selfpay2": 0, "t_firstpay": "1800.00",
        "t_bigpay": "1080.00", "t_bigselfpay": "120.00", "t_bcpay": "0.00",
        "t_jcpay": None, "t_officalpay": "0.00", "t_fundpay": "1080.00",
        "t_selfpayall": "1920.00", "t_personcountpay": "0.00", "t_cashpay": "1920.00",
        "t_bigillpay": None, "nt_civilpay": Decimal("0.00"),
    }


class TestBuildOutpatientFacts:
    def test_column_mapping_labels_and_order(self):
        view = build_outpatient_facts(_trade_row_full())
        assert view.chain == "outpatient"
        assert view.identifier == "T001"
        assert view.trade_date == "2024-06-01"
        assert view.insurance_type == "3"
        assert view.medical_category == "11"
        assert view.person_type == "11"
        assert view.hospital_level is None  # o_Trade 无机构等级列
        assert [item.label for item in view.items] == [
            "费用总金额", "医保范围内金额", "医保范围外金额", "自付一", "自付二",
            "起付金额", "大额支付", "大额个人自付", "退休补充保险补助", "军残支付",
            "公疗补充支付", "退役医疗费支付", "基金合计", "个人支付总金额", "大病保险支付", "民政救助支付",
        ]
        assert [item.label for item in view.payment_items] == [
            "个人账户支付", "现金支付",
        ]
        assert _item(view, "费用总金额").value == "3000.00"
        assert _item(view, "大额个人自付").value == "120.00"

    def test_zero_values_preserved(self):
        """Decimal("0.00")/int 0 是 falsy：必须显式 is None 判断，零值照常显示。"""
        view = build_outpatient_facts(_trade_row_full())
        assert _item(view, "医保范围外金额").value == "0.00"
        assert _item(view, "自付二").value == "0"  # int 0 原样字符串化
        assert _item(view, "退休补充保险补助").value == "0.00"
        assert _item(view, "个人账户支付", payment=True).value == "0.00"
        assert _item(view, "民政救助支付").value == "0.00"

    def test_missing_values_become_none_not_zero(self):
        view = build_outpatient_facts(_trade_row_full())
        assert _item(view, "军残支付").value is None  # 列值为 NULL
        assert _item(view, "大病保险支付").value is None
        # 整列未返回（键不存在）同样 None，不转零
        row = _trade_row_full()
        del row["t_bcpay"]
        view = build_outpatient_facts(row)
        assert _item(view, "退休补充保险补助").value is None

    def test_blank_text_becomes_none(self):
        row = _trade_row_full()
        row["pn_persontype"] = "  "
        assert build_outpatient_facts(row).person_type is None

    def test_retire_officer_payment_and_flag_are_source_facts(self):
        row = {**_trade_row_full(), "retire_officer_pay": Decimal("44.30"), "retire_officer_flag": 1}
        view = build_outpatient_facts(row)
        assert view.retire_officer_flag == "1"
        assert _item(view, "退役医疗费支付").value == "44.30"
        row.update(retire_officer_pay=Decimal("0.00"), retire_officer_flag=0)
        view = build_outpatient_facts(row)
        assert view.retire_officer_flag == "0"
        assert _item(view, "退役医疗费支付").value == "0.00"
        view = build_outpatient_facts({})
        assert view.retire_officer_flag is None
        assert _item(view, "退役医疗费支付").value is None

    def test_retire_flag_uses_public_text_sanitizer(self):
        from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
        from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result

        facts = build_outpatient_facts({"retire_officer_flag": "source-flag"})
        view = to_public_contract_dict(_result(), summary_text="", summary_source="template",
            settlement_facts=facts, sanitize=lambda value: value.replace("source-flag", "cleaned"))
        assert view["settlement_facts"]["retire_officer_flag"] == "cleaned"


def _special_rows():
    settlement = {
        "djh": "814", "jyrq": "2024-05-06", "fyfs": "0", "zje": "100.00",
        "ptybn": "0.00", "ptybw": "0.00", "tsbybn": "90.00", "tsbybw": "10.00",
        "ybnqfje": "0.00", "grziftw": "5.00", "tczhf": "50.00", "tczif": "30.00",
        "degwyzhf": "0.00", "degwyzif": "0.00", "bczhf": "0.00", "jczhf": "0.00",
        "gfylbchbx": "0.00", "xjzf": "15.00", "zhzf": "0.00",
        "big_ill_pay": "0.00", "civil_in": None,
    }
    registration = {"djh": "814", "yllb": "12", "fund_type": "3", "cblb": "11"}
    return settlement, registration


class TestBuildSpecialMzFacts:
    def test_fund_payments_are_not_payment_methods(self):
        view = build_outpatient_facts(_trade_row_full())
        assert [item.label for item in view.payment_items] == ["个人账户支付", "现金支付"]
        assert _item(view, "民政救助支付").value == "0.00"

    def test_column_mapping_and_labels(self):
        view = build_special_mz_facts(*_special_rows())
        assert view.chain == "special"
        assert view.identifier == "814"
        assert view.trade_date == "2024-05-06"
        assert view.medical_category == "12"  # 登记行 yllb
        assert view.insurance_type == "3"  # 登记行 FUND_TYPE（小写键）
        assert view.person_type == "11"  # 登记行 cblb
        assert _item(view, "总费用").value == "100.00"
        assert _item(view, "特殊病医保内").value == "90.00"
        assert _item(view, "先行自付").value == "5.00"
        assert _item(view, "统筹基金支付").value == "50.00"
        assert _item(view, "大额互助支付").value == "0.00"  # 零值保留
        assert _item(view, "民政救助支付").value is None  # 缺失不转零
        assert _item(view, "账户支付", payment=True).value == "0.00"
        assert _item(view, "现金支付", payment=True).value == "15.00"
        assert _item(view, "个人支付总金额").value == "15.00"  # 原单无合计列：按账户+现金支付两列合计

    def test_missing_registration_row_degrades(self):
        view = build_special_mz_facts(_special_rows()[0], None)
        assert view.identifier == "814"
        assert view.medical_category is None
        assert view.insurance_type is None


# ── 四入口 DecompositionOutcome 接线 ──────────────────────────────


class TestOutpatientOutcomeWiring:
    def test_full_pipeline_returns_facts(self):
        from src.runtime.policy_qa.fee_decomposition.snapshot_service import (
            decompose_outpatient_trade,
        )
        outcome = decompose_outpatient_trade(
            helpers._service_conn(), "T001", "H001", MODE,
            profile_resolver=lambda _row: ("employee", "outpatient"))
        assert isinstance(outcome, DecompositionOutcome)
        assert outcome.result.execution_status in ("partial", "complete")
        facts = outcome.facts
        assert facts is not None and facts.chain == "outpatient"
        assert facts.identifier == "T001"
        assert facts.hospital_level == "14"
        assert _item(facts, "费用总金额").value == "3000.00"
        assert _item(facts, "医保范围外金额").value == "0.00"  # 零值保留

    def test_unavailable_after_trade_located_still_carries_facts(self):
        """无 resolver → UNSUPPORTED_PROFILE unavailable；事实区独立于算法（方案 §53）。"""
        from src.runtime.policy_qa.fee_decomposition.snapshot_service import (
            decompose_outpatient_trade,
        )
        outcome = decompose_outpatient_trade(helpers._service_conn(), "T001", "H001", MODE)
        assert outcome.result.execution_status == "unavailable"
        assert outcome.facts is not None
        assert outcome.facts.identifier == "T001"

    def test_trade_not_found_has_no_facts(self):
        """原始行未取到 → facts=None（不冒充已取到全单字段）。"""
        from src.runtime.policy_qa.fee_decomposition.snapshot_service import (
            decompose_outpatient_trade,
        )
        outcome = decompose_outpatient_trade(
            helpers._service_conn(trade_rows=[]), "T404", "H001", MODE)
        assert outcome.result.execution_status == "unavailable"
        assert outcome.facts is None


def _ok(data):
    return SimpleNamespace(status=AdapterCallStatus.SUCCESS, data=data, message=None)


class TestSpecialOutcomeWiring:
    def test_special_mz_unavailable_after_settlement_row_carries_facts(self, monkeypatch):
        """明细缺失（DETAIL_MISSING）→ unavailable，但结算/登记行已取到 → 携带 facts。"""
        from src.runtime.policy_qa.fee_decomposition import (
            snapshot_service_special_mz as svc,
        )
        settlement, registration = _special_rows()
        monkeypatch.setattr(svc, "locate_special_mz_registration", lambda *a: _ok(
            {"match_status": "unique_match", "registration_row": registration}))
        monkeypatch.setattr(svc, "load_special_mz_settlement", lambda *a: _ok(
            {"settlement_row": settlement}))
        monkeypatch.setattr(svc, "load_special_mz_fee_items", lambda *a: _ok(
            {"item_rows": [], "row_count": 0}))
        outcome = svc.decompose_special_mz_settlement(object(), "814", "H001", MODE)
        assert outcome.result.execution_status == "unavailable"
        facts = outcome.facts
        assert facts is not None and facts.chain == "special"
        assert facts.identifier == "814"
        assert _item(facts, "总费用").value == "100.00"

    def test_special_mz_registration_not_found_has_no_facts(self, monkeypatch):
        from src.runtime.policy_qa.fee_decomposition import (
            snapshot_service_special_mz as svc,
        )
        monkeypatch.setattr(svc, "locate_special_mz_registration", lambda *a: _ok(
            {"match_status": "not_found", "registration_row": None}))
        outcome = svc.decompose_special_mz_settlement(object(), "814", "H001", MODE)
        assert outcome.result.execution_status == "unavailable"
        assert outcome.facts is None

    def test_resident_special_carries_facts(self, monkeypatch):
        from src.runtime.policy_qa.fee_decomposition import (
            snapshot_service_special_mz_resident as svc,
        )
        settlement, registration = _special_rows()
        registration = {**registration, "fund_type": "93"}
        monkeypatch.setattr(svc, "locate_special_mz_resident_registration", lambda *a: _ok(
            {"match_status": "unique_match", "registration_row": registration}))
        monkeypatch.setattr(svc, "load_special_mz_settlement", lambda *a: _ok(
            {"settlement_row": settlement}))
        monkeypatch.setattr(svc, "load_special_mz_fee_items", lambda *a: _ok(
            {"item_rows": [], "row_count": 0}))
        outcome = svc.decompose_special_mz_resident_settlement(object(), "814", "H001", MODE)
        assert outcome.result.execution_status == "unavailable"
        assert outcome.facts is not None
        assert outcome.facts.insurance_type == "93"

    def test_fixed_kidney_keeps_facts_and_algorithm_version(self, monkeypatch):
        """肾定额入口委托职工门特服务：facts 透传，algorithm_version 覆盖不丢。"""
        import src.adapters.data_supply.outpatient_special_fixed_kidney_queries as kidney_q
        from src.runtime.policy_qa.fee_decomposition import (
            snapshot_service_special_mz as svc,
        )
        from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_fixed_kidney import (
            decompose_special_fixed_kidney_settlement,
        )
        settlement, registration = _special_rows()
        monkeypatch.setattr(kidney_q, "locate_special_fixed_kidney_registration",
                            lambda *a: _ok({"match_status": "unique_match",
                                            "registration_row": registration}))
        monkeypatch.setattr(kidney_q, "load_special_fixed_kidney_settlement",
                            lambda *a: _ok({"settlement_row": settlement}))
        monkeypatch.setattr(svc, "load_special_mz_fee_items", lambda *a: _ok(
            {"item_rows": [], "row_count": 0}))
        outcome = decompose_special_fixed_kidney_settlement(object(), "814", "H001", MODE)
        assert outcome.result.algorithm_version == "employee_special_fixed_kidney_v1"
        assert outcome.facts is not None
        assert outcome.facts.identifier == "814"
