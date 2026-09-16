"""运营问数通道修正测试（2026-09-15 缺陷驱动）：

WF_DATA_QUERY 原走 SemanticQuery（单笔锚点模型）——运营聚合问法
「门诊统筹基金支付是多少」无 anchor，planner 抛「锚点未登记」穿透崩流。
修正：意图解析面向 Flow 已发布消费契约指标目录；执行走 FlowQueryService
.query_by_metrics（受控视图 + 勾稽门禁），与 #42 验收「指标类→受控问数」一致。
"""
from __future__ import annotations

import os

os.environ["USE_MEMORY_STORAGE"] = "1"  # 防御：独立设开关，不依赖兄弟文件 import 副作用

import json

import pytest

import src.runtime.policy_qa.data_query_intent_parser as parser_module
import src.runtime.tool_registry.data_tools as data_tools
from src.data_platform.storage.flow.flow_in_memory import InMemoryGovernedFlowStorage
from src.data_platform.storage.tool.in_memory import InMemoryToolVersionStorage
from src.domain.governed_flow.models import (
    ConsumerNode,
    FlowDefinition,
    FlowPublishedRevision,
    FlowStatus,
)
from src.runtime.flow.flow_query_service import FlowQueryService
from src.runtime.workflow.definitions import WF_DATA_QUERY
from src.runtime.workflow.executor import WorkflowExecutor
from src.runtime.tool_registry.service import ToolRegistryService
from src.domain.tool.models import (
    ToolContractKind,
    ToolDefinition,
    ToolStatus,
    ToolVersion,
)


def _published_flow_storage() -> InMemoryGovernedFlowStorage:
    """造一个已发布 flow：consumer 契约覆盖 op_fund_pay / op_total_fee。"""
    storage = InMemoryGovernedFlowStorage()
    flow = FlowDefinition(
        flow_id="flow_op",
        name="门诊运营加工",
        owner="data_governance",
        status=FlowStatus.PUBLISHED,
        revision=3,
        content_hash="c",
        nodes=[
            ConsumerNode(
                node_id="consumer_1", name="受控问数",
                consumer_kind="query_planner",
                consumes=["op_total_fee", "op_fund_pay"],
            )
        ],
        edges=[],
        source_contracts=[
            {"dataset_code": "mz_trade", "object_code": "mzjyxx", "fields": ["T_FundPay"]}
        ],
        metric_outputs=[
            {
                "metric_code": "op_fund_pay", "name": "门诊统筹基金支付金额",
                "node_id": "agg_1", "policy_definition": "口径句v4：统筹基金支付合计",
            },
            {
                "metric_code": "op_total_fee", "name": "门诊总费用",
                "node_id": "agg_1", "policy_definition": "口径句v4：医疗总费用合计",
            },
        ],
    )
    storage.create_flow(flow)
    storage.save_published_revision(FlowPublishedRevision(
        revision_id="flow_op-rev3", flow_id="flow_op", flow_revision=3,
        content_hash="c" * 64, semantic_revision="s" * 32, artifact_hash="a" * 64,
        published_at="2026-09-15T00:00:00Z", published_by="tester",
        definition=flow,
    ))
    storage.set_active_revision("flow_op", "flow_op-rev3")
    return storage


class _StubReader:
    def read(self, view_name: str, columns: list[str]) -> list[dict]:
        return [{"op_fund_pay": 113.66, "op_total_fee": 6643.69}]


class _FakeGateway:
    """mock LLM：类级 payload 由测试设置后直接替换 ModelGateway。"""

    payload: dict = {}

    def generate(self, **_kwargs):
        from src.model_service.models import ModelResponse, TokenUsage

        return ModelResponse(
            content=json.dumps(self.payload, ensure_ascii=False),
            model_name="fake",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
            finish_reason="stop",
        )


@pytest.fixture
def flow_storage(monkeypatch):
    storage = _published_flow_storage()
    monkeypatch.setattr(
        "src.data_platform.storage.flow.flow_factory.get_governed_flow_storage",
        lambda: storage,
    )
    # data_tools 内部 import factory，同样替换其取到的存储
    monkeypatch.setattr(
        "src.runtime.flow.flow_query_service.get_governed_flow_storage",
        lambda: storage,
        raising=False,
    )
    return storage


class TestParseIntentFlowChannel:
    @pytest.mark.asyncio
    async def test_parse_targets_flow_contract_metrics(self, monkeypatch, flow_storage):
        """意图解析目录=Flow 消费契约指标；输出 metric_codes，不再构造 SemanticQuery。"""
        fake = type("FakeGateway", (_FakeGateway,), {"payload": {
            "metrics": ["op_fund_pay"], "dimensions": [],
            "clarification_needed": False, "clarification_message": None,
        }})
        monkeypatch.setattr(parser_module, "ModelGateway", fake)
        result = await parser_module.parse_data_query_intent("门诊统筹基金支付是多少")

        assert result["clarification_needed"] is False
        assert result["metric_codes"] == ["op_fund_pay"]
        assert result["metrics"] == ["op_fund_pay"]
        assert "semantic_query" not in result or result.get("semantic_query") is None

    @pytest.mark.asyncio
    async def test_parse_rejects_metric_outside_contract(self, monkeypatch, flow_storage):
        fake = type("FakeGateway", (_FakeGateway,), {"payload": {
            "metrics": ["mzjyxx.T_FundPay"], "dimensions": [],
            "clarification_needed": False, "clarification_message": None,
        }})
        monkeypatch.setattr(parser_module, "ModelGateway", fake)
        result = await parser_module.parse_data_query_intent("统筹基金支付")

        assert result["clarification_needed"] is True
        assert "不在" in result["clarification_message"]


class TestFlowMetricsTool:
    def test_tool_query_flow_metrics_returns_rows_and_conclusion(self, monkeypatch, flow_storage):
        from src.runtime.tool_registry.data_tools import _query_flow_metrics

        class _StubService:
            def query_by_metrics(self, codes, dimensions=None, caller_role=None):
                class _R:
                    def model_dump(self, **_kw):
                        return {
                            "rows": [{"op_fund_pay": 113.66}],
                            "quality_status": "passed",
                            "metrics": list(codes),
                            "view_name": "v_flow_flow_op",
                            "flow_id": "flow_op",
                            "revision_id": "flow_op-rev3",
                            "artifact_hash": "a" * 64,
                            "published_by": "tester",
                            "published_at": "2026-09-15T00:00:00Z",
                        }
                return _R()

        monkeypatch.setattr(data_tools, "_flow_query_service", lambda: _StubService())
        output = _query_flow_metrics(["op_fund_pay"])

        assert output["quality_status"] == "passed"
        assert output["rows"][0]["op_fund_pay"] == 113.66
        assert "113.66" in output["conclusion"]
        assert output["citations"][0]["flow_id"]


class TestWorkflowChannelE2E:
    @pytest.mark.asyncio
    async def test_wf_data_query_uses_flow_metrics_tool(self):
        """工作流第二步必须是 Flow 消费通道（不再是语义层单笔锚点查询）。"""
        step_ids = [step.tool_id for step in WF_DATA_QUERY.steps]
        assert "tool_query_flow_metrics" in step_ids
        assert "tool_query_semantic_metrics" not in step_ids

    @pytest.mark.asyncio
    async def test_wf_data_query_executes_end_to_end(self, monkeypatch, flow_storage):
        """parse（mock LLM）→ flow 消费（stub 视图读取），全链 COMPLETE。"""
        import src.runtime.tool_registry.data_tools as data_tools

        class _StubService:
            def query_by_metrics(self, codes, dimensions=None, caller_role=None):
                class _R:
                    def model_dump(self, **_kw):
                        return {
                            "rows": [{"op_fund_pay": 113.66}],
                            "quality_status": "passed",
                            "metrics": list(codes),
                            "view_name": "v_flow_flow_op",
                            "flow_id": "flow_op",
                            "revision_id": "flow_op-rev3",
                            "artifact_hash": "a" * 64,
                            "published_by": "tester",
                            "published_at": "2026-09-15T00:00:00Z",
                        }
                return _R()

        monkeypatch.setattr(data_tools, "_flow_query_service", lambda: _StubService())

        async def _fake_parse(question: str) -> dict:
            return {
                "metric_codes": ["op_fund_pay"], "metrics": ["op_fund_pay"],
                "dimensions": [], "clarification_needed": False,
                "clarification_message": None,
            }

        registry = ToolRegistryService(InMemoryToolVersionStorage())  # 独立存储，不污染进程单例

        def _version(tool_id: str) -> ToolVersion:
            return ToolVersion(
                version_id=f"tv-{tool_id}", tool_id=tool_id, semantic_version="1.0.0",
                definition=ToolDefinition(
                    tool_id=tool_id, name=tool_id, description=tool_id,
                    contract_kind=ToolContractKind.FUNCTION, target_ref="src.runtime.flow.flow_query_service.FlowQueryService.query_by_metrics",
                ),
                status=ToolStatus.MATERIALIZED,
            )

        registry.register(_version("tool_parse_data_query_intent"), implementation=_fake_parse)
        registry.register(
            _version("tool_query_flow_metrics"),
            implementation=lambda metric_codes, dimensions=None, clarification_needed=False, clarification_message=None, caller_role=None: data_tools._query_flow_metrics(
                metric_codes, dimensions,
                clarification_needed=clarification_needed,
                clarification_message=clarification_message,
            ),
        )
        executor = WorkflowExecutor(registry)

        result = await executor.execute(WF_DATA_QUERY, context={"question": "门诊统筹基金支付是多少"})

        assert result.status.value == "complete"
        query_step = next(s for s in result.step_results if s.step_id == "query_flow_metrics")
        assert query_step.output["rows"][0]["op_fund_pay"] == 113.66
        assert "113.66" in query_step.output["conclusion"]
