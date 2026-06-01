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
            target_fee_item="pooling_self_pay",
            target_fee_label="统筹自付",
        )

        assert result.target_fee_item == "pooling_self_pay"
        assert result.target_fee_label == "统筹自付"

    def test_rewritten_question_separates_search_query_and_context(self):
        """测试重写问题区分检索问题与解释上下文"""
        from src.runtime.policy_qa.models import RewrittenQuestion

        rewritten_question = RewrittenQuestion(
            original="为什么我这次统筹自付这么多？",
            rewritten="解释本次住院统筹自付金额形成原因",
            search_query="北京市医保住院统筹自付 起付线 分段 自付比例",
            explanation_context={
                "settlement_id": "1671213",
                "target_fee_item": "pooling_self_pay",
                "target_fee_label": "统筹自付",
            },
            semantic_mappings={"统筹自付": "pooling_self_pay"},
            warnings=["检索问题已去除个人金额上下文"],
        )

        assert rewritten_question.original == "为什么我这次统筹自付这么多？"
        assert rewritten_question.rewritten == "解释本次住院统筹自付金额形成原因"
        assert rewritten_question.search_query == "北京市医保住院统筹自付 起付线 分段 自付比例"
        assert rewritten_question.explanation_context == {
            "settlement_id": "1671213",
            "target_fee_item": "pooling_self_pay",
            "target_fee_label": "统筹自付",
        }
        assert rewritten_question.semantic_mappings == {"统筹自付": "pooling_self_pay"}
        assert rewritten_question.warnings == ["检索问题已去除个人金额上下文"]

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
        from src.runtime.policy_qa.models import SegmentCalculationResult, SegmentInfo

        result = SegmentCalculationResult(
            segments=[
                SegmentInfo(
                    lower=650.0,
                    upper=30000.0,
                    amount=29350.0,
                    base_ratio=0.15,
                    person_ratio=0.6,
                    actual_ratio=0.09,
                    pay=2641.50,
                )
            ],
            total_pay=2641.50,
            authoritative_amount=2641.49,
            reconciliation_difference=0.01,
            reconciliation_tolerance=0.01,
            reconciliation_matched=True,
            reconciliation_message="分段计算金额与权威字段误差在容差内",
            warnings=["按两位小数展示可能存在尾差"],
        )

        assert len(result.segments) == 1
        assert result.total_pay == 2641.50
        assert result.authoritative_amount == 2641.49
        assert result.reconciliation_difference == 0.01
        assert result.reconciliation_tolerance == 0.01
        assert result.reconciliation_matched is True
        assert result.reconciliation_message == "分段计算金额与权威字段误差在容差内"
        assert result.warnings == ["按两位小数展示可能存在尾差"]


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


class TestExplanationGenerator:
    """测试解释生成器"""

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


class TestPolicyQAOrchestrator:
    """测试政策问答编排器"""

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
