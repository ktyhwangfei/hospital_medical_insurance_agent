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


def parse_source_field(source_field: str) -> tuple[str | None, str, str]:
    """解析 source_field 为 (datasource_id, table, column)。

    三段式 "ds.table.column" → (ds, table, column)，声明指标所属数据源；
    两段式 "table.column"   → (None, table, column)，向后兼容（走默认源）；
    超过三段 "ds.dbo.t.c"   → (ds, "dbo.t", c)，中间段归 table；
    单段   "column"         → (None, column, column)。

    [来源: docs/steering/政策知识管线设计.md §7.6 三段式寻址]
    """
    parts = source_field.split(".")
    if len(parts) >= 3:
        return parts[0], ".".join(parts[1:-1]), parts[-1]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    return None, source_field, source_field


class SemanticDataSource:
    """语义层 → 真实 SQL Server 的取数通道。

    Usage::

        src = SemanticDataSource()
        plan = src.build_query_plan(["zyfdxx.bdtczf", "zyjyxx.rylb"])
        values = src.query(["zyfdxx.bdtczf"], context={"djh": 1})
    """

    def __init__(self, meta_store=None) -> None:
        self._registry = get_semantic_registry()
        self._meta_store = meta_store  # 注入 PolicyMetaStore（多源路由，P7.2b）

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

    def _get_meta_store(self):
        """PolicyMetaStore 实例（可注入；不可用时返回 None，调用方降级）。"""
        if self._meta_store is not None:
            return self._meta_store
        try:
            from src.data_platform.storage.postgresql.policy_meta_store import PolicyMetaStore
            return PolicyMetaStore()
        except Exception:
            logger.debug("PolicyMetaStore 不可用", exc_info=True)
            return None

    def _resolve_datasource_connection(self, ds_id):
        """按 datasource_id 从注册表取连接配置（P7.2b 多源路由）。

        ds_id=None → 回退默认源（_resolve_source_config）；
        ds_id 存在且启用 → 返回其 connection_config；
        未找到/禁用 → None（调用方跳过该组）。
        """
        if not ds_id:
            return self._resolve_source_config()
        meta = self._get_meta_store()
        if meta is None:
            return None
        ds = meta.get_datasource(ds_id)
        if ds and ds.get("enabled") and ds.get("connection_config"):
            return ds["connection_config"]
        return None

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

    def connect_datasource(self, datasource_id: str) -> Any:
        """复用已注册数据源配置建立连接，供受控适配器使用。"""
        cfg = self._resolve_datasource_connection(datasource_id)
        if not cfg:
            raise RuntimeError(f"数据源 '{datasource_id}' 未注册、未启用或缺少连接配置")
        return self._connect(cfg)

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
        ds_id, table, column = parse_source_field(sf)
        return {
            "metric_code": metric_code,
            "name": metric.name,
            "source_field": sf,
            "datasource_id": ds_id,
            "table": table,
            "column": column,
            "object_code": metric.object_code,
            "semantic_type": metric.semantic_type,
            "metric_type": metric.metric_type,
            "unmapped": False,
        }

    # ============================================================
    # 查询计划（纯元数据，不执行）
    # ============================================================

    def build_query_plan(self, metric_codes: list[str]) -> dict[str, Any]:
        """生成查询计划：打几张表、各取哪些列、filter 列、未映射项。

        多源支持：按 (datasource_id, table) 分组，不同数据源的同名表分开。
        """
        resolved = [self.resolve_metric(c) for c in metric_codes]
        mapped = [r for r in resolved if not r.get("unmapped")]
        unmapped = [r for r in resolved if r.get("unmapped")]

        # 按 (datasource_id, table) 分组（datasource_id=None 表示走默认源）
        groups: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
        for r in mapped:
            groups.setdefault((r.get("datasource_id"), r["table"]), []).append(r)

        return {
            "total_metrics": len(metric_codes),
            "mapped_count": len(mapped),
            "unmapped_count": len(unmapped),
            "filter_column": DEFAULT_FILTER_COLUMN,
            "filter_context_key": DEFAULT_FILTER_CONTEXT_KEY,
            "tables": [
                {
                    "datasource_id": ds_id,
                    "table": tbl,
                    "columns": [m["column"] for m in metrics],
                    "metrics": [
                        {"metric_code": m["metric_code"], "name": m["name"],
                         "column": m["column"], "semantic_type": m.get("semantic_type")}
                        for m in metrics
                    ],
                }
                for (ds_id, tbl), metrics in groups.items()
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
    ) -> dict[str, Any]:
        """按指标编码查询真实值。

        Args:
            metric_codes: 指标编码列表
            context: 必须包含 filter_context_key（默认 "djh"）对应的值
        Returns:
            {metric_code: value}，未映射或取数失败的返回 None
        """
        context = context or {}
        filter_value = context.get(DEFAULT_FILTER_CONTEXT_KEY)

        return self._query_flat(metric_codes, filter_value)

    def _query_flat(
        self, metric_codes: list[str], filter_value: Any
    ) -> dict[str, Any]:
        """单表读取器；多行时拒绝猜测结果粒度。"""
        resolved = [self.resolve_metric(c) for c in metric_codes]
        # 多源分组：按 (datasource_id, table)（P7.2b）
        groups: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
        for r in resolved:
            if r.get("unmapped"):
                continue
            groups.setdefault((r.get("datasource_id"), r["table"]), []).append(r)
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

        # 多源：每组按 datasource_id 选连接（P7.2b）
        for (ds_id, table), metrics in groups.items():
            cfg = self._resolve_datasource_connection(ds_id)
            if not cfg:
                logger.warning("query: 跳过无连接组 ds=%s table=%s", ds_id, table)
                continue
            try:
                conn = self._connect(cfg)
            except Exception as exc:
                logger.warning("query: 连接失败 ds=%s table=%s: %s", ds_id, table, exc)
                continue
            try:
                schema = cfg.get("schema", "dbo")
                # 同表多列合并为一次 SELECT（批量取数）
                cols = ", ".join(f"[{m['column']}]" for m in metrics)
                sql = (
                    f"SELECT {cols} "
                    f"FROM [{schema}].[{table}] "
                    f"WHERE [{DEFAULT_FILTER_COLUMN}] = ?"
                )
                try:
                    cursor = conn.cursor()
                    cursor.execute(sql, filter_value)
                    rows = cursor.fetchall()
                    if len(rows) == 1:
                        for m, val in zip(metrics, rows[0]):
                            results[m["metric_code"]] = val
                    elif len(rows) > 1:
                        logger.warning("query: ds=%s table=%s 返回多行，需使用 Query Planner", ds_id, table)
                except Exception:
                    logger.warning("query: 取数失败 ds=%s table=%s", ds_id, table, exc_info=True)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        # 值域转换：对声明了 value_domain 的枚举型指标，码→标准标签
        # [来源: 语义层值域注册表]
        self._apply_value_domains(metric_codes, results)
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
