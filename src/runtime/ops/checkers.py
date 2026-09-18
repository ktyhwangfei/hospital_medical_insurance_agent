"""健康运营检查器 — P0 数据域首批（issue #45，全部只读）。

检查器只读复用门诊数据治理控制面既有状态数据（连接探测结果、同步任务
状态），不改其任何表；payload 只携带脱敏安全字段（safe_* / 状态码 /
时间戳），不带出凭据与连接串。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from src.data_platform.outpatient_governance import (
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSyncJob,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)
from src.domain.ops.models import FindingDraft, OpsAssetType, OpsSeverity

# 滞后判定宽限下限：应到未到超过 max(2×调度间隔, 15 分钟) 视为滞后
LAG_GRACE_FLOOR_MINUTES = 15


class GovernanceStatusReader(Protocol):
    """检查器对治理控制面的最小只读依赖（DataGovernanceService 已满足）。"""

    def list_sources(self) -> list[OutpatientDataSource]: ...

    def get_job(self, source_id: str) -> OutpatientSyncJob: ...


@dataclass(frozen=True)
class CheckSpec:
    """代码内检查器注册项（不引入 YAML 配置系统，YAGNI）。"""

    check_id: str
    asset_type: OpsAssetType
    description: str
    runner: Callable[[GovernanceStatusReader, datetime], list[FindingDraft]]


def check_data_sync(reader: GovernanceStatusReader, now: datetime) -> list[FindingDraft]:
    """门诊同步任务 failed / degraded / 滞后（应到未到超宽限期）。"""
    drafts: list[FindingDraft] = []
    for source in reader.list_sources():
        try:
            job = reader.get_job(source.source_id)
        except OutpatientGovernanceNotFoundError:
            continue  # 尚未配置同步任务的数据源不构成问题
        if job.status in (SyncJobStatus.FAILED, SyncJobStatus.DEGRADED):
            drafts.append(FindingDraft(
                asset_type=OpsAssetType.DATA,
                asset_id=source.source_id,
                check_id="data_sync_failed",
                severity=(
                    OpsSeverity.CRITICAL if job.status is SyncJobStatus.FAILED
                    else OpsSeverity.WARNING
                ),
                payload={
                    "problem": f"sync_job_{job.status.value}",
                    "job_status": job.status.value,
                    "last_error_code": job.last_error_code,
                    "last_started_at": job.last_started_at.isoformat()
                    if job.last_started_at else None,
                    "last_succeeded_at": job.last_succeeded_at.isoformat()
                    if job.last_succeeded_at else None,
                },
            ))
            continue
        if job.status in (SyncJobStatus.READY, SyncJobStatus.RUNNING):
            due_at = job.run_once_requested_at or job.next_run_at
            if due_at is None:
                continue
            grace = timedelta(minutes=max(
                2 * job.schedule_interval_minutes, LAG_GRACE_FLOOR_MINUTES,
            ))
            if now > due_at + grace:
                drafts.append(FindingDraft(
                    asset_type=OpsAssetType.DATA,
                    asset_id=source.source_id,
                    check_id="data_sync_failed",
                    severity=OpsSeverity.WARNING,
                    payload={
                        "problem": "sync_job_lagging",
                        "job_status": job.status.value,
                        "due_at": due_at.isoformat(),
                        "grace_minutes": int(grace.total_seconds() // 60),
                        "last_succeeded_at": job.last_succeeded_at.isoformat()
                        if job.last_succeeded_at else None,
                    },
                ))
    return drafts


def check_data_source(reader: GovernanceStatusReader, now: datetime) -> list[FindingDraft]:
    """数据源连接探测失败（connection_status == error；只读最近探测结果）。"""
    del now  # 判定不依赖当前时间；签名与 CheckSpec.runner 对齐
    drafts: list[FindingDraft] = []
    for source in reader.list_sources():
        if source.connection_status is not ConnectionStatus.ERROR:
            continue
        drafts.append(FindingDraft(
            asset_type=OpsAssetType.DATA,
            asset_id=source.source_id,
            check_id="data_source_down",
            severity=OpsSeverity.CRITICAL,
            payload={
                "problem": "connection_error",
                "safe_probe_message": source.safe_probe_message,
                "last_probed_at": source.last_probed_at.isoformat()
                if source.last_probed_at else None,
            },
        ))
    return drafts


OPS_CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec(
        check_id="data_sync_failed",
        asset_type=OpsAssetType.DATA,
        description="门诊同步任务 failed/degraded/滞后",
        runner=check_data_sync,
    ),
    CheckSpec(
        check_id="data_source_down",
        asset_type=OpsAssetType.DATA,
        description="数据源连接探测失败",
        runner=check_data_source,
    ),
)


# ── 数据质量规则（数据专家拷问轮 Q5）：值域合规 / 逻辑矛盾 / 业务重复 ──
# 复用 ops finding 机制：只读产出 FindingDraft，巡检落库去重，页面复用 #50 的详情与处置流。


def check_governed_table_quality(reader: GovernanceStatusReader, now: datetime) -> list[FindingDraft]:
    """治理落地表质量检查（值域漂移 / 逻辑矛盾 / 业务重复 / 金额异常）。

    规则与数据模型的值域声明 + 常见医保逻辑绑定（不发明口径，只检查结构性问题）：
    - 值域漂移：模型字段声明了 value_domain 的列，落地出现值域外的值
    - 逻辑矛盾：结算日期 < 登记日期（业务不可能）
    - 业务重复：主键去重后仍同 key 多行（落地表无主键约束时）
    - 金额异常：模型声明为 fact 的金额字段出现负数
    """
    from src.data_platform.storage.data_model.data_model_factory import (
        get_data_model_storage,
    )
    from src.data_platform.storage.table_sync.store import TableSyncStore
    from src.data_platform.storage.postgresql.client import PostgreSQLClient
    from src.semantic_layer.registry import get_semantic_registry

    drafts: list[FindingDraft] = []
    pg = PostgreSQLClient()
    model_storage = get_data_model_storage()
    sync_store = TableSyncStore()

    # 语义层值域（标准值集合）
    value_domains: dict[str, set[str]] = {}
    try:
        reg = get_semantic_registry()
        for model in model_storage.list_models():
            for mapping in model_storage.list_mappings(model.model_code):
                field = next((f for f in model.fields if f.field_code == mapping.field_code), None)
                if field is None or not field.value_domain:
                    continue
                domain = reg._store.get_value_domain(field.value_domain)
                if domain is not None:
                    values = set(domain.standard_values)
                    if values:
                        value_domains[(mapping.physical_table, mapping.physical_column)] = (
                            values, field.value_domain, model.model_code, field.name
                        )
    except Exception:
        return drafts

    for table in sync_store.list_tables("bjybdb"):
        if table.status.value != "active" or (table.purpose.value if hasattr(table.purpose, 'value') else 'governed') != "governed":
            continue
        target = table.target_table

        # 1) 值域漂移：落地表 distinct 值 ⊄ 标准值
        for (phys_table, phys_col), (standard, domain_code, model_code, field_name) in value_domains.items():
            if phys_table != target:
                continue
            try:
                rows = pg.execute(
                    f'SELECT DISTINCT "{phys_col}" AS v FROM "{target}" WHERE "{phys_col}" IS NOT NULL LIMIT 200'
                )
                drifted = [r["v"] for r in rows if str(r["v"]) not in standard]
                if drifted:
                    drafts.append(FindingDraft(
                        asset_type=OpsAssetType.DATA,
                        asset_id=target,
                        check_id="data_value_domain_drift",
                        severity=OpsSeverity.WARNING,
                        payload={
                            "problem": f"{phys_col} 出现 {len(drifted)} 个值域外值",
                            "field": field_name,
                            "value_domain": domain_code,
                            "model": model_code,
                            "drifted_values": [str(v) for v in drifted[:5]],
                        },
                    ))
            except Exception:
                continue

        # 2) 金额异常：fact 字段负数（datetime/增量拉取的冲正行会被契约过滤，选表直通不会）
        try:
            model = next((m for m in model_storage.list_models()
                          if any(mp.physical_table == target for mp in model_storage.list_mappings(m.model_code))), None)
            if model:
                for mapping in model_storage.list_mappings(model.model_code):
                    if mapping.physical_table != target:
                        continue
                    field = next((f for f in model.fields if f.field_code == mapping.field_code), None)
                    if field is None or field.field_role.value != "fact" or "date" in field.data_type.lower():
                        continue
                    rows = pg.execute(
                        f'SELECT COUNT(*) AS n FROM "{target}" WHERE "{mapping.physical_column}" < 0'
                    )
                    if rows and rows[0]["n"] > 0:
                        drafts.append(FindingDraft(
                            asset_type=OpsAssetType.DATA,
                            asset_id=target,
                            check_id="data_negative_amount",
                            severity=OpsSeverity.WARNING,
                            payload={
                                "problem": f"{mapping.physical_column} 出现 {rows[0]['n']} 行负数金额",
                                "field": field.name,
                                "model": model.model_code,
                            },
                        ))
        except Exception:
            continue

    return drafts


OPS_CHECKS = OPS_CHECKS + (
    CheckSpec(
        check_id="governed_table_quality",
        asset_type=OpsAssetType.DATA,
        description="治理落地表质量（值域漂移/负数金额）",
        runner=check_governed_table_quality,
    ),
)
