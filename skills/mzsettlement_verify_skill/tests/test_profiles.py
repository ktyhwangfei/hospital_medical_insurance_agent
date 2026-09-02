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


def test_personal_total_payment_followup_maps_to_personal_liability_profile():
    assembler = OutpatientSettlementVerifierAssembler()

    # 缺陷复现：用户按结算单字段名追问「个人支付总金额」时，
    # 「个人付」hint 因中间插入「支」无法子串命中，落入 overall 通用 dump。
    assert assembler.detect_profile("个人支付总金额为什么这么多14.40 元") == (
        "personal-liability-explanation"
    )
    assert assembler.detect_profile("个人负担为什么是14.40") == (
        "personal-liability-explanation"
    )


def test_personal_liability_answer_renders_reconciliation_equations():
    assembler = OutpatientSettlementVerifierAssembler()
    # 复现 person-11 场景：个人支付总 14.40 的因果依赖费用总额与退役医疗支付两个字段
    context = assembler.build_context(
        [
            SimpleNamespace(rows=[{
                "T_FeeAll": "90.00",
                "T_FeeIn": "84.00",
                "T_FeeOut": "6.00",
                "T_FundPay": "75.60",
                "T_BigPay": "58.80",
                "T_SelfPayAll": "14.40",
                "T_SelfPay1": "25.20",
                "T_SelfPay2": "6.00",
                "T_BigSelfPay": "25.20",
                "T_FirstPay": "0.00",
                "T_OfficalPay": "0.00",
                "T_PersonCountPay": "0.00",
                "T_CashPay": "14.40",
                "RETIRE_OFFICER_PAY": "16.80",
                "P_FundType": "城镇职工",
                "PN_PersonType": "在职",
                "T_CureType": "普通急诊",
                "HospitalLevel": "三级",
                "P_JCLevel": "不享受伤残待遇",
                "T_TradeDate": "2024-09-13 15:04:37",
            }]),
            SimpleNamespace(rows=[
                {
                    "ItemName": "复方丹参滴丸", "Fee": "20.00",
                    "FeeIn": "20.00", "FeeOut": "0.00", "FeeItem_SelfPay2": "0.00",
                },
                {
                    "ItemName": "真空采血管", "Fee": "10.00",
                    "FeeIn": "10.00", "FeeOut": "0.00", "FeeItem_SelfPay2": "0.00",
                },
                {
                    "ItemName": "注射用培美曲塞二钠",
                    "Fee": "60.00",
                    "FeeIn": "54.00",
                    "FeeOut": "6.00",
                    "FeeItem_SelfPay2": "6.00",
                },
            ]),
        ],
        "personal-liability-explanation",
    )

    result = assembler.execute(
        context,
        profile_id="personal-liability-explanation",
        policy_evidence=[{"source_id": "POLICY-1"}],
    )
    answer = result.summary

    # 新增字段仍随场景采集（结构化输出供前端卡片），文本不再整段罗列
    fields = {item.field_name: str(item.value) for item in result.field_explanations}
    assert fields["费用总金额"] == "90.00"
    assert fields["退役医疗支付"] == "16.80"
    assert "费用金额（取结算单原始字段）" not in answer
    # 首行直接给出核心分解算式，回答「个人支付总金额为什么这么多」
    assert (
        "个人支付总金额 14.40 元 = 费用总金额 90.00 元 - 基金支付总金额 75.60 元"
        in answer.splitlines()[0]
    )
    # 费用分解：逐层拆到根（自付一/自付二来源、专项渠道替付、账户/现金分摊）
    assert "费用分解" in answer
    assert (
        "个人自付一 25.20 元 = 医保范围内金额 84.00 元 - 门诊大额基金支付 58.80 元"
        in answer
    )
    assert (
        "个人自付二 6.00 元 = 费用明细先自付合计：注射用培美曲塞二钠 6.00 元"
        in answer
    )
    assert (
        "个人支付总金额 14.40 元 = 统筹自付（自付一 + 自付二）31.20 元"
        " - 退役医疗支付 16.80 元" in answer
    )
    assert "个人账户支付 0.00 元 + 现金支付 14.40 元" in answer
    # 问题相关性精简：有分解段时不再重复渲染勾稽段
    assert "金额勾稽" not in answer
    # 与个人负担无关的费用明细（先自付为 0）不进入回答
    assert "复方丹参滴丸" not in answer
    assert "真空采血管" not in answer
    # 先自付相关明细保留且只保留关键字段
    assert "先自付相关" in answer and "项目编码" not in answer
    assert result.status != "unavailable"


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
            "T_FeeAll": "20.00",
            "T_SelfPayAll": 20,
            "T_SelfPay1": 10,
            "T_SelfPay2": 10,
            "T_BigSelfPay": 0,
            "T_FirstPay": 5,
            "T_FeeIn": 10,
            "T_FeeOut": 10,
            "T_FundPay": 0,
            "T_BigPay": 0,
            "T_BCPay": 0,
            "T_BigillPay": 0,
            "T_JCPay": 0,
            "NT_CivilPay": 0,
            "T_OfficalPay": 0,
            "T_PersonCountPay": 20,
            "T_CashPay": 0,
            "RETIRE_OFFICER_PAY": 0,
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
        "费用总金额", "退役医疗支付", "门诊大额基金支付", "补充保险支付",
        "大病支付", "军残补助支付", "医疗救助支付",
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


def test_deductible_profile_explains_zero_deductible_via_annual_accumulation():
    """起付金额 0 + 年度累计非零 → 解读为年度累计口径下起付已过线，基金照常支付。"""
    assembler = OutpatientSettlementVerifierAssembler()
    context = assembler.build_context(
        [SimpleNamespace(rows=[{
            "T_FirstPay": "0.00",
            "TB_FeeIn": "19391.00",
            "TA_FeeIn": "19475.00",
            "T_BigPay": "58.80",
            "P_FundType": "城镇职工",
            "PN_PersonType": "在职",
            "T_CureType": "普通急诊",
            "HospitalLevel": "三级",
            "P_JCLevel": "不享受伤残待遇",
            "T_TradeDate": "2024-09-13 15:04:37",
        }])],
        "deductible-and-annual-progress",
    )

    with_policy = assembler.execute(
        context,
        profile_id="deductible-and-annual-progress",
        policy_evidence=[
            {"source_id": "POLICY-1", "rule_type": "起付线", "rule_value": "1800元"},
        ],
    )
    answer = with_policy.summary
    assert "起付线解读" in answer
    assert "起付线按年度累计口径" in answer
    assert "19391.00 元" in answer
    assert "不再重复收取起付" in answer
    assert "门诊大额基金支付 58.80 元" in answer
    assert "1800" in answer  # 政策门槛被引用

    without_policy = assembler.execute(
        context, profile_id="deductible-and-annual-progress", policy_evidence=[]
    )
    assert any("起付线金额政策" in item for item in without_policy.uncertainties)


def test_overall_profile_includes_fee_decomposition_with_payor_identity():
    """总体核验也要讲费用构成故事：支付方恒等式置首，起付拆解进入分解段。"""
    assembler = OutpatientSettlementVerifierAssembler()
    context = assembler.build_context(
        [SimpleNamespace(rows=[{
            "T_FeeAll": "3000.00", "T_FeeIn": "2400.00", "T_FeeOut": "600.00",
            "T_FundPay": "420.00", "T_BigPay": "420.00",
            "T_SelfPayAll": "2580.00", "T_SelfPay1": "1980.00", "T_SelfPay2": "600.00",
            "T_BigSelfPay": "180.00", "T_FirstPay": "1800.00",
            "T_PersonCountPay": "260.80", "T_CashPay": "2319.20",
            "P_FundType": "城镇职工", "PN_PersonType": "在职",
            "T_CureType": "普通门诊", "P_JCLevel": "不享受伤残待遇",
            "T_TradeDate": "2024-11-20 09:44:26",
        }])],
        "overall-settlement-verification",
    )

    result = assembler.execute(
        context,
        profile_id="overall-settlement-verification",
        policy_evidence=[{"source_id": "POLICY-1"}],
    )
    answer = result.summary

    assert "费用分解" in answer
    # 支付方恒等式置首，保证费用组成三要素在精简文本中仍完整
    assert (
        "费用总金额 3000.00 元 = 基金支付总金额 420.00 元 + 个人支付总金额 2580.00 元"
        in answer
    )
    # 阶段故事（起付段）进入总体回答
    assert "起付金额 1800.00 元" in answer
    assert "个人自付一 1980.00 元" in answer
    assert "医保范围内金额 2400.00 元" in answer
    # 有分解段时不再重复整段罗列字段与勾稽段（前端卡片仍展示结构化字段）
    assert "费用金额（取结算单原始字段）：" not in answer
    assert "金额勾稽（取结算单原始字段确定性核算）" not in answer


def test_large_self_pay_question_routes_and_focuses_on_large_self_pay():
    """「大额自付为什么这么多」要命中个人负担场景且首行讲大额自付。"""
    assembler = OutpatientSettlementVerifierAssembler()

    assert assembler.detect_profile("大额自付为什么这么多") == (
        "personal-liability-explanation"
    )

    # 恒等式不成立的单（如 person-803）：自付一行走渠道版，仍要有大额自付事实行作首行
    context = assembler.build_context(
        [SimpleNamespace(rows=[{
            "T_FeeAll": "90.00", "T_FeeIn": "84.00", "T_FeeOut": "6.00",
            "T_FundPay": "79.80", "T_BigPay": "67.20",
            "T_SelfPayAll": "10.20", "T_SelfPay1": "12.60", "T_SelfPay2": "6.00",
            "T_BigSelfPay": "16.80", "T_FirstPay": "0.00",
            "T_PersonCountPay": "0.00", "T_CashPay": "10.20",
            "T_BCPay": "8.40", "T_OfficalPay": "4.20",
            "P_FundType": "城镇职工", "PN_PersonType": "在职",
            "T_CureType": "普通门诊", "P_JCLevel": "不享受伤残待遇",
            "T_TradeDate": "2024-09-13 00:00:00",
        }])],
        "personal-liability-explanation",
    )
    result = assembler.execute(
        context,
        profile_id="personal-liability-explanation",
        policy_evidence=[{"source_id": "POLICY-1"}],
        question="大额自付为什么这么多",
    )
    headline = result.summary.splitlines()[0]
    assert "大额自付 16.80 元" in headline
    assert "医保范围内" in headline


def test_personal_liability_headline_follows_asked_field_and_splits_deductible():
    """问自付一时首行讲自付一；起付>0 且恒等式成立时拆为起付段+统筹段。"""
    assembler = OutpatientSettlementVerifierAssembler()
    context = assembler.build_context(
        [SimpleNamespace(rows=[{
            "T_FeeAll": "3000.00", "T_FeeIn": "2400.00", "T_FeeOut": "600.00",
            "T_FundPay": "420.00", "T_BigPay": "420.00",
            "T_SelfPayAll": "2580.00", "T_SelfPay1": "1980.00", "T_SelfPay2": "600.00",
            "T_BigSelfPay": "180.00", "T_FirstPay": "1800.00",
            "T_PersonCountPay": "260.80", "T_CashPay": "2319.20",
            "P_FundType": "城镇职工", "PN_PersonType": "在职",
            "T_CureType": "普通门诊", "P_JCLevel": "不享受伤残待遇",
            "T_TradeDate": "2024-11-20 09:44:26",
        }])],
        "personal-liability-explanation",
    )

    result = assembler.execute(
        context,
        profile_id="personal-liability-explanation",
        policy_evidence=[{"source_id": "POLICY-1"}],
        question="个人自付一为什么这么多",
    )
    answer = result.summary
    headline = answer.splitlines()[0]
    # 首行跟随所问字段，且拆到根：起付段 + 统筹段个人分担
    assert "个人自付一 1980.00 元" in headline
    assert "起付金额 1800.00 元" in headline
    assert "大额自付 180.00 元" in headline
    # 首行不重复出现在分解段，其余分解行保留
    assert answer.count("个人自付一 1980.00 元") == 1
    assert "个人支付总金额 2580.00 元 = 统筹自付" in answer
    assert "个人自付二 600.00 元" in answer


def test_deductible_question_by_field_name_routes_to_deductible_profile():
    """用户按字段名问「起付金额」也要命中起付线场景，不能因子串不匹配落入总体 dump。"""
    assembler = OutpatientSettlementVerifierAssembler()

    assert assembler.detect_profile("为什么起付金额这么多") == (
        "deductible-and-annual-progress"
    )


def test_reimbursement_queries_annual_big_pay_accumulation():
    """封顶解读依赖年度大额支付累计，场景查询必须请求 TB/TA_BigPay。"""
    assembler = OutpatientSettlementVerifierAssembler()

    queries = assembler.build_semantic_queries(
        "TRADE-1", "reimbursement-and-cap-verification"
    )
    metrics = queries[0].metrics
    assert "mzjyxx.TB_BigPay" in metrics
    assert "mzjyxx.TA_BigPay" in metrics


def test_reimbursement_profile_explains_cap_progress_from_annual_accumulation():
    """大额段/超封顶阶段解读：陈述年度累计与本笔支付事实，门槛值声明不确定性。"""
    assembler = OutpatientSettlementVerifierAssembler()
    near_cap = assembler.build_context(
        [SimpleNamespace(rows=[{
            "T_FeeIn": "221.50", "T_FirstPay": "0.00", "T_BigPay": "155.05",
            "T_BigSelfPay": "66.45", "T_BeyondBig": "0.00",
            "TB_BigPay": "12158.69", "TA_BigPay": "12313.74",
            "P_FundType": "城镇职工", "PN_PersonType": "在职",
            "T_CureType": "普通门诊", "P_JCLevel": "不享受伤残待遇",
            "T_TradeDate": "2024-09-13 15:04:27",
        }])],
        "reimbursement-and-cap-verification",
    )
    result = assembler.execute(
        near_cap,
        profile_id="reimbursement-and-cap-verification",
        policy_evidence=[{"source_id": "POLICY-1"}],
    )
    answer = result.summary
    assert "封顶与大额段解读" in answer
    assert "12158.69" in answer and "12313.74" in answer
    assert "155.05 元 正常报销" in answer
    assert any("门诊大额封顶线" in item for item in result.uncertainties)

    over_cap = assembler.build_context(
        [SimpleNamespace(rows=[{
            "T_FeeIn": "84.00", "T_FirstPay": "0.00", "T_BigPay": "0.00",
            "T_BigSelfPay": "21.00", "T_BeyondBig": "84.00",
            "TB_BigPay": "5000.00", "TA_BigPay": "5000.00",
            "P_FundType": "城镇居民基本医疗保险_无保障老年人", "PN_PersonType": "城镇老年人",
            "T_CureType": "普通急诊", "P_JCLevel": "不享受伤残待遇",
            "T_TradeDate": "2024-09-14 00:00:00",
        }])],
        "reimbursement-and-cap-verification",
    )
    over_result = assembler.execute(
        over_cap,
        profile_id="reimbursement-and-cap-verification",
        policy_evidence=[{"source_id": "POLICY-1"}],
    )
    over_answer = over_result.summary
    assert "本笔超封顶金额 84.00 元" in over_answer
    assert "超出部分医保基金不再支付、由个人承担" in over_answer


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
