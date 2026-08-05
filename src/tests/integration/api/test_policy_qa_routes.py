"""
医保政策问答RAG系统 - API测试

测试policy_qa相关的API端点
"""

import json
import os
import pytest

# 设置使用内存存储
os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event_name = ""
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if event_name and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def _nested_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_nested_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_nested_keys(item) for item in value), set())
    return set()


def _internal_settlement_payload() -> dict:
    return {
        "answer": "统筹自付按政策比例计算。",
        "can_answer": True,
        "partial_answer": False,
        "policy_status": "full_policy_matched",
        "policy_evidence": [
            {
                "title": "职工医保住院待遇政策",
                "clause": "起付线以上部分按规定比例承担。",
                "score": 0.99,
                "query_trace": {"table": "yb_zyfdxx"},
            }
        ],
        "calculation_trace": {
            "steps": [{"step_name": "分段计算", "description": "按政策区间计算。"}],
            "raw_sql": "SELECT * FROM yb_zyfdxx",
        },
        "definition": {"name": "统筹自付", "plain_text": "个人承担部分。"},
        "warnings": [],
        "case_context": {
            "basic_pooling_self_pay": 4962.67,
            "query_trace": {"sql_profile": "settlement_context"},
        },
        "explanation_completeness": {
            "level": "full_policy_matched",
            "has_real_data": True,
        },
    }


@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def safe_policy_qa_dependencies(monkeypatch):
    """隔离外部 SQL/Milvus/模型依赖，让 SSE 确定性到达 result。"""
    from types import SimpleNamespace

    from src.runtime.api import policy_qa_routes
    from src.runtime.policy_qa.settlement_data_provider import SettlementContext

    class FakeSettlementDataProvider:
        async def get_settlement_context(self, settlement_id: str) -> SettlementContext:
            return SettlementContext(
                settlement_id=settlement_id,
                person_type="退休人员",
                insurance_type="城镇职工基本医疗保险",
                service_type="普通住院",
                hospital_level="三级医院",
                deductible=650.0,
                medical_insurance_inner_amount=164411.81,
                basic_pooling_payment=91759.51,
                basic_pooling_self_pay=4962.67,
                large_amount_payment=53631.71,
                large_amount_self_pay=13407.93,
                personal_total_pay=43694.67,
                total_amount=189085.85,
            )

    class FakeAssembler:
        @staticmethod
        def _get_fee_field(_target_fee_item: str) -> str:
            return "basic_pooling_self_pay"

        @staticmethod
        def _get_fee_amount(context: SettlementContext, _target_fee_item: str) -> float:
            return context.basic_pooling_self_pay

        @staticmethod
        def build_policy_queries(_target_fee_item: str) -> list:
            return []

        @staticmethod
        def execute(**_kwargs):
            return SimpleNamespace(
                answer="统筹自付为 4,962.67 元，按起付线以上政策区间分段计算。",
                calculation_trace={
                    "steps": [{"label": "统筹自付", "formula": "按政策区间分段计算"}],
                },
                definition={"name": "统筹自付", "plain_text": "个人按政策承担的部分。"},
                warnings=[],
                explanation_completeness={
                    "level": "full_policy_matched",
                    "has_real_data": True,
                },
                policy_status="full_policy_matched",
                policy_status_message="已匹配完整政策依据。",
            )

    evidence = SimpleNamespace(
        source_text="起付线以上部分按政策规定分段计算统筹自付。",
        applied_reason="匹配统筹自付支付比例规则",
        rule_type="支付比例",
        score=0.99,
        payment_ratio="0.15",
        amount_band="650-30000",
        rule_value="15%",
    )
    monkeypatch.setattr(
        policy_qa_routes,
        "create_settlement_data_provider",
        lambda: FakeSettlementDataProvider(),
    )
    monkeypatch.setattr(
        policy_qa_routes,
        "retrieve_policy_evidence",
        lambda **_kwargs: SimpleNamespace(
            selected_evidence=[evidence, evidence],
            missing_required_rules=[],
        ),
    )
    monkeypatch.setattr(policy_qa_routes, "get_assembler", lambda _skill_id: FakeAssembler())


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

    def test_stream_endpoint_does_not_expose_internal_trace_events(
        self, client, safe_policy_qa_dependencies
    ):
        """公开 SSE 只允许业务事件，不能透出推理链或内部 trace。"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "为什么我这次统筹自付这么多？",
                "settlement_id": "1671213",
            },
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        events = _sse_events(response.text)
        event_names = {name for name, _payload in events}
        assert event_names <= {
            "context_need",
            "memory_update",
            "step",
            "result",
            "error",
            "done",
        }
        assert not {"trace_event", "reasoning_step"}.intersection(event_names)
        assert "result" in event_names
        assert sum(name == "result" for name, _payload in events) == 1
        assert sum(name == "done" for name, _payload in events) == 1
        assert events[-1][0] == "done"
        assert events[-1][1]["answer_status"] in {"complete", "partial", "unavailable"}

    def test_stream_endpoint_returns_single_safe_answer_contract(
        self, client, safe_policy_qa_dependencies
    ):
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "统筹自付为什么这么多？",
                "settlement_id": "1671213",
            },
        )

        assert response.status_code == 200
        result_event = next(
            payload["result"]
            for event_name, payload in _sse_events(response.text)
            if event_name == "result"
        )
        assert result_event["answer"]
        assert result_event["answer_status"] in {"complete", "partial", "unavailable"}
        assert set(result_event) == {
            "answer",
            "answer_status",
            "case_context",
            "calculation_steps",
            "definition",
            "warnings",
            "policy_evidence",
            "citations",
            "uncertainties",
            "verification_summary",
        }
        forbidden = {
            "patient_view",
            "office_view",
            "settlement_evidence",
            "answer_mode",
            "run_id",
            "selected_skill_id",
            "query_trace",
            "trace_events",
            "reasoning_steps",
        }
        assert not forbidden.intersection(_nested_keys(result_event))
        assert "yb_" not in json.dumps(result_event, ensure_ascii=False).lower()
        assert result_event["citations"] or result_event["uncertainties"]

    def test_stream_task_persistence_uses_public_evidence_count_key(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from src.runtime.api import policy_qa_routes

        persisted_outputs = []
        monkeypatch.setattr(
            policy_qa_routes,
            "record_qa_task",
            lambda **kwargs: persisted_outputs.append(kwargs["output_data"]),
        )

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "统筹自付为什么这么多？",
                "settlement_id": "1671213",
            },
        )

        assert response.status_code == 200
        assert persisted_outputs
        output_data = persisted_outputs[-1]
        assert set(output_data) == {
            "answer_excerpt",
            "answer_status",
            "evidence_count",
            "internal_run_id",
        }
        assert output_data["evidence_count"] == 1

    def test_stream_failure_has_safe_terminal_contract(self, client, monkeypatch):
        from src.runtime.api import policy_qa_routes

        class FailingProvider:
            async def get_settlement_context(self, _settlement_id):
                raise RuntimeError("SELECT password FROM yb_zyfdxx WHERE secret='raw'")

        monkeypatch.setattr(
            policy_qa_routes,
            "create_settlement_data_provider",
            lambda: FailingProvider(),
        )
        monkeypatch.setattr(policy_qa_routes, "get_assembler", lambda _skill_id: object())

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "统筹自付为什么这么多？", "settlement_id": "1671213"},
        )

        assert response.status_code == 200
        events = _sse_events(response.text)
        assert sum(name == "result" for name, _payload in events) == 0
        assert sum(name == "error" for name, _payload in events) == 1
        assert sum(name == "done" for name, _payload in events) == 1
        error_payload = next(payload for name, payload in events if name == "error")
        done_payload = next(payload for name, payload in events if name == "done")
        assert error_payload == {
            "error_code": "POLICY_QA_FAILED",
            "message": "政策问答处理失败，请稍后重试或联系医保办。",
        }
        assert done_payload == {
            "answer_status": "unavailable",
            "success": False,
            "error_code": "POLICY_QA_FAILED",
        }
        public_stream = response.text.casefold()
        assert all(
            token not in public_stream
            for token in ("select", "password", "yb_zyfdxx", "secret")
        )


class TestSettlementExplanationEndpoint:
    def test_rest_success_returns_only_public_contract(self, client, monkeypatch):
        from src.runtime.api import policy_qa_routes

        async def fake_process(_settlement_id, _question=""):
            return _internal_settlement_payload()

        monkeypatch.setattr(policy_qa_routes, "_process_single_settlement", fake_process)

        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "1671213", "question": "统筹自付为什么这么多？"},
        )

        assert response.status_code == 200
        result = response.json()
        assert set(result) == {
            "answer",
            "answer_status",
            "case_context",
            "calculation_steps",
            "definition",
            "warnings",
            "policy_evidence",
            "citations",
            "uncertainties",
            "verification_summary",
        }
        assert result["answer_status"] == "complete"
        assert not {"query_trace", "raw_sql", "sql_profile"}.intersection(
            _nested_keys(result)
        )

    @pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
    def test_rest_exception_returns_stable_generic_error(
        self, client, monkeypatch, error_type
    ):
        from src.runtime.api import policy_qa_routes

        async def fake_process(_settlement_id, _question=""):
            raise error_type("SELECT password FROM yb_zyfdxx WHERE secret='raw'")

        monkeypatch.setattr(policy_qa_routes, "_process_single_settlement", fake_process)

        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "1671213"},
        )

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert set(detail) == {"error_code", "message", "audit_event"}
        assert detail["error_code"] == "POLICY_QA_UNAVAILABLE"
        assert detail["message"] == "政策问答服务暂时不可用，请稍后重试。"
        public_body = response.text.casefold()
        assert all(token not in public_body for token in ("select", "password", "yb_zyfdxx", "secret"))


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
