from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pyodbc
import yaml

import time
from pprint import pprint

from .case_context import RawBusinessContext


class SqlTemplateStore:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)

        if not self.config_path.exists():
            raise FileNotFoundError(f"SQL 配置文件不存在: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

        self.queries = self.config.get("queries", {})

    def get_sql(self, name: str) -> str:
        item = self.queries.get(name)

        if not item:
            raise KeyError(f"SQL 配置中不存在 query: {name}")

        sql = item.get("sql")

        if not sql:
            raise ValueError(f"SQL 配置 query={name} 缺少 sql")

        return sql

    def get_params(self, name: str) -> list[str]:
        item = self.queries.get(name)

        if not item:
            raise KeyError(f"SQL 配置中不存在 query: {name}")

        return item.get("params", [])


class SqlServerBusinessDataClient:
    def __init__(
        self,
        *,
        sql_config_path: str | Path,
        host: str | None = None,
        port: str | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        driver: str = "SQL Server",
    ):
        self.host = host or os.getenv("MSSQL_HOST", "localhost")
        self.port = port or os.getenv("MSSQL_PORT", "1433")
        self.database = database or os.getenv("MSSQL_DATABASE")
        self.user = user or os.getenv("MSSQL_USER")
        self.password = password or os.getenv("MSSQL_PASSWORD")
        self.driver = os.getenv("MSSQL_DRIVER", driver)

        if not self.database:
            raise ValueError("缺少 MSSQL_DATABASE")
        if not self.user:
            raise ValueError("缺少 MSSQL_USER")
        if not self.password:
            raise ValueError("缺少 MSSQL_PASSWORD")

        self.sql_store = SqlTemplateStore(sql_config_path)

    def _connect(self):
        conn_str = (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.host},{self.port};"
            f"DATABASE={self.database};"
            f"UID={self.user};"
            f"PWD={self.password};"
        )
        # TrustServerCertificate 仅在 ODBC Driver 17+ 受支持
        if "ODBC Driver 17" in self.driver or "ODBC Driver 18" in self.driver:
            conn_str += "TrustServerCertificate=yes;"
        return pyodbc.connect(conn_str)

    def get_case_context_raw(
        self,
        *,
        settlement_id: str | None = None,
        person_id: str | None = None,
        visit_id: str | None = None,
        question: str | None = None,
    ) -> RawBusinessContext:
        if not settlement_id:
            raise ValueError("当前 SQL Server 查询必须提供 settlement_id")

        row, sql_text, sql_params_dict, elapsed_ms, columns = self._query_one(
            query_name="settlement_context",
            params={
                "djh": settlement_id,
            },
        )

        if not row:
            raise ValueError(f"未查询到结算记录 djh={settlement_id}")


        return RawBusinessContext(
            case_id=str(row.get("djh")),
            settlement_id=str(row.get("djh")),
            person_id=str(row.get("djh")),
            visit_id=str(row.get("djh")),

            raw_person_type=row.get("fund_type"),
            raw_insurance_type=row.get("fund_type"),
            raw_service_type=row.get("yllb"),

            raw_hospital_level=row.get("hospital_level"),
            raw_hospital_name=row.get("hospital_name"),

            raw_admission_count=row.get("bnzqslj"),
            raw_settlement_year=row.get("fynd"),

            raw_target_amount=row.get("bcqfje"),

            raw_data=row,

            # ★ SQL 可观测性
            query_sql=sql_text,
            query_params=sql_params_dict,
            query_duration_ms=elapsed_ms,
            query_result_columns=columns,
        )

    def _query_one(
        self,
        *,
        query_name: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any], float, list[str]]:
        """执行单条 SQL 查询，返回 (结果行, SQL文本, 参数, 耗时ms, 列名)。"""

        sql = self.sql_store.get_sql(query_name)
        param_names = self.sql_store.get_params(query_name)

        values = [params.get(name) for name in param_names]
        param_dict = dict(zip(param_names, values))

        print("\n" + "=" * 80)
        print(f"[SQL QUERY] {query_name}")

        print("\n[SQL]")
        print(sql)

        print("\n[PARAM_NAMES]")
        pprint(param_names)

        print("\n[PARAM_VALUES]")
        pprint(values)

        start_time = time.time()

        with self._connect() as conn:
            cursor = conn.cursor()

            cursor.execute(sql, *values)

            row = cursor.fetchone()
            columns = [col[0] for col in cursor.description] if cursor.description else []

            elapsed = round(time.time() - start_time, 3)
            elapsed_ms = int(elapsed * 1000)

            print(f"\n[SQL ELAPSED] {elapsed}s")

            if not row:
                print("\n[SQL RESULT] EMPTY")
                print("=" * 80)
                return None, sql, param_dict, elapsed_ms, columns

            result = dict(zip(columns, row))

            print("\n[SQL RESULT]")
            pprint(result)

            print("=" * 80)

            return result, sql, param_dict, elapsed_ms, columns