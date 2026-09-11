"""门诊运营分析服务：六指标总览 / 维度拆分 / 月度趋势 / 行级下钻 / 周报（#40）。

设计约束（冻结契约）：
- 只做有界确定性聚合：SQL 为常量模板 + 参数化过滤，禁止任意 SQL 拼接。
- 聚合范围与已签核口径句 v4 完全一致——谓词逐字取自
  docs/processing/outpatient_processed_view.sql（v_op_outpatient_processed），
  不在服务里重新发明口径。
- 就诊人次 / 次均费用 / 科室维度：HIS 就诊关联是 P1 必需输入且禁止跨源临时
  JOIN → 固定 unavailable + halt_reason=data_unavailable，绝不估算。
- 溯源：所有结果携带 mz_trade.data_batch_id（指标批次）；周报结论每条引用批次
  与指标口径（registry 指标 definition 含口径句 v4）。
- AI 摘要：仅基于已计算数值生成；模型未配置时诚实降级（summary=None +
  uncertainties），不返回示例假数据。
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Protocol

from src.domain.ops_analytics.models import (
    OpsAnalyticsDimension,
    OpsConclusion,
    OpsDimensionBreakdown,
    OpsDimensionItem,
    OpsDrillResult,
    OpsDrillRow,
    OpsMetricCard,
    OpsOverview,
    OpsTrendPoint,
    OpsWeekDelta,
    OpsWeeklyReport,
    dec_to_float,
)

# 口径句 v4 谓词（逐字复制自 docs/processing/outpatient_processed_view.sql，
# 有效结算口径的唯一真源；列名保留大小写必须双引号）。
_V4_WHERE = (
    "NULLIF(tr.\"T_State\", '')::NUMERIC IN (2, 3) "
    "AND NULLIF(tr.\"NP_Settle_State\", '')::NUMERIC = 1 "
    "AND NULLIF(tr.\"T_HasRefundmented\", '')::NUMERIC != 1 "
    "AND (tr.\"T_PartialReturnFlag\" IS NULL OR tr.\"T_PartialReturnFlag\" = '') "
    "AND (NULLIF(tr.\"T_CureType\", '')::NUMERIC IN (11, 17, 18, 19) "
    "OR tr.\"T_CureType\" IS NULL)"
)

_TABLE = 'public.mz_trade AS tr'

# 险种/医疗类别码表唯一真源在 src/semantic_layer/seed.py（_YB_DICTIONARY_MAPPINGS）。
_FUND_TYPE_CN: dict[str, str] = {
    "3": "城镇职工", "4": "工伤保险", "31": "离休统筹", "32": "公疗医照",
    "33": "征地超转人员", "80": "军休干部", "91": "城镇居民基本医疗保险_学生儿童",
    "92": "城镇居民基本医疗保险_无保障老年人", "93": "城镇居民基本医疗保险_无业",
    "999": "国家平台险种",
}
_CURE_TYPE_CN: dict[str, str] = {
    "11": "普通门诊", "17": "门诊挂号", "18": "急诊挂号", "19": "普通急诊",
}
# [来源: docs/processing/outpatient_processed_view.sql L18「有效结算档（中心端完成/同步）」]
_SETTLE_STATE_CN: dict[str, str] = {
    "2": "有效结算（中心端完成）", "3": "有效结算（同步）",
}

# 维度 → (列名, 中文名, 码表)；department 无数据列，走 unavailable 分支。
_DIMENSIONS: dict[str, tuple[str, str, dict[str, str]]] = {
    "fund_type": ("P_FundType", "险种", _FUND_TYPE_CN),
    "cure_type": ("T_CureType", "门诊业务类别", _CURE_TYPE_CN),
    "settle_state": ("T_State", "结算状态", _SETTLE_STATE_CN),
}

_DIMENSION_NAMES = {
    "fund_type": "险种", "cure_type": "门诊业务类别",
    "settle_state": "结算状态", "department": "科室",
}

_HALT_DATA_UNAVAILABLE = "data_unavailable"
_HALT_DETAIL_ENCOUNTER = (
    "门诊医保就诊人次需 HIS 就诊关联（P1 必需输入），当前数据供给未接入；"
    "禁止跨源临时 JOIN，不提供估算值"
)
_HALT_DETAIL_DEPARTMENT = (
    "mz_trade 无科室列，科室维度需 HIS 关联（P1 必需输入）后开放；"
    "可用「结算状态下钻就诊明细」替代"
)


class _QueryClient(Protocol):
    """与 PostgreSQLClient.execute 同形的读取面（测试注入假实现）。"""

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...


def _code_label(code: Any, mapping: dict[str, str]) -> str:
    text = "" if code is None else str(code)
    return mapping.get(text, text if text else "未登记")


def _batch_ids(row: dict[str, Any], key: str = "batch_ids") -> list[str]:
    raw = row.get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    return sorted({str(item) for item in raw if item is not None})


class OpsAnalyticsService:
    """门诊运营分析：只读、有界、确定性聚合 + 可溯源周报。"""

    def __init__(self, client: _QueryClient, model_gateway: Any | None = None) -> None:
        self._client = client
        self._model_gateway = model_gateway

    # ── 六指标总览 ──────────────────────────────────────────────

    def overview(self) -> OpsOverview:
        sql = (
            f"SELECT COUNT(DISTINCT tr.\"T_TradeNo\") AS valid_count, "
            f"COALESCE(SUM(tr.\"T_FeeAll\"), 0) AS total_fee, "
            f"COALESCE(SUM(tr.\"T_FundPay\"), 0) AS fund_pay, "
            f"COALESCE(SUM(tr.\"T_SelfPayAll\"), 0) AS self_pay, "
            f"COUNT(*) AS row_count, MIN(tr.\"T_TradeDate\") AS date_min, "
            f"MAX(tr.\"T_TradeDate\") AS date_max, "
            f"MAX(tr.semantic_version) AS semantic_version, "
            f"ARRAY_AGG(DISTINCT tr.data_batch_id) FILTER "
            f"(WHERE tr.data_batch_id IS NOT NULL) AS batch_ids "
            f"FROM {_TABLE} WHERE {_V4_WHERE}"
        )
        rows = self._client.execute(sql)
        row = rows[0] if rows else {}
        batch_ids = _batch_ids(row)
        row_count = int(row.get("row_count") or 0)

        cards = [
            OpsMetricCard(
                metric_code="mzjyxx.op_valid_settle_count", name="有效结算笔数",
                unit="笔", precision=0, result_status="complete",
                value=dec_to_float(row.get("valid_count"), 0),
            ),
            OpsMetricCard(
                metric_code="mzjyxx.op_total_fee", name="总费用",
                unit="元", precision=2, result_status="complete",
                value=dec_to_float(row.get("total_fee"), 2),
            ),
            OpsMetricCard(
                metric_code="mzjyxx.op_fund_pay", name="统筹基金支付",
                unit="元", precision=2, result_status="complete",
                value=dec_to_float(row.get("fund_pay"), 2),
            ),
            OpsMetricCard(
                metric_code="mzjyxx.op_self_pay", name="个人支付",
                unit="元", precision=2, result_status="complete",
                value=dec_to_float(row.get("self_pay"), 2),
            ),
            OpsMetricCard(
                metric_code="mzjyxx.insured_encounter_count", name="门诊医保就诊人次",
                unit="人次", precision=0, result_status="unavailable",
                halt_reason=_HALT_DATA_UNAVAILABLE, halt_detail=_HALT_DETAIL_ENCOUNTER,
            ),
            OpsMetricCard(
                metric_code="mzjyxx.average_fee", name="次均费用",
                unit="元", precision=2, result_status="unavailable",
                halt_reason=_HALT_DATA_UNAVAILABLE,
                halt_detail="次均费用=总费用/就诊人次，人次口径未接入前不可计算",
            ),
        ]
        return OpsOverview(
            result_status="complete" if row_count > 0 else "partial",
            halt_reason=None if row_count > 0 else _HALT_DATA_UNAVAILABLE,
            generated_at=dt.datetime.now().isoformat(timespec="seconds"),
            date_min=str(row.get("date_min") or "") or None,
            date_max=str(row.get("date_max") or "") or None,
            row_count=row_count,
            semantic_version=str(row.get("semantic_version") or "") or None,
            data_batch_ids=batch_ids,
            cards=cards,
        )

    # ── 维度拆分（五维度中的三个可用维度；科室 unavailable）────

    def breakdown(
        self, dimension: OpsAnalyticsDimension, top_n: int = 10
    ) -> OpsDimensionBreakdown:
        if dimension == "department":
            return OpsDimensionBreakdown(
                dimension="department", dimension_name="科室",
                result_status="unavailable",
                halt_reason=_HALT_DATA_UNAVAILABLE,
                halt_detail=_HALT_DETAIL_DEPARTMENT,
            )
        column, dim_name, mapping = _DIMENSIONS[dimension]
        top_n = max(1, min(top_n, 50))
        sql = (
            f"SELECT tr.\"{column}\" AS dim_code, "
            f"COUNT(DISTINCT tr.\"T_TradeNo\") AS valid_count, "
            f"COALESCE(SUM(tr.\"T_FeeAll\"), 0) AS total_fee, "
            f"COALESCE(SUM(tr.\"T_FundPay\"), 0) AS fund_pay, "
            f"COALESCE(SUM(tr.\"T_SelfPayAll\"), 0) AS self_pay, "
            f"ARRAY_AGG(DISTINCT tr.data_batch_id) FILTER "
            f"(WHERE tr.data_batch_id IS NOT NULL) AS batch_ids "
            f"FROM {_TABLE} WHERE {_V4_WHERE} "
            f"GROUP BY tr.\"{column}\" ORDER BY valid_count DESC "
            f"LIMIT %s"
        )
        rows = self._client.execute(sql, (top_n,))
        total_count = sum(int(r.get("valid_count") or 0) for r in rows)
        items = [
            OpsDimensionItem(
                code=str(r.get("dim_code") if r.get("dim_code") is not None else ""),
                label=_code_label(r.get("dim_code"), mapping),
                valid_count=int(r.get("valid_count") or 0),
                total_fee=dec_to_float(r.get("total_fee"), 2) or 0.0,
                fund_pay=dec_to_float(r.get("fund_pay"), 2) or 0.0,
                self_pay=dec_to_float(r.get("self_pay"), 2) or 0.0,
                share=(
                    round(int(r.get("valid_count") or 0) / total_count, 4)
                    if total_count else 0.0
                ),
            )
            for r in rows
        ]
        return OpsDimensionBreakdown(
            dimension=dimension, dimension_name=dim_name,
            result_status="complete" if items else "partial",
            halt_reason=None if items else _HALT_DATA_UNAVAILABLE,
            data_batch_ids=sorted({b for r in rows for b in _batch_ids(r)}),
            items=items,
        )

    # ── 月度趋势（就诊时间维度）────────────────────────────────

    def trend(self, months: int = 12) -> list[OpsTrendPoint]:
        months = max(1, min(months, 36))
        sql = (
            f"SELECT to_char(date_trunc('month', tr.\"T_TradeDate\"), 'YYYY-MM') AS month, "
            f"COUNT(DISTINCT tr.\"T_TradeNo\") AS valid_count, "
            f"COALESCE(SUM(tr.\"T_FeeAll\"), 0) AS total_fee, "
            f"COALESCE(SUM(tr.\"T_FundPay\"), 0) AS fund_pay, "
            f"COALESCE(SUM(tr.\"T_SelfPayAll\"), 0) AS self_pay "
            f"FROM {_TABLE} WHERE {_V4_WHERE} "
            f"GROUP BY 1 ORDER BY 1 DESC LIMIT %s"
        )
        rows = self._client.execute(sql, (months,))
        points = [
            OpsTrendPoint(
                month=str(r.get("month") or ""),
                valid_count=int(r.get("valid_count") or 0),
                total_fee=dec_to_float(r.get("total_fee"), 2) or 0.0,
                fund_pay=dec_to_float(r.get("fund_pay"), 2) or 0.0,
                self_pay=dec_to_float(r.get("self_pay"), 2) or 0.0,
            )
            for r in rows
        ]
        points.reverse()  # 时间升序返回
        return points

    # ── 行级下钻（结算状态→就诊明细；科室维度的替代路径）────────

    def drill(
        self,
        dimension: OpsAnalyticsDimension | None = None,
        value: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> OpsDrillResult:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters = [_V4_WHERE]
        params: list[Any] = []
        if dimension and dimension != "department" and value:
            column = _DIMENSIONS[dimension][0]
            filters.append(f"tr.\"{column}\" = %s")
            params.append(value)
        if date_from:
            filters.append("tr.\"T_TradeDate\" >= %s")
            params.append(dt.date.fromisoformat(date_from))
        if date_to:
            filters.append("tr.\"T_TradeDate\" < (%s::date + 1)")
            params.append(dt.date.fromisoformat(date_to))
        where = " AND ".join(filters)

        count_sql = f"SELECT COUNT(*) AS total FROM {_TABLE} WHERE {where}"
        total = int((self._client.execute(count_sql, tuple(params)) or [{}])[0].get("total") or 0)
        if total == 0:
            return OpsDrillResult(
                result_status="partial", halt_reason=_HALT_DATA_UNAVAILABLE,
                total=0, limit=limit, offset=offset,
            )

        sql = (
            f"SELECT tr.\"T_TradeNo\" AS trade_no, tr.\"T_TradeDate\" AS trade_date, "
            f"tr.\"P_FundType\" AS fund_type, tr.\"T_CureType\" AS cure_type, "
            f"tr.\"T_State\" AS settle_state, tr.\"T_FeeAll\" AS total_fee, "
            f"tr.\"T_FundPay\" AS fund_pay, tr.\"T_SelfPayAll\" AS self_pay, "
            f"tr.data_batch_id AS data_batch_id "
            f"FROM {_TABLE} WHERE {where} "
            f"ORDER BY tr.\"T_TradeDate\" DESC, tr.\"T_TradeNo\" LIMIT %s OFFSET %s"
        )
        rows = self._client.execute(sql, tuple(params + [limit, offset]))
        drill_rows = [
            OpsDrillRow(
                trade_no=str(r.get("trade_no") or ""),
                trade_date=str(r.get("trade_date") or "") or None,
                fund_type=_code_label(r.get("fund_type"), _FUND_TYPE_CN),
                cure_type=_code_label(r.get("cure_type"), _CURE_TYPE_CN),
                settle_state=_code_label(r.get("settle_state"), _SETTLE_STATE_CN),
                total_fee=dec_to_float(r.get("total_fee"), 2) or 0.0,
                fund_pay=dec_to_float(r.get("fund_pay"), 2) or 0.0,
                self_pay=dec_to_float(r.get("self_pay"), 2) or 0.0,
                data_batch_id=str(r.get("data_batch_id") or "") or None,
            )
            for r in rows
        ]
        return OpsDrillResult(
            result_status="complete", total=total, limit=limit, offset=offset,
            data_batch_ids=sorted({
                str(r.get("data_batch_id"))
                for r in rows if r.get("data_batch_id") is not None
            }),
            rows=drill_rows,
        )

    # ── 周报：四指标环比 + 结论 + AI 摘要（可降级）─────────────

    def weekly_report(self, week_start: str | None = None) -> OpsWeeklyReport:
        if week_start:
            ws = dt.date.fromisoformat(week_start)
        else:
            today = dt.date.today()
            ws = today - dt.timedelta(days=today.weekday())  # 本周周一
        we = ws + dt.timedelta(days=7)
        pw = ws - dt.timedelta(days=7)

        sql = (
            f"SELECT CASE WHEN tr.\"T_TradeDate\" >= %s THEN 'cur' ELSE 'prev' END AS wk, "
            f"COUNT(DISTINCT tr.\"T_TradeNo\") AS valid_count, "
            f"COALESCE(SUM(tr.\"T_FeeAll\"), 0) AS total_fee, "
            f"COALESCE(SUM(tr.\"T_FundPay\"), 0) AS fund_pay, "
            f"COALESCE(SUM(tr.\"T_SelfPayAll\"), 0) AS self_pay, "
            f"COUNT(*) AS row_count, "
            f"ARRAY_AGG(DISTINCT tr.data_batch_id) FILTER "
            f"(WHERE tr.data_batch_id IS NOT NULL) AS batch_ids "
            f"FROM {_TABLE} WHERE {_V4_WHERE} "
            f"AND tr.\"T_TradeDate\" >= %s AND tr.\"T_TradeDate\" < %s "
            f"GROUP BY 1"
        )
        rows = self._client.execute(sql, (ws, pw, we))
        by_week = {str(r.get("wk")): r for r in rows}
        cur = by_week.get("cur", {})
        prev = by_week.get("prev", {})
        cur_rows = int(cur.get("row_count") or 0)
        prev_rows = int(prev.get("row_count") or 0)
        batch_ids = sorted(set(_batch_ids(cur)) | set(_batch_ids(prev)))

        specs = [
            ("mzjyxx.op_valid_settle_count", "有效结算笔数", "valid_count", "笔", 0),
            ("mzjyxx.op_total_fee", "总费用", "total_fee", "元", 2),
            ("mzjyxx.op_fund_pay", "统筹基金支付", "fund_pay", "元", 2),
            ("mzjyxx.op_self_pay", "个人支付", "self_pay", "元", 2),
        ]
        deltas: list[OpsWeekDelta] = []
        conclusions: list[OpsConclusion] = []
        for code, name, key, unit, precision in specs:
            cur_val = dec_to_float(cur.get(key), precision)
            prev_val = dec_to_float(prev.get(key), precision)
            delta = pct = None
            direction: str = "unknown"
            if cur_val is not None and prev_val is not None:
                delta = float(Decimal(str(cur_val)) - Decimal(str(prev_val)))
                if prev_val != 0:
                    pct = round(delta / abs(prev_val) * 100, 2)
                direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
            deltas.append(OpsWeekDelta(
                metric_code=code, name=name, unit=unit, precision=precision,
                current=cur_val, previous=prev_val, delta=delta, pct=pct,
                direction=direction,  # type: ignore[arg-type]
            ))
            if cur_val is not None and prev_val is not None:
                pct_text = f"{pct:+.1f}%" if pct is not None else "（上周为 0，无法计算百分比）"
                conclusions.append(OpsConclusion(
                    text=(
                        f"{name}：本周 {cur_val:g}{unit}，上周 {prev_val:g}{unit}，"
                        f"环比 {pct_text}"
                    ),
                    citations=[
                        {"type": "metric_definition", "metric_code": code},
                        *[{"type": "metric_batch", "data_batch_id": b} for b in batch_ids],
                    ],
                ))

        result_status = "complete" if cur_rows > 0 else "partial"
        halt_reason = None if cur_rows > 0 else _HALT_DATA_UNAVAILABLE
        report = OpsWeeklyReport(
            week_start=ws.isoformat(), result_status=result_status,
            halt_reason=halt_reason,
            current_week_rows=cur_rows, previous_week_rows=prev_rows,
            deltas=deltas, conclusions=conclusions,
            data_batch_ids=batch_ids,
        )
        report.summary = self._generate_summary(report)
        return report

    def _generate_summary(self, report: OpsWeeklyReport) -> str | None:
        """AI 运营摘要：仅基于已计算结论；模型不可用诚实降级。"""
        if not report.conclusions:
            return None
        if self._model_gateway is None:
            report.uncertainties.append("模型网关未配置，本周未生成 AI 运营摘要")
            return None
        prompt_lines = [f"门诊医保运营周报（周起始 {report.week_start}）："]
        prompt_lines += [f"- {c.text}" for c in report.conclusions]
        prompt_lines.append(
            "请用不超过 120 字给出运营摘要：仅陈述以上数值结论与值得关注的异动，"
            "不得引入任何未给出的数字或推测。"
        )
        try:
            from src.model_service.models import Message

            response = self._model_gateway.generate(
                [Message(role="user", content="\n".join(prompt_lines))],
                # model_type 必须是 "llm"：路由表只有 (default, llm) 兜底，
                # 此前误用 "chat" 会在未发布治理路由时抛 ModelRouteError 恒降级
                model_type="llm",
                scene="ops_weekly_summary",
            )
        except Exception as exc:  # 模型未配置/调用失败：降级，不阻断周报
            report.uncertainties.append(f"AI 摘要生成失败（{type(exc).__name__}），数值结论不受影响")
            return None
        return (getattr(response, "content", "") or "").strip() or None
