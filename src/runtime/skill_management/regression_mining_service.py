"""Skill 回归案例挖掘应用服务。

固定流水线：按服务端 ID 读取来源 → 所有权/租户校验 → 原因码映射维度 →
脱敏快照 → 二次敏感扫描 → 计算 source_hash → 按 (tenant, qa_turn) 去重创建 →
审计（不含原文）。原文患者标识绝不进入存储、模型输入、日志或审计事件。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol

from src.data_platform.storage.skill.regression_ports import SkillRegressionStorage
from src.domain.skill.regression_models import (
    SkillErrorDimension,
    SkillEvalCasePoolItem,
    SkillFeedbackReasonCode,
    reason_code_to_dimension,
)
from src.security.desensitization.service import (
    residual_sensitive_patterns as detect_residual_sensitive,
    sanitize_regression_snapshot,
)

logger = logging.getLogger(__name__)


class QATurnNotAccessibleError(PermissionError):
    """问答轮次不存在或不属于当前用户/租户（统一不泄露存在性）。"""


class SensitiveFeedbackRejectedError(ValueError):
    """脱敏后仍残留敏感信息，已阻断入池并记录安全审计。"""


@dataclass(frozen=True)
class RegressionPrincipal:
    """反馈/挖掘调用方身份（来自认证上下文，非查询参数）。"""

    user_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class QATurnSource:
    """按 qa_turn_id 从服务端读取的脱敏前来源快照。"""

    qa_turn_id: str
    user_id: str
    tenant_id: str
    question: str
    answer: str
    selected_skill_id: str | None = None


class QASourceReader(Protocol):
    def get_qa_turn(self, qa_turn_id: str) -> QATurnSource | None: ...


class HistoryMiningStatus(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    FORBIDDEN = "forbidden"
    REJECTED_SENSITIVE = "rejected_sensitive"


@dataclass(frozen=True)
class HistoryMiningOutcome:
    qa_turn_id: str
    status: HistoryMiningStatus
    pool_id: str | None = None


_BATCH_LIMIT = 100


def _source_hash(
    *, question: str, answer: str, comment: str, selected_skill_id: str | None
) -> str:
    payload = f"{question}|{answer}|{comment}|{selected_skill_id or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _coerce_reason_code(reason_code: SkillFeedbackReasonCode) -> SkillFeedbackReasonCode:
    if isinstance(reason_code, SkillFeedbackReasonCode):
        return reason_code
    return SkillFeedbackReasonCode(str(reason_code))


class RegressionMiningService:
    def __init__(
        self,
        *,
        storage: SkillRegressionStorage,
        qa_source_reader: QASourceReader,
        audit_emitter=None,
    ) -> None:
        self._storage = storage
        self._reader = qa_source_reader
        self._audit_emitter = audit_emitter

    def collect_feedback(
        self,
        *,
        principal: RegressionPrincipal,
        qa_turn_id: str,
        reason_code: SkillFeedbackReasonCode,
        comment: str | None,
        idempotency_key: str,
    ) -> SkillEvalCasePoolItem:
        reason_code = _coerce_reason_code(reason_code)
        source = self._load_and_authorize(principal, qa_turn_id)
        dimension = reason_code_to_dimension(reason_code)
        snapshot = sanitize_regression_snapshot(
            question=source.question,
            answer=source.answer,
            comment=comment,
        )
        self._block_if_residual_sensitive(snapshot)
        item = self._build_pool_item(
            principal=principal,
            source=source,
            dimension=dimension,
            reason_code=reason_code,
            snapshot=snapshot,
        )
        persisted = self._storage.create_pool_item(item)
        self._emit_audit(
            operation="skill_eval_feedback_collected",
            principal=principal,
            pool_id=persisted.pool_id,
            reason_code=reason_code.value,
            dimension=dimension.value,
        )
        return persisted

    def collect_from_history(
        self,
        *,
        principal: RegressionPrincipal,
        qa_turn_ids: list[str],
        reason_code: SkillFeedbackReasonCode,
        comment: str | None,
    ) -> list[HistoryMiningOutcome]:
        if len(qa_turn_ids) > _BATCH_LIMIT:
            raise ValueError(f"批量入池上限为 {_BATCH_LIMIT} 条")
        reason_code = _coerce_reason_code(reason_code)
        dimension = reason_code_to_dimension(reason_code)
        results: list[HistoryMiningOutcome] = []
        for qa_turn_id in qa_turn_ids:
            source = self._reader.get_qa_turn(qa_turn_id)
            if source is None or not self._same_tenant(principal, source):
                results.append(
                    HistoryMiningOutcome(qa_turn_id=qa_turn_id, status=HistoryMiningStatus.FORBIDDEN)
                )
                continue
            try:
                snapshot = sanitize_regression_snapshot(
                    question=source.question,
                    answer=source.answer,
                    comment=comment,
                )
            except Exception:  # noqa: BLE001 - 单项失败不回滚其他项
                logger.warning("sanitize failed for %s", qa_turn_id)
                results.append(
                    HistoryMiningOutcome(
                        qa_turn_id=qa_turn_id,
                        status=HistoryMiningStatus.REJECTED_SENSITIVE,
                    )
                )
                continue
            if detect_residual_sensitive(_snapshot_text(snapshot)):
                results.append(
                    HistoryMiningOutcome(
                        qa_turn_id=qa_turn_id,
                        status=HistoryMiningStatus.REJECTED_SENSITIVE,
                    )
                )
                continue
            before = self._storage.count_pool_items()
            item = self._build_pool_item(
                principal=principal,
                source=source,
                dimension=dimension,
                reason_code=reason_code,
                snapshot=snapshot,
            )
            persisted = self._storage.create_pool_item(item)
            status = (
                HistoryMiningStatus.DUPLICATE
                if self._storage.count_pool_items() == before
                else HistoryMiningStatus.CREATED
            )
            results.append(
                HistoryMiningOutcome(
                    qa_turn_id=qa_turn_id,
                    status=status,
                    pool_id=persisted.pool_id,
                )
            )
        return results

    def _load_and_authorize(
        self, principal: RegressionPrincipal, qa_turn_id: str
    ) -> QATurnSource:
        source = self._reader.get_qa_turn(qa_turn_id)
        if source is None or not self._is_owner(principal, source):
            raise QATurnNotAccessibleError("问答轮次不存在或无权访问")
        return source

    @staticmethod
    def _is_owner(principal: RegressionPrincipal, source: QATurnSource) -> bool:
        return (
            source.user_id == principal.user_id
            and source.tenant_id == principal.tenant_id
        )

    @staticmethod
    def _same_tenant(principal: RegressionPrincipal, source: QATurnSource) -> bool:
        # 评测者批量入池路径：同一租户即可（skill:evaluate 权限在 API 层校验）
        return source.tenant_id == principal.tenant_id

    def _block_if_residual_sensitive(self, snapshot) -> None:
        residual = detect_residual_sensitive(_snapshot_text(snapshot))
        if residual:
            self._emit_audit(
                operation="skill_eval_feedback_sensitive_blocked",
                principal=None,
                pool_id=None,
                reason_code="",
                dimension="",
            )
            raise SensitiveFeedbackRejectedError("反馈包含残留敏感信息，已拒绝入池")

    def _build_pool_item(
        self,
        *,
        principal: RegressionPrincipal,
        source: QATurnSource,
        dimension: SkillErrorDimension,
        reason_code: SkillFeedbackReasonCode,
        snapshot,
    ) -> SkillEvalCasePoolItem:
        return SkillEvalCasePoolItem.model_validate(
            {
                "pool_id": f"pool_{uuid.uuid4().hex}",
                "tenant_id": principal.tenant_id,
                "source_qa_turn_id": source.qa_turn_id,
                "source_user_id": principal.user_id,
                "reason_code": reason_code,
                "error_dimension": dimension,
                "comment": snapshot.comment,
                "question_excerpt": snapshot.question,
                "answer_excerpt": snapshot.answer,
                "source_selected_skill_id": source.selected_skill_id,
                "source_hash": _source_hash(
                    question=snapshot.question,
                    answer=snapshot.answer,
                    comment=snapshot.comment,
                    selected_skill_id=source.selected_skill_id,
                ),
                "created_by": principal.user_id,
            }
        )

    def _emit_audit(
        self,
        *,
        operation: str,
        principal: RegressionPrincipal | None,
        pool_id: str | None,
        reason_code: str,
        dimension: str,
    ) -> None:
        # 审计事件不含任何原始摘要或患者标识，仅记录操作与维度标签
        event = {
            "operation": operation,
            "pool_id": pool_id,
            "reason_code": reason_code,
            "dimension": dimension,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if principal is not None:
            logger.info("skill_eval_mining_audit user=%s tenant=%s %s", principal.user_id, principal.tenant_id, event)
        else:
            logger.info("skill_eval_mining_audit %s", event)
        if self._audit_emitter is not None:
            try:
                self._audit_emitter(event)
            except Exception:  # noqa: BLE001
                logger.debug("audit emitter failed", exc_info=True)


def _snapshot_text(snapshot) -> str:
    return f"{snapshot.question}\n{snapshot.answer}\n{snapshot.comment}"
