"""定时巡检调度 — issue #52 P1-6。

复用门诊同步 worker 的 claim_due_job 单进程 PostgreSQL 调度模式
（不引入 Airflow/Temporal/celery）：调度行（ops_inspection_schedule 单行）
+ 运行记录（ops_inspections），FOR UPDATE SKIP LOCKED 抢占保证并发/
多进程下同一时刻至多一次巡检。手动与定时共用同一互斥位：已有巡检执行中
时手动触发抛 InspectionInProgressError（API 409），定时轮询视为 idle。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from src.data_platform.storage.ops.ops_ports import OpsFindingStorage
from src.domain.ops.models import (
    InspectionInProgressError,
    OpsCheckerError,
    OpsInspectionRun,
    OpsInspectionStatus,
    OpsInspectionSummary,
    OpsInspectionTrigger,
)
from src.runtime.ops.service import OpsHealthService, OpsInspectionResult

logger = logging.getLogger(__name__)

# 定时巡检的系统操作者（区别于 finding 事件 actor 的 system:ops-inspector）
SCHEDULER_ACTOR = "system:ops-scheduler"

DEFAULT_INSPECTION_INTERVAL_MINUTES = 1440  # 默认每日


def default_inspection_interval_minutes() -> int:
    """巡检周期（分钟）：环境变量 OPS_INSPECTION_INTERVAL_MINUTES 覆盖，默认每日。

    非法值（非整数 / < 1）回退默认值，不让调度周期因配置笔误失效。
    """
    raw = os.getenv("OPS_INSPECTION_INTERVAL_MINUTES", "").strip()
    if not raw:
        return DEFAULT_INSPECTION_INTERVAL_MINUTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_INSPECTION_INTERVAL_MINUTES
    return value if value >= 1 else DEFAULT_INSPECTION_INTERVAL_MINUTES


class OpsInspectionScheduler:
    """巡检调度器：claim 抢占 → 复用 OpsHealthService 巡检 → 完成回填留痕。"""

    def __init__(
        self,
        storage: OpsFindingStorage,
        health: OpsHealthService,
        *,
        interval_minutes: int | None = None,
    ) -> None:
        self._storage = storage
        self._health = health
        if interval_minutes is not None and interval_minutes >= 1:
            self._interval = interval_minutes
        else:
            self._interval = default_inspection_interval_minutes()

    @property
    def interval_minutes(self) -> int:
        return self._interval

    def run_manual(self, *, actor: str, now: datetime | None = None) -> OpsInspectionResult:
        """手动巡检（立即到期）：抢占失败抛 InspectionInProgressError。"""
        now = now or datetime.now(timezone.utc)
        claimed = self._storage.claim_inspection(
            now, trigger_source=OpsInspectionTrigger.MANUAL, triggered_by=actor,
        )
        if claimed is None:
            active = self._storage.get_inspection_schedule().active_inspection_id
            raise InspectionInProgressError(active)
        return self._execute(claimed, now)

    def run_scheduled_once(self, *, now: datetime | None = None) -> OpsInspectionRun | None:
        """定时巡检一轮：未到期或已被占用返回 None（worker 视为 idle）。"""
        now = now or datetime.now(timezone.utc)
        claimed = self._storage.claim_inspection(
            now, trigger_source=OpsInspectionTrigger.SCHEDULED,
            triggered_by=SCHEDULER_ACTOR,
        )
        if claimed is None:
            return None
        try:
            self._execute(claimed, now)
        except Exception as exc:
            # _execute 已落 failed 留痕并推迟下轮；worker 不因单次失败退出
            logger.warning("定时巡检 %s 执行失败: %s", claimed.inspection_id, exc)
        return self._storage.get_inspection(claimed.inspection_id)

    def get_summary(self) -> OpsInspectionSummary:
        """巡检摘要：周期 + 下次巡检时间 + 最近一次运行（含进行中）。"""
        schedule = self._storage.get_inspection_schedule()
        return OpsInspectionSummary(
            interval_minutes=self._interval,
            next_run_at=schedule.next_run_at,
            in_progress=schedule.active_inspection_id is not None,
            latest=self._storage.get_latest_inspection(),
        )

    def _execute(self, claimed: OpsInspectionRun, now: datetime) -> OpsInspectionResult:
        """执行一次已抢占的巡检并回填留痕；异常路径落 failed 后原样上抛。"""
        try:
            result = self._health.run_inspection(now=now)
        except Exception as exc:
            # 巡检整体崩溃（存储不可用等）：落 failed 留痕，消息用安全文案
            # （异常文本可能含连接信息，不落库）；下轮推迟一个周期避免失败风暴
            logger.warning("巡检 %s 执行异常: %s", claimed.inspection_id, exc)
            self._storage.complete_inspection(
                claimed.inspection_id,
                finished_at=now,
                status=OpsInspectionStatus.FAILED,
                finding_count=0,
                new_finding_count=0,
                checker_errors=[OpsCheckerError(
                    check_id="inspection", message="巡检执行异常，详见服务端日志",
                )],
                next_run_at=now + timedelta(minutes=self._interval),
            )
            raise
        self._storage.complete_inspection(
            claimed.inspection_id,
            finished_at=now,
            status=OpsInspectionStatus.SUCCEEDED,
            finding_count=result.finding_count,
            new_finding_count=result.new_finding_count,
            checker_errors=result.checker_errors,
            next_run_at=now + timedelta(minutes=self._interval),
        )
        return result.model_copy(update={
            "inspection_id": claimed.inspection_id,
            "trigger_source": claimed.trigger_source,
        })
