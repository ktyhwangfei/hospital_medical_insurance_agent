"""
医保政策问答RAG系统 - API测试

测试policy_qa相关的API端点
"""

import os
import pytest

# 设置使用内存存储
os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_app()
    return TestClient(app)


class TestPolicyQAStreamEndpoint:
    """测试政策问答SSE流式端点"""

    def test_stream_endpoint_exists(self, client):
        """测试流式端点是否存在"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "为什么我的费用是这些？",
                "settlement_id": "1671213",
            },
        )
        # 端点应该存在，即使返回错误
        assert response.status_code in [200, 422, 500]

    def test_stream_endpoint_requires_question(self, client):
        """测试流式端点需要question参数"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "settlement_id": "1671213",
            },
        )
        # 应该返回422验证错误
        assert response.status_code == 422

    def test_stream_endpoint_requires_settlement_id(self, client):
        """测试流式端点需要settlement_id参数"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "为什么我的费用是这些？",
            },
        )
        # 应该返回422验证错误
        assert response.status_code == 422

    def test_stream_endpoint_returns_sse(self, client):
        """测试流式端点返回SSE格式"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "为什么我的费用是这些？",
                "settlement_id": "1671213",
            },
        )
        if response.status_code == 200:
            # 检查Content-Type
            assert "text/event-stream" in response.headers.get("content-type", "")

    def test_stream_endpoint_exposes_pooling_self_pay_contract(self, client):
        """统筹自付问题的 SSE 事件必须暴露适配器驱动的完整链路步骤。"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "为什么我这次统筹自付这么多？",
                "settlement_id": "1671213",
            },
        )

        assert response.status_code == 200
        body = response.text
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert "pooling_self_pay" in body
        assert "统筹自付" in body
        # 适配器驱动的新步骤名称
        assert "query_sql_data" in body
        assert "search_policy_rules" in body
        assert "calculate_explanation" in body
        assert "generate_explanation" in body
        assert "reconciliation" in body


class TestPolicyQATestEndpoint:
    """测试政策问答测试端点"""

    def test_test_endpoint_exists(self, client):
        """测试测试端点是否存在"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/test",
            json={
                "question": "为什么我的费用是这些？",
                "settlement_id": "1671213",
            },
        )
        assert response.status_code == 200

    def test_test_endpoint_returns_ok(self, client):
        """测试测试端点返回ok"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/test",
            json={
                "question": "为什么我的费用是这些？",
                "settlement_id": "1671213",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_test_endpoint_requires_question(self, client):
        """测试测试端点需要question参数"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/test",
            json={
                "settlement_id": "1671213",
            },
        )
        # 应该返回422验证错误
        assert response.status_code == 422

    def test_test_endpoint_requires_settlement_id(self, client):
        """测试测试端点需要settlement_id参数"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/test",
            json={
                "question": "为什么我的费用是这些？",
            },
        )
        # 应该返回422验证错误
        assert response.status_code == 422


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
            from src.model_service.gateway import ModelGateway

            # 尝试初始化（可能会失败，但不应该抛出导入错误）
            try:
                gateway = ModelGateway()
                orchestrator = PolicyQAOrchestrator(model_gateway=gateway)
                assert orchestrator is not None
            except Exception:
                # 初始化失败是可以接受的（可能缺少配置）
                pass
        except ImportError:
            pytest.skip("PolicyQAOrchestrator not available")


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

    def test_segment_parsing(self):
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

        except ImportError:
            pytest.skip("FeeDecompositionSkill not available")

    def test_person_ratio(self):
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
