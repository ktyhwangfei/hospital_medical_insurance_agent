"""
医保政策问答RAG系统 - 单元测试

测试policy_qa模块的各个组件
"""

import pytest

# 设置环境变量
import os
os.environ["USE_MEMORY_STORAGE"] = "1"


class TestPolicyQAModels:
    """测试policy_qa模型"""

    def test_policy_qa_response_has_single_answer(self):
        from src.runtime.policy_qa.models import PolicyQAResponse

        response = PolicyQAResponse(
            step="answer_generation",
            status="done",
            answer="已完成解释",
            answer_status="complete",
        )
        assert response.answer == "已完成解释"
        assert response.answer_status == "complete"
        assert not hasattr(response, "patient_view")
        assert not hasattr(response, "office_view")

    def test_policy_qa_intent_enum(self):
        """测试PolicyQAIntent枚举"""
        from src.runtime.policy_qa.models import PolicyQAIntent

        assert PolicyQAIntent.FEE_DECOMPOSITION.value == "fee_decomposition"
        assert PolicyQAIntent.TREATMENT_DECOMPOSITION.value == "treatment_decomposition"
        assert PolicyQAIntent.DEDUCTIBLE.value == "deductible"
        assert PolicyQAIntent.PAYMENT_RATIO.value == "payment_ratio"
        assert PolicyQAIntent.CAP_AMOUNT.value == "cap_amount"
        assert PolicyQAIntent.GENERAL.value == "general"

    def test_policy_qa_request(self):
        """测试PolicyQARequest模型"""
        from src.runtime.policy_qa.models import PolicyQARequest

        request = PolicyQARequest(
            question="为什么我的费用是这些？",
            settlement_id="1671213",
        )
        assert request.question == "为什么我的费用是这些？"
        assert request.settlement_id == "1671213"
        assert request.session_id is None

    def test_policy_qa_request_with_session(self):
        """测试PolicyQARequest模型（带session_id）"""
        from src.runtime.policy_qa.models import PolicyQARequest

        request = PolicyQARequest(
            question="为什么我的费用是这些？",
            settlement_id="1671213",
            session_id="test-session-123",
        )
        assert request.question == "为什么我的费用是这些？"
        assert request.settlement_id == "1671213"
        assert request.session_id == "test-session-123"

    def test_policy_qa_intent_result(self):
        """测试PolicyQAIntentResult模型"""
        from src.runtime.policy_qa.models import PolicyQAIntent, PolicyQAIntentResult

        result = PolicyQAIntentResult(
            intent=PolicyQAIntent.FEE_DECOMPOSITION,
            settlement_id="1671213",
            need_patient_data=True,
            query_type="费用分解",
            confidence=0.9,
        )
        assert result.intent == PolicyQAIntent.FEE_DECOMPOSITION
        assert result.settlement_id == "1671213"
        assert result.need_patient_data is True
        assert result.query_type == "费用分解"
        assert result.confidence == 0.9

    def test_intent_result_supports_target_fee_item(self):
        """测试意图结果支持结构化目标费用项"""
        from src.runtime.policy_qa.models import PolicyQAIntent, PolicyQAIntentResult

        result = PolicyQAIntentResult(
            intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
            settlement_id="1671213",
            need_patient_data=True,
            query_type="统筹自付解释",
            confidence=0.95,
            target_fee_item="pooling_self_pay",
            target_fee_label="统筹自付",
        )

        assert result.need_patient_data is True
        assert result.query_type == "统筹自付解释"
        assert result.confidence == 0.95
        assert result.target_fee_item == "pooling_self_pay"
        assert result.target_fee_label == "统筹自付"

    def test_rewritten_question_separates_search_query_and_context(self):
        """测试重写问题区分检索问题与解释上下文"""
        from src.runtime.policy_qa.models import RewrittenQuestion

        rewritten = RewrittenQuestion(
            original="为什么我这次统筹自付这么多？",
            rewritten="城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例",
            search_query="城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例",
            explanation_context={
                "fund_type": "城镇职工",
                "person_type": "退休",
                "medical_type": "普通住院",
                "pooling_self_pay": 4962.67,
            },
            semantic_mappings={"统筹自付": "pooling_self_pay"},
            warnings=["检索问题已去除个人金额上下文"],
        )

        assert rewritten.original == "为什么我这次统筹自付这么多？"
        assert rewritten.rewritten == "城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例"
        assert rewritten.search_query == "城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例"
        assert "【业务上下文】" not in rewritten.search_query
        assert rewritten.explanation_context == {
            "fund_type": "城镇职工",
            "person_type": "退休",
            "medical_type": "普通住院",
            "pooling_self_pay": 4962.67,
        }
        assert rewritten.explanation_context["person_type"] == "退休"
        assert rewritten.explanation_context["pooling_self_pay"] == 4962.67
        assert rewritten.semantic_mappings == {"统筹自付": "pooling_self_pay"}
        assert rewritten.warnings == ["检索问题已去除个人金额上下文"]

    def test_sql_query_result(self):
        """测试SQLQueryResult模型"""
        from src.runtime.policy_qa.models import SQLQueryResult

        result = SQLQueryResult()
        assert result.yb_zyfdxx == {}
        assert result.yb_zyfymx == []
        assert result.yb_dyxxnd == {}
        assert result.yb_dyxxzy == {}
        assert result.yb_brdjxx == {}

    def test_segment_info(self):
        """测试SegmentInfo模型"""
        from src.runtime.policy_qa.models import SegmentInfo

        info = SegmentInfo(
            lower=650.0,
            upper=30000.0,
            amount=29350.0,
            base_ratio=0.15,
            person_ratio=0.6,
            actual_ratio=0.09,
            pay=2641.50,
            calculation="29,350.00 × 15% × 60% = 29,350.00 × 9% = 2,641.50",
        )
        assert info.lower == 650.0
        assert info.upper == 30000.0
        assert info.amount == 29350.0
        assert info.base_ratio == 0.15
        assert info.person_ratio == 0.6
        assert info.actual_ratio == 0.09
        assert info.pay == 2641.50

    def test_segment_calculation_result(self):
        """测试SegmentCalculationResult模型"""
        from src.runtime.policy_qa.models import SegmentCalculationResult, SegmentInfo

        result = SegmentCalculationResult()
        assert result.segments == []
        assert result.total_pay == 0.0

        result.segments.append(SegmentInfo(
            lower=650.0,
            upper=30000.0,
            amount=29350.0,
            base_ratio=0.15,
            person_ratio=0.6,
            actual_ratio=0.09,
            pay=2641.50,
        ))
        result.total_pay = 2641.50

        assert len(result.segments) == 1
        assert result.total_pay == 2641.50

    def test_segment_calculation_result_supports_reconciliation_and_warnings(self):
        """测试分段计算结果支持权威金额对账与告警"""
        from src.runtime.policy_qa.models import SegmentCalculationResult

        result = SegmentCalculationResult(
            total_pay=4962.68,
            authoritative_amount=4962.67,
            reconciliation_difference=0.01,
            reconciliation_tolerance=0.01,
            reconciliation_matched=True,
            reconciliation_message="政策解释计算与业务库金额一致",
            warnings=["按现有字段估算统筹分段基数"],
        )

        assert result.total_pay == 4962.68
        assert result.authoritative_amount == 4962.67
        assert result.reconciliation_difference == 0.01
        assert result.reconciliation_tolerance == 0.01
        assert result.reconciliation_matched is True
        assert result.reconciliation_message == "政策解释计算与业务库金额一致"
        assert result.warnings == ["按现有字段估算统筹分段基数"]


class TestFeeDecompositionSkill:
    """测试费用拆分计算Skill"""

    def test_skill_import(self):
        """测试Skill是否可以导入"""
        try:
            from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
            assert True
        except ImportError:
            pytest.skip("FeeDecompositionSkill not available")

    def test_skill_initialization(self):
        """测试Skill是否可以初始化"""
        try:
            from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
            skill = FeeDecompositionSkill()
            assert skill is not None
        except ImportError:
            pytest.skip("FeeDecompositionSkill not available")

    def test_parse_band(self):
        """测试分段解析"""
        try:
            from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
            skill = FeeDecompositionSkill()

            # 测试解析分段
            lower, upper = skill._parse_band("650-30000")
            assert lower == 650.0
            assert upper == 30000.0

            # 测试解析无限大
            lower, upper = skill._parse_band("40000-inf")
            assert lower == 40000.0
            assert upper == float("inf")

            # 测试解析单个值
            lower, upper = skill._parse_band("1000")
            assert lower == 1000.0
            assert upper == float("inf")

        except ImportError:
            pytest.skip("FeeDecompositionSkill not available")

    def test_get_person_ratio(self):
        """测试人员系数"""
        try:
            from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
            skill = FeeDecompositionSkill()

            # 测试退休人员
            patient = {"PER_TYPE": "2"}
            ratio = skill._get_person_ratio(patient)
            assert ratio == 0.6

            # 测试在职人员
            patient = {"PER_TYPE": "1"}
            ratio = skill._get_person_ratio(patient)
            assert ratio == 1.0

            # 测试未知人员
            patient = {"PER_TYPE": "99"}
            ratio = skill._get_person_ratio(patient)
            assert ratio == 1.0

        except ImportError:
            pytest.skip("FeeDecompositionSkill not available")

    def test_calculate_segmented(self):
        """测试分段计算"""
        try:
            from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
            skill = FeeDecompositionSkill()

            # 测试分段计算（5元组：lower, upper, base_ratio, rule_id, policy_source）
            segments = [
                (650, 30000, 0.15, "rule_1", "起付线以上至3万元部分，自付比例15%"),
                (30000, 40000, 0.10, "rule_2", "3万至4万元部分，自付比例10%"),
                (40000, float("inf"), 0.05, "rule_3", "4万元以上部分，自付比例5%"),
            ]
            result = skill._calculate_segmented(
                amount=97372.18,
                segments=segments,
                person_ratio=0.6,
                deductible=650,
            )

            # 验证计算结果
            assert len(result.segments) == 3
            assert abs(result.total_pay - 4962.67) < 0.01

        except ImportError:
            pytest.skip("FeeDecompositionSkill not available")

    def test_get_person_ratio_recognizes_retired_text(self):
        """人员系数不能只依赖数字代码，也要识别退休文本。"""
        from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill

        skill = FeeDecompositionSkill()

        assert skill._get_person_ratio({"PER_TYPE": "退休"}) == 0.6
        assert skill._get_person_ratio({"PER_TYPE": "退休人员"}) == 0.6
        assert skill._get_person_ratio({"PER_TYPE": "在职"}) == 1.0

    def test_decompose_pooling_self_pay_reconciles_with_authoritative_amount(self):
        """统筹自付以业务库金额为权威值，并保存分段解释计算值。"""
        from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
        from src.runtime.policy_qa.models import PolicyRule, SQLQueryResult

        sql_result = SQLQueryResult(
            yb_brdjxx={"PER_TYPE": "退休", "PER_TYPE_raw": "退休人员"},
            yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
            yb_zyfdxx={
                "bdfyzje": 189085.85,
                "bdybnzje": 164411.81,
                "bdtczf": 4962.67,
                "bdtczfje": 91759.51,
                "bddegwyzf": 13407.93,
                "bddegwyzfje": 53631.71,
                "bdgryf": 43694.67,
            },
        )
        rules = [
            PolicyRule(
                rule_id="r1",
                rule_type="统筹分段",
                amount_band="650-30000",
                payment_ratio="0.15",
                source_text="起付线以上至3万元部分，自付比例15%",
            ),
            PolicyRule(
                rule_id="r2",
                rule_type="统筹分段",
                amount_band="30000-40000",
                payment_ratio="0.10",
                source_text="3万元至4万元部分，自付比例10%",
            ),
            PolicyRule(
                rule_id="r3",
                rule_type="统筹分段",
                amount_band="40000-inf",
                payment_ratio="0.05",
                source_text="4万元以上部分，自付比例5%",
            ),
        ]

        result = FeeDecompositionSkill().decompose(sql_result, rules)

        assert result.treatment.pooling_self_pay.value == 4962.67
        assert result.segments.authoritative_amount == 4962.67
        assert result.segments.reconciliation_tolerance == 0.01
        assert result.segments.reconciliation_matched is False
        assert "政策解释计算与结算结果存在差异，需要人工复核" in result.segments.reconciliation_message
        assert any("估算统筹分段基数" in warning for warning in result.segments.warnings)


class TestQuestionRewriter:
    """测试问题重写器"""

    def test_rewriter_import(self):
        """测试重写器是否可以导入"""
        try:
            from src.runtime.policy_qa.question_rewriter import QuestionRewriter
            assert True
        except ImportError:
            pytest.skip("QuestionRewriter not available")

    def test_rewriter_initialization(self):
        """测试重写器是否可以初始化"""
        try:
            from src.runtime.policy_qa.question_rewriter import QuestionRewriter
            rewriter = QuestionRewriter()
            assert rewriter is not None
        except ImportError:
            pytest.skip("QuestionRewriter not available")

    @pytest.mark.asyncio
    async def test_rewrite_pooling_self_pay_uses_short_search_query(self):
        """统筹自付解释必须使用短检索查询，并保留结构化解释上下文。"""
        from src.runtime.policy_qa.models import PolicyQAIntent, SQLQueryResult
        from src.runtime.policy_qa.question_rewriter import QuestionRewriter

        sql_result = SQLQueryResult(
            yb_brdjxx={
                "fund_type": "城镇职工",
                "fund_type_raw": "城镇职工",
                "PER_TYPE": "退休",
                "PER_TYPE_raw": "退休人员",
                "yllb": "普通住院",
                "yllb_raw": "普通住院",
            },
            yb_dyxxnd={"fynd": "2025"},
            yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
            yb_zyfdxx={
                "bdfyzje": 189085.85,
                "bdybnzje": 164411.81,
                "bdtczf": 4962.67,
                "bdtczfje": 91759.51,
                "bddegwyzf": 13407.93,
                "bddegwyzfje": 53631.71,
            },
        )

        result = await QuestionRewriter().rewrite(
            "为什么我这次统筹自付这么多？",
            sql_result,
            intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
            target_fee_item="pooling_self_pay",
        )

        assert result.rewritten == result.search_query
        assert "【业务上下文】" not in result.search_query
        assert "城镇职工" in result.search_query
        assert "退休人员" in result.search_query
        assert "住院" in result.search_query
        assert "统筹" in result.search_query
        assert "起付线以上" in result.search_query
        assert "自付比例" in result.search_query
        assert "退休人员个人负担比例" in result.search_query
        assert result.explanation_context["target_fee_item"] == "pooling_self_pay"
        assert result.explanation_context["target_fee_label"] == "统筹自付"
        assert result.explanation_context["pooling_self_pay"] == 4962.67
        assert result.semantic_mappings["target_fee_item"] == "pooling_self_pay"
        assert result.semantic_mappings["fund_type"] == "城镇职工"
        assert result.semantic_mappings["per_type"] == result.explanation_context["person_type"]
        assert result.semantic_mappings["yllb"] == "普通住院"

    def test_pooling_self_pay_retired_detection_includes_retired_status_variants(self):
        """统筹自付退休判断必须覆盖政策字段常见取值。"""
        from src.runtime.policy_qa.question_rewriter import QuestionRewriter

        rewriter = QuestionRewriter()

        assert rewriter._is_retired("退休", None) is True
        assert rewriter._is_retired("退职", None) is True
        assert rewriter._is_retired("2", None) is True
        assert rewriter._is_retired("在职", "1") is False


class TestIntentDetector:
    """测试意图识别器"""

    def test_detector_import(self):
        """测试识别器是否可以导入"""
        try:
            from src.runtime.policy_qa.intent_detector import IntentDetector
            assert True
        except ImportError:
            pytest.skip("IntentDetector not available")

    def test_detector_initialization(self):
        """测试识别器是否可以初始化"""
        try:
            from src.runtime.policy_qa.intent_detector import IntentDetector
            detector = IntentDetector()
            assert detector is not None
        except ImportError:
            pytest.skip("IntentDetector not available")

    def test_keyword_based_detection(self):
        """测试基于关键词的意图识别"""
        try:
            from src.runtime.policy_qa.intent_detector import IntentDetector
            from src.runtime.policy_qa.models import PolicyQAIntent

            detector = IntentDetector()

            # 测试费用分解
            result = detector._keyword_based_detection("为什么我的费用是这些？")
            assert result.intent == PolicyQAIntent.FEE_DECOMPOSITION

            # 测试起付线
            result = detector._keyword_based_detection("起付线是多少？")
            assert result.intent == PolicyQAIntent.DEDUCTIBLE

            # 测试报销比例
            result = detector._keyword_based_detection("报销比例是多少？")
            assert result.intent == PolicyQAIntent.PAYMENT_RATIO

            # 测试封顶线
            result = detector._keyword_based_detection("封顶线是多少？")
            assert result.intent == PolicyQAIntent.CAP_AMOUNT

        except ImportError:
            pytest.skip("IntentDetector not available")

    def test_detects_pooling_self_pay_target(self):
        """统筹自付问题必须命中结构化目标费用项。"""
        from src.runtime.policy_qa.intent_detector import IntentDetector
        from src.runtime.policy_qa.models import PolicyQAIntent

        detector = IntentDetector()
        result = detector._keyword_based_detection("为什么我这次统筹自付这么多？")

        assert result.intent == PolicyQAIntent.TREATMENT_DECOMPOSITION
        assert result.query_type == "统筹自付解释"
        assert result.target_fee_item == "pooling_self_pay"
        assert result.target_fee_label == "统筹自付"
        assert result.need_patient_data is True

    def test_detects_pooling_self_pay_synonym(self):
        """统筹自费是统筹自付的口语同义表达。"""
        from src.runtime.policy_qa.intent_detector import IntentDetector

        detector = IntentDetector()
        result = detector._keyword_based_detection("统筹自费为什么这么高？")

        assert result.target_fee_item == "pooling_self_pay"
        assert result.target_fee_label == "统筹自付"


class TestExplanationGenerator:
    """测试解释生成器"""

    def test_safe_money_formats_zero_but_preserves_missing_values(self):
        from src.runtime.policy_qa.explanation_generator import _safe_money

        assert _safe_money(0) == "0.00"
        assert _safe_money(0.0) == "0.00"
        assert _safe_money(None) == "未获取"
        assert _safe_money("") == "未获取"

    def test_explanation_generator_returns_one_answer(self):
        import asyncio

        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.models import ExplanationContext

        generator = ExplanationGenerator(model_gateway=None)
        answer = asyncio.run(generator.generate_answer(ExplanationContext()))
        assert isinstance(answer, str)
        assert answer
        assert not hasattr(generator, "generate_dual_views")

    def test_streaming_generation_preserves_governed_system_role(self, monkeypatch):
        import asyncio
        from types import SimpleNamespace

        from src.model_service.governance_assets import (
            GovernanceAssetPreview,
            GovernanceAssetType,
        )
        from src.runtime.policy_qa import explanation_generator as module
        from src.runtime.policy_qa.models import ExplanationContext

        captured = []

        class FakeGateway:
            _config = SimpleNamespace(base_url="https://model.test")

            def generate_stream(self, *, messages, **_kwargs):
                captured.extend(messages)
                return iter([SimpleNamespace(content="ok")])

        monkeypatch.setattr(
            module,
            "render_governed_prompt",
            lambda *_args, **_kwargs: GovernanceAssetPreview(
                asset_type=GovernanceAssetType.PROMPT,
                asset_id="policy_qa.patient_explain",
                rendered_system_prompt="governed system",
                rendered_user_prompt="governed user",
            ),
        )

        async def collect():
            return [
                chunk
                async for chunk in module.ExplanationGenerator(FakeGateway()).generate(
                    ExplanationContext()
                )
            ]

        assert asyncio.run(collect()) == ["ok"]
        assert [(message.role, message.content) for message in captured] == [
            ("system", "governed system"),
            ("user", "governed user"),
        ]

    def test_generator_import(self):
        """测试生成器是否可以导入"""
        try:
            from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
            assert True
        except ImportError:
            pytest.skip("ExplanationGenerator not available")

    def test_generator_initialization(self):
        """测试生成器是否可以初始化"""
        try:
            from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
            generator = ExplanationGenerator()
            assert generator is not None
        except ImportError:
            pytest.skip("ExplanationGenerator not available")

    def test_placeholder_explains_pooling_self_pay_with_reconciliation(self):
        """统筹自付占位解释必须展示结构化分段事实与对账结果。"""
        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.models import (
            ExplanationContext,
            FeeDecompositionResult,
            PolicyQAIntent,
            PolicyQAIntentResult,
            SegmentCalculationResult,
            SegmentInfo,
            TreatmentDecomposition,
            TreatmentItem,
        )

        context = ExplanationContext(
            question="为什么我这次统筹自付这么多？",
            intent=PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="1671213",
                target_fee_item="pooling_self_pay",
                target_fee_label="统筹自付",
            ),
            decomposition=FeeDecompositionResult(
                treatment=TreatmentDecomposition(
                    pooling_self_pay=TreatmentItem(
                        value=4962.67,
                        source="yb_zyfdxx.bdtczf",
                    ),
                    deductible=TreatmentItem(
                        value=650.0,
                        source="yb_dyxxzy.bcqfje",
                    ),
                ),
                segments=SegmentCalculationResult(
                    total_pay=4962.68,
                    authoritative_amount=4962.67,
                    reconciliation_difference=0.01,
                    reconciliation_tolerance=0.01,
                    reconciliation_matched=True,
                    reconciliation_message="政策解释计算与业务库金额一致",
                    warnings=["按现有字段估算统筹分段基数：医保内金额 - 大额支付 - 大额自付"],
                    segments=[
                        SegmentInfo(
                            lower=650,
                            upper=30000,
                            amount=29350,
                            base_ratio=0.15,
                            person_ratio=0.6,
                            actual_ratio=0.09,
                            pay=2641.5,
                            calculation="29,350.00 × 15% × 60% = 29,350.00 × 9% = 2,641.50",
                            policy_source="起付线以上至3万元部分，自付比例15%",
                        )
                    ],
                ),
            ),
        )

        text = ExplanationGenerator()._generate_placeholder(context)

        assert "业务库已结算的统筹自付金额为 4,962.67 元" in text
        assert "基础自付比例" in text
        assert "退休人员系数" in text
        assert "政策解释计算与业务库金额一致" in text
        assert "起付线以上至3万元部分，自付比例15%" in text

    def test_pooling_self_pay_placeholder_includes_patient_context_and_authoritative_statement(self):
        """统筹自付解释必须说明患者上下文和业务库金额权威性。"""
        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.models import (
            ExplanationContext,
            FeeDecompositionResult,
            PolicyQAIntent,
            PolicyQAIntentResult,
            RewrittenQuestion,
            SegmentCalculationResult,
            TreatmentDecomposition,
            TreatmentItem,
        )

        context = ExplanationContext(
            question="为什么我这次统筹自付这么多？",
            intent=PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="1671213",
                target_fee_item="pooling_self_pay",
                target_fee_label="统筹自付",
            ),
            rewritten_question=RewrittenQuestion(
                explanation_context={
                    "fund_type": "城镇职工",
                    "medical_type": "普通住院",
                    "person_type": "退休",
                    "year": "2025",
                }
            ),
            decomposition=FeeDecompositionResult(
                treatment=TreatmentDecomposition(
                    pooling_self_pay=TreatmentItem(value=4962.67, source="yb_zyfdxx.bdtczf"),
                ),
                segments=SegmentCalculationResult(
                    total_pay=4962.67,
                    authoritative_amount=4962.67,
                    reconciliation_matched=True,
                    reconciliation_message="政策解释计算与业务库金额一致",
                ),
            ),
        )

        text = ExplanationGenerator()._generate_placeholder(context)

        assert "城镇职工" in text
        assert "普通住院" in text
        assert "退休" in text
        assert "业务库金额为本次结算的权威金额" in text

    def test_pooling_self_pay_placeholder_declares_uncertainty_without_segments(self):
        """缺少统筹分段规则时不能编造比例，必须输出不确定性声明。"""
        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.models import (
            ExplanationContext,
            FeeDecompositionResult,
            PolicyQAIntent,
            PolicyQAIntentResult,
            SegmentCalculationResult,
            TreatmentDecomposition,
            TreatmentItem,
        )

        context = ExplanationContext(
            question="为什么我这次统筹自付这么多？",
            intent=PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="1671213",
                target_fee_item="pooling_self_pay",
            ),
            decomposition=FeeDecompositionResult(
                treatment=TreatmentDecomposition(
                    pooling_self_pay=TreatmentItem(value=4962.67, source="yb_zyfdxx.bdtczf"),
                ),
                segments=SegmentCalculationResult(total_pay=0.0),
            ),
        )

        text = ExplanationGenerator()._generate_placeholder(context)

        assert "未检索到完整的统筹分段政策规则" in text
        assert "不确定性：缺少统筹分段比例政策依据" in text
        assert "无法稳定解释计算过程" in text


class TestPolicyQAOrchestrator:
    """测试政策问答编排器"""

    def test_detect_intent_propagates_governance_runtime_error(self, monkeypatch):
        import asyncio

        import src.runtime.policy_qa.intent_detector as intent_detector_module
        from src.model_service.governance_runtime import GovernanceRuntimeError
        from src.runtime.policy_qa.models import PolicyQARequest
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        def raise_governance_error(*args, **kwargs):
            raise GovernanceRuntimeError("active prompt is corrupt")

        monkeypatch.setattr(
            intent_detector_module,
            "render_governed_prompt",
            raise_governance_error,
        )
        orchestrator = PolicyQAOrchestrator(model_gateway=object())

        with pytest.raises(GovernanceRuntimeError, match="active prompt is corrupt"):
            asyncio.run(
                orchestrator._detect_intent(
                    PolicyQARequest(question="今天天气怎么样", settlement_id="S001")
                )
            )

    def test_validate_output_rejects_deterministic_answer_without_source(self):
        """普通业务词不能冒充政策来源。"""
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        result = PolicyQAOrchestrator._validate_output(
            "统筹支付金额为100元。",
            [],
        )

        assert result["passed"] is False
        assert result["answer_has_policy_reference"] is False

    def test_validate_output_accepts_real_policy_source_or_uncertainty(self):
        """真实政策证据或明确不确定性声明满足来源安全约束。"""
        from src.runtime.policy_qa.models import PolicyRule
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        with_source = PolicyQAOrchestrator._validate_output(
            "本次金额为100元。",
            [PolicyRule(source_text="根据本市医保办法第十条执行。")],
        )
        with_uncertainty = PolicyQAOrchestrator._validate_output(
            "未检索到可核验的政策依据，无法可靠确认，请建议核对医保结算单。",
            [],
        )

        assert with_source["passed"] is True
        assert with_source["answer_has_policy_reference"] is True
        assert with_uncertainty["passed"] is True
        assert with_uncertainty["answer_has_uncertainty"] is True

    def test_unsafe_generated_answer_is_not_yielded(self, monkeypatch):
        """来源校验失败时，原始确定性答案不得对外发送。"""
        import asyncio

        import src.runtime.policy_qa.orchestrator as orchestrator_module
        from src.runtime.policy_qa.models import (
            PolicyQAIntent,
            PolicyQAIntentResult,
            PolicyQARequest,
            SQLQueryResult,
        )
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        unsafe_answer = "本次统筹支付金额确定为100元。"

        class FakeSQLFetcher:
            async def fetch_all_tables(self, settlement_id):
                return SQLQueryResult(
                    yb_brdjxx={
                        "fund_type": "城镇职工",
                        "PER_TYPE": "退休",
                        "yllb": "普通住院",
                    },
                    yb_dyxxnd={"fynd": "2025"},
                    yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 10000.0},
                    yb_zyfdxx={
                        "bdfyzje": 12000.0,
                        "bdybnzje": 10000.0,
                        "bdtczf": 100.0,
                        "bdtczfje": 8000.0,
                        "bddegwyzf": 50.0,
                        "bddegwyzfje": 500.0,
                        "bdgryf": 3500.0,
                    },
                )

        class EmptySearchEngine:
            def search(self, question, top_k=10, expr=None):
                return []

            def search_with_context(self, **kwargs):
                return []

        class UnsafeGenerator:
            async def generate_answer(self, context):
                return unsafe_answer

        class FakeIntentDetector:
            async def detect(self, question):
                return PolicyQAIntentResult(
                    intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                    settlement_id="",
                    need_patient_data=True,
                    query_type="统筹自付解释",
                    target_fee_item="pooling_self_pay",
                    target_fee_label="统筹自付",
                    confidence=1.0,
                )

        orchestrator = PolicyQAOrchestrator(
            model_gateway=None,
            sql_fetcher=FakeSQLFetcher(),
            search_engine=EmptySearchEngine(),
            explanation_generator=UnsafeGenerator(),
        )
        orchestrator.intent_detector = FakeIntentDetector()
        monkeypatch.setattr(
            orchestrator_module,
            "route_question",
            lambda question: "settlement_explain_skill",
        )

        async def collect_events():
            return [
                event
                async for event in orchestrator.process(
                    PolicyQARequest(
                        question="为什么我这次统筹自付这么多？",
                        settlement_id="1671213",
                    )
                )
            ]

        events = asyncio.run(collect_events())
        answer_events = [event for event in events if event.answer]
        final_event = next(event for event in events if event.step == "trace_result")

        assert answer_events
        assert all(event.answer != unsafe_answer for event in answer_events)
        assert all(event.answer_status == "unavailable" for event in answer_events)
        assert "建议" in answer_events[0].answer
        assert final_event.detail["status"] == "failed"

    def test_orchestrator_import(self):
        """测试编排器是否可以导入"""
        try:
            from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator
            assert True
        except ImportError:
            pytest.skip("PolicyQAOrchestrator not available")

    def test_orchestrator_initialization(self):
        """测试编排器是否可以初始化"""
        try:
            from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator
            orchestrator = PolicyQAOrchestrator(model_gateway=None)
            assert orchestrator is not None
        except ImportError:
            pytest.skip("PolicyQAOrchestrator not available")

    @pytest.mark.asyncio
    async def test_search_policy_rules_uses_pooling_self_pay_filters(self):
        """统筹自付检索必须优先命中统筹分段等相关政策规则。"""
        from src.runtime.policy_qa.models import PolicyQAIntent, SQLQueryResult
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        class FakeSearchEngine:
            def __init__(self):
                self.calls = []

            def search(self, question, top_k=10, expr=None):
                self.calls.append({"question": question, "top_k": top_k, "expr": expr})
                return [
                    {
                        "rule_id": "rule_pooling_segment_1",
                        "rule_type": "统筹分段",
                        "source_text": "起付线以上至3万元部分，退休人员按统筹分段比例自付。",
                        "insu_type": "城镇职工",
                        "psn_type": "退休",
                        "med_type": "普通住院",
                        "payment_ratio": "0.15",
                        "amount_band": "650-30000",
                        "score": 0.98,
                    }
                ]

        search_engine = FakeSearchEngine()
        orchestrator = PolicyQAOrchestrator(
            model_gateway=None,
            search_engine=search_engine,
        )
        sql_result = SQLQueryResult(
            yb_brdjxx={
                "fund_type": "城镇职工",
                "PER_TYPE": "退休",
                "yllb": "普通住院",
            }
        )

        rules = await orchestrator._search_policy_rules(
            "城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例",
            sql_result,
            intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
            target_fee_item="pooling_self_pay",
        )

        assert len(rules) == 1
        assert rules[0].rule_type == "统筹分段"
        assert search_engine.calls
        first_expr = search_engine.calls[0]["expr"]
        assert "统筹分段" in first_expr
        assert "城镇职工" in first_expr

    @pytest.mark.asyncio
    async def test_process_intent_detail_includes_target_fee_item(self):
        """统筹自付问题的意图 SSE detail 必须暴露结构化目标费用项。"""
        from src.runtime.policy_qa.models import PolicyQARequest
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        orchestrator = PolicyQAOrchestrator(model_gateway=None)
        events = []

        async for event in orchestrator.process(
            PolicyQARequest(question="为什么我这次统筹自付这么多？", settlement_id="1671213")
        ):
            events.append(event)
            if event.step == "intent_detection" and event.status == "done":
                break

        intent_done = events[-1]
        assert intent_done.detail["intent"] == "treatment_decomposition"
        assert intent_done.detail["query_type"] == "统筹自付解释"
        assert intent_done.detail["target_fee_item"] == "pooling_self_pay"
        assert intent_done.detail["target_fee_label"] == "统筹自付"

    @pytest.mark.asyncio
    async def test_process_query_sql_data_exposes_settlement_details(self):
        """查询 SSE detail 必须通过 adapter 暴露结算明细数据。"""
        from src.runtime.policy_qa.models import PolicyQARequest, SQLQueryResult
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        class FakeSQLFetcher:
            async def fetch_all_tables(self, settlement_id):
                return SQLQueryResult(
                    yb_brdjxx={
                        "fund_type": "城镇职工",
                        "fund_type_raw": "城镇职工",
                        "PER_TYPE": "退休",
                        "PER_TYPE_raw": "退休人员",
                        "yllb": "普通住院",
                        "yllb_raw": "普通住院",
                    },
                    yb_dyxxnd={"fynd": "2025"},
                    yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
                    yb_zyfdxx={"bdtczf": 4962.67, "bdtczfje": 91759.51},
                )

        orchestrator = PolicyQAOrchestrator(
            model_gateway=None,
            sql_fetcher=FakeSQLFetcher(),
        )

        query_done = None
        async for event in orchestrator.process(
            PolicyQARequest(question="为什么我这次统筹自付这么多？", settlement_id="1671213")
        ):
            if event.step == "settlement_query" and event.status == "done":
                query_done = event
                break

        assert query_done is not None
        assert query_done.detail["settlement_id"] == "1671213"
        assert "yb_zyfdxx" in query_done.detail["tables"]

    def test_serialize_decomposition_includes_reconciliation_and_warnings(self):
        """分解 detail 必须输出统筹自付对账结构和数据口径提示。"""
        from src.runtime.policy_qa.models import (
            FeeDecompositionResult,
            SegmentCalculationResult,
            SegmentInfo,
        )
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        decomposition = FeeDecompositionResult(
            segments=SegmentCalculationResult(
                total_pay=4962.68,
                authoritative_amount=4962.67,
                reconciliation_difference=0.01,
                reconciliation_tolerance=0.01,
                reconciliation_matched=True,
                reconciliation_message="政策解释计算与业务库金额一致",
                warnings=["按现有字段估算统筹分段基数：医保内金额 - 大额支付 - 大额自付"],
                segments=[
                    SegmentInfo(
                        lower=650,
                        upper=30000,
                        amount=29350,
                        base_ratio=0.15,
                        person_ratio=0.6,
                        actual_ratio=0.09,
                        pay=2641.5,
                        rule_id="r1",
                        policy_source="起付线以上至3万元部分，自付比例15%",
                    )
                ],
            )
        )

        detail = PolicyQAOrchestrator(model_gateway=None)._serialize_decomposition(decomposition)

        assert detail["segments"]["warnings"] == ["按现有字段估算统筹分段基数：医保内金额 - 大额支付 - 大额自付"]
        assert detail["segments"]["reconciliation"]["authoritative_amount"] == 4962.67
        assert detail["segments"]["reconciliation"]["calculated_amount"] == 4962.68
        assert detail["segments"]["reconciliation"]["difference"] == 0.01
        assert detail["segments"]["reconciliation"]["tolerance"] == 0.01
        assert detail["segments"]["reconciliation"]["matched"] is True
        assert detail["segments"]["reconciliation"]["message"] == "政策解释计算与业务库金额一致"


class TestExtractSegmentRatios:
    """测试 _extract_segment_ratios 对真实 Milvus 数据结构的解析。"""

    def _make_real_evidence(self):
        """构造与真实 Milvus 返回结构一致的测试数据。"""
        return [
            {
                "source_text": "1. 起付标准至3万元的部分，统筹基金支付85%，职工支付15%；\n{\"ratio\": 0.85}",
                "rule_type": "支付比例",
                "psn_type": "",
                "amount_band": "nan",
                "rule_tags": ["支付比例", "城镇职工基本医疗保险", "住院-普通住院", "三级医院", "全部"],
                "rule_value": "{\"ratio\": 0.85}",
            },
            {
                "source_text": "2. 超过3万元至4万元的部分，统筹基金支付90%，职工支付10%；\n{\"ratio\": 0.9}",
                "rule_type": "支付比例",
                "psn_type": "",
                "amount_band": "nan",
                "rule_tags": ["支付比例", "城镇职工基本医疗保险", "住院-普通住院", "三级医院", "全部"],
                "rule_value": "{\"ratio\": 0.9}",
            },
            {
                "source_text": "3. 超过4万元的部分，统筹基金支付95%，职工支付5%。\n{\"ratio\": 0.95}",
                "rule_type": "支付比例",
                "psn_type": "",
                "amount_band": "nan",
                "rule_tags": ["支付比例", "城镇职工基本医疗保险", "住院-普通住院", "三级医院", "全部"],
                "rule_value": "{\"ratio\": 0.95}",
            },
            {
                "source_text": "（四）退休人员个人支付比例为职工支付比例的60%。但基本医疗保险统筹基金按照比例支付的最高数额不得超过本规定第十三条规定的最高支付限额。",
                "rule_type": "计算公式",
                "psn_type": "",
                "amount_band": "nan",
                "rule_tags": ["计算公式", "城镇职工基本医疗保险", "住院-普通住院", "nan", "退休人员"],
                "rule_value": "{\"expression\": \"retiree_personal_payment_ratio = employee_personal_payment_ratio * 0.6\", \"target\": \"retiree_personal_payment_ratio\", \"base\": \"employee_personal_payment_ratio\", \"operator\": \"*\", \"multiplier\": 0.6}",
            },
        ]

    def test_detects_3_employee_segments(self):
        """3 条支付比例证据应解析出 3 个分段。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios(self._make_real_evidence())
        assert len(seg["employee"]) == 3

    def test_detects_retiree_rule_with_empty_psn_type(self):
        """退休规则证据的 psn_type 为空时，应通过 source_text/rule_tags 多源检测。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios(self._make_real_evidence())
        assert seg["retiree"] is not None, "退休人员 60% 规则未被检测到（psn_type 为空时的多源检测失败）"
        assert seg["retiree"]["ratio"] == 60

    def test_has_complete_is_true_with_4_evidence(self):
        """4 条证据（3 段比例 + 退休公式）时 has_complete 必须为 True。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios(self._make_real_evidence())
        assert seg["has_complete"] is True, f"has_complete 应为 True，实际: {seg}"

    def test_retiree_segments_calculated_correctly(self):
        """退休人员分段比例应正确计算：15%×60%=9%, 10%×60%=6%, 5%×60%=3%。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios(self._make_real_evidence())
        assert seg["retiree"] is not None
        retiree_segs = seg["retiree"]["segments"]
        assert len(retiree_segs) == 3
        assert retiree_segs[0] == 9  # 15 * 60 / 100 = 9
        assert retiree_segs[1] == 6  # 10 * 60 / 100 = 6
        assert retiree_segs[2] == 3  # 5 * 60 / 100 = 3

    def test_empty_evidence_returns_not_complete(self):
        """空证据列表应返回 has_complete=False。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios([])
        assert seg["has_complete"] is False
        assert seg["retiree"] is None


class TestPolicyQATurnId:
    """服务端 qa_turn_id 全链路：task 主键、result、done、history 共享同一服务端 ID。"""

    def test_record_qa_task_uses_server_qa_turn_id(self):
        """record_qa_task 必须以服务端 qa_turn_id 作为 task 主键，不再根据问题正文计算。"""
        from src.runtime.policy_qa.persistence import record_qa_task
        from src.runtime.task_closure.service import get_task

        qa_turn_id = "qat_01JTEST000000000000000001"
        saved = record_qa_task(
            qa_turn_id=qa_turn_id,
            workflow_id="wf-1",
            session_id="session-1",
            user_id="user-1",
            tenant_id="tenant-1",
            question="起付线怎么计算",
            output={
                "answer_excerpt": "按年度累计计算",
                "selected_skill_id": "deductible",
            },
        )
        assert saved == qa_turn_id
        task = get_task(qa_turn_id)
        assert task is not None
        assert task["task_id"] == qa_turn_id
        assert task["output_data"]["selected_skill_id"] == "deductible"
        # 内部 input 不再保存原始患者问题正文，仅保留脱敏摘要
        assert "question" not in task["input_data"]
        assert task["input_data"]["question_excerpt"]
        assert task["input_data"]["tenant_id"] == "tenant-1"

    def test_record_qa_task_is_idempotent_on_same_turn_id(self):
        """同一 qa_turn_id 重复记录不会产生第二个主键。"""
        from src.runtime.policy_qa.persistence import record_qa_task

        first = record_qa_task(
            qa_turn_id="qat_idem_1",
            workflow_id="wf-idem",
            session_id="sess-idem",
            user_id="user-1",
            tenant_id="tenant-1",
            question="统筹自付怎么算",
            output={"answer_excerpt": "分段计算", "selected_skill_id": "settlement_explain_skill"},
        )
        second = record_qa_task(
            qa_turn_id="qat_idem_1",
            workflow_id="wf-idem",
            session_id="sess-idem",
            user_id="user-1",
            tenant_id="tenant-1",
            question="统筹自付怎么算",
            output={"answer_excerpt": "分段计算", "selected_skill_id": "settlement_explain_skill"},
        )
        assert first == second == "qat_idem_1"
