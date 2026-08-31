"""
医保政策问答RAG系统 - API测试

测试policy_qa相关的API端点
"""

import json
import os
from decimal import Decimal
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


def test_verified_official_preview_completes_without_policy_evidence():
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="院端预结算未接受本次拟退方案（QTY_EXCEEDED）：拟退数量超过可退数量。",
        can_answer=True,
        partial_answer=False,
        policy_status="no_policy_matched",
        policy_evidence=[],
        calculation_steps=[],
        definition={"name": "门诊部分项目预退费分析"},
        warnings=[],
        case_context=None,
        source_citations=[
            {"title": "院端收费系统预结算", "excerpt": "预结算凭证：PRE-001；响应码：QTY_EXCEEDED"}
        ],
        verified_external_result=True,
    )

    assert result.answer_status == "complete"
    assert result.policy_evidence == []
    assert result.verification_summary.policy_count == 0
    assert result.verification_summary.settlement_checked is True
    assert result.citations[0].title == "院端收费系统预结算"
    assert not any("政策依据" in item for item in result.uncertainties)


def test_verified_preview_rejects_internal_implementation_as_source():
    from src.runtime.api.policy_qa_routes import _build_public_result

    result = _build_public_result(
        answer="院端预结算成功。",
        can_answer=True,
        partial_answer=False,
        policy_status="no_policy_matched",
        policy_evidence=[],
        calculation_steps=[],
        definition=None,
        warnings=[],
        case_context=None,
        source_citations=[
            {"title": "SELECT * FROM yb_mz_js", "excerpt": "raw_sql=secret"}
        ],
        verified_external_result=True,
    )

    assert result.answer_status == "unavailable"
    assert result.citations == []


def test_pre_refund_billing_adapter_is_dependency_injectable():
    from src.runtime.api import policy_qa_routes

    assert hasattr(policy_qa_routes, "get_pre_refund_billing_adapter")


class ApiPreRefundBillingAdapter:
    def __init__(self, *results):
        self._results = list(results)
        self.preview_calls = 0

    def query_billing_status(self, patient_id: str, encounter_id: str):
        raise AssertionError("预退费 API 不应查询旧收费状态")

    def preview_partial_refund(self, original_trade_no: str, items):
        self.preview_calls += 1
        return self._results.pop(0)


def _api_pre_refund_preview(*, accepted: bool = True):
    from src.adapters.billing.models import (
        PartialRefundPreview,
        PreviewedRefundItem,
        SettlementAmountSnapshot,
    )

    if not accepted:
        return PartialRefundPreview(
            accepted=False,
            original_trade_no="OP-001",
            response_code="QTY_EXCEEDED",
            response_message="拟退数量超过可退数量",
            preview_id="PRE-REJECT-001",
            source_system="院端收费系统",
            source_reference="PRE-REJECT-001",
            items=(),
            before=None,
            after=None,
        )
    return PartialRefundPreview(
        accepted=True,
        original_trade_no="OP-001",
        response_code="0",
        response_message="预结算成功",
        preview_id="PRE-001",
        source_system="院端收费系统",
        source_reference="PRE-001",
        items=(
            PreviewedRefundItem(
                fee_detail_id="F001",
                refund_quantity=Decimal("1"),
                refundable_quantity=Decimal("1"),
                refund_amount=Decimal("20"),
            ),
        ),
        before=SettlementAmountSnapshot(
            total_amount=Decimal("100"),
            fund_amount=Decimal("60"),
            personal_amount=Decimal("40"),
        ),
        after=SettlementAmountSnapshot(
            total_amount=Decimal("80"),
            fund_amount=Decimal("48"),
            personal_amount=Decimal("32"),
        ),
    )


def _api_pre_refund_result(*, accepted: bool = True):
    from src.adapters.base.models import AdapterCallContext
    from src.adapters.base.service import successful_result

    return successful_result(
        context=AdapterCallContext(),
        source_system="billing",
        source_record_id="PRE-001",
        capability="preview_partial_refund",
        data={"preview": _api_pre_refund_preview(accepted=accepted)},
    )


def _pre_refund_client(adapter) -> TestClient:
    from src.runtime.api import policy_qa_routes

    app = create_app()
    app.dependency_overrides[policy_qa_routes.get_pre_refund_billing_adapter] = (
        lambda: adapter
    )
    return TestClient(app)


class TestPreRefundPolicyQAStream:
    def test_success_uses_official_preview_without_querying_settlement_provider(
        self, monkeypatch
    ):
        from src.runtime.api import policy_qa_routes

        adapter = ApiPreRefundBillingAdapter(_api_pre_refund_result())
        provider_calls = 0

        def forbidden_provider():
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("预退费分支不应创建原结算查询 provider")

        monkeypatch.setattr(
            policy_qa_routes,
            "create_settlement_data_provider",
            forbidden_provider,
        )
        response = _pre_refund_client(adapter).post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "分析部分项目预退费",
                "settlement_id": "OP-001",
                "pre_refund_items": [
                    {"fee_detail_id": "F001", "refund_quantity": "1"}
                ],
            },
        )

        events = _sse_events(response.text)
        result = next(data["result"] for name, data in events if name == "result")
        done = next(data for name, data in events if name == "done")

        assert response.status_code == 200
        assert provider_calls == 0
        assert adapter.preview_calls == 1
        assert result["answer_status"] == "complete"
        assert "预计退还" in result["answer"]
        assert result["citations"]
        assert result["policy_evidence"] == []
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
        assert done["attempt_count"] == 1
        assert done["halt_reason"] == "official_pre_settlement_verified"

    def test_official_rejection_is_complete(self):
        adapter = ApiPreRefundBillingAdapter(
            _api_pre_refund_result(accepted=False)
        )

        response = _pre_refund_client(adapter).post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "退费试算",
                "settlement_id": "OP-001",
                "pre_refund_items": [
                    {"fee_detail_id": "F001", "refund_quantity": "2"}
                ],
            },
        )
        result = next(
            data["result"]
            for name, data in _sse_events(response.text)
            if name == "result"
        )

        assert result["answer_status"] == "complete"
        assert "QTY_EXCEEDED" in result["answer"]
        assert result["verification_summary"]["policy_count"] == 0

    def test_duplicate_fee_detail_ids_are_rejected_before_adapter(self):
        adapter = ApiPreRefundBillingAdapter(_api_pre_refund_result())

        response = _pre_refund_client(adapter).post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "预退费分析",
                "settlement_id": "OP-001",
                "pre_refund_items": [
                    {"fee_detail_id": "F001", "refund_quantity": "1"},
                    {"fee_detail_id": "F001", "refund_quantity": "1"},
                ],
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "DUPLICATE_FEE_DETAIL_ID"
        assert adapter.preview_calls == 0

    def test_non_positive_refund_quantity_returns_422(self):
        adapter = ApiPreRefundBillingAdapter(_api_pre_refund_result())

        response = _pre_refund_client(adapter).post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "预退费分析",
                "settlement_id": "OP-001",
                "pre_refund_items": [
                    {"fee_detail_id": "F001", "refund_quantity": "0"}
                ],
            },
        )

        assert response.status_code == 422
        assert adapter.preview_calls == 0

    def test_actual_refund_waits_for_human_and_never_calls_adapter(
        self, monkeypatch
    ):
        from src.runtime.api.schemas import AgentResponse

        adapter = ApiPreRefundBillingAdapter(_api_pre_refund_result())
        confirmation = AgentResponse(
            scenario="high_risk_action_confirmation",
            status="waiting_human_confirmation",
            uncertainties=["AI 不会自动执行退费"],
            blocked_actions=["执行退费"],
        )
        monkeypatch.setattr(
            "src.runtime.policy_qa.pre_refund_flow.build_human_confirmation_response",
            lambda actions: confirmation,
        )

        response = _pre_refund_client(adapter).post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "请立即执行退费",
                "settlement_id": "OP-001",
                "pre_refund_items": [
                    {"fee_detail_id": "F001", "refund_quantity": "1"}
                ],
            },
        )
        events = _sse_events(response.text)
        result = next(data["result"] for name, data in events if name == "result")
        done = next(data for name, data in events if name == "done")

        assert result["answer_status"] == "unavailable"
        assert done["status"] == "waiting_human_confirmation"
        assert done["halt_reason"] == "high_risk_action_requires_human_confirmation"
        assert adapter.preview_calls == 0


@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_app()
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/medical-insurance-ai-agent/chat"),
        ("post", "/api/v1/medical-insurance-ai-agent/chat/stream"),
        ("get", "/api/v1/medical-insurance-ai-agent/workflows"),
        ("post", "/api/v1/medical-insurance-ai-agent/tasks/confirm"),
    ],
)
def test_retired_business_api_is_not_registered(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.post(path, json={}) if method == "post" else client.get(path)

    assert response.status_code == 404


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

    def test_transient_settlement_failure_recovers_once(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from src.runtime.api import policy_qa_routes
        from src.runtime.policy_qa.settlement_data_provider import (
            SettlementContext,
            SettlementDataUnavailableError,
        )

        class FlakyProvider:
            calls = 0

            async def get_settlement_context(self, settlement_id: str):
                self.calls += 1
                if self.calls == 1:
                    raise SettlementDataUnavailableError("temporary")
                return SettlementContext(
                    settlement_id=settlement_id,
                    basic_pooling_self_pay=4962.67,
                    total_amount=189085.85,
                )

        provider = FlakyProvider()
        monkeypatch.setattr(
            policy_qa_routes, "create_settlement_data_provider", lambda: provider
        )

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "统筹自付怎么算", "settlement_id": "S-1"},
        )
        events = _sse_events(response.text)

        assert provider.calls == 2
        assert any(name == "step" and data["step"] == "recovery" for name, data in events)
        done = next(data for name, data in events if name == "done")
        assert done["attempt_count"] == 2
        assert done["halt_reason"] == "verified"

    def test_missing_settlement_does_not_retry(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from src.runtime.api import policy_qa_routes
        from src.runtime.policy_qa.settlement_data_provider import SettlementNotFoundError

        class MissingProvider:
            calls = 0

            async def get_settlement_context(self, _settlement_id: str):
                self.calls += 1
                raise SettlementNotFoundError("missing")

        provider = MissingProvider()
        monkeypatch.setattr(
            policy_qa_routes, "create_settlement_data_provider", lambda: provider
        )

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "统筹自付怎么算", "settlement_id": "S-404"},
        )
        events = _sse_events(response.text)

        assert provider.calls == 1
        assert not any(name == "step" and data["step"] == "recovery" for name, data in events)
        done = next(data for name, data in events if name == "done")
        assert done["attempt_count"] == 1
        assert done["halt_reason"] == "non_retryable_error"

    def test_transient_failure_stops_after_two_attempts(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from src.runtime.api import policy_qa_routes
        from src.runtime.policy_qa.settlement_data_provider import SettlementDataUnavailableError

        class BrokenProvider:
            calls = 0

            async def get_settlement_context(self, _settlement_id: str):
                self.calls += 1
                raise SettlementDataUnavailableError("temporary")

        provider = BrokenProvider()
        monkeypatch.setattr(
            policy_qa_routes, "create_settlement_data_provider", lambda: provider
        )

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "统筹自付怎么算", "settlement_id": "S-1"},
        )
        events = _sse_events(response.text)

        assert provider.calls == 2
        done = next(data for name, data in events if name == "done")
        assert done["attempt_count"] == 2
        assert done["halt_reason"] == "stalled"

    def test_transient_policy_failure_recovers_once(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from types import SimpleNamespace

        from src.runtime.api import policy_qa_routes
        from src.runtime.policy_qa.structured_policy_retriever import (
            PolicyRetrievalUnavailableError,
        )

        calls = 0

        def flaky_retrieval(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PolicyRetrievalUnavailableError("temporary")
            return SimpleNamespace(selected_evidence=[], missing_required_rules=[])

        monkeypatch.setattr(policy_qa_routes, "retrieve_policy_evidence", flaky_retrieval)

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "统筹自付怎么算", "settlement_id": "S-1"},
        )
        events = _sse_events(response.text)

        assert calls == 2
        assert any(name == "step" and data["step"] == "recovery" for name, data in events)
        done = next(data for name, data in events if name == "done")
        assert done["attempt_count"] == 2
        assert done["halt_reason"] == "verified"

    def test_retry_budget_exhaustion_across_different_sources_is_not_stalled(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from src.runtime.api import policy_qa_routes
        from src.runtime.policy_qa.settlement_data_provider import SettlementDataUnavailableError
        from src.runtime.policy_qa.structured_policy_retriever import (
            PolicyRetrievalUnavailableError,
        )

        stable_provider = policy_qa_routes.create_settlement_data_provider()

        class FlakyProvider:
            calls = 0

            async def get_settlement_context(self, settlement_id: str):
                self.calls += 1
                if self.calls == 1:
                    raise SettlementDataUnavailableError("temporary")
                return await stable_provider.get_settlement_context(settlement_id)

        provider = FlakyProvider()
        policy_calls = 0

        def broken_retrieval(**_kwargs):
            nonlocal policy_calls
            policy_calls += 1
            raise PolicyRetrievalUnavailableError("temporary")

        monkeypatch.setattr(
            policy_qa_routes, "create_settlement_data_provider", lambda: provider
        )
        monkeypatch.setattr(policy_qa_routes, "retrieve_policy_evidence", broken_retrieval)

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "统筹自付怎么算", "settlement_id": "S-1"},
        )
        done = next(data for name, data in _sse_events(response.text) if name == "done")

        assert provider.calls == 2
        assert policy_calls == 1
        assert done["attempt_count"] == 2
        assert done["halt_reason"] == "max_attempts"

    def test_verified_partial_result_does_not_retry(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from types import SimpleNamespace

        from src.runtime.api import policy_qa_routes

        calls = 0

        def empty_retrieval(**_kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                selected_evidence=[], missing_required_rules=["required"]
            )

        assembler = policy_qa_routes.get_assembler("settlement_explain_skill")
        monkeypatch.setattr(
            assembler,
            "execute",
            lambda **_kwargs: SimpleNamespace(
                answer="已核对真实结算金额，但政策依据不完整。",
                calculation_trace={"steps": []},
                definition={},
                warnings=["缺少必需政策规则"],
                explanation_completeness={
                    "level": "partial_policy_matched",
                    "has_real_data": True,
                },
                policy_status="no_policy_matched",
            ),
        )
        monkeypatch.setattr(policy_qa_routes, "retrieve_policy_evidence", empty_retrieval)

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "统筹自付怎么算", "settlement_id": "S-1"},
        )
        events = _sse_events(response.text)

        assert calls == 1
        assert not any(name == "step" and data["step"] == "recovery" for name, data in events)
        result = next(data["result"] for name, data in events if name == "result")
        assert result["answer_status"] == "partial"
        done = next(data for name, data in events if name == "done")
        assert done["attempt_count"] == 1
        assert done["halt_reason"] == "verified"

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

    def test_stream_result_and_done_share_qa_turn_id(
        self, client, safe_policy_qa_dependencies
    ):
        """result 与 done 事件必须携带同一服务端 qa_turn_id，且以 qat_ 前缀生成。"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "统筹自付为什么这么多？",
                "settlement_id": "1671213",
            },
        )

        assert response.status_code == 200
        events = _sse_events(response.text)
        result_payload = next(payload for name, payload in events if name == "result")
        done_payload = next(payload for name, payload in events if name == "done")
        assert result_payload["qa_turn_id"] == done_payload["qa_turn_id"]
        assert result_payload["qa_turn_id"].startswith("qat_")
        # 公开 result 内部仍不泄露内部路由字段
        assert "selected_skill_id" not in _nested_keys(result_payload["result"])

    def test_stream_task_persistence_uses_server_turn_id_and_internal_fields(
        self, client, safe_policy_qa_dependencies, monkeypatch
    ):
        from src.runtime.api import policy_qa_routes

        persisted = []
        monkeypatch.setattr(
            policy_qa_routes,
            "record_qa_task",
            lambda **kwargs: persisted.append(kwargs),
        )

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "统筹自付为什么这么多？",
                "settlement_id": "1671213",
            },
        )

        assert response.status_code == 200
        assert persisted
        call = persisted[-1]
        assert call["qa_turn_id"].startswith("qat_")
        output_data = call["output"]
        assert set(output_data) == {
            "answer_excerpt",
            "answer_status",
            "evidence_count",
            "internal_run_id",
            "selected_skill_id",
            "question_excerpt",
            "attempt_count",
            "halt_reason",
        }
        assert output_data["evidence_count"] == 1
        assert output_data["attempt_count"] == 1
        assert output_data["halt_reason"] == "verified"

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
        assert error_payload.pop("qa_turn_id").startswith("qat_")
        assert done_payload.pop("qa_turn_id").startswith("qat_")
        assert error_payload == {
            "error_code": "POLICY_QA_FAILED",
            "attempt_count": 1,
            "halt_reason": "non_retryable_error",
            "message": "政策问答处理失败，请稍后重试或联系医保办。",
        }
        assert done_payload == {
            "answer_status": "unavailable",
            "success": False,
            "error_code": "POLICY_QA_FAILED",
            "attempt_count": 1,
            "halt_reason": "non_retryable_error",
        }
        public_stream = response.text.casefold()
        assert all(
            token not in public_stream
            for token in ("select", "password", "yb_zyfdxx", "secret")
        )


class TestSettlementExplanationEndpoint:
    @pytest.mark.parametrize(
        ("params", "expected_code", "expected_message"),
        [
            (
                {"settlement_id": ""},
                "POLICY_QA_INVALID_REQUEST",
                "settlement_id 不能为空。",
            ),
            (
                {"settlement_id": "S001", "compare_with": "S001"},
                "POLICY_QA_INVALID_COMPARISON",
                "对比结算单号不能与主结算单号相同。",
            ),
        ],
    )
    def test_rest_explicit_400_uses_standard_error_model(
        self, client, params, expected_code, expected_message
    ):
        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params=params,
        )

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert set(detail) == {"error_code", "message", "audit_event"}
        assert detail["error_code"] == expected_code
        assert detail["message"] == expected_message
        assert detail["audit_event"] == {"operation": "settlement_explanation"}

    @pytest.mark.parametrize(
        ("unsafe_text", "forbidden_token"),
        [
            ("来源zyfdxx.bdgryf。", "zyfdxx.bdgryf"),
            ("来源ZYDYXX.BCYBNJE!", "zydyxx.bcybnje"),
            ("金额bddezf。", "bddezf"),
            ("金额BDGRYF，", "bdgryf"),
            ("执行MERGE INTO claims USING source ON claims.id=source.id。", "merge"),
            ("连接DSN=hospital;password=secret;token=abc123。", "password"),
        ],
    )
    def test_rest_success_sanitizes_extended_internal_text(
        self, client, monkeypatch, unsafe_text, forbidden_token
    ):
        from src.runtime.api import policy_qa_routes

        async def fake_process(_settlement_id, _question=""):
            payload = _internal_settlement_payload()
            payload["answer"] = unsafe_text
            return payload

        monkeypatch.setattr(policy_qa_routes, "_process_single_settlement", fake_process)

        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "1671213"},
        )

        assert response.status_code == 200
        assert forbidden_token not in response.json()["answer"].casefold()

    @pytest.mark.parametrize(
        "internal_excerpt",
        [
            "zyfdxx.bdgryf",
            "yb_zyfdxx.bdtczf",
            "tables_queried",
        ],
    )
    def test_rest_drops_table_or_field_only_evidence(
        self, client, monkeypatch, internal_excerpt
    ):
        from src.runtime.api import policy_qa_routes

        async def fake_process(_settlement_id, _question=""):
            payload = _internal_settlement_payload()
            payload["policy_evidence"] = [
                {
                    "title": "内部字段",
                    "clause": internal_excerpt,
                    "score": 0.99,
                }
            ]
            return payload

        monkeypatch.setattr(policy_qa_routes, "_process_single_settlement", fake_process)

        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "1671213"},
        )

        assert response.status_code == 200
        result = response.json()
        assert result["policy_evidence"] == []
        assert result["citations"] == []
        assert result["verification_summary"]["policy_count"] == 0
        assert result["answer_status"] == "partial"
        assert result["uncertainties"]

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


class TestSettlementExplanationCompare:
    """compare_with 对比模式：settlement_compare_skill 确定性 diff + 归因。"""

    @staticmethod
    def _contexts():
        from src.runtime.policy_qa.settlement_data_provider import SettlementContext

        def _make(sid, deductible, date, cycle_count, cycle_no, person_type="退休人员"):
            return SettlementContext(
                settlement_id=sid,
                person_type=person_type,
                insurance_type="城镇职工基本医疗保险",
                service_type="普通住院",
                hospital_level="三级医院",
                deductible=deductible,
                medical_insurance_inner_amount=20000.0,
                basic_pooling_payment=15000.0,
                basic_pooling_self_pay=4962.67,
                large_amount_payment=0.0,
                large_amount_self_pay=0.0,
                personal_total_pay=6000.0,
                total_amount=21000.0,
                settlement_date=date,
                yearly_cycle_count=cycle_count,
                cycle_no=cycle_no,
            )

        return {
            # 基准：上年末第二次住院，起付线已减半
            "S001": _make("S001", 325.0, "2025-12-20", 2, "2"),
            # 对比单：新一年首次住院，起付线重新累计（跨年场景）
            "S002": _make("S002", 650.0, "2026-01-05", 1, "1"),
            # 第三张：人员类别变化场景
            "S003": _make("S003", 650.0, "2026-02-10", 1, "1", person_type="在职人员"),
        }

    def _mount(self, monkeypatch, contexts, with_evidence=True):
        from types import SimpleNamespace

        from skills.settlement_compare_skill.assembler import SettlementCompareAssembler
        from src.runtime.api import policy_qa_routes
        from src.runtime.policy_qa.settlement_data_provider import SettlementNotFoundError

        class FakeProvider:
            async def get_settlement_context(self, settlement_id: str):
                if settlement_id not in contexts:
                    raise SettlementNotFoundError(settlement_id)
                return contexts[settlement_id]

        monkeypatch.setattr(
            policy_qa_routes, "create_settlement_data_provider", lambda: FakeProvider()
        )
        monkeypatch.setattr(
            policy_qa_routes,
            "get_assembler",
            lambda skill_id: SettlementCompareAssembler()
            if skill_id == "settlement_compare_skill"
            else None,
        )

        def fake_retrieve(settlement_context, host, port, custom_queries=None):
            selected = []
            if with_evidence:
                for q in custom_queries or []:
                    # 每个 query 回 2 条证据，满足 _build_public_result 的 full 门槛（policy_count>=2）
                    for i in (1, 2):
                        selected.append(SimpleNamespace(
                            query_name=q.query_name,
                            source_text=f"{q.query_name} 对应的政策条文内容 {i}。",
                            rule_type="起付线",
                            score=1.0,
                            applied_reason="匹配对比归因政策规则",
                        ))
            return SimpleNamespace(selected_evidence=selected, missing_required_rules=[])

        monkeypatch.setattr(policy_qa_routes, "retrieve_policy_evidence", fake_retrieve)

    def test_compare_cross_year_deductible_complete(self, client, monkeypatch):
        """跨年住院对比：起付线差异命中归因规则，证据齐全 → complete。"""
        self._mount(monkeypatch, self._contexts())

        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "S001", "compare_with": "S002"},
        )

        assert response.status_code == 200
        result = response.json()
        assert result["answer_status"] == "complete"
        assert "S002" in result["answer"]
        assert "起付线" in result["answer"]
        assert "重新累计" in result["answer"]
        # 逐项差异进入公开计算步骤
        assert result["calculation_steps"]
        assert result["citations"]
        assert result["verification_summary"]["policy_count"] > 0

    def test_compare_backward_compatible_single_value(self, client, monkeypatch):
        """compare_with 单值用法保持兼容。"""
        self._mount(monkeypatch, self._contexts())
        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "S001", "compare_with": "S002"},
        )
        assert response.status_code == 200

    def test_compare_three_settlements_comma_separated(self, client, monkeypatch):
        """逗号分隔支持 3 张：基准 vs S002、基准 vs S003 各成一节。"""
        self._mount(monkeypatch, self._contexts())
        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "S001", "compare_with": "S002,S003"},
        )
        assert response.status_code == 200
        answer = response.json()["answer"]
        assert "【结算单 S002】" in answer
        assert "【结算单 S003】" in answer
        # S003 人员类别变化 → 命中人员类别归因
        assert "人员类别" in answer

    def test_compare_duplicate_extra_ids_deduped(self, client, monkeypatch):
        """compare_with 内重复 id 去重后仍合法。"""
        self._mount(monkeypatch, self._contexts())
        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "S001", "compare_with": "S002,S002"},
        )
        assert response.status_code == 200

    def test_compare_over_limit_400(self, client, monkeypatch):
        """含主结算单超过 5 张 → 400。"""
        self._mount(monkeypatch, self._contexts())
        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "S001", "compare_with": "S002,S003,S004,S005,S006"},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error_code"] == "POLICY_QA_INVALID_COMPARISON"

    def test_compare_settlement_not_found_404(self, client, monkeypatch):
        """任一对比结算单不存在 → 404。"""
        self._mount(monkeypatch, self._contexts())
        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "S001", "compare_with": "S999"},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["error_code"] == "POLICY_QA_SETTLEMENT_NOT_FOUND"

    def test_compare_no_evidence_partial_with_uncertainties(self, client, monkeypatch):
        """政策证据缺失 → 不为 complete，且声明 uncertainties。"""
        self._mount(monkeypatch, self._contexts(), with_evidence=False)
        response = client.get(
            "/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation",
            params={"settlement_id": "S001", "compare_with": "S002"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["answer_status"] in {"partial", "unavailable"}
        assert result["citations"] == []
        assert result["uncertainties"]


class TestPolicyQAFeedback:
    """「回答有误」反馈端点：客户端不能伪造来源，服务端按 ID 读取并鉴权。"""

    def _seed_qa_turn(
        self,
        *,
        qa_turn_id="qat_feedback_1",
        user_id="user-1",
        tenant_id="default",
        selected_skill_id="deductible",
    ) -> None:
        from src.runtime.task_closure.service import create_task

        create_task(
            task_id=qa_turn_id,
            task_type="policy_qa",
            description="政策问答",
            responsible_role="cashier",
            workflow_id="wf-fb",
            executor_type="skill",
            input_data={
                "question_excerpt": "起付线怎么计算",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "role": "cashier",
                "session_id": "sess-fb",
            },
            output_data={
                "answer_excerpt": "按年度累计计算",
                "answer_status": "complete",
                "selected_skill_id": selected_skill_id,
            },
            status="completed",
        )

    def _client_with_principal(self, principal):
        from src.runtime.api.app import create_app
        from src.runtime.api import policy_qa_routes

        app = create_app()
        app.dependency_overrides[policy_qa_routes.get_policy_qa_feedback_principal] = (
            lambda: principal
        )
        return TestClient(app)

    def test_feedback_rejects_client_supplied_source_fields(self):
        from src.runtime.skill_management.regression_mining_service import (
            RegressionPrincipal,
        )

        # 客户端不得携带 question/answer/selected_skill_id（鉴权通过后仍拒绝）
        client = self._client_with_principal(
            RegressionPrincipal(user_id="user-1", tenant_id="default")
        )
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/feedback",
            json={
                "qa_turn_id": "qat_feedback_1",
                "reason_code": "wrong_calculation",
                "question": "伪造问题",
                "selected_skill_id": "fake",
            },
        )
        assert response.status_code == 422

    def test_feedback_returns_pool_id_and_dedups(self):
        from src.runtime.skill_management.regression_mining_service import (
            RegressionPrincipal,
        )

        self._seed_qa_turn()
        client = self._client_with_principal(
            RegressionPrincipal(user_id="user-1", tenant_id="default")
        )
        body = {
            "qa_turn_id": "qat_feedback_1",
            "reason_code": "wrong_calculation",
            "comment": "计算口径不对",
        }
        first = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/feedback",
            json=body,
        )
        second = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/feedback",
            json=body,
        )
        assert first.status_code == 200
        assert first.json()["pool_id"] == second.json()["pool_id"]
        assert first.json()["error_dimension"] == "calculation"

    def test_feedback_cross_user_returns_404_without_disclosure(self):
        from src.runtime.skill_management.regression_mining_service import (
            RegressionPrincipal,
        )

        self._seed_qa_turn(user_id="user-1", tenant_id="default")
        client = self._client_with_principal(
            RegressionPrincipal(user_id="intruder", tenant_id="default")
        )
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/feedback",
            json={
                "qa_turn_id": "qat_feedback_1",
                "reason_code": "wrong_routing",
            },
        )
        assert response.status_code == 404
        # 不泄露存在性：错误体不包含内部细节
        assert "detail" in response.json()


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
