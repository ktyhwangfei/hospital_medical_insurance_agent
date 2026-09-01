"""Skill 端到端评测的稳定失败归因与聚类。"""

from __future__ import annotations

from src.domain.skill.governance_models import (
    FailureAttribution,
    FailureCluster,
    SkillEvalDimension,
    SkillEvalFailureOwner,
    SkillEvalStage,
    SkillEvalTask,
    canonical_eval_hash,
)


def attribute_failure(
    *,
    task_id: str,
    failure_code: str,
    dimension: SkillEvalDimension | None = None,
    evidence_refs: tuple[str, ...] = (),
    before_settlement_prefix: bool = False,
) -> FailureAttribution:
    """按稳定机器码归因；prefix 通过时优先定位到边界之前。"""
    if before_settlement_prefix:
        owner = SkillEvalFailureOwner.AGENT
        stage = SkillEvalStage.SETTLEMENT_LOOKUP
    elif failure_code.startswith("JUDGE_"):
        owner = SkillEvalFailureOwner.EVALUATOR
        stage = SkillEvalStage.JUDGE
    elif failure_code.startswith("EVALUATOR_"):
        owner = SkillEvalFailureOwner.EVALUATOR
        stage = SkillEvalStage.DETERMINISTIC_VERIFICATION
    elif failure_code.startswith("DATASET_"):
        owner = SkillEvalFailureOwner.DATASET
        stage = SkillEvalStage.PREFLIGHT
    else:
        owner = SkillEvalFailureOwner.AGENT
        stage = _stage_for_code(failure_code)
    return FailureAttribution(
        task_id=task_id,
        owner_type=owner,
        stage=stage,
        failure_code=failure_code,
        dimension=dimension,
        summary=f"{stage.value} 阶段未通过：{failure_code}",
        evidence_refs=evidence_refs,
    )


def _stage_for_code(code: str) -> SkillEvalStage:
    prefixes = (
        ("SETTLEMENT_", SkillEvalStage.SETTLEMENT_LOOKUP),
        ("ROUTE_", SkillEvalStage.ROUTING),
        ("POLICY_", SkillEvalStage.POLICY_RETRIEVAL),
        ("CALCULATION_", SkillEvalStage.CALCULATION),
        ("CITATION_", SkillEvalStage.DETERMINISTIC_VERIFICATION),
        ("QUALITY_", SkillEvalStage.ANSWER_COMPOSITION),
        ("SAFETY_", SkillEvalStage.DETERMINISTIC_VERIFICATION),
    )
    return next(
        (stage for prefix, stage in prefixes if code.startswith(prefix)),
        SkillEvalStage.SKILL_EXECUTION,
    )


def cluster_failures(
    tasks: dict[str, SkillEvalTask],
    attributions: list[FailureAttribution],
) -> tuple[FailureCluster, ...]:
    """按可重复键聚类，不依赖自然语言相似度。"""
    groups: dict[tuple[object, ...], list[FailureAttribution]] = {}
    for item in attributions:
        task = tasks[item.task_id]
        key = (
            item.owner_type,
            item.stage,
            item.failure_code,
            item.dimension,
            task.target_skill_id,
            tuple(sorted(task.business_tags)),
        )
        groups.setdefault(key, []).append(item)

    clusters: list[FailureCluster] = []
    for key, items in sorted(groups.items(), key=lambda pair: str(pair[0])):
        owner, stage, code, dimension, skill_id, business_tags = key
        task_ids = tuple(sorted(item.task_id for item in items))
        cluster_key = "|".join(str(value) for value in key)
        clusters.append(
            FailureCluster(
                cluster_id=f"EVC_{canonical_eval_hash(cluster_key)[:24]}",
                cluster_key=cluster_key,
                owner_type=owner,
                stage=stage,
                failure_code=code,
                dimension=dimension,
                target_skill_id=skill_id,
                task_ids=task_ids,
                representative_task_id=task_ids[0],
                business_tags=business_tags,
            )
        )
    return tuple(clusters)
