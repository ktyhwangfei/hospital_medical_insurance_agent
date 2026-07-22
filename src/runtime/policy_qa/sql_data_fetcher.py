"""
医保政策问答RAG系统 - SQL数据获取

封装SqlServerBusinessDataClient，查询所有相关表
"""

from __future__ import annotations

import logging
import time as _time
from pathlib import Path
from typing import Any

from src.knowledge_extension.rule_explanation.policy_retrieval.sqlserver_business_data_client import (
    SqlServerBusinessDataClient,
)
from src.runtime.policy_qa.models import SQLQueryResult
from src.runtime.policy_qa.dictionary_normalizer import get_normalizer

logger = logging.getLogger(__name__)


class SQLDataFetcher:
    """
    SQL数据获取器

    封装SqlServerBusinessDataClient，查询所有相关表
    """

    def __init__(
        self,
        sql_config_path: str | Path | None = None,
        host: str | None = None,
        port: str | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        if sql_config_path is None:
            # 默认配置路径: src/knowledge_extension/rule_explanation/policy_retrieval/config/business_sql.yaml
            sql_config_path = Path(__file__).parent.parent.parent / "knowledge_extension" / "rule_explanation" / "policy_retrieval" / "config" / "business_sql.yaml"

        self.client = SqlServerBusinessDataClient(
            sql_config_path=sql_config_path,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
        )
        self.normalizer = get_normalizer()

    async def fetch_all_tables(self, settlement_id: str) -> SQLQueryResult:
        """
        查询所有相关表

        Args:
            settlement_id: 结算ID(登记号)

        Returns:
            SQLQueryResult: 所有表的数据
        """
        print(f"\n[SQL-FETCH] ====== 开始查询 settlement_id={settlement_id} ======", flush=True)
        start_time = _time.time()
        
        try:
            # 获取原始业务上下文
            print(f"[SQL-FETCH] 调用 get_case_context_raw...", flush=True)
            raw_context = self.client.get_case_context_raw(settlement_id=settlement_id)
            print(f"[SQL-FETCH] get_case_context_raw 返回成功", flush=True)

            # 从 raw_data 提取数据（SqlServerBusinessDataClient 返回的是单表查询）
            raw_data = raw_context.raw_data or {}
            
            print(f"\n[SQL-FETCH] raw_data 字段:", flush=True)
            for k, v in raw_data.items():
                print(f"[SQL-FETCH]   {k}: {v}", flush=True)

            # 转换为SQLQueryResult
            result = SQLQueryResult()

            # 1. yb_zyfdxx: 待遇分解表（从 raw_data 提取）
            result.yb_zyfdxx = {
                "djh": raw_data.get("djh", ""),
                "bdfyzje": float(raw_data.get("bdfyzje", 0)),
                "bdybnzje": float(raw_data.get("bcybnje", 0)),  # 注意：字段名映射
                "bdtczfje": float(raw_data.get("bdtczfje", 0)),
                "bdtczf": float(raw_data.get("bdtczf", 0)),
                "bddegwyzfje": float(raw_data.get("bddegwyzfje", 0)),
                "bddegwyzf": float(raw_data.get("bddegwyzf", 0)),
                "bdgryf": float(raw_data.get("bdgryf", 0)),
            }
            print(f"\n[SQL-FETCH] 转换后 yb_zyfdxx:", flush=True)
            for k, v in result.yb_zyfdxx.items():
                print(f"[SQL-FETCH]   {k}: {v}", flush=True)

            # 2. yb_zyfymx: 费用明细表（需要单独查询）
            # 注意：当前 SqlServerBusinessDataClient 只查询了 settlement_context
            # 费用明细需要额外查询 fee_catalog_context
            print(f"\n[SQL-FETCH] 费用明细表需要单独查询（当前未实现）", flush=True)
            result.yb_zyfymx = []

            # 3. yb_dyxxnd: 年度累计表（从 raw_data 提取）
            result.yb_dyxxnd = {
                "djh": raw_data.get("djh", ""),
                "fynd": raw_data.get("fynd", ""),
                "bnzqslj": int(raw_data.get("bnzqslj", 0)),
                "bnybnje": float(raw_data.get("bcybnje", 0)),  # 使用本次医保内作为近似
                "bntczfje": float(raw_data.get("bdtczfje", 0)),
                "bndezfje": float(raw_data.get("bddegwyzfje", 0)),
            }
            print(f"\n[SQL-FETCH] 转换后 yb_dyxxnd:", flush=True)
            for k, v in result.yb_dyxxnd.items():
                print(f"[SQL-FETCH]   {k}: {v}", flush=True)

            # 4. yb_dyxxzy: 住院信息表（从 raw_data 提取）
            result.yb_dyxxzy = {
                "djh": raw_data.get("djh", ""),
                "fynd": raw_data.get("fynd", ""),
                "zqxh": raw_data.get("zqxh", ""),
                "bcqfje": float(raw_data.get("bcqfje", 0)),
                "bcybnje": float(raw_data.get("bcybnje", 0)),
            }
            print(f"\n[SQL-FETCH] 转换后 yb_dyxxzy:", flush=True)
            for k, v in result.yb_dyxxzy.items():
                print(f"[SQL-FETCH]   {k}: {v}", flush=True)

            # 5. yb_brdjxx: 患者登记表（从 raw_data 提取 + 标准化）
            raw_fund_type = raw_data.get("fund_type", "")
            raw_per_type = raw_data.get("PER_TYPE", "")
            raw_yllb = raw_data.get("yllb", "")
            
            # 标准化
            normalized_fund_type = self.normalizer.normalize_insurance_type(raw_fund_type)
            normalized_per_type = self.normalizer.normalize_population(raw_per_type)
            normalized_yllb = self.normalizer.normalize_medical_type(raw_yllb)
            
            result.yb_brdjxx = {
                "djh": raw_data.get("djh", ""),
                "fund_type": normalized_fund_type,
                "fund_type_raw": raw_fund_type,  # 保留原始值
                "PER_TYPE": normalized_per_type,
                "PER_TYPE_raw": raw_per_type,  # 保留原始值
                "yllb": normalized_yllb,
                "yllb_raw": raw_yllb,  # 保留原始值
            }
            print(f"\n[SQL-FETCH] 转换后 yb_brdjxx (已标准化):", flush=True)
            for k, v in result.yb_brdjxx.items():
                print(f"[SQL-FETCH]   {k}: {v}", flush=True)

            duration_ms = int((_time.time() - start_time) * 1000)
            print(f"\n[SQL-FETCH] ====== 查询完成 ({duration_ms}ms) ======\n", flush=True)

            # 记录基础设施事件（含 SQL 文本和结果详情）
            self._record_sql_event(
                query_name="settlement_context",
                settlement_id=settlement_id,
                sql_summary="Tables: yb_zyfdxx, yb_zyfymx, yb_dyxxnd, yb_dyxxzy, yb_brdjxx",
                sql_text=raw_context.query_sql,
                params=raw_context.query_params,
                result_fields=raw_context.query_result_columns,
                result_sample=raw_context.raw_data,
                row_count=1 if raw_context.raw_data else 0,
                duration_ms=duration_ms,
                status="completed",
            )

            return result

            # 2. yb_zyfymx: 费用明细表
            if raw_context.fee_details:
                result.yb_zyfymx = [
                    {
                        "djh": item.get("djh", ""),
                        "xh": item.get("xh", ""),
                        "xmdm": item.get("xmdm", ""),
                        "xmmc": item.get("xmmc", ""),
                        "sfxmdj": item.get("sfxmdj", ""),
                        "zje": float(item.get("zje", 0)),
                        "ybnje": float(item.get("ybnje", 0)),
                        "ybwje": float(item.get("ybwje", 0)),
                        "txbz": item.get("txbz", ""),
                        "SP_SCALE": float(item.get("SP_SCALE", 0)),
                        "MEDIC_L": float(item.get("MEDIC_L", 0)),
                    }
                    for item in raw_context.fee_details
                ]
                print(f"\n[SQL-FETCH] 转换后 yb_zyfymx: {len(result.yb_zyfymx)} 条", flush=True)
                # 打印前3条示例
                for i, item in enumerate(result.yb_zyfymx[:3]):
                    print(f"[SQL-FETCH]   [{i}] {item.get('xmmc', '')}: zje={item.get('zje', 0)}, ybnje={item.get('ybnje', 0)}, ybwje={item.get('ybwje', 0)}, sfxmdj={item.get('sfxmdj', '')}", flush=True)

            # 3. yb_dyxxnd: 年度累计表
            if raw_context.annual:
                result.yb_dyxxnd = {
                    "djh": raw_context.annual.get("djh", ""),
                    "fynd": raw_context.annual.get("fynd", ""),
                    "bnzqslj": int(raw_context.annual.get("bnzqslj", 0)),
                    "bnybnje": float(raw_context.annual.get("bnybnje", 0)),
                    "bntczfje": float(raw_context.annual.get("bntczfje", 0)),
                    "bndezfje": float(raw_context.annual.get("bndezfje", 0)),
                }
                print(f"\n[SQL-FETCH] 转换后 yb_dyxxnd:", flush=True)
                for k, v in result.yb_dyxxnd.items():
                    print(f"[SQL-FETCH]   {k}: {v}", flush=True)

            # 4. yb_dyxxzy: 住院信息表
            if raw_context.admission:
                result.yb_dyxxzy = {
                    "djh": raw_context.admission.get("djh", ""),
                    "fynd": raw_context.admission.get("fynd", ""),
                    "zqxh": raw_context.admission.get("zqxh", ""),
                    "bcqfje": float(raw_context.admission.get("bcqfje", 0)),
                    "bcybnje": float(raw_context.admission.get("bcybnje", 0)),
                }
                print(f"\n[SQL-FETCH] 转换后 yb_dyxxzy:", flush=True)
                for k, v in result.yb_dyxxzy.items():
                    print(f"[SQL-FETCH]   {k}: {v}", flush=True)

            # 5. yb_brdjxx: 患者登记表
            if raw_context.patient:
                result.yb_brdjxx = {
                    "djh": raw_context.patient.get("djh", ""),
                    "fund_type": raw_context.patient.get("fund_type", ""),
                    "PER_TYPE": raw_context.patient.get("PER_TYPE", ""),
                    "yllb": raw_context.patient.get("yllb", ""),
                }
                print(f"\n[SQL-FETCH] 转换后 yb_brdjxx:", flush=True)
                for k, v in result.yb_brdjxx.items():
                    print(f"[SQL-FETCH]   {k}: {v}", flush=True)

            print(f"\n[SQL-FETCH] ====== 查询完成 ======\n", flush=True)
            return result

        except Exception as e:
            logger.exception(f"Failed to fetch SQL data for settlement_id={settlement_id}")
            raise

    def _record_sql_event(
        self,
        query_name: str,
        settlement_id: str = "",
        sql_summary: str = "",
        sql_text: str = "",
        params: dict | None = None,
        result_fields: list | None = None,
        result_sample: dict | None = None,
        row_count: int = 0,
        duration_ms: float = 0,
        status: str = "completed",
        error_message: str | None = None,
    ) -> None:
        """记录 SQL 查询事件（静默失败不影响主流程）"""
        try:
            from src.runtime.infra_event.recorder import record_sql_query
            record_sql_query(
                query_name=query_name,
                settlement_id=settlement_id,
                sql_summary=sql_summary,
                sql_text=sql_text,
                params=params,
                result_fields=result_fields,
                result_sample=result_sample,
                row_count=row_count,
                duration_ms=duration_ms,
                status=status,
                error_message=error_message,
            )
        except Exception:
            pass

    async def fetch_treatment(self, settlement_id: str) -> dict[str, Any]:
        """
        查询待遇分解表

        Args:
            settlement_id: 结算ID

        Returns:
            待遇分解数据
        """
        try:
            raw_context = self.client.get_case_context_raw(settlement_id=settlement_id)
            if raw_context.treatment:
                return {
                    "djh": raw_context.treatment.get("djh", ""),
                    "bdfyzje": float(raw_context.treatment.get("bdfyzje", 0)),
                    "bdybnzje": float(raw_context.treatment.get("bdybnzje", 0)),
                    "bdtczfje": float(raw_context.treatment.get("bdtczfje", 0)),
                    "bdtczf": float(raw_context.treatment.get("bdtczf", 0)),
                    "bddegwyzfje": float(raw_context.treatment.get("bddegwyzfje", 0)),
                    "bddegwyzf": float(raw_context.treatment.get("bddegwyzf", 0)),
                    "bdgryf": float(raw_context.treatment.get("bdgryf", 0)),
                }
            return {}
        except Exception as e:
            logger.exception(f"Failed to fetch treatment for settlement_id={settlement_id}")
            raise

    async def fetch_fee_details(self, settlement_id: str) -> list[dict[str, Any]]:
        """
        查询费用明细表

        Args:
            settlement_id: 结算ID

        Returns:
            费用明细列表
        """
        try:
            raw_context = self.client.get_case_context_raw(settlement_id=settlement_id)
            if raw_context.fee_details:
                return [
                    {
                        "djh": item.get("djh", ""),
                        "xh": item.get("xh", ""),
                        "xmdm": item.get("xmdm", ""),
                        "xmmc": item.get("xmmc", ""),
                        "sfxmdj": item.get("sfxmdj", ""),
                        "zje": float(item.get("zje", 0)),
                        "ybnje": float(item.get("ybnje", 0)),
                        "ybwje": float(item.get("ybwje", 0)),
                        "txbz": item.get("txbz", ""),
                        "SP_SCALE": float(item.get("SP_SCALE", 0)),
                        "MEDIC_L": float(item.get("MEDIC_L", 0)),
                    }
                    for item in raw_context.fee_details
                ]
            return []
        except Exception as e:
            logger.exception(f"Failed to fetch fee details for settlement_id={settlement_id}")
            raise

    async def fetch_annual(self, settlement_id: str) -> dict[str, Any]:
        """
        查询年度累计表

        Args:
            settlement_id: 结算ID

        Returns:
            年度累计数据
        """
        try:
            raw_context = self.client.get_case_context_raw(settlement_id=settlement_id)
            if raw_context.annual:
                return {
                    "djh": raw_context.annual.get("djh", ""),
                    "fynd": raw_context.annual.get("fynd", ""),
                    "bnzqslj": int(raw_context.annual.get("bnzqslj", 0)),
                    "bnybnje": float(raw_context.annual.get("bnybnje", 0)),
                    "bntczfje": float(raw_context.annual.get("bntczfje", 0)),
                    "bndezfje": float(raw_context.annual.get("bndezfje", 0)),
                }
            return {}
        except Exception as e:
            logger.exception(f"Failed to fetch annual for settlement_id={settlement_id}")
            raise

    async def fetch_admission(self, settlement_id: str) -> dict[str, Any]:
        """
        查询住院信息表

        Args:
            settlement_id: 结算ID

        Returns:
            住院信息数据
        """
        try:
            raw_context = self.client.get_case_context_raw(settlement_id=settlement_id)
            if raw_context.admission:
                return {
                    "djh": raw_context.admission.get("djh", ""),
                    "fynd": raw_context.admission.get("fynd", ""),
                    "zqxh": raw_context.admission.get("zqxh", ""),
                    "bcqfje": float(raw_context.admission.get("bcqfje", 0)),
                    "bcybnje": float(raw_context.admission.get("bcybnje", 0)),
                }
            return {}
        except Exception as e:
            logger.exception(f"Failed to fetch admission for settlement_id={settlement_id}")
            raise

    async def fetch_patient(self, settlement_id: str) -> dict[str, Any]:
        """
        查询患者登记表

        Args:
            settlement_id: 结算ID

        Returns:
            患者登记数据
        """
        try:
            raw_context = self.client.get_case_context_raw(settlement_id=settlement_id)
            if raw_context.patient:
                return {
                    "djh": raw_context.patient.get("djh", ""),
                    "fund_type": raw_context.patient.get("fund_type", ""),
                    "PER_TYPE": raw_context.patient.get("PER_TYPE", ""),
                    "yllb": raw_context.patient.get("yllb", ""),
                }
            return {}
        except Exception as e:
            logger.exception(f"Failed to fetch patient for settlement_id={settlement_id}")
            raise
