"""限制性备注单单只读回放；输出全部费用行的状态及可复核脱敏输入。"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.domain.directory_compliance.configuration import RuleDocument
from src.domain.directory_compliance.engine import evaluate_rule, is_placeholder_text, locate_rule
from src.domain.directory_compliance.explanation import build_ops_explanation, build_patient_explanation
from src.domain.directory_compliance.models import (
    ComplianceRule, DiagnosisFact, FieldObservation, FieldReadStatus, LineComplianceResult,
    RuleLookupResult, RuleLookupStatus, SettlementLineContext, ValueDomainMapping,
)
from src.domain.directory_compliance.rules_seed import BASELINE_MAPPINGS, SEED_RULES
from src.security.desensitization.detection import redact_sensitive_text

DEFAULT_TRADE_NO = "011100030X260416006969"
HOSP_CODE = "01110003"


def _get_conn():
    import pyodbc

    candidates = [Path("deploy/docker/.env")]
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True,
        ).stdout.strip()
        if common:
            candidates.append(Path(common).parent / "deploy/docker/.env")
    except Exception:
        pass
    password = None
    for candidate in candidates:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.startswith("SA_PASSWORD="):
                    password = line.split("=", 1)[1].strip()
            break
    if not password:
        raise RuntimeError("未找到 deploy/docker/.env 的 SA_PASSWORD")
    return pyodbc.connect(
        "DRIVER={SQL Server};SERVER=localhost,1433;DATABASE=bjybdb;"
        f"UID=sa;PWD={password};",
        autocommit=True, timeout=10,
    )



class CatalogSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    bz: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None


class TradeHeaderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trade_date: datetime
    fund_type: str | None = None
    state: int | None = None
    has_refunded: int | None = None
    fee_all: Decimal | None = None
    fee_in: Decimal | None = None
    fee_out: Decimal | None = None
    fund_pay: Decimal | None = None
    no_right_reason: str | None = None


class ProbeLineReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    line_id: str
    item_code: str
    item_name: str
    lookup: RuleLookupResult
    context: SettlementLineContext | None = None
    catalog_candidates: tuple[CatalogSnapshot, ...] = ()
    result: LineComplianceResult | None = None
    patient_explanation: str
    ops_explanation: str


class ProbeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observed_at: datetime
    case_ref: str
    scope_note: str = "只读草稿回放；不是经独立临床审核的正式核验，不代表基金支付原因"
    trade_header: TradeHeaderSnapshot
    bill_line_count: int
    restricted_inpay_lines: int
    line_results: tuple[ProbeLineReport, ...]
    rules_snapshot: tuple[RuleDocument, ...]
    mappings_snapshot: tuple[ValueDomainMapping, ...]


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def build_probe_report(
    header: Mapping[str, Any], fee_lines: Sequence[Mapping[str, Any]],
    diagnoses: Sequence[Mapping[str, Any]], catalog_rows: Sequence[Mapping[str, Any]],
    *, catalog_failed: bool = False, diagnosis_failed: bool = False,
    rules: Sequence[ComplianceRule] = SEED_RULES,
    mappings: Sequence[ValueDomainMapping] = BASELINE_MAPPINGS,
) -> ProbeReport:
    """纯装配入口便于离线验证；查询失败与查询无记录分开。"""
    case_ref = hashlib.sha256(_text(header.get("T_TradeNo")).encode()).hexdigest()[:12]
    trade_date = _date(header.get("T_TradeDate"))
    if trade_date is None:
        raise ValueError("结算日期缺失或无效，不能定位当日规则")
    catalog_by_code: dict[str, list[CatalogSnapshot]] = {}
    for row in catalog_rows:
        code = _text(row.get("ypbm"))
        catalog_by_code.setdefault(code, []).append(CatalogSnapshot(
            code=code, bz=redact_sensitive_text(_text(row.get("bz"))) or None,
            effective_from=_date(row.get("sxrq")), effective_to=_date(row.get("jzrq")),
        ))
    results: list[ProbeLineReport] = []
    restricted_count = 0
    key_counts = Counter(_text(row.get("ItemId")) for row in fee_lines)
    for index, row in enumerate(fee_lines, 1):
        code = _text(row.get("ItemCode"))
        name = redact_sensitive_text(_text(row.get("ItemName")))
        line_id = _text(row.get("ItemId")) or f"row-{index}"
        source_ref = hashlib.sha256(f"{case_ref}:{line_id}".encode()).hexdigest()[:12]
        candidates = tuple(c for c in catalog_by_code.get(code, ()) if (
            c.effective_from is None or c.effective_to is None
            or c.effective_from <= trade_date <= c.effective_to
        ))
        catalog = candidates[0] if len(candidates) == 1 else None
        catalog_status = (
            FieldReadStatus.FETCH_FAILED if catalog_failed else
            FieldReadStatus.AMBIGUOUS if len(candidates) > 1 else
            FieldReadStatus.INVALID if catalog and (
                catalog.effective_from is None or catalog.effective_to is None
            ) else FieldReadStatus.PRESENT if catalog else FieldReadStatus.EMPTY
        )
        recipe = _text(row.get("RecipeNo"))
        selected = [d for d in diagnoses if recipe and _text(d.get("RecipeNo")) == recipe]
        facts = tuple(DiagnosisFact(
            code=redact_sensitive_text(_text(d.get("DiagnoseCode"))) or None,
            name=redact_sensitive_text(_text(d.get("DiagnoseName"))) or None,
            association="same_prescription",
        ) for d in selected)
        diagnosis_status = (
            FieldReadStatus.FETCH_FAILED if diagnosis_failed else
            FieldReadStatus.INVALID if not recipe else
            FieldReadStatus.EMPTY if not facts else
            FieldReadStatus.PLACEHOLDER if all(
                is_placeholder_text(d.code or "") and is_placeholder_text(d.name or "") for d in facts
            ) else FieldReadStatus.PRESENT
        )
        def observed(status: FieldReadStatus, source: str,
                     association: Literal["same_line", "same_prescription", "same_settlement", "unknown"] = "same_line",
                     reason: str = "") -> FieldObservation:
            return FieldObservation(status=status, source=f"{source}:{source_ref}",
                                    association=association, reason=reason)
        states = {
            "item.code": observed(FieldReadStatus.PRESENT if code else FieldReadStatus.EMPTY, "o_FeeItem.ItemCode"),
            "fee.date": observed(FieldReadStatus.PRESENT, "o_Trade.T_TradeDate"),
            "catalog": observed(catalog_status, "yb_ypzdml"),
            "diagnosis.code": observed(diagnosis_status, "o_Diagnose.DiagnoseCode", "same_prescription"),
            "diagnosis.name": observed(diagnosis_status, "o_Diagnose.DiagnoseName", "same_prescription"),
            "diagnosis.medical_record": observed(FieldReadStatus.NOT_AVAILABLE, "probe",
                                                  reason="本轮不获取非结构化病历"),
            "price.payment_base": observed(FieldReadStatus.NOT_AVAILABLE, "probe",
                                            reason="未取得费用分解的支付基数，禁止从FeeIn倒推"),
        }
        for key, column in (("price.unit_price", "UnitPrice"), ("item.count", "Count"),
                            ("item.specification", "Specification")):
            value = row.get(column)
            state = FieldReadStatus.EMPTY if value is None or value == "" else FieldReadStatus.PRESENT
            states[key] = observed(state, f"o_FeeItem.{column}")
        try:
            context = SettlementLineContext.model_validate({
                "hospital_code": HOSP_CODE, "trade_date": trade_date, "item_code": code, "item_name": name,
                "unit_price": row.get("UnitPrice"), "count": row.get("Count"), "specification": row.get("Specification"),
                "fee": row.get("Fee"), "fee_in": row.get("FeeIn"), "fee_out": row.get("FeeOut"),
                "same_recipe_diagnoses": facts, "field_states": states, "catalog_bz": catalog.bz if catalog else None,
                "catalog_effective_from": catalog.effective_from if catalog else None,
                "catalog_effective_to": catalog.effective_to if catalog else None,
            })
        except ValidationError:
            results.append(ProbeLineReport(
                line_id=line_id, item_code=code, item_name=name, catalog_candidates=candidates,
                lookup=RuleLookupResult(status=RuleLookupStatus.NOT_EVALUATED, reason="行输入类型或金额无效"),
                patient_explanation="本行资料尚不能用于条件解释，请参照原结算记录。",
                ops_explanation="行输入校验未通过，未执行匹配。",
            ))
            continue
        if not _text(row.get("ItemId")):
            lookup = RuleLookupResult(status=RuleLookupStatus.NOT_EVALUATED, reason="费用行源键缺失")
        elif key_counts[line_id] > 1:
            lookup = RuleLookupResult(status=RuleLookupStatus.AMBIGUOUS, reason="费用行源键重复，未执行核验")
        elif (header.get("T_State") != 4 or header.get("T_HasRefundmented") != 0
                or context.fee <= 0):
            lookup = RuleLookupResult(status=RuleLookupStatus.NOT_EVALUATED, reason="结算状态/退费或非正费用不在本次核验范围")
        else:
            lookup = locate_rule(context, rules)
        # 唯一草稿仅用于回放；不冒充已发布规则命中或正式患者结论。
        rule = lookup.rule
        result = evaluate_rule(rule, context, mappings) if rule else None
        if rule and context.fee_in > 0:
            restricted_count += 1
        results.append(ProbeLineReport(
            line_id=line_id, item_code=code, item_name=name, lookup=lookup, context=context,
            catalog_candidates=candidates, result=result,
            patient_explanation=build_patient_explanation(result) if result else
                "目前未形成可核实的支付条件结论，具体费用请参照原费用解释。",
            ops_explanation=build_ops_explanation(result) if result else lookup.reason,
        ))
    return ProbeReport(
        observed_at=datetime.now(timezone.utc), case_ref=case_ref,
        trade_header=TradeHeaderSnapshot(
            trade_date=header["T_TradeDate"], fund_type=_text(header.get("P_FundType")) or None,
            state=header.get("T_State"), has_refunded=header.get("T_HasRefundmented"),
            fee_all=header.get("T_FeeAll"), fee_in=header.get("T_FeeIn"),
            fee_out=header.get("T_FeeOut"), fund_pay=header.get("T_FundPay"),
            no_right_reason=_text(header.get("PN_NoRightReason")) or None,
        ),
        bill_line_count=len(fee_lines), restricted_inpay_lines=restricted_count,
        line_results=tuple(results), rules_snapshot=tuple(RuleDocument.from_rule(r) for r in rules),
        mappings_snapshot=tuple(mappings),
    )


def run_probe(trade_no: str) -> ProbeReport:
    import pyodbc

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT T_TradeNo,T_TradeDate,P_FundType,T_State,T_HasRefundmented,"
            "T_FeeAll,T_FeeIn,T_FeeOut,T_FundPay,PN_NoRightReason"
            " FROM dbo.o_Trade WHERE T_TradeNo=? AND T_HospCode=?", trade_no, HOSP_CODE,
        )
        columns = [c[0] for c in cur.description]
        raw = cur.fetchone()
        if raw is None:
            raise RuntimeError("结算单不存在或不属于本院")
        header = dict(zip(columns, raw))
        cur.execute(
            "SELECT ItemId,ItemCode,ItemName,UnitPrice,Count,Specification,Fee,FeeIn,FeeOut,RecipeNo"
            " FROM dbo.o_FeeItem WHERE T_TradeNo=? ORDER BY ItemId", trade_no,
        )
        columns = [c[0] for c in cur.description]
        lines = [dict(zip(columns, r)) for r in cur.fetchall()]
        diagnosis_failed = catalog_failed = False
        try:
            cur.execute("SELECT RecipeNo,DiagnoseCode,DiagnoseName FROM dbo.o_Diagnose WHERE T_TradeNo=?", trade_no)
            columns = [c[0] for c in cur.description]
            diagnoses = [dict(zip(columns, r)) for r in cur.fetchall()]
        except pyodbc.Error:
            diagnoses, diagnosis_failed = [], True
        codes = sorted({_text(row.get("ItemCode")) for row in lines} - {""})
        catalog_rows = []
        if codes:
            try:
                placeholders = ",".join("?" for _ in codes)
                cur.execute(
                    "SELECT ypbm,bz,sxrq,jzrq FROM dbo.yb_ypzdml WHERE ypbm IN (" + placeholders + ")",
                    *codes,
                )
                columns = [c[0] for c in cur.description]
                catalog_rows = [dict(zip(columns, r)) for r in cur.fetchall()]
            except pyodbc.Error:
                catalog_failed = True
        return build_probe_report(header, lines, diagnoses, catalog_rows,
                                  diagnosis_failed=diagnosis_failed, catalog_failed=catalog_failed)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-no", default=DEFAULT_TRADE_NO)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = run_probe(args.trade_no)
    if args.output:
        Path(args.output).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    for line in report.line_results:
        outcome = line.result.status.value if line.result else line.lookup.status.value
        print(f"[{outcome}] {line.item_name}: {line.lookup.reason}")
        if line.result:
            for verdict in line.result.verdicts:
                print(f"  {verdict.condition.source_span}: {verdict.status.value}; {verdict.missing}")
        print(f"  {line.patient_explanation}")


if __name__ == "__main__":
    main()
