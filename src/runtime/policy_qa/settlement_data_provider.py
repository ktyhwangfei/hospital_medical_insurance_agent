"""基于已发布语义查询模型读取整次住院结算上下文。"""

from __future__ import annotations

import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from src.adapters.ports import DataSupplyConnectionPort
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

class SettlementListItem(BaseModel):
    """按时间段列出的结算单摘要。"""

    settlement_id: str
    settlement_date: str = ""
    person_type: str = ""
    insurance_type: str = ""
    service_type: str = ""
    total_amount: float | None = None
    coverage_status: Literal["complete", "partial", "unavailable"] = "complete"


class PatientSummary(BaseModel):
    """患者定位摘要（临时方案：正式接入登录验证后由登录态取代）。

    身份证号脱敏后输出（安全约束：敏感数据脱敏后输出）；卡号用于
    后续结算单过滤，不视为高敏字段。
    """

    card_no: str = ""
    id_no_masked: str = ""
    name: str = ""
    gender: str = ""
    birth_date: str = ""
    registration_id: str = ""


def mask_id_no(id_no: str) -> str:
    """身份证号脱敏：保留前 3 后 4，中间打码；非 18 位原样返回。"""
    if len(id_no) != 18:
        return id_no
    return f"{id_no[:3]}{'*' * 11}{id_no[-4:]}"


_GENDER_MAP = {"1": "男", "2": "女"}


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

    async def list_settlements_by_date_range(
        self, date_from: str, date_to: str, limit: int = 50
    ) -> list[SettlementListItem]:
        """按时间段列出结算单摘要。"""
        ...

    async def lookup_patient(self, key: str) -> PatientSummary | None:
        """按身份证号或卡号定位患者（脱敏摘要）。"""
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
        supply: "DataSupplyConnectionPort | None" = None,
    ) -> None:
        self._registry = registry or get_semantic_registry()
        if service is None:
            # #27 供给收敛：默认装配一档 SQL Server 直连适配器（组合根在此，
            # adapters 不反向依赖 runtime）；二档医院替换 supply 实现即可。
            if supply is None:
                from src.adapters.data_supply import SqlServerDirectSupplyAdapter
                from src.runtime.discovery.semantic_source import get_semantic_data_source

                source = get_semantic_data_source()
                supply = SqlServerDirectSupplyAdapter(connect_fn=source.open_connection)
            service = SemanticQueryService(self._registry, supply.connect)
        self._service = service
        # 列表查询直连数据源：supply 参数或默认装配的 connect（须在默认 supply
        # 构造之后取值，否则无参构造时 _connect 恒为 None → 列表端点误报 503）
        self._connect = supply.connect if supply else None
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

    async def list_settlements_by_date_range(
        self,
        date_from: str,
        date_to: str,
        limit: int = 50,
        patient_key: str | None = None,
    ) -> list[SettlementListItem]:
        """按结算时间段列出住院结算单摘要。

        直接通过数据供给适配器查询，原因：语义查询模型当前以单结算单锚点
        为主，未提供无锚点的列表聚合能力。本查询只读取，使用语义种子中登记
        的表/列映射（一档 SQL Server 直连）。
        patient_key 可选：身份证号（sfz）或卡号（kh），提供时仅返回该患者的
        结算单（临时患者定位方案，正式由登录态取代）。
        """
        if self._connect is None:
            raise RuntimeError(
                "list_settlements_by_date_range 需要数据供给连接（DATA_SOURCE_MODE=real_db）"
            )

        # 校验日期格式（YYYY-MM-DD）
        for label, value in (("date_from", date_from), ("date_to", date_to)):
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"{label} 需为 YYYY-MM-DD 格式: {value}") from exc

        # 字段/表名与语义种子 `seed.py` 中 `inpatient_settlement` 模型一致：
        # 人员类别 PER_TYPE 在 yb_zyjyxx、险种 FUND_TYPE/医疗类别 yllb 在 yb_brdjxx、
        # 结算日期取该单最后一段的报导结束日期 MAX(bdjzrq)（活库 yb_zyfdxx 无 bdjsrq 列）
        # patient_key：临时患者定位（身份证 sfz / 卡号 kh），正式方案由登录态取代
        patient_filter = "AND (r.sfz = ? OR r.kh = ?)" if patient_key else ""
        sql = f"""
        SELECT TOP (?) r.djh AS settlement_id,
               MAX(t.PER_TYPE) AS person_type_code,
               MAX(r.FUND_TYPE) AS insurance_type_code,
               MAX(r.yllb) AS service_type_code,
               SUM(p.bdfyzje) AS total_amount,
               MAX(p.bdjzrq) AS settlement_date
        FROM yb_brdjxx r
        INNER JOIN yb_zyfdxx p ON r.djh = p.djh
        LEFT JOIN yb_zyjyxx t ON r.djh = t.djh
        WHERE 1 = 1 {patient_filter}
        GROUP BY r.djh
        HAVING MAX(p.bdjzrq) >= ? AND MAX(p.bdjzrq) <= ?
        ORDER BY MAX(p.bdjzrq) DESC
        """
        params: tuple = (limit, date_from, date_to)
        if patient_key:
            params = (limit, patient_key, patient_key, date_from, date_to)

        connection = None
        try:
            connection = self._connect("bjybdb")
            cursor = connection.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description] if cursor.description else []
            raw_rows = [dict(zip(columns, row)) for row in rows]
        except (ConnectionError, TimeoutError) as exc:
            raise SettlementDataUnavailableError(str(exc)) from exc
        except pyodbc.Error as exc:
            sqlstate = str(exc.args[0]) if exc.args else ""
            if sqlstate.startswith("08") or sqlstate in {"HYT00", "HYT01"}:
                raise SettlementDataUnavailableError(str(exc)) from exc
            raise
        finally:
            if connection:
                connection.close()

        items: list[SettlementListItem] = []
        for row in raw_rows:
            total = row.get("total_amount")
            settlement_date = row.get("settlement_date")
            if settlement_date is not None and not isinstance(settlement_date, str):
                settlement_date = str(settlement_date)[:10]
            items.append(
                SettlementListItem(
                    settlement_id=str(row.get("settlement_id", "")),
                    settlement_date=settlement_date or "",
                    person_type=self._resolve("PERSON_TYPE", row.get("person_type_code")),
                    insurance_type=self._resolve("FUND_TYPE", row.get("insurance_type_code")),
                    service_type=self._resolve("YLLB", row.get("service_type_code")),
                    total_amount=float(total) if total is not None else None,
                )
            )
        return items

    async def lookup_patient(self, key: str) -> PatientSummary | None:
        """按身份证号（sfz）或卡号（kh）定位患者，返回脱敏摘要。

        临时患者定位方案：正式接入登录验证后由登录态直接给出患者身份，
        本方法随之退役。未命中返回 None（调用方映射 404）。
        """
        if self._connect is None:
            raise RuntimeError(
                "lookup_patient 需要数据供给连接（DATA_SOURCE_MODE=real_db）"
            )
        text = key.strip()
        if not text:
            raise ValueError("key 不能为空")

        sql = """
        SELECT TOP (1) kh, sfz, xm, xb, csrq, djh
        FROM yb_brdjxx
        WHERE (sfz = ? OR kh = ?)
        ORDER BY djh DESC
        """
        connection = None
        try:
            connection = self._connect("bjybdb")
            cursor = connection.cursor()
            cursor.execute(sql, (text, text))
            row = cursor.fetchone()
        except (ConnectionError, TimeoutError) as exc:
            raise SettlementDataUnavailableError(str(exc)) from exc
        except pyodbc.Error as exc:
            sqlstate = str(exc.args[0]) if exc.args else ""
            if sqlstate.startswith("08") or sqlstate in {"HYT00", "HYT01"}:
                raise SettlementDataUnavailableError(str(exc)) from exc
            raise
        finally:
            if connection:
                connection.close()

        if row is None:
            return None

        card_no, id_no, name, gender_code, birth, registration_id = row
        birth_str = str(birth)[:10] if birth is not None else ""
        return PatientSummary(
            card_no=str(card_no or ""),
            id_no_masked=mask_id_no(str(id_no or "")),
            name=str(name or ""),
            gender=_GENDER_MAP.get(str(gender_code or ""), str(gender_code or "")),
            birth_date=birth_str,
            registration_id=str(registration_id or ""),
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
