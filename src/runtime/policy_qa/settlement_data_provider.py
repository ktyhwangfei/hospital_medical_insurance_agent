"""基于已发布语义查询模型读取整次住院结算上下文。"""

from __future__ import annotations

import logging
import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol

from pydantic import BaseModel, Field

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


class SettlementBillField(BaseModel):
    """费用构成行；金额为展示字符串（两位小数），源字段缺失时为 None。"""

    key: str
    label: str
    amount: str | None = None


class SettlementBillFeeItem(BaseModel):
    """费用明细行（只展示源表已有字段，不做目录属性推导）。"""

    item_code: str = ""
    item_name: str = ""
    item_type: str = ""
    quantity: str | None = None
    unit_price: str | None = None
    total_amount: str | None = None
    insurance_inner: str | None = None
    insurance_outer: str | None = None


class SettlementBill(BaseModel):
    """单张结算单右侧栏展示数据：费用构成 + 费用明细。"""

    settlement_id: str
    service_type: str = ""
    settlement_date: str = ""
    fields: list[SettlementBillField] = Field(default_factory=list)
    fee_items: list[SettlementBillFeeItem] = Field(default_factory=list)
    fee_items_state: Literal["complete", "missing"] = "complete"
    warnings: list[str] = Field(default_factory=list)


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


# ── 结算单费用构成字段口径 ────────────────────────────────────
# 门诊普通交易（o_Trade）：字段--标签对齐 #85 settlement_templates
# （employee/resident_outpatient），只含源表真实列。
_TRADE_BILL_FIELDS: tuple[tuple[str, str], ...] = (
    ("T_FeeAll", "费用总金额"),
    ("T_SelfPayAll", "个人支付总金额"),
    ("T_FeeIn", "医疗保险范围内金额"),
    ("T_FeeOut", "范围外金额"),
    ("T_FirstPay", "起付金额"),
    ("T_SelfPay1", "个人支付自付（一）"),
    ("T_SelfPay2", "个人支付自付（二）"),
    ("T_BeyondBig", "大额超封顶金额"),
    ("T_FundPay", "基金支付金额"),
    ("T_PersonCountPay", "当次个人帐户支付金额"),
    ("T_BigPay", "当次门诊大额基金支付金额"),
    ("T_JCPay", "残疾军人补助支付金额"),
    ("T_CashPay", "当次个人现金支付金额"),
    ("T_BCPay", "补充保险支付金额"),
    ("T_BigillPay", "大病支付"),
    ("NT_CivilPay", "救助支付"),
    ("RETIRE_OFFICER_PAY", "退役医疗费"),
    ("T_OfficalPay", "单位补充医疗保险（原公疗）支付金额"),
)

# 门特（yb_mzjyxx）：第三项为物理列；个人支付总金额为 xjzf+zhzf 派生。
_SPECIAL_BILL_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    ("zje", "费用总金额", "zje"),
    ("personal_total_pay", "个人支付总金额", None),
    ("tsbybn", "医疗保险范围内金额", "tsbybn"),
    ("tsbybw", "范围外金额", "tsbybw"),
    ("ptybn", "普通门诊范围内金额", "ptybn"),
    ("ptybw", "普通门诊范围外金额", "ptybw"),
    ("ybnqfje", "起付金额", "ybnqfje"),
    ("grziftw", "个人支付自付（二）", "grziftw"),
    ("grzif1", "个人支付自付（一）", "grzif1"),
    ("tczhf", "统筹基金支付", "tczhf"),
    ("tczif", "统筹自付", "tczif"),
    ("degwyzhf", "当次门诊大额基金支付金额", "degwyzhf"),
    ("degwyzif", "大额自付金额", "degwyzif"),
    ("bczhf", "补充保险支付金额", "bczhf"),
    ("jczhf", "残疾军人补助支付金额", "jczhf"),
    ("BIG_ILL_PAY", "大病支付", "BIG_ILL_PAY"),
    ("CIVIL_IN", "救助支付", "CIVIL_IN"),
    ("zhzf", "当次个人帐户支付金额", "zhzf"),
    ("xjzf", "当次个人现金支付金额", "xjzf"),
    ("RETIRE_OFFICER_PAY", "退役医疗费", "RETIRE_OFFICER_PAY"),
    ("gfylbchbx", "单位补充医疗保险（原公疗）支付金额", "gfylbchbx"),
    ("FEEIN_DB_PAY", "大病支付（医保内）", "FEEIN_DB_PAY"),
    ("FEEOUT_DB_PAY", "大病支付（医保外）", "FEEOUT_DB_PAY"),
    ("FEEIN_MAF_PAY", "救助支付（医保内）", "FEEIN_MAF_PAY"),
    ("FEEOUT_MAF_PAY", "救助支付（医保外）", "FEEOUT_MAF_PAY"),
)

# 住院：标签沿用语义种子 inpatient_settlement 的指标名。
_INPATIENT_BILL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("total_amount", "住院总费用", "total_amount"),
    ("personal_total_pay", "个人总支付", "personal_total_pay"),
    ("medical_insurance_inner_amount", "医保内费用", "medical_insurance_inner_amount"),
    ("deductible", "起付线", "deductible"),
    ("basic_pooling_payment", "统筹支付", "basic_pooling_payment"),
    ("basic_pooling_self_pay", "统筹自付", "basic_pooling_self_pay"),
    ("large_amount_payment", "大额支付", "large_amount_payment"),
    ("large_amount_self_pay", "大额自付", "large_amount_self_pay"),
)

_BILL_ITEM_TYPE_LABELS = {"0": "药品", "1": "诊疗项目", "2": "服务设施", "3": "耗材"}
_TRADE_ID_RE = re.compile(r"[A-Za-z0-9]{15,}")


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _bill_amount(value) -> str | None:
    number = _to_decimal(value)
    return None if number is None else f"{number:.2f}"


def _bill_quantity(value) -> str | None:
    number = _to_decimal(value)
    if number is None:
        return None
    return format(number.normalize(), "f")


def _bill_sum(*values) -> Decimal | None:
    present = [number for number in (_to_decimal(v) for v in values) if number is not None]
    return sum(present) if present else None


def _bill_date(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.replace("T", " ")[:19]
    return str(value)[:19]


def _bill_item_type(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return _BILL_ITEM_TYPE_LABELS.get(text, "")


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
        self,
        date_from: str,
        date_to: str,
        limit: int = 50,
        patient_key: str | None = None,
    ) -> list[SettlementListItem]:
        """按时间段列出结算单摘要。"""
        ...

    async def lookup_patient(self, key: str) -> PatientSummary | None:
        """按身份证号或卡号定位患者（脱敏摘要）。"""
        ...

    async def get_settlement_bill(
        self, settlement_id: str, service_type: str = ""
    ) -> SettlementBill:
        """单张结算单的费用构成与费用明细（右侧栏展示）。"""
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
            from src.runtime.discovery.semantic_source import get_semantic_data_source

            if supply is None:
                from src.adapters.data_supply import SqlServerDirectSupplyAdapter

                supply = SqlServerDirectSupplyAdapter(
                    connect_fn=get_semantic_data_source().open_connection
                )
            # #78：门诊查询模型落 PG 落地库，按数据源方言编译/传参
            service = SemanticQueryService(
                self._registry,
                supply.connect,
                datasource_kind=get_semantic_data_source().datasource_kind,
            )
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

        # 门诊患者的身份与交易只在 o_Trade，住院链路查不到；仅按人浏览
        # （patient_key）时追加门诊单，无 patient_key 保持住院-only 不变。
        if patient_key:
            items.extend(
                self._list_outpatient_settlements(date_from, date_to, patient_key)
            )
            items.sort(key=lambda item: item.settlement_date, reverse=True)
            del items[limit:]
        return items

    def _list_outpatient_settlements(
        self, date_from: str, date_to: str, patient_key: str
    ) -> list[SettlementListItem]:
        """按患者身份列门诊交易摘要（#78 口径，逐字移植）。

        经 o_Trade.T_FeeNo ↔ yb_mzjyxx.SETL_ID ↔ yb_brdjxx.djh 判断门特
        （yllb='12'）：门特粒度是 mzjyxx 的 djh 结算行，以登记号 djh 作为
        settlement_id、日期/金额取 m.jyrq/m.zje 结算口径；其余普通门诊以
        交易号 T_TradeNo 保持交易行粒度。
        """
        date_to_exclusive = (
            datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        sql = """
        SELECT t.T_TradeNo, t.T_TradeDate, t.T_FeeAll, t.P_FundType,
               b.djh AS reg_djh, b.yllb AS reg_yllb,
               m.jyrq AS setl_date, m.zje AS setl_amount
        FROM o_Trade t
        LEFT JOIN yb_mzjyxx m ON m.SETL_ID = t.T_FeeNo
        LEFT JOIN yb_brdjxx b ON b.djh = m.djh
        WHERE (t.P_IDNo = ? OR t.P_ICNo = ? OR t.P_CardNo = ?)
          AND t.T_TradeDate >= ? AND t.T_TradeDate < ?
        ORDER BY t.T_TradeDate DESC
        """
        params = (patient_key, patient_key, patient_key, date_from, date_to_exclusive)
        raw_rows = self._query_rows(sql, params)

        outpatient_items: list[SettlementListItem] = []
        # 门特按 djh 收敛：多笔 HIS 交易汇入同一门特结算；djh 缺失时按交易行兜底。
        special_by_key: dict[str, SettlementListItem] = {}
        for row in raw_rows:
            trade_date = row.get("T_TradeDate")
            if trade_date is not None and not isinstance(trade_date, str):
                trade_date = str(trade_date)[:19]
            if isinstance(trade_date, str):
                trade_date = trade_date.replace("T", " ")
            total = row.get("T_FeeAll")
            if str(row.get("reg_yllb") or "") == "12":
                djh = str(row.get("reg_djh") or "")
                key = djh or f"__trade__{row.get('T_TradeNo') or ''}"
                setl_date = row.get("setl_date") or trade_date
                if setl_date is not None and not isinstance(setl_date, str):
                    setl_date = str(setl_date)[:19]
                if isinstance(setl_date, str):
                    setl_date = setl_date.replace("T", " ")
                setl_amount = row.get("setl_amount")
                if setl_amount is None:
                    setl_amount = total
                existing = special_by_key.get(key)
                if existing is None or (setl_date or "") > existing.settlement_date:
                    special_by_key[key] = SettlementListItem(
                        settlement_id=djh,
                        settlement_date=setl_date or "",
                        insurance_type=self._resolve("FUND_TYPE", row.get("P_FundType")),
                        service_type="门诊特殊病",
                        total_amount=float(setl_amount) if setl_amount is not None else None,
                    )
                continue
            outpatient_items.append(
                SettlementListItem(
                    settlement_id=str(row.get("T_TradeNo") or ""),
                    settlement_date=trade_date or "",
                    insurance_type=self._resolve("FUND_TYPE", row.get("P_FundType")),
                    service_type="门诊",
                    total_amount=float(total) if total is not None else None,
                )
            )
        # 门特身份在登记表 yb_brdjxx，o_Trade.T_FeeNo 与医保结算号体系不同，
        # 仅靠交易号关联会整单漏掉门特结算，故按人直查一次。
        for item in self._list_special_settlements(date_from, date_to, patient_key):
            existing = special_by_key.get(item.settlement_id)
            if existing is None or item.settlement_date > existing.settlement_date:
                special_by_key[item.settlement_id] = item
        return outpatient_items + list(special_by_key.values())

    def _list_special_settlements(
        self, date_from: str, date_to: str, patient_key: str
    ) -> list[SettlementListItem]:
        """按身份直接列门特结算（yb_brdjxx.sfz/kh × yb_mzjyxx 结算行）。"""
        date_to_exclusive = (
            datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        sql = """
        SELECT b.djh AS settlement_id, m.jyrq AS settlement_date, m.zje AS total_amount,
               b.FUND_TYPE AS fund_type
        FROM yb_brdjxx b
        INNER JOIN yb_mzjyxx m ON m.djh = b.djh
        WHERE (b.sfz = ? OR b.kh = ?) AND b.yllb = '12'
          AND m.jyrq >= ? AND m.jyrq < ?
        ORDER BY m.jyrq DESC
        """
        raw_rows = self._query_rows(sql, (patient_key, patient_key, date_from, date_to_exclusive))

        items: dict[str, SettlementListItem] = {}
        for row in raw_rows:
            settlement_date = row.get("settlement_date")
            if settlement_date is not None and not isinstance(settlement_date, str):
                settlement_date = str(settlement_date)[:19]
            if isinstance(settlement_date, str):
                settlement_date = settlement_date.replace("T", " ")
            key = str(row.get("settlement_id") or "")
            if not key or key in items:
                continue
            total = row.get("total_amount")
            items[key] = SettlementListItem(
                settlement_id=key,
                settlement_date=settlement_date or "",
                insurance_type=self._resolve("FUND_TYPE", row.get("fund_type")),
                service_type="门诊特殊病",
                total_amount=float(total) if total is not None else None,
            )
        return list(items.values())

    def _query_rows(self, sql: str, params: tuple) -> list[dict]:
        """执行只读直连查询并返回列名映射行（连接/超时统一映射为数据源不可用）。"""
        connection = None
        try:
            connection = self._connect("bjybdb")
            cursor = connection.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description] if cursor.description else []
            return [dict(zip(columns, row)) for row in rows]
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

    # ── 单张结算单：费用构成 + 费用明细（右侧栏）────────────────

    def _bill_kind(self, settlement_id: str, service_type: str) -> str:
        """判定取数链路：special（门特）/ trade（门诊 HIS 交易）/ inpatient。"""
        text = service_type or ""
        if "门诊特殊病" in text:
            return "special"
        if "门诊" in text:
            return "trade"
        # @换结算 指令不带 service_type：字母数字长单号是门诊 HIS 交易号
        return "trade" if _TRADE_ID_RE.fullmatch(settlement_id or "") else "inpatient"

    def _bill_fee_items(
        self, kind: str, settlement_id: str, warnings: list[str]
    ) -> tuple[list[SettlementBillFeeItem], Literal["complete", "missing"]]:
        """费用明细：门诊走 o_FeeItem，门特/住院走医保费用明细表。

        明细读取失败不拖垮费用构成，如实降级为 missing 并附 warning。
        """
        if kind == "trade":
            sql = (
                "SELECT ItemCode, ItemName, ItemType, [Count], UnitPrice, "
                "Fee, FeeIn, FeeOut FROM o_FeeItem "
                "WHERE T_TradeNo = ? ORDER BY ItemId, ItemNo"
            )
        elif kind == "special":
            sql = (
                "SELECT xmdm, xmmc, xmlb, sl, dj, zje, ybnje, ybwje "
                "FROM yb_mzfymx WHERE djh = ? ORDER BY xh"
            )
        else:
            sql = (
                "SELECT xmdm, xmmc, xmlb, sl, dj, zje, ybnje, ybwje "
                "FROM yb_zyfymx WHERE djh = ? ORDER BY xh"
            )
        try:
            rows = self._query_rows(sql, (settlement_id,))
        except SettlementDataUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[settlement-bill] 费用明细读取失败 kind=%s id=%s: %s",
                kind, settlement_id, exc,
            )
            warnings.append("费用明细读取失败，暂只展示费用构成。")
            return [], "missing"
        if not rows:
            return [], "missing"

        items: list[SettlementBillFeeItem] = []
        for row in rows:
            if kind == "trade":
                items.append(
                    SettlementBillFeeItem(
                        item_code=str(row.get("ItemCode") or ""),
                        item_name=str(row.get("ItemName") or ""),
                        item_type=_bill_item_type(row.get("ItemType")),
                        quantity=_bill_quantity(row.get("Count")),
                        unit_price=_bill_amount(row.get("UnitPrice")),
                        total_amount=_bill_amount(row.get("Fee")),
                        insurance_inner=_bill_amount(row.get("FeeIn")),
                        insurance_outer=_bill_amount(row.get("FeeOut")),
                    )
                )
            else:
                items.append(
                    SettlementBillFeeItem(
                        item_code=str(row.get("xmdm") or ""),
                        item_name=str(row.get("xmmc") or ""),
                        item_type=_bill_item_type(row.get("xmlb")),
                        quantity=_bill_quantity(row.get("sl")),
                        unit_price=_bill_amount(row.get("dj")),
                        total_amount=_bill_amount(row.get("zje")),
                        insurance_inner=_bill_amount(row.get("ybnje")),
                        insurance_outer=_bill_amount(row.get("ybwje")),
                    )
                )
        return items, "complete"

    async def get_settlement_bill(
        self, settlement_id: str, service_type: str = ""
    ) -> SettlementBill:
        """单张结算单的费用构成与费用明细。

        service_type 来自列表项（门诊/门诊特殊病/住院）：门特 djh 为纯数字，
        与住院登记号同形，必须靠该字段区分取数链路。
        """
        if self._connect is None:
            raise RuntimeError(
                "get_settlement_bill 需要数据供给连接（DATA_SOURCE_MODE=real_db）"
            )
        kind = self._bill_kind(settlement_id, service_type)
        warnings: list[str] = []

        if kind == "inpatient":
            context = await self.get_settlement_context(settlement_id)
            if not context.amounts_reliable:
                warnings.append("该结算单的金额字段未通过语义模型完整校验，展示值可能不完整。")
            items, state = self._bill_fee_items(kind, settlement_id, warnings)
            return SettlementBill(
                settlement_id=settlement_id,
                service_type=context.service_type or service_type,
                settlement_date=context.settlement_date,
                fields=[
                    SettlementBillField(
                        key=key, label=label, amount=_bill_amount(getattr(context, attr))
                    )
                    for key, label, attr in _INPATIENT_BILL_FIELDS
                ],
                fee_items=items,
                fee_items_state=state,
                warnings=warnings,
            )

        if kind == "special":
            cols = list(dict.fromkeys(
                col for _, _, col in _SPECIAL_BILL_FIELDS if col
            ))
            rows = self._query_rows(
                "SELECT TOP (1) jyrq, " + ", ".join(cols)
                + " FROM yb_mzjyxx WHERE djh = ? ORDER BY jyrq DESC",
                (settlement_id,),
            )
            if not rows:
                raise SettlementNotFoundError(
                    f"未查询到门特结算记录: djh={settlement_id}"
                )
            row = rows[0]
            fields = [
                SettlementBillField(
                    key=key,
                    label=label,
                    amount=_bill_amount(
                        _bill_sum(row.get("xjzf"), row.get("zhzf"))
                        if key == "personal_total_pay"
                        else row.get(col or key)
                    ),
                )
                for key, label, col in _SPECIAL_BILL_FIELDS
            ]
            service_label = "门诊特殊病"
            settlement_date = _bill_date(row.get("jyrq"))
        else:
            cols = [col for col, _ in _TRADE_BILL_FIELDS]
            rows = self._query_rows(
                "SELECT TOP (1) T_TradeDate, " + ", ".join(cols)
                + " FROM o_Trade WHERE T_TradeNo = ?",
                (settlement_id,),
            )
            if not rows:
                raise SettlementNotFoundError(
                    f"未查询到门诊交易记录: T_TradeNo={settlement_id}"
                )
            row = rows[0]
            fields = [
                SettlementBillField(key=col, label=label, amount=_bill_amount(row.get(col)))
                for col, label in _TRADE_BILL_FIELDS
            ]
            service_label = "门诊"
            settlement_date = _bill_date(row.get("T_TradeDate"))

        items, state = self._bill_fee_items(kind, settlement_id, warnings)
        return SettlementBill(
            settlement_id=settlement_id,
            service_type=service_label,
            settlement_date=settlement_date,
            fields=fields,
            fee_items=items,
            fee_items_state=state,
            warnings=warnings,
        )

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
            # 回退 o_Trade：门诊患者身份只在门诊交易主表，yb_brdjxx（住院登记）
            # 按 sfz/kh 命中 0 行；按身份列取最近一笔交易组装脱敏摘要（#78 口径）。
            fallback_sql = """
            SELECT TOP (1) P_Name, P_Sex, P_Birthday, P_IDNo, P_CardNo
            FROM o_Trade
            WHERE (P_IDNo = ? OR P_ICNo = ? OR P_CardNo = ?)
            ORDER BY T_TradeDate DESC
            """
            rows = self._query_rows(fallback_sql, (text, text, text))
            if not rows:
                return None
            trade = rows[0]
            birth = trade.get("P_Birthday")
            return PatientSummary(
                card_no=str(trade.get("P_CardNo") or ""),
                id_no_masked=mask_id_no(str(trade.get("P_IDNo") or "")),
                name=str(trade.get("P_Name") or ""),
                gender=_GENDER_MAP.get(str(trade.get("P_Sex") or ""), str(trade.get("P_Sex") or "")),
                birth_date=str(birth)[:10] if birth is not None else "",
                # 门诊交易无住院登记号
                registration_id="",
            )

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
        except pyodbc.DataError as exc:
            # 门诊普通单号是 o_Trade 交易号（字母数字），绑定到住院登记号的
            # 数字列会报 22018 转换失败：该单不在住院语义模型内，按未找到
            # 结算记录诚实告知，避免误报为数据源不可用（503）。
            sqlstate = str(exc.args[0]) if exc.args else ""
            if sqlstate.startswith("22018"):
                raise SettlementNotFoundError(
                    f"住院结算模型中无此结算单: anchor={query.scope.anchor.value}"
                ) from exc
            raise
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
