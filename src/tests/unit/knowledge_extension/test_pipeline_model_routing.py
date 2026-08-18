from src.knowledge_extension.rule_explanation import pipeline_orchestrator as pipeline_module
from src.model_service.models import ModelResponse, TokenUsage


def test_policy_fact_extraction_uses_dedicated_gateway_scene(monkeypatch):
    captured = {}

    class FakeGateway:
        def generate(self, *, messages, model_type, scene, max_tokens):
            captured.update(
                messages=messages,
                model_type=model_type,
                scene=scene,
                max_tokens=max_tokens,
            )
            return ModelResponse(
                content='[{"fact_text":"测试政策事实","rules":[]}]',
                model_name="deepseek-chat",
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
                finish_reason="stop",
            )

    monkeypatch.setattr(pipeline_module, "ModelGateway", FakeGateway)

    facts = pipeline_module.PipelineOrchestrator()._extract_policy_facts(
        "测试政策正文",
        document_title="测试政策",
    )

    assert facts == [{"fact_text": "测试政策事实", "rules": []}]
    assert captured["model_type"] == "llm"
    assert captured["scene"] == "policy_fact_extraction"
    assert captured["max_tokens"] == 8192
