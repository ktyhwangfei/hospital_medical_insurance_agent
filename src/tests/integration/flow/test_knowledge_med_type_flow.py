"""Issue #19 Flow：零知识构建全程按医疗类别区分。

链路：LLM 桩返回不含 med_type 的规则 → 提取 intake 用单元原文分类回填
（在职职工住院费用 → 住院）→ 变更集候选 after.fields 携带 med_type
（前端按医疗类别筛选的数据来源）。
"""
from __future__ import annotations

import json

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
from src.tests.integration.flow.test_knowledge_build_flow import BuildFlowStore
from src.tests.unit.knowledge_extension.test_knowledge_workbench import _leaf_ids


def test_zero_knowledge_build_carries_med_type_from_unit(monkeypatch) -> None:
    """LLM 未提取 med_type 时，单元分类沿构建链路进入变更集候选。"""
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
        task_id_factory=lambda: "KB_FLOW_MED_TYPE",
    )
    # LLM 桩：规则刻意不带 med_type（Issue #19 缺口场景）
    monkeypatch.setattr(
        ModelGateway,
        "generate",
        lambda self, **kwargs: ModelResponse(
            content=json.dumps(
                [{
                    "fact_text": "在职职工住院费用，统筹基金支付百分之八十。",
                    "rules": [{
                        "rule_type": "payment_ratio",
                        "psn_type": "在职职工",
                        "med_type": "",
                        "payment_ratio": "80%",
                        "source_text": "在职职工住院费用，统筹基金支付百分之八十。",
                        "confidence": 0.9,
                    }],
                }],
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
            name="医疗类别区分构建",
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

    # 1) 提取记录：单元分类 + 规则继承（所有单元区分医疗类别）
    extraction = store.extractions[0]
    fields = extraction["extracted_fields"]
    assert fields["unit_med_type"] == "住院"
    assert fields["rules"][0]["med_type"] == "住院"

    # 2) 变更集候选：after.fields 携带 med_type（前端按医疗类别筛选的数据源）
    change_set = change_sets.get(task.result_change_set_id or "")
    assert change_set is not None and len(change_set.items) == 1
    after_fields = {
        f["field_code"]: f["raw_value"]
        for f in change_set.items[0].after["fields"]
    }
    assert after_fields.get("med_type") == "住院"
