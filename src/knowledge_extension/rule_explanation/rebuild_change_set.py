"""P0 数据修复：原地重建变更集 CS_TASK_866e20c68f2f97db（同 ID 刷新 items）。

背景：U1 修复 parse 后，ext_2c1072e169ea（封顶线）/ext_3e563525f068（调整方案）
的 unit_id 已重挂到第三十六条 proviso 叶子（n_am4Z-vrXIWM- / n_gY4pJLBgwSAX）。
本脚本用工作台最新归属（含 proviso 单元）重新聚合变更集，使页面反映修复。

用法：python -m src.knowledge_extension.rule_explanation.rebuild_change_set
"""
from __future__ import annotations

import sys

from src.config.production import DATABASE_URL
from src.knowledge_extension.rule_explanation.change_set_models import SourceUnitRevision
from src.knowledge_extension.rule_explanation.change_set_service import (
    ChangeSetService,
    SelectedKnowledgeUnit,
)
from src.knowledge_extension.rule_explanation.change_set_store import (
    PostgresChangeSetStore,
)
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    KnowledgeBuildUnitRevision,
)
from src.knowledge_extension.rule_explanation.knowledge_build_service import (
    unit_revision_id_for,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)
from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

CHANGE_SET_ID = "CS_TASK_866e20c68f2f97db"
# 原构建任务的单元选择（旧变更集快照已被误覆盖，从任务 payload 恢复）
TASK_ID = "KB_20260807_b141165f3192"


def _load_task_units() -> list[KnowledgeBuildUnitRevision]:
    import json

    import psycopg

    from src.config.production import DATABASE_URL as URL

    with psycopg.connect(URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT payload FROM policy_knowledge_build_tasks WHERE task_id=%s",
            (TASK_ID,),
        )
        row = cur.fetchone()
        if row is None or not row[0]:
            raise RuntimeError(f"任务 {TASK_ID} 不存在")
        payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return [KnowledgeBuildUnitRevision(**u) for u in payload["units"]]


def main() -> int:
    workbench = KnowledgeWorkbenchService(pipeline_store=PipelineStore())
    store = PostgresChangeSetStore(database_url=DATABASE_URL)
    service = ChangeSetService(workbench_service=workbench, store=store)

    cs = store.get(CHANGE_SET_ID)
    if cs is None:
        print(f"[error] 变更集不存在: {CHANGE_SET_ID}")
        return 1
    print(f"[info] 变更集: {CHANGE_SET_ID} items={len(cs.items)} status={cs.status}")

    original_units = _load_task_units()
    print(f"[info] 原任务选择单元数: {len(original_units)}")

    # 工作台最新单元（U1 修复后归属，含 proviso）
    document = workbench.get_document(cs.doc_id)
    units_by_key = {(u.doc_id, u.unit_id): u for u in document.units}
    print(f"[info] 工作台单元数: {len(document.units)}")

    # 选择：原任务选中的单元 + 与它们同父条款路径的新增 reviewed 单元（如第三十六条 proviso）
    selected: list[SelectedKnowledgeUnit] = []
    seen: set[tuple[str, str]] = set()
    parent_paths: set[str] = set()
    for rev in original_units:
        unit = units_by_key.get((rev.doc_id, rev.unit_id))
        if unit is None:
            print(f"[warn] 原单元已不在工作台: {rev.unit_id}")
            continue
        source_rev = SourceUnitRevision(
            doc_id=rev.doc_id,
            doc_title=unit.doc_title,
            unit_id=rev.unit_id,
            unit_revision_id=rev.unit_revision_id,
            path=list(unit.path),
        )
        selected.append(SelectedKnowledgeUnit(unit=unit, source_revision=source_rev))
        seen.add((rev.doc_id, rev.unit_id))
        if len(unit.path) >= 2:
            parent_paths.add("\0".join(unit.path[:-1]))
    for unit in document.units:
        key = (unit.doc_id, unit.unit_id)
        if key in seen or unit.status not in {"reviewed", "published"}:
            continue
        # 仅收与已选单元同一父条款（如第三十六条 proviso 补充句），不收整篇其他条款
        if len(unit.path) < 2 or "\0".join(unit.path[:-1]) not in parent_paths:
            continue
        rev = SourceUnitRevision(
            doc_id=unit.doc_id,
            doc_title=unit.doc_title,
            unit_id=unit.unit_id,
            unit_revision_id=unit_revision_id_for(
                doc_id=unit.doc_id, unit_id=unit.unit_id, source_text=unit.source_text
            ),
            path=list(unit.path),
        )
        selected.append(SelectedKnowledgeUnit(unit=unit, source_revision=rev))
        seen.add(key)
        print(f"[info] 新增同条款单元: {unit.unit_id} ({unit.path[-1][:36]})")

    # 同 ID 重建（task_id 不变 → change_set_id_for_task 不变）
    rebuilt = service.build_for_units(
        task_id=cs.build_task_id or f"KB_rebuild_{CHANGE_SET_ID}",
        task_name=cs.doc_title,
        units=selected,
        semantic_contract_version=cs.semantic_contract_version or "",
        supersedes_candidate_id=cs.supersedes_candidate_id,
    )
    assert rebuilt.change_set_id == CHANGE_SET_ID, (
        f"重建 ID 不一致: {rebuilt.change_set_id} != {CHANGE_SET_ID}"
    )

    store.save(rebuilt)
    print(f"[done] 重建完成: {rebuilt.change_set_id} items={len(rebuilt.items)} "
          f"source_units={len(rebuilt.source_units)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
