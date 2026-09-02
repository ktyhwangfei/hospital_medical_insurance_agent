"""基于已发布语义查询模型读取整次住院结算上下文。"""

from __future__ import annotations

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Literal, Protocol

from src.semantic_layer.query_planner import (
    QueryAnchor,
    QueryScope,
    SemanticQuery,
    SemanticQueryResult,
    SemanticQueryService,
)
from src.semantic_layer.registry import SemanticRegistry, get_semantic_registry

import pyodbc

logger = logging.getLogger(__name__)


# ── Data model for settlement context ─────────────────────────

@dataclass
class SettlementContext:
    """整次住院语义查询结果；覆盖不完整时金额字段保持 ``None``。"""
    settlement_id: str = ""
    person_type: str = ""            # e.g. "退休人员"
    insurance_type: str = ""         # e.g. "城镇职工基本医疗保险"
    service_type: str = ""           # e.g. "普通住院"
    hospital_level: str = ""         # derived from hospital level code if available
    deductible: float | None = None
    medical_insurance_inner_amount: float | None = None
    basic_pooling_payment: float | None = None
    basic_pooling_self_pay: float | None = None
    large_amount_payment: float | None = None
    large_amount_self_pay: float | None = None
    personal_total_pay: float | None = None
    total_amount: float | None = None
    settlement_date: str = ""
    yearly_cycle_count: int = 0
    cycle_no: str = ""
    query_scope: Literal["whole_admission", "segment"] = "whole_admission"
    segment_count: int = 0
    matched_segment_count: int = 0
    coverage_status: Literal["complete", "partial", "unavailable"] = "unavailable"
    stay_start_date: str | None = None
    stay_end_date: str | None = None
    amounts_reliable: bool = False
    model_version: str = ""
    warnings: list[str] = field(default_factory=list)
    # Query trace
    tables_queried: list[str] = field(default_factory=list)
    query_profile: str = ""


# ── Protocol ──────────────────────────────────────────────────

class SettlementDataProvider(Protocol):
    """Protocol for settlement context data retrieval."""

    async def get_settlement_context(self, settlement_id: str) -> SettlementContext:
        """Query and return normalized settlement context."""
        ...

    async def run_semantic_query(self, query: SemanticQuery) -> SemanticQueryResult:
        """执行 Skill 声明的已发布只读语义查询。"""
        ...


# ── Semantic query implementation ─────────────────────────────

class SemanticSettlementDataProvider:
    """通过已发布语义模型查询全部住院分段。"""

    _METRICS = [
        "total_amount", "medical_insurance_inner_amount", "deductible",
        "basic_pooling_payment", "basic_pooling_self_pay",
        "large_amount_payment", "large_amount_self_pay", "personal_total_pay",
        "yearly_cycle_count", "person_type", "insurance_type", "service_type",
    ]

    def __init__(
        self,
        service: SemanticQueryService | None = None,
        registry: SemanticRegistry | None = None,
    ) -> None:
        self._registry = registry or get_semantic_registry()
        if service is None:
            from src.runtime.discovery.semantic_source import get_semantic_data_source

            source = get_semantic_data_source()

            def connect(datasource_id: str):
                config = source._resolve_datasource_connection(datasource_id)
                if config is None:
                    config = source._resolve_source_config()
                return source._connect(config)

            service = SemanticQueryService(self._registry, connect)
        self._service = service
        logger.info("[SETTLEMENT-DATA-PROVIDER] Semantic query provider initialized")

    async def get_settlement_context(self, settlement_id: str) -> SettlementContext:
        query = SemanticQuery(
            object_code="inpatient_settlement",
            scope=QueryScope(
                entity_code="inpatient_admission",
                anchor=QueryAnchor(
                    field_code="inpatient_registration.registration_id",
                    value=settlement_id,
                ),
                query_scope="whole_admission",
            ),
            metrics=self._METRICS,
        )
        result = await self.run_semantic_query(query)
        evidence = result.evidence
        row = result.rows[0] if result.rows else {}
        reliable = result.quality_status == "complete"

        def money(name: str) -> float | None:
            value = row.get(name)
            return float(value) if reliable and value is not None else None

        return SettlementContext(
            settlement_id=settlement_id,
            person_type=self._resolve("PERSON_TYPE", row.get("person_type")),
            insurance_type=self._resolve("FUND_TYPE", row.get("insurance_type")),
            service_type=self._resolve("YLLB", row.get("service_type")),
            deductible=money("deductible"),
            medical_insurance_inner_amount=money("medical_insurance_inner_amount"),
            basic_pooling_payment=money("basic_pooling_payment"),
            basic_pooling_self_pay=money("basic_pooling_self_pay"),
            large_amount_payment=money("large_amount_payment"),
            large_amount_self_pay=money("large_amount_self_pay"),
            personal_total_pay=money("personal_total_pay"),
            total_amount=money("total_amount"),
            settlement_date=evidence.stay_end_date or "",
            yearly_cycle_count=int(row.get("yearly_cycle_count") or 0),
            query_scope=result.query_scope,
            segment_count=evidence.segment_count,
            matched_segment_count=evidence.matched_segment_count,
            coverage_status=result.quality_status,
            stay_start_date=evidence.stay_start_date,
            stay_end_date=evidence.stay_end_date,
            amounts_reliable=reliable,
            model_version=result.model_version,
            warnings=result.warnings,
            tables_queried=evidence.datasets_used,
            query_profile=f"semantic:{evidence.plan_hash}",
        )

    async def run_semantic_query(self, query: SemanticQuery) -> SemanticQueryResult:
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._service.execute(query)
            )
        except (ConnectionError, TimeoutError) as exc:
            raise SettlementDataUnavailableError(str(exc)) from exc
        except pyodbc.Error as exc:
            sqlstate = str(exc.args[0]) if exc.args else ""
            if sqlstate.startswith("08") or sqlstate in {"HYT00", "HYT01"}:
                raise SettlementDataUnavailableError(str(exc)) from exc
            raise
        if result.evidence.anchor_count == 0:
            raise SettlementNotFoundError(
                f"未查询到真实结算数据: anchor={query.scope.anchor.value}"
            )
        versions = self._registry.list_object_versions(query.object_code)
        if versions:
            version = versions[-1]
            metrics = {item.metric_code: item for item in version.metrics}
            fields = {item.field_code: item for item in version.fields}
            value_domains: dict[str, str] = {}
            for code in query.metrics:
                metric = metrics.get(
                    code if "." in code else f"{query.object_code}.{code}"
                )
                field = fields.get(metric.fact_field_code or "") if metric else None
                domain_code = metric.value_domain if metric else None
                domain_code = domain_code or (field.value_domain if field else None)
                if domain_code:
                    value_domains[code.rsplit(".", 1)[-1]] = domain_code
            value_domains.update({
                code.rsplit(".", 1)[-1]: fields[code].value_domain
                for code in query.group_by
                if code in fields and fields[code].value_domain
            })
            for row in result.rows:
                for alias, domain_code in value_domains.items():
                    if row.get(alias) is not None:
                        row[alias] = self._registry.resolve_value(
                            domain_code, str(row[alias])
                        )
        return result

    def _resolve(self, domain_code: str, value) -> str:
        return "" if value is None else self._registry.resolve_value(domain_code, str(value))


class SettlementNotFoundError(Exception):
    """Raised when settlement data cannot be found in real DB."""
    pass


class SettlementDataUnavailableError(Exception):
    """Raised for retryable settlement source failures."""

    pass


# ── Factory ───────────────────────────────────────────────────

def create_settlement_data_provider() -> SettlementDataProvider:
    """Create provider based on DATA_SOURCE_MODE config.

    Returns a SemanticSettlementDataProvider when DATA_SOURCE_MODE=real_db.
    In any other mode, raises RuntimeError — this endpoint is designed for
    real database queries only and never falls back to mock.

    Raises:
        RuntimeError: if DATA_SOURCE_MODE != "real_db"
    """
    from src.config.production import DATA_SOURCE_MODE

    if DATA_SOURCE_MODE == "real_db":
        logger.info("[SETTLEMENT] Using semantic query provider (REAL_DB mode)")
        return SemanticSettlementDataProvider()

    logger.info(
        "[SETTLEMENT] DATA_SOURCE_MODE=%s — real DB endpoint not available. "
        "Set DATA_SOURCE_MODE=real_db to enable.",
        DATA_SOURCE_MODE,
    )
    raise RuntimeError(
        f"DATA_SOURCE_MODE={DATA_SOURCE_MODE} — "
        "REAL_DB mode required for settlement explanation queries. "
        "Set DATA_SOURCE_MODE=real_db"
    )
