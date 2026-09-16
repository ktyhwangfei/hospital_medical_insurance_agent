"""结算事实记录查询能力：退费记录 / 人员定位 / 费用明细 / 待遇叠加 / 同药跨单对比。

组合根：解析已注册 SQL Server 数据源（PolicyMetaStore 首个启用的库级数据源，
回退 discovery 最近扫描 / 环境变量链），建连后调用
`src.adapters.data_supply.settlement_record_queries` 的只读查询，
输出为可直接进 Workflow/Tool 的 dict。本模块不写业务规则（T7/T8 规则未接入，
相关结论一律落 uncertainties，不编造）。
"""

from __future__ import annotations

from typing import Any

from src.runtime.tool_registry.service import ToolInvocationError

from src.adapters.data_supply import settlement_record_queries as queries

# 同药对比判定阈值：金额/比例差异在此容差内视为一致（与结算政策对比口径一致）。
DIFF_TOLERANCE = 0.02


def _open_connection() -> Any:
    """按注册数据源建连：首个启用的 SQL Server 数据源 → 既有回退链。

    连接失败拋 ToolInvocationError：Workflow 层捕获后降级为该步骤 unavailable，
    而非 500（瞬时断库 fail-closed，不编造结果）。
    """
    try:
        from src.runtime.discovery.semantic_source import get_semantic_data_source

        source = get_semantic_data_source()
        try:
            from src.data_platform.storage.postgresql.policy_meta_store import PolicyMetaStore

            for ds in PolicyMetaStore().list_datasources(enabled_only=True):
                cfg = ds.get("connection_config") or {}
                if cfg.get("sqlserver") or cfg.get("host"):
                    return source.connect_datasource(ds["id"])
        except Exception:  # noqa: BLE001 — 注册表不可用时回退 discovery/env 链
            pass
        return source.open_connection()
    except Exception as exc:  # noqa: BLE001
        raise ToolInvocationError(f"结算记录数据源不可用：{exc}") from exc


def _require_success(result, capability: str) -> None:
    """适配器 FAILED（SQL 异常等）也统一拋 ToolInvocationError，交 Workflow 降级。"""
    if result.status.value != "success":
        raise ToolInvocationError(f"{capability} 查询失败：{result.message or '数据源异常'}")


def get_refund_record(
    *,
    settlement_id: str = "",
    id_card: str = "",
    insurance_card_no: str = "",
    visit_date: str = "",
) -> dict:
    """查询已发生退费/冲正记录（target_ref 能力入口，供 tool_get_refund_record 包装）。

    settlement_id 走医保端链路（住院 tflydjh）；人员标识 + 日期走 HIS 端 o_Trade
    退费交易链路（门诊，测试库医保端与 HIS 端无 djh 直接 join）。
    """
    if not settlement_id and not (id_card or insurance_card_no):
        return {
            "records": [],
            "refunded_count": 0,
            "conclusion": "缺少结算单号且无人员标识，无法定位退费记录",
            "uncertainties": ["需要结算单号，或人员唯一标识 + 就诊日期"],
        }
    conn = _open_connection()
    try:
        uncertainties = [
            "退费重算规则（统筹/自付如何随退费回冲）尚无权威规则来源，本结论仅陈述退费事实，不做金额重算归因"
        ]
        records: list[dict] = []
        if settlement_id:
            result = queries.query_inpatient_refund_records(conn, settlement_id)
            _require_success(result, "住院退费记录")
            records = result.data.get("records", [])
            conclusion = result.data.get("conclusion", "")
        else:
            conclusion = ""
        if id_card or insurance_card_no:
            result = queries.query_outpatient_refund_records(
                conn, id_card=id_card, insurance_card_no=insurance_card_no, visit_date=visit_date
            )
            _require_success(result, "门诊退费记录")
            records.extend(result.data.get("records", []))
            conclusion = f"{conclusion}；{result.data.get('conclusion', '')}".lstrip("；")
        return {
            "records": records,
            "refunded_count": len(records),
            "conclusion": conclusion or "未查询到退费记录",
            "uncertainties": uncertainties,
        }
    finally:
        conn.close()


def resolve_settlement_by_person(
    *,
    id_card: str = "",
    patient_id: str = "",
    insurance_card_no: str = "",
    visit_date: str = "",
) -> dict:
    """人员唯一标识 + 就诊日期 → 结算单候选（供 tool_resolve_settlement_by_person 包装）。"""
    conn = _open_connection()
    try:
        result = queries.resolve_settlements_by_person(
            conn,
            id_card=id_card,
            patient_id=patient_id,
            insurance_card_no=insurance_card_no,
            visit_date=visit_date,
        )
        _require_success(result, "人员定位结算单")
        return dict(result.data)
    finally:
        conn.close()


def get_fee_detail(settlement_id: str = "", settlement_ids: list[str] | None = None) -> dict:
    """按结算单查询费用明细（供 tool_get_fee_detail 包装）。

    双入口：单笔 settlement_id，或批量 settlement_ids（同药跨单对比的上游取数）。
    批量返回 {"details": {settlement_id: 单笔输出}}；单笔返回单笔结构。
    """
    if settlement_ids:
        ids = [s for s in ((settlement_ids,) if isinstance(settlement_ids, str) else settlement_ids) if s]
        details = {sid: get_fee_detail(sid) for sid in ids}
        missing = [sid for sid, d in details.items() if not d.get("items")]
        return {
            "details": details,
            "settlement_count": len(details),
            "conclusion": (
                f"已取回 {len(details)} 笔结算单费用明细"
                + (f"，其中 {len(missing)} 笔无明细" if missing else "")
            ),
        }
    conn = _open_connection()
    try:
        result = queries.query_fee_detail(conn, settlement_id)
        _require_success(result, "费用明细")
        return dict(result.data)
    finally:
        conn.close()


def get_benefit_stacking(settlement_id: str) -> dict:
    """按结算单查询待遇叠加分摊事实（供 tool_get_benefit_stacking 包装）。"""
    conn = _open_connection()
    try:
        result = queries.query_benefit_stacking(conn, settlement_id)
        _require_success(result, "待遇叠加")
        return dict(result.data)
    finally:
        conn.close()


# ── 同药跨单对比（纯逻辑，可独立测试） ────────────────────────


def _drug_key(item: dict) -> str:
    """同药对齐键：优先国标码，回退项目代码（盘点两者均 100% 填充）。"""
    return item.get("nation_code") or item.get("item_code") or ""


def _num(value: Any) -> float:
    return float(value) if value is not None else 0.0


def compare_same_drug_fee_details(
    fee_details: dict[str, dict],
) -> dict:
    """跨结算单同药对比（纯函数）。

    输入：{settlement_id: tool_get_fee_detail 输出}；按对齐键分组后，
    对出现在 ≥2 张结算单的项目逐项对比数量/单价/医保内占比/先行自付。
    差异归因（政策时段/调价/待遇累计）不在本函数范围内——只做确定性事实对比。
    """
    by_drug: dict[str, list[dict]] = {}
    for settlement_id, detail in fee_details.items():
        for item in detail.get("items", []):
            key = _drug_key(item)
            if not key:
                continue
            by_drug.setdefault(key, []).append(
                {
                    "settlement_id": settlement_id,
                    "item_name": item.get("item_name") or "",
                    "quantity": _num(item.get("quantity")),
                    "unit_price": _num(item.get("unit_price")),
                    "total_amount": _num(item.get("total_amount")),
                    "inner_ratio": (
                        _num(item.get("insurance_inner_amount")) / _num(item.get("total_amount"))
                        if _num(item.get("total_amount")) > 0
                        else None
                    ),
                    "pre_self_pay": _num(item.get("pre_self_pay_amount")),
                    "service_type": item.get("service_type") or "",
                }
            )

    comparisons: list[dict] = []
    for key, entries in sorted(by_drug.items()):
        settlements = {e["settlement_id"] for e in entries}
        if len(settlements) < 2:
            continue
        base = entries[0]
        flags: list[str] = []
        for other in entries[1:]:
            if abs(base["unit_price"] - other["unit_price"]) > DIFF_TOLERANCE:
                flags.append(f"单价不一致：{base['unit_price']} vs {other['unit_price']}")
            if abs(base["quantity"] - other["quantity"]) > DIFF_TOLERANCE:
                flags.append(f"数量不一致：{base['quantity']} vs {other['quantity']}")
            if base["inner_ratio"] is not None and other["inner_ratio"] is not None:
                if abs(base["inner_ratio"] - other["inner_ratio"]) > DIFF_TOLERANCE:
                    flags.append(
                        f"医保内占比不一致：{base['inner_ratio']:.4f} vs {other['inner_ratio']:.4f}"
                    )
            if abs(base["pre_self_pay"] - other["pre_self_pay"]) > DIFF_TOLERANCE:
                flags.append(f"先行自付不一致：{base['pre_self_pay']} vs {other['pre_self_pay']}")
        comparisons.append(
            {
                "drug_key": key,
                "item_name": base["item_name"],
                "settlement_ids": sorted(settlements),
                "entries": entries,
                "differences": flags,
                "match": not flags,
            }
        )

    all_match = all(c["match"] for c in comparisons) if comparisons else None
    diff_count = sum(1 for c in comparisons if not c["match"])
    if not comparisons:
        conclusion = "未找到跨结算单出现的同码项目，无法做同药对比"
    elif diff_count == 0:
        conclusion = f"{len(comparisons)} 个跨单同码项目逐项一致，未发现费用事实差异"
    else:
        conclusion = f"{len(comparisons)} 个跨单同码项目中 {diff_count} 个存在事实差异（单价/数量/医保内占比/先行自付），差异归因需结合政策时段与待遇累计进一步核验"
    uncertainties = [
        "同药对比仅核验费用事实（单价/数量/占比/先行自付）；差异的报销归因（政策时段变化、乙类先行自付规则、年度累计）需权威规则来源，当前未接入"
    ]
    return {
        "comparisons": comparisons,
        "comparison_count": len(comparisons),
        "all_match": all_match,
        "conclusion": conclusion,
        "uncertainties": uncertainties,
    }
