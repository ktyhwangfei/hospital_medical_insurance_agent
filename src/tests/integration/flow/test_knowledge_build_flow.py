from __future__ import annotations

import json
from typing import Any

from src.knowledge_extension.rule_explanation.change_set_service import ChangeSetService
from src.knowledge_extension.rule_explanation.change_set_store import InMemoryChangeSetStore
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    CreateKnowledgeBuildTaskRequest,
    KnowledgeBuildUnitRevision,
)
from src.knowledge_extension.rule_explanation.knowledge_build_service import (
    KnowledgeBuildService,
    unit_revision_id_for,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    InMemoryKnowledgeBuildStore,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)
from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
    PolicyRuleCompiler,
)
from src.knowledge_extension.rule_explanation.policy_compiler.service import (
    PolicyCompilationService,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    InMemoryCompilationTraceStore,
)
from src.model_service.gateway import ModelGateway
from src.model_service.models import ModelResponse, TokenUsage
from src.semantic_layer.models import BusinessObject
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.tests.unit.knowledge_extension.test_knowledge_workbench import (
    FakePipelineStore,
    _leaf_ids,
    _rules,
)


class BuildFlowStore(FakePipelineStore):
    def batch_create_extractions(self, items: list[dict[str, Any]]) -> int:
        self.extractions.extend({**item, "status": "draft"} for item in items)
        return len(items)

    def update_extraction(
        self, extraction_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        extraction = self.get_extraction(extraction_id)
        if extraction is None:
            raise KeyError(extraction_id)
        extraction.update(data)
        return extraction

    def get_extraction(self, extraction_id: str) -> dict[str, Any] | None:
        return next(
            (
                extraction
                for extraction in self.extractions
                if extraction["extraction_id"] == extraction_id
            ),
            None,
        )


def test_zero_knowledge_build_extracts_compiles_and_persists_trace(monkeypatch) -> None:
    unit_id = _leaf_ids()[0]
    store = BuildFlowStore(
        [],
        unit_audit={unit_id: {"action": "approve", "reviewer": "reviewer"}},
    )
    registry_store = InMemoryRegistryStore()
    registry_store.save_object(
        BusinessObject(
            object_code="zcgz",
            domain_code="policy",
            name="政策规则",
            status="published",
            current_version="2",
        )
    )
    workbench = KnowledgeWorkbenchService(
        store, registry=SemanticRegistry(registry_store)
    )
    traces = InMemoryCompilationTraceStore()
    change_sets = InMemoryChangeSetStore()
    service = KnowledgeBuildService(
        workbench,
        ChangeSetService(
            workbench,
            change_sets,
            compilation_service=PolicyCompilationService(
                store, PolicyRuleCompiler(), traces
            ),
        ),
        InMemoryKnowledgeBuildStore(),
        orchestrator=PipelineOrchestrator(store),
        task_id_factory=lambda: "KB_FLOW_ZERO_KNOWLEDGE",
    )
    monkeypatch.setattr(
        ModelGateway,
        "generate",
        lambda self, **kwargs: ModelResponse(
            content=json.dumps(
                [{"fact_text": "测试事实", "rules": [_rules()[0]]}],
                ensure_ascii=False,
            ),
            model_name="flow-model",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        ),
    )
    unit = workbench.get_document("doc_1", include_knowledge=False).units[0]

    task = service.create_task(
        CreateKnowledgeBuildTaskRequest(
            name="零知识构建",
            created_by="tester",
            build_mode="INITIAL",
            unit_revisions=[
                KnowledgeBuildUnitRevision(
                    doc_id=unit.doc_id,
                    unit_id=unit.unit_id,
                    unit_revision_id=unit_revision_id_for(
                        doc_id=unit.doc_id,
                        unit_id=unit.unit_id,
                        source_text=unit.source_text,
                    ),
                )
            ],
        )
    )

    change_set = change_sets.get(task.result_change_set_id or "")
    assert task.status == "WAITING_REVIEW"
    assert change_set is not None and len(change_set.items) == 1
    item = change_set.items[0]
    assert item.compilation_status == "PASS"
    trace = traces.get_rule_trace(item.rule_id, run_id=item.compile_run_id)
    assert trace is not None
    assert trace.run.unit_id == unit_id
    assert store.extractions[0]["status"] == "reviewed"
