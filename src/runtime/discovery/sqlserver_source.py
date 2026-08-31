"""SQL Server 数据发现源：通过 information_schema + extended_properties 扫描表结构。"""
from __future__ import annotations

import hashlib

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# 按优先级排列的 ODBC 驱动备选列表
_DRIVER_CANDIDATES = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server",  # 旧版/内置驱动，无需额外安装
]


def _build_conn_str(cfg: dict, driver: str | None = None) -> str:
    """构建 SQL Server 连接字符串。driver 参数覆盖 cfg 中的 driver。"""
    driver = driver or cfg.get("driver", _DRIVER_CANDIDATES[0])
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 1433)
    database = cfg.get("database", "")
    user = cfg.get("user", "")
    password = cfg.get("password", "")
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
    )
    if "ODBC Driver 17" in driver or "ODBC Driver 18" in driver:
        conn_str += "TrustServerCertificate=yes;"
    return conn_str


def _env_fallback_conn_str() -> str | None:
    host = os.getenv("MSSQL_HOST")
    port = os.getenv("MSSQL_PORT", "1433")
    database = os.getenv("MSSQL_DATABASE")
    user = os.getenv("MSSQL_USER")
    password = os.getenv("MSSQL_PASSWORD")
    driver = os.getenv("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server")
    if not all([host, database, user, password]):
        return None
    return _build_conn_str({
        "host": host,
        "port": int(port),
        "database": database,
        "user": user,
        "password": password,
        "driver": driver,
    })


def _connect(conn_str: str) -> Any:
    try:
        import pyodbc
        return pyodbc.connect(conn_str, autocommit=True, connect_timeout=10)
    except ImportError:
        raise RuntimeError("pyodbc 未安装，无法连接 SQL Server")


def _query_tables(conn: Any, schema: str, tables: list[str], exclude_prefixes: list[str]) -> list[dict]:
    cursor = conn.cursor()
    where_parts = ["TABLE_TYPE = 'BASE TABLE'", f"TABLE_SCHEMA = '{schema}'"]
    params: list[Any] = []
    if tables:
        placeholders = ",".join(["?"] * len(tables))
        where_parts.append(f"TABLE_NAME IN ({placeholders})")
        params.extend(tables)
    if exclude_prefixes:
        exclude_conditions = " AND ".join([f"TABLE_NAME NOT LIKE '{p}%'" for p in exclude_prefixes])
        where_parts.append(f"({exclude_conditions})")
    where_clause = " AND ".join(where_parts)
    sql = f"SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE {where_clause} ORDER BY TABLE_NAME"
    cursor.execute(sql, *params)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _query_columns(conn: Any, schema: str, table: str) -> list[dict]:
    cursor = conn.cursor()
    sql = """
        SELECT 
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE,
            CHARACTER_MAXIMUM_LENGTH,
            NUMERIC_PRECISION,
            NUMERIC_SCALE,
            ORDINAL_POSITION
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """
    cursor.execute(sql, schema, table)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _query_column_descriptions(conn: Any, schema: str, table: str) -> dict[str, str]:
    cursor = conn.cursor()
    sql = """
        SELECT 
            c.name AS column_name,
            CAST(ep.value AS NVARCHAR(MAX)) AS description
        FROM sys.columns c
        LEFT JOIN sys.extended_properties ep 
            ON ep.major_id = c.object_id 
            AND ep.minor_id = c.column_id 
            AND ep.name = 'MS_Description'
        WHERE c.object_id = OBJECT_ID(?)
    """
    full_name = f"{schema}.{table}"
    cursor.execute(sql, full_name)
    result: dict[str, str] = {}
    for row in cursor.fetchall():
        col_name = row[0]
        desc = row[1]
        if desc:
            result[col_name] = desc
    return result


# SQL Server 中不能直接用于 COUNT/DISTINCT/MAX/MIN 的类型
_UNQUERYABLE_TYPES = ("image", "text", "ntext", "sql_variant", "geography", "geometry", "hierarchyid", "xml")


def _is_unqueryable_type(data_type: str) -> bool:
    """判断数据类型是否无法用于 COUNT/DISTINCT/MAX/MIN 等聚合/比较操作。"""
    dt = data_type.lower()
    return dt in _UNQUERYABLE_TYPES or any(dt.startswith(t) for t in _UNQUERYABLE_TYPES)


def _query_table_non_null_rates(conn: Any, schema: str, table: str, columns: list[dict]) -> dict[str, float]:
    """批量计算整表所有列的非空率（一次表扫描）。跳过 image/text 等不可 COUNT 的类型。"""
    full_name = f"[{schema}].[{table}]"
    cursor = conn.cursor()
    count_parts: list[str] = []
    col_map: dict[int, tuple[str, str]] = {}  # alias index → (col_name, data_type)
    idx = 0
    for c in columns:
        col_name = c["COLUMN_NAME"]
        data_type = c["DATA_TYPE"]
        if _is_unqueryable_type(data_type):
            continue  # 跳过不可查询类型
        count_parts.append(f"COUNT([{col_name}])")
        col_map[idx] = (col_name, data_type)
        idx += 1
    if not count_parts:
        return {c["COLUMN_NAME"]: 0.0 for c in columns}
    col_aliases = [f"c_{i}" for i in range(len(count_parts))]
    selects = ", ".join(f"{p} AS {a}" for p, a in zip(count_parts, col_aliases))
    sql = f"SELECT COUNT(*) AS _total, {selects} FROM {full_name}"
    try:
        cursor.execute(sql)
        row = cursor.fetchone()
        if not row or row[0] == 0:
            return {c["COLUMN_NAME"]: 0.0 for c in columns}
        total = row[0]
        result: dict[str, float] = {}
        for i in range(len(count_parts)):
            col_name, _ = col_map[i]
            result[col_name] = round(row[i + 1] * 100.0 / total, 2)
        for c in columns:
            if c["COLUMN_NAME"] not in result:
                result[c["COLUMN_NAME"]] = 0.0
        return result
    except Exception:
        logger.warning("批量统计非空率失败 %s.%s", schema, table, exc_info=True)
        return {c["COLUMN_NAME"]: 0.0 for c in columns}


def _query_sample_values(conn: Any, schema: str, table: str, column: str, data_type: str, top_n: int = 5) -> list[str]:
    """获取多个样本值（TOP N DISTINCT 非空值）。跳过 image/text 等不可 DISTINCT 的类型。"""
    if _is_unqueryable_type(data_type):
        return []
    cursor = conn.cursor()
    full_name = f"[{schema}].[{table}]"
    sql = f"SELECT DISTINCT TOP {top_n} [{column}] FROM {full_name} WHERE [{column}] IS NOT NULL"
    try:
        cursor.execute(sql)
        rows = cursor.fetchall()
        return [str(row[0]) for row in rows if row[0] is not None]
    except Exception:
        logger.warning("获取样本值失败 %s.%s.%s", schema, table, column, exc_info=True)
    return []


def _query_non_null_count(conn: Any, schema: str, table: str, column: str, data_type: str) -> int:
    """查询字段的非空行数。跳过不可 COUNT 的类型。"""
    if _is_unqueryable_type(data_type):
        return 0
    cursor = conn.cursor()
    full_name = f"[{schema}].[{table}]"
    sql = f"SELECT COUNT([{column}]) FROM {full_name} WHERE [{column}] IS NOT NULL"
    try:
        cursor.execute(sql)
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        logger.warning("获取非空行数失败 %s.%s.%s", schema, table, column, exc_info=True)
        return 0


def _is_numeric_or_datetime_type(data_type: str) -> bool:
    """判断字段类型是否为数值或时间类型。"""
    dt_lower = data_type.lower()
    numeric_types = (
        "int", "bigint", "smallint", "tinyint", "decimal",
        "numeric", "float", "real", "money", "smallmoney",
        "bit", "bigint",
    )
    datetime_types = (
        "datetime", "datetime2", "smalldatetime", "date",
        "time", "datetimeoffset", "timestamp",
    )
    return any(dt_lower.startswith(t) for t in numeric_types + datetime_types)


def _is_string_type(data_type: str) -> bool:
    """判断字段类型是否为字符串类型。"""
    dt_lower = data_type.lower()
    string_types = (
        "varchar", "nvarchar", "char", "nchar",
    )
    return any(dt_lower.startswith(t) for t in string_types)


def _is_long_text_type(data_type: str, max_length: int | None) -> bool:
    """判断字段是否为长文本类型。"""
    dt_lower = data_type.lower()
    if any(dt_lower.startswith(t) for t in ("text", "ntext", "xml")):
        return True
    if "max" in dt_lower:
        return True
    if max_length is not None and max_length >= 1000:
        return True
    return False


def _query_column_max_min(conn: Any, schema: str, table: str, column: str, data_type: str) -> tuple[str | None, str | None]:
    """查询数值/时间列的最大值和最小值。跳过不可比较的类型。"""
    if _is_unqueryable_type(data_type):
        return (None, None)
    cursor = conn.cursor()
    full_name = f"[{schema}].[{table}]"
    sql = f"SELECT MAX([{column}]), MIN([{column}]) FROM {full_name} WHERE [{column}] IS NOT NULL"
    try:
        cursor.execute(sql)
        row = cursor.fetchone()
        if row:
            return (str(row[0]) if row[0] is not None else None,
                    str(row[1]) if row[1] is not None else None)
    except Exception:
        logger.warning("获取 max/min 失败 %s.%s.%s", schema, table, column, exc_info=True)
    return (None, None)


def _query_top_freq_values(conn: Any, schema: str, table: str, column: str, data_type: str, top_n: int = 5) -> list[dict]:
    """查询频率最高的 TOP N 值及其出现次数。跳过不可 GROUP BY 的类型。"""
    if _is_unqueryable_type(data_type):
        return []
    cursor = conn.cursor()
    full_name = f"[{schema}].[{table}]"
    sql = (
        f"SELECT TOP {top_n} [{column}], COUNT(*) AS cnt "
        f"FROM {full_name} "
        f"WHERE [{column}] IS NOT NULL "
        f"GROUP BY [{column}] "
        f"ORDER BY cnt DESC"
    )
    try:
        cursor.execute(sql)
        return [{"value": str(row[0]), "count": int(row[1])} for row in cursor.fetchall()]
    except Exception:
        logger.warning("获取频率 TOP 值失败 %s.%s.%s", schema, table, column, exc_info=True)
        return []


def _classify_enum_type(distinct_count: int | None) -> str | None:
    """根据 distinct 值数量分类枚举类型。"""
    if distinct_count is None:
        return None
    if distinct_count <= 50:
        return "枚举类型"
    if distinct_count <= 100:
        return "海量枚举类型"
    return None


def _compute_sample_stats(
    conn: Any, schema: str, table: str, column: str,
    data_type: str, max_length: int | None,
    distinct_count: int | None, non_null_count: int,
) -> dict | None:
    """计算样本值统计信息。

    按字段类型区分：
    - 时间/数值：max, min, top 5 频率值
    - 字符串：枚举类型分类（≤50 枚举类型，51-100 海量枚举类型）
    - 长文本：标记 is_long_text
    """
    stats: dict = {
        "max": None,
        "min": None,
        "top_freq": None,
        "enum_type": None,
        "is_long_text": False,
        "non_null_count": non_null_count,
    }

    if _is_numeric_or_datetime_type(data_type):
        max_val, min_val = _query_column_max_min(conn, schema, table, column, data_type)
        stats["max"] = max_val
        stats["min"] = min_val
        top_freq = _query_top_freq_values(conn, schema, table, column, data_type, top_n=5)
        stats["top_freq"] = top_freq if top_freq else None

    if _is_string_type(data_type):
        stats["enum_type"] = _classify_enum_type(distinct_count)
        if _is_long_text_type(data_type, max_length):
            stats["is_long_text"] = True

    # 检查是否是长文本类型（不论字段类型）
    if _is_long_text_type(data_type, max_length):
        stats["is_long_text"] = True

    return stats if any(v is not None and v != [] and v != 0 for v in [
        stats["max"], stats["min"], stats["top_freq"],
        stats["enum_type"], stats["is_long_text"],
    ]) or non_null_count > 0 else None


def _query_sample_value(conn: Any, schema: str, table: str, column: str, data_type: str) -> str | None:
    """获取单个样本值（保留兼容）。"""
    values = _query_sample_values(conn, schema, table, column, data_type, top_n=1)
    return values[0] if values else None


def _query_distinct_count(conn: Any, schema: str, table: str, column: str, data_type: str) -> int | None:
    """查询字段的精确 distinct 值数量。跳过不可 DISTINCT 的类型。"""
    if _is_unqueryable_type(data_type):
        return None
    cursor = conn.cursor()
    full_name = f"[{schema}].[{table}]"
    sql = f"SELECT COUNT(DISTINCT [{column}]) FROM {full_name} WHERE [{column}] IS NOT NULL"
    try:
        cursor.execute(sql)
        row = cursor.fetchone()
        if row:
            return int(row[0])
    except Exception:
        logger.warning("获取 distinct 计数失败 %s.%s.%s", schema, table, column, exc_info=True)
    return None


def _query_total_count(conn: Any, schema: str, table: str) -> int:
    """查询表的行数。"""
    cursor = conn.cursor()
    full_name = f"[{schema}].[{table}]"
    sql = f"SELECT COUNT(*) FROM {full_name}"
    try:
        cursor.execute(sql)
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        logger.warning("获取表行数失败 %s.%s", schema, table, exc_info=True)
        return 0


def _detect_is_dictionary(distinct_count: int | None, total_rows: int, sample_values: list[str]) -> bool:
    """判断字段是否为字典/枚举类型。

    规则：
    1. distinct_count <= 100 且 distinct_count/total_rows < 0.2
    2. 或 sample_values 全是短字符串（长度 < 20）且 distinct_count 较小
    """
    if distinct_count is None:
        return False
    if distinct_count <= 100 and total_rows > 0 and distinct_count / total_rows < 0.2:
        return True
    # 辅助判断：样本值全是短码
    if distinct_count <= 200 and sample_values and all(len(v) < 20 for v in sample_values):
        return True
    return False


def _query_table_last_modified(conn: Any, schema: str, table: str) -> str | None:
    """查询表的最后修改时间（DDL 修改时间）。"""
    cursor = conn.cursor()
    full_name = f"{schema}.{table}"
    sql = "SELECT modify_date FROM sys.objects WHERE object_id = OBJECT_ID(?) AND type = 'U'"
    try:
        cursor.execute(sql, full_name)
        row = cursor.fetchone()
        if row and row[0]:
            return row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0])
    except Exception:
        logger.warning("获取表修改时间失败 %s.%s", schema, table, exc_info=True)
    return None


def _suggest_object(table_name: str) -> str | None:
    mapping = {
        "yb_settlement": "Settlement",
        "yb_fee_detail": "FeeDetail",
        "yb_jsxx": "Settlement",
        "yb_mx": "FeeDetail",
    }
    return mapping.get(table_name)


def _try_connect(cfg: dict) -> Any:
    """尝试连接 SQL Server，依次尝试用户指定的驱动及备选驱动列表。
    返回 (connection, used_driver) 或抛出 RuntimeError。
    """
    import pyodbc

    user_driver = cfg.get("driver", "")
    # 构建尝试列表：用户指定 → 系统备选（去重）
    tried: set[str] = set()
    drivers_to_try: list[str] = []
    if user_driver:
        drivers_to_try.append(user_driver)
        tried.add(user_driver)
    for d in _DRIVER_CANDIDATES:
        if d not in tried:
            drivers_to_try.append(d)
            tried.add(d)

    last_error = None
    for driver in drivers_to_try:
        try:
            conn_str = _build_conn_str(cfg, driver)
            conn = pyodbc.connect(conn_str, autocommit=True, connect_timeout=10)
            if driver != user_driver:
                logger.info("ODBC 驱动降级：'%s' → '%s' 连接成功", user_driver or "(默认)", driver)
            return conn, driver
        except pyodbc.Error as exc:
            last_error = exc
            logger.debug("驱动 '%s' 连接失败: %s", driver, exc)
            continue
        except Exception as exc:
            last_error = exc
            logger.debug("驱动 '%s' 连接失败: %s", driver, exc)
            continue

    # 所有驱动都失败了
    tried_summary = " → ".join(drivers_to_try)
    raise RuntimeError(
        f"SQL Server 连接失败，已尝试驱动: {tried_summary}。"
        f"错误: {last_error}"
    ) from last_error


def _compute_column_hash(schema_name: str, table_name: str, columns: list[dict]) -> str:
    """计算表结构哈希（表名+列名+类型+长度+是否可空），用于快速检测表结构变化。"""
    key = f"{schema_name}.{table_name}|" + "|".join(
        f"{c['COLUMN_NAME']}:{c['DATA_TYPE']}:{c.get('CHARACTER_MAXIMUM_LENGTH','')}:{c.get('IS_NULLABLE','')}"
        for c in columns
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _scan_single_table_full(conn: Any, tschema: str, tname: str,
                            sample_limit: int,
                            columns: list[dict] | None = None) -> tuple[list[dict], int]:
    """对单表执行完整扫描（列信息 + 非空率 + 样本值 + 统计）。

    可传入 columns 避免重复查询 INFORMATION_SCHEMA。
    Returns: (fields_list, total_rows)
    """
    if columns is None:
        columns = _query_columns(conn, tschema, tname)
    descriptions: dict[str, str] = {}
    try:
        descriptions = _query_column_descriptions(conn, tschema, tname)
    except Exception:
        logger.warning("获取列描述失败 %s.%s", tschema, tname, exc_info=True)
    nn_rates = _query_table_non_null_rates(conn, tschema, tname, columns)
    total_rows = _query_total_count(conn, tschema, tname)
    table_last_modified = _query_table_last_modified(conn, tschema, tname)

    fields: list[dict] = []
    for col in columns:
        col_name = col["COLUMN_NAME"]
        data_type = col["DATA_TYPE"]
        max_length = col.get("CHARACTER_MAXIMUM_LENGTH")

        sample_values = _query_sample_values(conn, tschema, tname, col_name, data_type, top_n=sample_limit)
        sample = sample_values[0] if sample_values else None
        distinct_count = _query_distinct_count(conn, tschema, tname, col_name, data_type)
        non_null_count = _query_non_null_count(conn, tschema, tname, col_name, data_type)
        is_dictionary = _detect_is_dictionary(distinct_count, total_rows, sample_values)
        sample_stats = _compute_sample_stats(
            conn, tschema, tname, col_name,
            data_type, max_length, distinct_count, non_null_count,
        )

        fields.append({
            "field_name": col_name,
            "table_name": tname,
            "table_schema": tschema,
            "data_type": data_type,
            "is_nullable": col["IS_NULLABLE"],
            "description": descriptions.get(col_name),
            "non_null_rate": nn_rates.get(col_name, 0.0),
            "non_null_row_count": non_null_count,
            "distinct_count": distinct_count,
            "sample_value": sample,
            "sample_values": sample_values,
            "sample_stats": sample_stats,
            "is_dictionary": is_dictionary,
            "last_updated": table_last_modified,
            "suggested_object": _suggest_object(tname),
        })
    return fields, total_rows


def scan_sqlserver(cfg: dict, store=None, connection=None) -> dict:
    """扫描 SQL Server，返回 discovery 结果结构。

    如果 store（DiscoveryStore）可用，使用增量扫描：
    - 表结构未变 → 复用缓存结果（秒级完成）
    - 表结构变化或新表 → 完整扫描
    """
    schema = cfg.get("schema", "dbo")
    tables_filter = cfg.get("tables", [])
    exclude_prefixes = cfg.get("exclude_prefixes", ["sys_", "dt_", "MSreplication_"])
    sample_limit = cfg.get("sample_limit", 10000)

    conn = connection
    if conn is None:
        try:
            conn, _used_driver = _try_connect(cfg)
        except RuntimeError:
            if not cfg.get("fallback_to_env"):
                raise
            env_conn_str = _env_fallback_conn_str()
            if not env_conn_str:
                raise
            logger.info("页面配置连接失败，回退到环境变量配置")
            try:
                conn = _connect(env_conn_str)
            except Exception as exc2:
                raise RuntimeError(f"SQL Server 环境变量连接也失败: {exc2}") from exc2
    try:
        return _scan_connected(
            conn, schema, tables_filter, exclude_prefixes, sample_limit, store
        )
    finally:
        conn.close()


def _scan_connected(conn, schema, tables_filter, exclude_prefixes, sample_limit, store):
    tables = _query_tables(conn, schema, tables_filter, exclude_prefixes)
    fields: list[dict] = []
    tables_seen: set[str] = set()
    table_statuses: list[dict] = []  # per-table progress info

    for table_info in tables:
        tname = table_info["TABLE_NAME"]
        tschema = table_info["TABLE_SCHEMA"]
        tables_seen.add(tname)

        # 获取当前列信息用于哈希比较
        try:
            current_columns = _query_columns(conn, tschema, tname)
            current_hash = _compute_column_hash(tschema, tname, current_columns)
        except Exception:
            logger.warning("获取表结构失败 %s.%s，跳过", tschema, tname, exc_info=True)
            table_statuses.append({"table": tname, "status": "error", "fields": 0, "new": 0, "cached": False})
            continue

        # ── 增量扫描：检查缓存 ──
        table_fields: list[dict] = []
        total_rows = 0
        cached = False
        if store:
            try:
                cp = store.get_table_checkpoint(tname, tschema)
                if cp and cp.get("column_hash") == current_hash and cp.get("result_snapshot"):
                    # 结构未变，复用缓存
                    snapshot = cp["result_snapshot"]
                    table_fields = snapshot.get("fields", [])
                    total_rows = snapshot.get("total_rows", 0)
                    cached = True
                    logger.info("增量扫描: %s.%s 结构未变，复用缓存（%d 字段）",
                                tschema, tname, len(table_fields))
            except Exception:
                logger.warning("读取检查点失败 %s.%s，回退到完整扫描", tschema, tname, exc_info=True)

        # ── 完整扫描（缓存未命中或结构变化） ──
        if not cached:
            try:
                table_fields, total_rows = _scan_single_table_full(conn, tschema, tname, sample_limit, current_columns)
                # 保存检查点
                if store:
                    try:
                        store.save_table_checkpoint(
                            tname, tschema, current_hash, total_rows,
                            len(table_fields),
                            {"fields": table_fields, "total_rows": total_rows},
                        )
                    except Exception:
                        logger.warning("保存检查点失败 %s.%s", tschema, tname, exc_info=True)
            except Exception:
                logger.warning("扫描表失败 %s.%s，跳过", tschema, tname, exc_info=True)
                if store:
                    try:
                        store.save_table_checkpoint(
                            tname, tschema, current_hash, 0, 0,
                            {"fields": [], "total_rows": 0},
                            error_message=str(Exception),
                        )
                    except Exception:
                        pass
                table_statuses.append({"table": tname, "status": "error", "fields": 0, "new": 0, "cached": False})
                continue

        table_statuses.append({
            "table": tname,
            "status": "completed",
            "fields": len(table_fields),
            "new": 0,  # 由上级调用者计算
            "cached": cached,
        })
        fields.extend(table_fields)

    return {
        "tables": sorted(list(tables_seen)),
        "total_fields": len(fields),
        "fields": fields,
        "table_statuses": table_statuses,
    }
