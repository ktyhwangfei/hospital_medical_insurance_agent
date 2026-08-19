"""Issue #19：构建单元医疗类别（服务端确定性分类 + 人工修正覆盖）。

验证：
- list_eligible_units 自动分类（单元原文就近、路径兜底、无信号回退通用）
- 人工修正 override 优先于自动分类，med_type_source=manual
- 删除 override 后恢复自动分类
- InMemory/Postgres UnitMedTypeStore 行为一致（内存实现聚焦测试）
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.change_set_models import (
    SourceUnitRevision,
)
from src.knowledge_extension.rule_explanation.change_set_service import (
    ChangeSetService,
    SelectedKnowledgeUnit,
)
from src.knowledge_extension.rule_explanation.change_set_store import (
    InMemoryChangeSetStore,
)
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    CreateKnowledgeBuildTaskRequest,
    KnowledgeBuildUnitRevision,
)
from src.knowledge_extension.rule_explanation.knowledge_build_service import (
    KnowledgeBuildService,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    InMemoryKnowledgeBuildStore,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeItem,
)
from src.knowledge_extension.rule_explanation.unit_med_type_store import (
    InMemoryUnitMedTypeStore,
    UnitMedTypeOverride,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)


class _WorkbenchStub:
    """最小工作台桩：直接返回指定单元列表。"""

    def __init__(self, units: list[ApprovedUnit]):
        self._units = units

    def get_document(self, doc_id: str, include_knowledge: bool = True):
        return type("Doc", (), {
            "doc_id": doc_id,
            "doc_title": "测试政策",
            "contract_version": "v1",
            "units": self._units,
        })()

    def list_document_ids(self) -> list[str]:
        return ["doc_1"]


class _ChangeSetStub:
    def list_change_sets(self):
        return []


def _unit(unit_id: str, text: str, path: list[str]) -> ApprovedUnit:
    return ApprovedUnit(
        unit_id=unit_id,
        doc_id="doc_1",
        doc_title="待遇管理政策",
        path=path,
        source_text=text,
        order_no=0,
        status="reviewed",
        knowledge_count=0,
        knowledge=[],
    )


def _knowledge_item(unit_id: str) -> KnowledgeItem:
    return KnowledgeItem(
        knowledge_id=f"kn_{unit_id}",
        unit_id=unit_id,
        extraction_id=f"ext_{unit_id}",
        relationship_source="persisted",
        business_sentence="测试",
        source_text="测试",
        fields=[],
        confidence={
            "completeness": 1.0, "source_fidelity": 1.0,
            "model_confidence": 1.0, "overall": 1.0,
        },
        citations=[],
    )


def _service(units: list[ApprovedUnit], med_store=None) -> KnowledgeBuildService:
    return KnowledgeBuildService(
        _WorkbenchStub(units),  # type: ignore[arg-type]
        _ChangeSetStub(),       # type: ignore[arg-type]
        InMemoryKnowledgeBuildStore(),
        med_type_store=med_store,
    )


def test_auto_classification_unit_text_first_then_path_fallback():
    units = [
        _unit("u_inpatient", "在职职工住院费用统筹基金支付85%", ["第三章", "第十二条"]),
        # 单元原文无类别信号 → 路径含"门诊"则用路径
        _unit("u_outpatient", "支付范围为定点零售药店", ["第三章 门诊待遇", "第八条"]),
        # 全部无信号 → 通用
        _unit("u_general", "基本医疗保险费的征缴", ["第一章", "第二条"]),
    ]
    result = _service(units).list_eligible_units()
    by_unit = {u.unit_id: u for u in result}
    assert by_unit["u_inpatient"].med_type == "住院"
    assert by_unit["u_inpatient"].med_type_source == "auto"
    assert by_unit["u_outpatient"].med_type == "门诊"
    assert by_unit["u_general"].med_type == "通用"


def test_manual_override_wins_and_delete_restores_auto():
    units = [_unit("u1", "在职职工住院费用统筹基金支付85%", ["第十二条"])]
    med_store = InMemoryUnitMedTypeStore()
    med_store.set(UnitMedTypeOverride(
        doc_id="doc_1", unit_id="u1", med_type="门诊特殊病", updated_by="tester",
    ))
    service = _service(units, med_store)

    overridden = {u.unit_id: u for u in service.list_eligible_units()}
    assert overridden["u1"].med_type == "门诊特殊病"
    assert overridden["u1"].med_type_source == "manual"

    med_store.delete("doc_1", "u1")
    restored = {u.unit_id: u for u in service.list_eligible_units()}
    assert restored["u1"].med_type == "住院"
    assert restored["u1"].med_type_source == "auto"


def test_in_memory_store_roundtrip():
    store = InMemoryUnitMedTypeStore()
    store.set(UnitMedTypeOverride(doc_id="d", unit_id="u", med_type="急诊", updated_by="a"))
    got = store.get("d", "u")
    assert got is not None and got.med_type == "急诊"
    assert store.list_all()[0].med_type == "急诊"
    assert store.delete("d", "u") is True
    assert store.get("d", "u") is None
    assert store.delete("d", "u") is False


def test_classify_compound_and_purchase_aliases():
    """用户验证发现的两类别名缺口：复合类别「门（急）诊」与「购药」。"""
    from src.knowledge_extension.rule_explanation.policy_extract.med_type_classifier import (
        classify_med_type,
    )
    # 门（急）诊：北京政策的合并结算类别，归门诊（用户人工修正印证）
    assert classify_med_type("可享受门（急）诊医疗保险待遇") == "门诊"
    assert classify_med_type("医保门(急)诊的起付标准为550元") == "门诊"
    assert classify_med_type("门急诊起付标准为1800元") == "门诊"
    # 购药：定点零售药店购药费用是独立医疗类别
    assert classify_med_type("到定点零售药店购药的费用") == "购药"


def test_classify_mixed_clause_first_occurrence_wins():
    """混合条款（门诊、急诊、住院…购药同现）：首次出现的类别信号胜出，不被字典序抢占。"""
    from src.knowledge_extension.rule_explanation.policy_extract.med_type_classifier import (
        classify_med_type,
    )
    text = "第四十九条 门诊、急诊医疗费用和住院医疗费用中由个人支付的部分，以及在定点零售药店购药的费用，由个人直接结算"
    assert classify_med_type(text) == "门诊"
    # 长别名优先：同一起始位置时「急诊留观」胜过「急诊」
    assert classify_med_type("急诊留观费用按规定报销") == "急诊留观"
