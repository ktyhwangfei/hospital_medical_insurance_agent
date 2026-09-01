from datetime import datetime
from skills.mzsettlement_verify_skill.assembler import OutpatientSettlementVerifierAssembler
from pathlib import Path
from types import SimpleNamespace

import yaml

from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.skill_infra.skill_router import route_question, route_question_with_scores


PROFILE_QUESTIONS = {
    "overall-settlement-verification": "这次门诊结算对不对",
    "personal-liability-explanation": "为什么个人付这么多",
    "payment-channel-verification": "账户、现金和基金分别支付多少",
    "deductible-and-annual-progress": "为什么扣起付线，今年累计多少",
    "reimbursement-and-cap-verification": "为什么按这个报销比例，超过封顶了吗",
    "fee-item-scope-explanation": "哪个药产生了医保外费用",
    "eligibility-and-special-benefit": "慢特病和公务员待遇为什么没参与",
    "cross-region-and-institution": "异地门诊是否按这个医院等级结算",
    "transaction-status-and-refund": "这笔交易结算成功了吗",
}


def test_nine_profiles_route_and_only_request_published_metrics():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    registry.publish_object("mzjyxx")
    published = {
        metric.metric_code for metric in registry.list_object_versions("mzjyxx")[-1].metrics
    }
    assembler = OutpatientSettlementVerifierAssembler()
    manifest = yaml.safe_load(
        (Path(__file__).parents[1] / "skill_manifest.yaml").read_text(encoding="utf-8")
    )

    assert set(assembler.profile_ids) == set(PROFILE_QUESTIONS)
    assert {
        f"mzjyxx.{code}" for code in manifest["needed_objects"][0]["metrics"]
    } <= published
    for profile_id, question in PROFILE_QUESTIONS.items():
        assert assembler.detect_profile(question) == profile_id
        queries = assembler.build_semantic_queries("SET-001", profile_id)
        assert queries
        assert queries[0].scope.entity_code == "outpatient_transaction"
        assert queries[0].scope.anchor.field_code == "mz_trade.T_TradeNo"
        assert all(
            (code if "." in code else f"mzjyxx.{code}") in published
            for query in queries for code in query.metrics
        )


def test_procedure_questions_are_excluded_and_write_actions_require_human():
    assembler = OutpatientSettlementVerifierAssembler()

    assert assembler.detect_profile("如何办理异地就医备案") is None
    assert assembler.detect_profile("请帮我冲正这笔门诊结算") == (
        "transaction-status-and-refund"
    )
    assert assembler.requires_human_confirmation("请帮我冲正这笔门诊结算") is True
    assert assembler.requires_human_confirmation("立即执行门诊退费") is True


def test_manifest_exposes_all_profiles_and_query_object():
    manifest = yaml.safe_load(
        (Path(__file__).parents[1] / "skill_manifest.yaml").read_text(encoding="utf-8")
    )

    assert manifest["business_action"] == "verify"
    assert manifest["needed_objects"][0]["object_code"] == "mzjyxx"
    assert {
        item["profile_id"] for item in manifest["execution_contract"]["profiles"]
    } == set(PROFILE_QUESTIONS)


def test_query_result_builds_business_context_without_turning_missing_into_zero():
    assembler = OutpatientSettlementVerifierAssembler()
    result = SimpleNamespace(rows=[{
        "T_FeeAll": 100,
        "T_FeeIn": 80,
        "T_FeeOut": 20,
        "T_CashPay": 0,
        "T_PersonCountPay": None,
        "P_FundType": "职工基本医疗保险",
        "PN_PersonType": "退休",
        "T_CureType": "普通门诊",
        "HospitalLevel": "三级", "P_JCLevel": "不享受伤残待遇",
        "T_TradeDate": datetime(2026, 8, 26),
        "SETL_DATE": datetime(2026, 8, 26, 10, 30),
    }])

    context = assembler.build_context([result], "overall-settlement-verification")
    policy_context = assembler.build_policy_context(
        context, "overall-settlement-verification"
    )

    assert context.cash_payment == 0
    assert context.account_payment is None
    assert policy_context["险种"] == "职工基本医疗保险"
    assert policy_context["结算日期"] == "2026-08-26 00:00:00"
    assert context.additional_metrics["SETL_DATE"] == "2026-08-26 10:30:00"


def test_global_router_does_not_take_over_inpatient_or_procedure_questions():
    assert route_question("这次门诊结算对不对") == "mzsettlement_verify_skill"
    assert route_question("门诊起付线为什么扣了") == "mzsettlement_verify_skill"
    assert route_question("为什么个人付了186.21元") == "mzsettlement_verify_skill"
    assert route_question_with_scores("为什么个人付了186.21元？")[0].confidence >= 0.3
    assert route_question("住院起付线多少") == "settlement_explain_skill"
    assert route_question("如何办理异地就医备案") is None


def test_pooling_self_pay_followup_maps_to_personal_liability_profile():
    assembler = OutpatientSettlementVerifierAssembler()

    assert assembler.detect_profile("为什么统筹自付这么多") == (
        "personal-liability-explanation"
    )


def test_generic_outpatient_explanation_routes_to_overall_profile():
    assembler = OutpatientSettlementVerifierAssembler()

    assert route_question("请解释这笔门诊费用") == "mzsettlement_verify_skill"
    assert assembler.detect_profile("请解释这笔门诊费用") == (
        "overall-settlement-verification"
    )
    assert route_question("这个费用解释一下") == "mzsettlement_verify_skill"
    assert assembler.detect_profile("这个费用解释一下") == (
        "overall-settlement-verification"
    )


def test_personal_liability_queries_summary_and_fee_item_breakdown():
    assembler = OutpatientSettlementVerifierAssembler()

    queries = assembler.build_semantic_queries(
        "TRADE-1", "personal-liability-explanation"
    )

    assert len(queries) == 2
    assert queries[1].scope.query_scope == "fee_item"
    assert "mzjyxx.FeeItem_SelfPay2" in queries[1].metrics


def test_non_amount_profile_facts_are_explained_with_business_labels():
    assembler = OutpatientSettlementVerifierAssembler()
    context = assembler.build_context(
        [SimpleNamespace(rows=[{
            "T_FeeAll": 100,
            "T_State": "已结算",
            "T_HasRefundmented": 0,
            "NP_Settle_State": "成功",
        }])],
        "transaction-status-and-refund",
    )

    result = assembler.execute(
        context, profile_id="transaction-status-and-refund"
    )
    checks = {item.name: item.value for item in result.context_checks}

    assert checks["交易状态"] == "已结算"
    assert checks["是否已退费"] == "0"
    assert not any("T_" in item.name or "NP_" in item.name for item in result.context_checks)
    assert result.status != "unavailable"


def test_profile_does_not_report_unrequested_amounts_as_missing():
    assembler = OutpatientSettlementVerifierAssembler()
    context = assembler.build_context(
        [SimpleNamespace(rows=[{
            "T_SelfPayAll": 20,
            "T_SelfPay1": 10,
            "T_SelfPay2": 10,
            "T_BigSelfPay": 0,
            "T_FirstPay": 5,
            "T_FeeIn": 10,
            "T_FeeOut": 10,
            "T_FundPay": 0,
            "T_OfficalPay": 0,
            "T_PersonCountPay": 20,
            "T_CashPay": 0,
            "P_FundType": "职工",
            "PN_PersonType": "在职",
            "T_CureType": "普通门诊",
            "HospitalLevel": "三级", "P_JCLevel": "不享受伤残待遇",
            "T_TradeDate": "2026-08-26",
        }])],
        "personal-liability-explanation",
    )

    result = assembler.execute(
        context,
        profile_id="personal-liability-explanation",
        policy_evidence=[{"source_id": "POLICY-1"}],
    )

    assert {item.field_name for item in result.field_explanations} == {
        "个人支付总金额", "个人自付一", "个人自付二", "大额自付",
        "起付金额", "个人账户支付", "现金支付", "医保范围内金额",
        "医保范围外金额", "基金支付总金额", "单位补充医疗支付",
    }
    assert result.status == "complete"


def test_profile_core_amount_controls_unavailable_without_blocking_status_profile():
    assembler = OutpatientSettlementVerifierAssembler()
    missing_personal_total = assembler.build_context(
        [SimpleNamespace(rows=[{"T_SelfPay1": 10}])],
        "personal-liability-explanation",
    )
    status_only = assembler.build_context(
        [SimpleNamespace(rows=[{"T_State": "已结算"}])],
        "transaction-status-and-refund",
    )
    missing_status = assembler.build_context(
        [SimpleNamespace(rows=[{"T_HasRefundmented": 0}])],
        "transaction-status-and-refund",
    )

    assert assembler.execute(
        missing_personal_total,
        profile_id="personal-liability-explanation",
        policy_evidence=[{"source_id": "POLICY-1"}],
    ).status == "unavailable"
    assert assembler.execute(
        status_only,
        profile_id="transaction-status-and-refund",
        policy_evidence=[{"source_id": "POLICY-1"}],
    ).status != "unavailable"
    assert assembler.execute(
        missing_status,
        profile_id="transaction-status-and-refund",
        policy_evidence=[{"source_id": "POLICY-1"}],
    ).status == "unavailable"


def test_duplicate_trade_rows_are_unavailable_instead_of_using_first_row():
    assembler = OutpatientSettlementVerifierAssembler()
    context = assembler.build_context(
        [SimpleNamespace(rows=[{"T_FeeAll": 100}, {"T_FeeAll": 100}])],
        "overall-settlement-verification",
    )

    result = assembler.execute(
        context,
        profile_id="overall-settlement-verification",
        policy_evidence=[{"source_id": "POLICY-1"}],
    )

    assert result.status == "unavailable"
    assert any("返回 2 条" in item for item in result.uncertainties)


def test_fee_item_profile_keeps_item_dimensions_and_business_labels():
    assembler = OutpatientSettlementVerifierAssembler()
    detail_query = assembler.build_semantic_queries(
        "TRADE-1", "fee-item-scope-explanation"
    )[1]
    assert "mz_fee_item.ItemCode" in detail_query.group_by
    assert "mzjyxx.ItemCode" not in detail_query.metrics

    context = assembler.build_context([
        SimpleNamespace(rows=[{
            "T_FeeAll": 10, "T_FeeIn": 8, "T_FeeOut": 2, "T_SelfPay2": 0,
            "P_FundType": "职工", "PN_PersonType": "在职",
            "T_CureType": "普通门诊", "HospitalLevel": "三级",
            "P_JCLevel": "不享受伤残待遇",
            "T_TradeDate": "2026-08-26",
        }]),
        SimpleNamespace(rows=[{
            "ItemName": "测试药品", "ItemCode": "ITEM-1", "StandardCode": "STD-1",
            "ItemType": "药品", "FeeType": "西药费", "F_LEVEL": "乙类",
            "Fee": 10, "FeeIn": 8, "FeeOut": 2, "FeeItem_SelfPay2": 0,
            "FEE_SP_SCALE": 0.1, "FEE_MEDIC_L": 9, "MEDIC_L": 10,
            "SPEDRUG_FLAG": 0, "State": 0,
        }]),
    ], "fee-item-scope-explanation")
    result = assembler.execute(
        context, profile_id="fee-item-scope-explanation",
        policy_evidence=[{"source_id": "POLICY-1"}],
    )
    detail = next(item.value for item in result.context_checks if item.name == "费用明细 1")

    assert "项目编码=ITEM-1" in detail
    assert "先自付比例=0.1" in detail
    assert "ItemCode" not in detail


def test_policy_queries_use_supported_rule_types_and_settlement_dimensions():
    assembler = OutpatientSettlementVerifierAssembler()
    context = assembler.build_context(
        [SimpleNamespace(rows=[{
            "P_FundType": "职工基本医疗保险", "PN_PersonType": "退休人员",
            "T_CureType": "普通门诊", "HospitalLevel": "三级",
            "P_JCLevel": "不享受伤残待遇",
        }])],
        "reimbursement-and-cap-verification",
    )

    queries = assembler.build_policy_queries(
        "reimbursement-and-cap-verification", context
    )

    assert {item.filters["rule_type"] for item in queries} == {"支付比例", "封顶线"}
    assert all(item.filters["insu_type"] == "城镇职工基本医疗保险" for item in queries)
    assert all(item.filters["med_type"] == "门诊-普通门急诊" for item in queries)
    assert all(item.filters["psn_type"] == "退休人员" for item in queries)
    assert all(item.filters["hosp_lv"] == "三级" for item in queries)
    assert all(item.search_text for item in queries)
    assert all(item.exact_match_fields == ["insu_type", "med_type"] for item in queries)

    age_band_context = context.model_copy(update={
        "person_type": "70岁以上退休人员",
    })
    age_band_queries = assembler.build_policy_queries(
        "reimbursement-and-cap-verification", age_band_context
    )
    assert all(
        item.filters["psn_type"] == "70岁以上退休人员"
        for item in age_band_queries
    )


def test_personal_liability_policy_queries_require_relevant_text_and_context():
    assembler = OutpatientSettlementVerifierAssembler()
    context = assembler.build_context(
        [SimpleNamespace(rows=[{
            "P_FundType": "公疗医照", "PN_PersonType": "在职正部级医疗照顾人员",
            "T_CureType": "普通急诊", "HospitalLevel": "三级",
        }])],
        "personal-liability-explanation",
    )

    queries = assembler.build_policy_queries(
        "personal-liability-explanation", context
    )

    assert {item.filters["rule_type"] for item in queries} == {
        "起付线", "支付比例", "排除规则",
    }
    assert all(item.search_text for item in queries)
    assert all(item.exact_match_fields == ["insu_type", "med_type"] for item in queries)
