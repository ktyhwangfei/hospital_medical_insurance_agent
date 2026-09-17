"""记录查询映射：逻辑查询 → 各院区物理表/列的声明式映射（产品化多院扩展点）。

背景（docs/reviews/2026-09-16-tool69-real-capability-vs-4-questions.md §6.4）：
退费/费用明细/待遇叠加/人员定位四类记录查询曾硬编码单一前置机 schema（bjybdb），
换医院即需改代码。本映射层把表名/列名外置为可注册配置：
- 默认映射 = 当前测试基线 schema（bjybdb 形态）；
- 各院区接入 = 向 PolicyMetaStore 登记覆盖映射（scripts/set_record_query_mapping.py），
  工具代码零改动（#27 数据供给分档的记录查询侧配套）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecordQueryDialect(StrEnum):
    """SQL 方言：决定标识符引用符。二档 PG 落地视图用 postgresql。"""

    MSSQL = "mssql"
    POSTGRESQL = "postgresql"


# 逻辑列名 → 默认物理列（bjybdb 基线）。院区覆盖时只需提供差异列。
DEFAULT_COLUMNS: dict[str, str] = {
    # 住院结算表（yb_zyjyxx）
    "ip_djh": "djh",
    "ip_jylsh": "jylsh",
    "ip_jyrq": "jyrq",
    "ip_zje": "zje",
    "ip_tflydjh": "tflydjh",
    "ip_big_ill_pay": "BIG_ILL_PAY",
    "ip_civil_in": "CIVIL_IN",
    "ip_db_pay_true": "DB_PAY_TRUE",
    "ip_maf_pay_true": "MAF_PAY_TRUE",
    "ip_tsbybn": "tsbybn",
    "ip_tsbybw": "tsbybw",
    # 门诊医保结算表（yb_mzjyxx）
    "op_set_djh": "djh",
    "op_set_jylsh": "jylsh",
    # HIS 门诊交易表（o_Trade）
    "op_trade_no": "T_TradeNo",
    "op_trade_date": "T_TradeDate",
    "op_fee_all": "T_FeeAll",
    "op_fee_in": "T_FeeIn",
    "op_fund_pay": "T_FundPay",
    "op_has_refundmented": "T_HasRefundmented",
    "op_ref_original_no": "TR_OraginalTradeNo",
    "op_ref_trade_no": "TR_RefundmentTradeNo",
    "op_partial_return": "T_PartialReturnFlag",
    "op_reversal_original_no": "T_OraginalTradeNo",
    "op_id_card": "P_IDNo",
    "op_card_ic": "P_ICNo",
    "op_card_no": "P_CardNo",
    # 原交易起付线/年度累计（Q4 退费结算架构核验事实）
    "op_first_pay": "T_FirstPay",
    "op_year": "TB_Year",
    "op_year_times": "TB_MZTimes",
    # 病人登记表（yb_brdjxx）
    "reg_djh": "djh",
    "reg_id_card": "sfz",
    "reg_card_no": "kh",
    "reg_admit_date": "ryrq",
    "reg_discharge_date": "cyrq",
    "reg_care_type": "yllb",
    "reg_spec1": "tsb1",
    "reg_spec2": "tsb2",
    "reg_spec3": "tsb3",
    "reg_low_income": "dbzbs",
    "reg_civil_type": "CIVIL_TYPE",
    "reg_person_type": "rylx",
    # 费用明细（yb_zyfymx / yb_mzfymx 共用逻辑列）
    "fee_seq": "xh",
    "fee_item_code": "xmdm",
    "fee_item_name": "xmmc",
    "fee_nation_code": "NATION_CODE",
    "fee_category": "sflb",
    "fee_qty": "sl",
    "fee_price": "dj",
    "fee_total": "zje",
    "fee_inner": "ybnje",
    "fee_outer": "ybwje",
    "fee_pre_self": "txfy",
    "fee_indiv_first": "grziftw",
    "fee_date": "fsrq",
}

_TABLES = (
    "inpatient_settlement_table",
    "outpatient_settlement_table",
    "outpatient_trade_table",
    "inpatient_fee_table",
    "outpatient_fee_table",
    "registration_table",
)


class RecordQueryMapping(BaseModel):
    """单数据源的记录查询映射。columns 支持部分覆盖（与默认合并）。"""

    model_config = ConfigDict(frozen=True)

    dialect: RecordQueryDialect = RecordQueryDialect.MSSQL
    inpatient_settlement_table: str = "dbo.yb_zyjyxx"
    outpatient_settlement_table: str = "dbo.yb_mzjyxx"
    outpatient_trade_table: str = "dbo.o_Trade"
    inpatient_fee_table: str = "dbo.yb_zyfymx"
    outpatient_fee_table: str = "dbo.yb_mzfymx"
    registration_table: str = "dbo.yb_brdjxx"
    columns: dict[str, str] = Field(default_factory=dict)

    @field_validator(*_TABLES)
    @classmethod
    def _non_empty_table(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("物理表名不能为空")
        return value

    def resolved_columns(self) -> dict[str, str]:
        """默认列与覆盖列合并后的完整映射。"""
        return {**DEFAULT_COLUMNS, **self.columns}

    def column(self, key: str) -> str:
        return self.resolved_columns()[key]

    def quote(self, identifier: str) -> str:
        """按方言引用标识符；已含分隔符的表名逐段引用。"""
        if self.dialect == RecordQueryDialect.POSTGRESQL:
            return ".".join(f'"{part}"' for part in identifier.split("."))
        return ".".join(f"[{part}]" for part in identifier.split("."))


DEFAULT_RECORD_QUERY_MAPPING = RecordQueryMapping()
