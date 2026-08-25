"""
Settlement data provider — real DB vs mock, config-driven.

Provides the protocol and implementations for retrieving settlement context
from either the real SQL Server database or (in future) mock sources.

When DATA_SOURCE_MODE=real_db, queries the SQL Server using the existing
settlement_context query defined in business_sql.yaml. Never falls back to
mock data — if the DB fails, the error propagates clearly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import pyodbc

logger = logging.getLogger(__name__)


# ── Data model for settlement context ─────────────────────────

@dataclass
class SettlementContext:
    """Normalized settlement context from real DB query.

    All fields are derived from the settlement_context SQL in business_sql.yaml,
    which joins: yb_brdjxx, yb_dyxxnd, yb_dyxxzy, yb_zyfdxx, yb_zyjyxx.
    """
    settlement_id: str = ""
    person_type: str = ""            # e.g. "退休人员"
    insurance_type: str = ""         # e.g. "城镇职工基本医疗保险"
    service_type: str = ""           # e.g. "普通住院"
    hospital_level: str = ""         # derived from hospital level code if available
    deductible: float = 0.0
    medical_insurance_inner_amount: float = 0.0
    basic_pooling_payment: float = 0.0
    basic_pooling_self_pay: float = 0.0
    large_amount_payment: float = 0.0
    large_amount_self_pay: float = 0.0
    personal_total_pay: float = 0.0
    total_amount: float = 0.0
    settlement_date: str = ""
    yearly_cycle_count: int = 0
    cycle_no: str = ""
    # Query trace
    tables_queried: list[str] = field(default_factory=list)
    query_profile: str = ""


# ── Protocol ──────────────────────────────────────────────────

class SettlementDataProvider(Protocol):
    """Protocol for settlement context data retrieval."""

    async def get_settlement_context(self, settlement_id: str) -> SettlementContext:
        """Query and return normalized settlement context."""
        ...


# ── Real DB Implementation ────────────────────────────────────

class RealDbSettlementDataProvider:
    """Query real SQL Server for settlement context.

    Uses SqlServerBusinessDataClient and the existing settlement_context SQL
    from business_sql.yaml. Never falls back to mock data.
    """

    def __init__(self):
        from pathlib import Path

        from src.knowledge_extension.rule_explanation.policy_retrieval.sqlserver_business_data_client import (
            SqlServerBusinessDataClient,
        )

        sql_config_path = (
            Path(__file__).parent.parent.parent
            / "knowledge_extension"
            / "rule_explanation"
            / "policy_retrieval"
            / "config"
            / "business_sql.yaml"
        )
        self.client = SqlServerBusinessDataClient(sql_config_path=sql_config_path)
        logger.info("[SETTLEMENT-DATA-PROVIDER] RealDbSettlementDataProvider initialized")

    async def get_settlement_context(self, settlement_id: str) -> SettlementContext:
        """Query real DB and return normalized SettlementContext.

        Args:
            settlement_id: 登记号 from the settlement system

        Returns:
            SettlementContext with all fields populated from the DB

        Raises:
            SettlementNotFoundError: if the settlement_id has no data
            RuntimeError: if data source mode is not real_db
            ValueError: if MSSQL_* env vars are not configured
        """
        import asyncio

        loop = asyncio.get_event_loop()

        # get_case_context_raw is a synchronous method that opens a new connection
        # each time — wrap in executor to avoid blocking the event loop.
        try:
            raw_context = await loop.run_in_executor(
                None,
                lambda: self.client.get_case_context_raw(settlement_id=settlement_id),
            )
        except ValueError as exc:
            if "未查询到结算记录" in str(exc):
                raise SettlementNotFoundError(str(exc)) from exc
            raise
        except (ConnectionError, TimeoutError) as exc:
            raise SettlementDataUnavailableError(str(exc)) from exc
        except pyodbc.Error as exc:
            sqlstate = str(exc.args[0]) if exc.args else ""
            if sqlstate.startswith("08") or sqlstate in {"HYT00", "HYT01"}:
                raise SettlementDataUnavailableError(str(exc)) from exc
            raise

        raw_data = raw_context.raw_data or {}

        if not raw_data or not raw_data.get("djh"):
            raise SettlementNotFoundError(
                f"未查询到真实结算数据: settlement_id={settlement_id}"
            )

        return SettlementContext(
            settlement_id=str(raw_data.get("djh", "")),
            person_type=self._normalize_person_type(str(raw_data.get("PER_TYPE", "") or "")),
            insurance_type=str(raw_data.get("fund_type", "")),
            service_type=str(raw_data.get("yllb", "")),
            hospital_level="",  # derived later from hospital info if available
            deductible=float(raw_data.get("bcqfje", 0) or 0),
            medical_insurance_inner_amount=float(raw_data.get("bcybnje", 0) or 0),
            basic_pooling_payment=float(raw_data.get("bdtczfje", 0) or 0),
            basic_pooling_self_pay=float(raw_data.get("bdtczf", 0) or 0),
            large_amount_payment=float(raw_data.get("bddegwyzfje", 0) or 0),
            large_amount_self_pay=float(raw_data.get("bddegwyzf", 0) or 0),
            personal_total_pay=float(raw_data.get("bdgryf", 0) or 0),
            total_amount=float(raw_data.get("bdfyzje", 0) or 0),
            settlement_date=str(raw_data.get("bdjzrq", "") or ""),
            yearly_cycle_count=int(raw_data.get("bnzqslj", 0) or 0),
            cycle_no=str(raw_data.get("zqxh", "") or ""),
            tables_queried=["yb_zyfdxx", "yb_dyxxzy", "yb_dyxxnd", "yb_brdjxx", "yb_zyjyxx"],
            query_profile="settlement_context",
        )

    @staticmethod
    def _normalize_person_type(code: str) -> str:
        """Map raw PER_TYPE code to Chinese label.

        The settlement_context SQL returns the raw PER_TYPE code from
        yb_zyjyxx table (e.g. '1', '2').  This method maps it to the
        human-readable label used in policy explanations.
        """
        mapping = {
            "1": "在职人员",
            "2": "退休人员",
            "3": "离休人员",
            "4": "学生儿童",
            "5": "无保障老年人",
            "6": "无业人员",
        }
        return mapping.get(code, code if code else "")


class SettlementNotFoundError(Exception):
    """Raised when settlement data cannot be found in real DB."""
    pass


class SettlementDataUnavailableError(Exception):
    """Raised for retryable settlement source failures."""

    pass


# ── Factory ───────────────────────────────────────────────────

def create_settlement_data_provider() -> SettlementDataProvider:
    """Create provider based on DATA_SOURCE_MODE config.

    Returns a RealDbSettlementDataProvider when DATA_SOURCE_MODE=real_db.
    In any other mode, raises RuntimeError — this endpoint is designed for
    real database queries only and never falls back to mock.

    Raises:
        RuntimeError: if DATA_SOURCE_MODE != "real_db"
    """
    from src.config.production import DATA_SOURCE_MODE

    if DATA_SOURCE_MODE == "real_db":
        logger.info("[SETTLEMENT] Using RealDbSettlementDataProvider (REAL_DB mode)")
        return RealDbSettlementDataProvider()

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
