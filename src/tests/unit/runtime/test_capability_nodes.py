"""Tests for capability nodes: models, registry, and executor."""
from src.runtime.capability_nodes import CapabilityExecutor, CapabilityNode, CapabilityRegistry


class TestCapabilityNodeModel:

    def test_create_node_with_minimal_fields(self):
        node = CapabilityNode(node_id="test_node", name="测试节点", description="A test node")
        assert node.node_id == "test_node"
        assert node.name == "测试节点"
        assert node.description == "A test node"
        assert node.capabilities == []
        assert node.version == "1.0.0"
        assert node.status == "active"
        assert node.input_schema == {}
        assert node.output_schema == {}

    def test_create_node_with_all_fields(self):
        node = CapabilityNode(
            node_id="full_node",
            name="全量节点",
            description="A node with all fields",
            capabilities=["risk_analysis", "rule_explanation"],
            version="2.0.0",
            status="inactive",
            input_schema={"type": "object", "properties": {"patient_id": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"risk": {"type": "string"}}},
        )
        assert node.node_id == "full_node"
        assert len(node.capabilities) == 2
        assert node.version == "2.0.0"
        assert node.status == "inactive"
        assert "patient_id" in node.input_schema["properties"]
        assert "risk" in node.output_schema["properties"]


class TestCapabilityRegistry:

    def setup_method(self) -> None:
        self.registry = CapabilityRegistry()
        self.node_a = CapabilityNode(
            node_id="node_a",
            name="节点A",
            description="First node",
            capabilities=["risk_analysis", "drg"],
        )
        self.node_b = CapabilityNode(
            node_id="node_b",
            name="节点B",
            description="Second node",
            capabilities=["pre_audit"],
        )

    def test_register_and_get_node(self):
        self.registry.register(self.node_a)
        retrieved = self.registry.get_node("node_a")
        assert retrieved is not None
        assert retrieved.node_id == "node_a"
        assert retrieved.name == "节点A"

    def test_get_node_returns_none_for_unknown(self):
        assert self.registry.get_node("nonexistent") is None

    def test_find_by_capability(self):
        self.registry.register(self.node_a)
        self.registry.register(self.node_b)
        results = self.registry.find_by_capability("risk_analysis")
        assert len(results) == 1
        assert results[0].node_id == "node_a"

    def test_find_by_capability_no_match(self):
        self.registry.register(self.node_a)
        results = self.registry.find_by_capability("nonexistent")
        assert results == []

    def test_list_nodes(self):
        self.registry.register(self.node_a)
        self.registry.register(self.node_b)
        all_nodes = self.registry.list_nodes()
        assert len(all_nodes) == 2
        node_ids = {n.node_id for n in all_nodes}
        assert node_ids == {"node_a", "node_b"}

    def test_register_replaces_existing(self):
        self.registry.register(self.node_a)
        replacement = CapabilityNode(node_id="node_a", name="替换节点", description="Replacement")
        self.registry.register(replacement)
        retrieved = self.registry.get_node("node_a")
        assert retrieved.name == "替换节点"

    def test_unregister(self):
        self.registry.register(self.node_a)
        self.registry.unregister("node_a")
        assert self.registry.get_node("node_a") is None
        assert self.registry.list_nodes() == []

    def test_unregister_nonexistent_does_not_raise(self):
        self.registry.unregister("nonexistent")
        assert True


class TestCapabilityExecutor:

    def setup_method(self) -> None:
        self.registry = CapabilityRegistry()
        self.registry.register(
            CapabilityNode(
                node_id="medical_record_risk_analysis",
                name="病案风险分析节点",
                description="分析病案首页质量风险",
                capabilities=["medical_record", "risk_analysis"],
                input_schema={"type": "object", "properties": {"patient_id": {"type": "string"}, "encounter_id": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"risk": {"type": "string"}}},
            )
        )
        self.registry.register(
            CapabilityNode(
                node_id="drg_dip_risk_analysis",
                name="DRG/DIP风险分析节点",
                description="分析DRG/DIP支付风险",
                capabilities=["drg_dip", "risk_analysis"],
                input_schema={"type": "object", "properties": {"patient_id": {"type": "string"}, "encounter_id": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"risk": {"type": "string"}}},
            )
        )
        self.registry.register(
            CapabilityNode(
                node_id="pre_audit_explanation",
                name="事前审核结果解释节点",
                description="解释事前审核结果",
                capabilities=["pre_audit", "rule_explanation"],
                input_schema={"type": "object", "properties": {"patient_id": {"type": "string"}, "encounter_id": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"risk": {"type": "string"}}},
            )
        )
        self.executor = CapabilityExecutor(self.registry)

    def test_execute_medical_record_risk_analysis(self):
        result = self.executor.execute("medical_record_risk_analysis", {"patient_id": "P001", "encounter_id": "E001"})
        assert result["status"] == "success"
        assert result["node_id"] == "medical_record_risk_analysis"
        assert "risk" in result["result"]
        assert result["result"]["source_system"] == "medical_record"

    def test_execute_drg_dip_risk_analysis(self):
        result = self.executor.execute("drg_dip_risk_analysis", {"patient_id": "P001", "encounter_id": "E001"})
        assert result["status"] == "success"
        assert result["node_id"] == "drg_dip_risk_analysis"
        assert "risk" in result["result"]
        assert result["result"]["source_system"] == "drg_dip"

    def test_execute_pre_audit_explanation(self):
        result = self.executor.execute("pre_audit_explanation", {"patient_id": "P001", "encounter_id": "E001"})
        assert result["status"] == "success"
        assert result["node_id"] == "pre_audit_explanation"
        assert "risk" in result["result"]
        assert result["result"]["source_system"] == "pre_audit"

    def test_execute_unknown_node(self):
        result = self.executor.execute("nonexistent_node", {})
        assert result["status"] == "error"
        assert "node not found" in result["error"]

    def test_execute_inactive_node(self):
        self.registry.register(
            CapabilityNode(node_id="inactive_node", name="非活跃节点", description="Not active", status="inactive")
        )
        result = self.executor.execute("inactive_node", {})
        assert result["status"] == "error"
        assert "not active" in result["error"]

    def test_execute_no_handler(self):
        self.registry.register(
            CapabilityNode(node_id="no_handler_node", name="无处理器", description="No handler")
        )
        result = self.executor.execute("no_handler_node", {})
        assert result["status"] == "error"
        assert "no handler registered" in result["error"]

    def test_register_custom_handler(self):
        self.registry.register(
            CapabilityNode(node_id="custom_node", name="自定义节点", description="Custom")
        )
        self.executor.register_handler("custom_node", lambda inputs: {"custom": True, "input_received": inputs.get("key")})
        result = self.executor.execute("custom_node", {"key": "value"})
        assert result["status"] == "success"
        assert result["result"]["custom"] is True
        assert result["result"]["input_received"] == "value"


class TestIntegration:

    def test_registry_and_executor_workflow(self):
        registry = CapabilityRegistry()
        registry.register(
            CapabilityNode(
                node_id="medical_record_risk_analysis",
                name="病案风险分析节点",
                description="分析病案首页质量风险",
                capabilities=["medical_record", "risk_analysis"],
            )
        )
        executor = CapabilityExecutor(registry)

        found = registry.find_by_capability("risk_analysis")
        assert len(found) == 1
        assert found[0].node_id == "medical_record_risk_analysis"

        result = executor.execute("medical_record_risk_analysis", {"patient_id": "P001", "encounter_id": "E001"})
        assert result["status"] == "success"
        assert "risk" in result["result"]
