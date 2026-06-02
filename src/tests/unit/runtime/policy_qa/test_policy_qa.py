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
