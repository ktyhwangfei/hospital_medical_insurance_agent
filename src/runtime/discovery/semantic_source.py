"""SemanticDataSource — 语义层取数适配器（读通道）。

职责:
1. 复用 discovery 已打通的真实 SQL Server 连接（source_config 来自最近一次成功扫描）
2. 把语义指标编码解析为 (table, column)，按表分组批量取数
3. 按 djh（医保登记号，yb_* 表通用主键）过滤行

设计理由:
- 语义层 metric.source_field = "yb_dyxxzy.bcqfje" 本身就是查询指令
- 同一表的多指标合并为一次 SELECT（批量取数）
- 复用 src/runtime/discovery/sqlserver_source.py 的连接/驱动降级逻辑，不另建通道
- 守防腐层：语义层不裸拼业务 SQL，统一走本适配器的 query_metrics

[来源: data_query.py 生产路径占位的落地实现]
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.runtime.discovery.sqlserver_source import (
    _build_conn_str,
    _env_fallback_conn_str,
    _try_connect,
)
from src.semantic_layer.registry import get_semantic_registry

logger = logging.getLogger(__name__)

# ── 行过滤键配置 ──────────────────────────────────────────────────
# yb_* 医保表通用主键为 djh（登记号）。物理列固定为 djh，
# 上下文键也用 "djh"（由调用方/编排层在 context 中提供）。
# 若某表主键不同，可在 OBJECT_FILTERS 中覆盖。
DEFAULT_FILTER_COLUMN = "djh"
DEFAULT_FILTER_CONTEXT_KEY = "djh"


class SemanticDataSource:
    """语义层 → 真实 SQL Server 的取数通道。

    Usage::

        src = SemanticDataSource()
        plan = src.build_query_plan(["zyfdxx.bdtczf", "zyjyxx.rylb"])
        values = src.query(["zyfdxx.bdtczf"], context={"djh": 1})
    """

    def __init__(self) -> None:
        self._registry = get_semantic_registry()

    # ============================================================
    # 连接复用
    # ============================================================

    def _resolve_source_config(self) -> dict:
        """取最近一次 discovery 成功扫描的 source_config；失败回退环境变量。"""
        try:
            from src.data_platform.storage.postgresql.discovery_store import DiscoveryStore

            cfg = DiscoveryStore().get_latest_source_config()
            if cfg and (cfg.get("sqlserver") or cfg.get("host")):
                # discovery 扫描时前端可能把连接包在 "sqlserver" 子键里
                return cfg.get("sqlserver", cfg)
        except Exception:
            logger.debug("取 discovery source_config 失败，回退环境变量", exc_info=True)
        return {}

    def _connect(self, cfg: dict):
        """复用 sqlserver_source 的驱动降级连接逻辑。

        优先用传入 cfg；失败时（若 cfg 允许）回退环境变量。
        """
        if cfg:
            try:
                conn, _driver = _try_connect(cfg)
                return conn
            except RuntimeError:
                if not cfg.get("fallback_to_env"):
                    raise

        # 环境变量回退
        env_conn_str = _env_fallback_conn_str()
        if not env_conn_str:
            raise RuntimeError(
                "SemanticDataSource 无可用 SQL Server 连接："
                "discovery 未成功扫描过，且未配置 MSSQL_HOST/MSSQL_DATABASE/MSSQL_USER/MSSQL_PASSWORD 环境变量"
            )
        import pyodbc  # noqa: F401  (由 _connect 触发友好报错)
        from src.runtime.discovery.sqlserver_source import _connect as raw_connect

        return raw_connect(env_conn_str)

    # ============================================================
    # 指标解析
    # ============================================================

    def resolve_metric(self, metric_code: str) -> dict[str, Any]:
        """指标编码 → 查询指令 {table, column, source_field, name, unmapped}。"""
        metric = self._registry.get_metric(metric_code)
        if not metric:
            return {"metric_code": metric_code, "unmapped": True, "reason": "指标不存在"}
        sf = metric.source_field
        if not sf:
            return {
                "metric_code": metric_code, "unmapped": True,
                "reason": "无 source_field", "name": metric.name,
            }
        table, column = (sf.split(".", 1) + [""])[:2] if "." in sf else (sf, sf)
        return {
            "metric_code": metric_code,
            "name": metric.name,
            "source_field": sf,
            "table": table,
            "column": column,
            "object_code": metric.object_code,
            "semantic_type": metric.semantic_type,
            "metric_type": metric.metric_type,
            "unmapped": False,
        }

    def group_by_table(
        self, resolved: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """按物理表分组（批量取数的基础）。"""
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in resolved:
            if r.get("unmapped"):
                continue
            groups.setdefault(r["table"], []).append(r)
        return groups

    # ============================================================
    # 查询计划（纯元数据，不执行）
    # ============================================================

    def build_query_plan(self, metric_codes: list[str]) -> dict[str, Any]:
        """生成查询计划：打几张表、各取哪些列、filter 列、未映射项。"""
        resolved = [self.resolve_metric(c) for c in metric_codes]
        mapped = [r for r in resolved if not r.get("unmapped")]
        unmapped = [r for r in resolved if r.get("unmapped")]
        groups = self.group_by_table(resolved)

        return {
            "total_metrics": len(metric_codes),
            "mapped_count": len(mapped),
            "unmapped_count": len(unmapped),
            "filter_column": DEFAULT_FILTER_COLUMN,
            "filter_context_key": DEFAULT_FILTER_CONTEXT_KEY,
            "tables": [
                {
                    "table": tbl,
                    "columns": [m["column"] for m in metrics],
                    "metrics": [
                        {"metric_code": m["metric_code"], "name": m["name"],
                         "column": m["column"], "semantic_type": m.get("semantic_type")}
                        for m in metrics
                    ],
                }
                for tbl, metrics in groups.items()
            ],
            "unmapped": unmapped,
        }

    # ============================================================
    # 真实取数（执行 SQL）
    # ============================================================

    def query(
        self,
        metric_codes: list[str],
        context: Optional[dict[str, Any]] = None,
        join_mode: str = "flat",
    ) -> dict[str, Any]:
        """按指标编码查询真实值。

        Args:
            metric_codes: 指标编码列表
            context: 必须包含 filter_context_key（默认 "djh"）对应的值
            join_mode: "flat"(默认) 每表单独 SELECT；"joined" 复用
                business_sql.yaml 的 settlement_context 多表 JOIN（含日期语义条件）

        Returns:
            {metric_code: value}，未映射或取数失败的返回 None
        """
        context = context or {}
        filter_value = context.get(DEFAULT_FILTER_CONTEXT_KEY)

        if join_mode == "joined" and filter_value is not None:
            joined = self._query_joined(metric_codes, filter_value)
            if joined is not None:
                return joined
            # joined 不可用时退回 flat
            logger.info("query: joined 模式不可用，退回 flat")

        return self._query_flat(metric_codes, filter_value)

    def _query_flat(
        self, metric_codes: list[str], filter_value: Any
    ) -> dict[str, Any]:
        """flat 模式：每表单独 SELECT TOP 1，取数后应用值域转换。"""
        resolved = [self.resolve_metric(c) for c in metric_codes]
        groups = self.group_by_table(resolved)
        results: dict[str, Any] = {c: None for c in metric_codes}

        if not groups:
            logger.warning("query: 无可取数的映射指标 (metric_codes=%s)", metric_codes)
            return results

        if filter_value is None:
            logger.warning(
                "query: context 缺少 %s，无法过滤行；返回全部为 None",
                DEFAULT_FILTER_CONTEXT_KEY,
            )
            return results

        cfg = self._resolve_source_config()
        conn = None
        try:
            conn = self._connect(cfg)
        except Exception as exc:
            logger.error("query: 连接 SQL Server 失败: %s", exc)
            return results

        try:
            schema = cfg.get("schema", "dbo")
            for table, metrics in groups.items():
                # 同表多列合并为一次 SELECT（批量取数）
                cols = ", ".join(f"[{m['column']}]" for m in metrics)
                sql = (
                    f"SELECT TOP 1 {cols} "
                    f"FROM [{schema}].[{table}] "
                    f"WHERE [{DEFAULT_FILTER_COLUMN}] = ?"
                )
                try:
                    cursor = conn.cursor()
                    cursor.execute(sql, filter_value)
                    row = cursor.fetchone()
                    if row:
                        for m, val in zip(metrics, row):
                            results[m["metric_code"]] = val
                except Exception:
                    logger.warning("query: 取数失败 table=%s", table, exc_info=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # 值域转换：对声明了 value_domain 的枚举型指标，码→标准标签
        # [来源: 弥合与 business_sql.yaml CASE 的转换差异]
        self._apply_value_domains(metric_codes, results)
        return results

    def _query_joined(
        self, metric_codes: list[str], djh: Any
    ) -> Optional[dict[str, Any]]:
        """joined 模式：复用 business_sql.yaml 的 settlement_context 多表 JOIN。

        复用经过业务调优的 JOIN（含 d.bdqsrq=c.bcqsrq 分段日期语义条件），
        避免重新生成高风险的 JOIN。business_sql 的 CASE 已转换码→标签，
        故本模式不再二次应用 value_domain。

        Returns None 表示 business_sql 路径不可用（调用方应退回 flat）。
        """
        try:
            from pathlib import Path

            from src.knowledge_extension.rule_explanation.policy_retrieval.sqlserver_business_data_client import (
                SqlServerBusinessDataClient,
            )

            sql_config_path = (
                Path(__file__).parent.parent.parent
                / "knowledge_extension" / "rule_explanation"
                / "policy_retrieval" / "config" / "business_sql.yaml"
            )
            client = SqlServerBusinessDataClient(sql_config_path=sql_config_path)
            raw_context = client.get_case_context_raw(settlement_id=str(djh))
            raw_data = raw_context.raw_data or {}
        except Exception:
            logger.warning("_query_joined: business_sql 路径失败", exc_info=True)
            return None

        if not raw_data:
            return None

        # 大小写不敏感的列名索引（SQL 别例大小写与 source_field 可能不一致）
        lower_index = {k.lower(): v for k, v in raw_data.items()}
        results: dict[str, Any] = {}
        for code in metric_codes:
            r = self.resolve_metric(code)
            col = (r.get("column") or "").lower()
            results[code] = lower_index.get(col)
        return results

    def _apply_value_domains(
        self, metric_codes: list[str], results: dict[str, Any]
    ) -> None:
        """对声明 value_domain 的指标，把原始码转为标准标签。

        非枚举指标/未声明 value_domain 的指标保持原值不变。
        resolve_value 找不到映射时返回原始值（registry 约定），安全无副作用。
        """
        for code in metric_codes:
            val = results.get(code)
            if val is None:
                continue
            metric = self._registry.get_metric(code)
            if not metric or not metric.value_domain:
                continue
            try:
                results[code] = self._registry.resolve_value(
                    metric.value_domain, str(val)
                )
            except Exception:
                logger.debug("resolve_value 失败 metric=%s", code, exc_info=True)


# ============================================================
# 全局单例
# ============================================================

_instance: Optional[SemanticDataSource] = None


def get_semantic_data_source() -> SemanticDataSource:
    global _instance
    if _instance is None:
        _instance = SemanticDataSource()
    return _instance
