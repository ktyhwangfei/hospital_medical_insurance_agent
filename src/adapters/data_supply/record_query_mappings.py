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
    "op_no_right_reason": "PN_NoRightReason",  # 无待遇原因码（'4'/'5' 实证全额自费，决策记录 D15）
    "op_id_card": "P_IDNo",
    "op_card_ic": "P_ICNo",
    "op_card_no": "P_CardNo",
    # 原交易起付线/年度累计（Q4 退费结算架构核验事实）
    "op_first_pay": "T_FirstPay",
    "op_year": "TB_Year",
    "op_year_times": "TB_MZTimes",
    # ── Issue #78 费用分解补充列（o_Trade）。候选映射，待黄金样本确认（设计 §16 P0）──
    "op_fund_type": "P_FundType",  # 险种代码（职工/居民码表待确认）
    "op_cure_type": "T_CureType",  # 医疗类别代码（普通门诊/门特码表待确认）
    "op_person_type": "PN_PersonType",  # 人员类别代码
    "op_birthday": "P_Birthday",  # 出生日期（仅内核计算年龄档，结果不外泄原文）
    "op_hosp_code": "T_HospCode",  # 费用发生机构代码
    "op_prior_fee_in": "TB_FeeIn",  # 年度医保内费用累计（交易前口径，实证见决策记录 D3）
    "op_prior_big_pay": "TB_BigPay",  # 年度大额累计支付（交易前口径，实证见决策记录 D4）
    # 交易后累计（TA_ 列）：仅用于逐交易增量恒等式自证（TA−TB==T，阶段 E），不作金额输入
    "op_after_fee_in": "TA_FeeIn",  # 年度医保内费用累计（交易后口径，恒等式自证用）
    "op_after_big_pay": "TA_BigPay",  # 年度大额累计支付（交易后口径，恒等式自证用）
    "op_official": "P_Official",  # 公务员待遇标识（字典 flid=150：0=享受 1=不享受）
    "op_official_code": "P_OfficialCode",  # 公疗待遇类别码（取值 '2'/'3' 语义待确认，决策记录 D6）
    "op_jc_level": "P_JCLevel",  # 军残等级候选列（0=无，1-4/5-6 档，决策记录 D7）
    "op_fee_out": "T_FeeOut",
    "op_self_pay_2": "T_SelfPay2",
    "op_big_pay": "T_BigPay",
    "op_big_self_pay": "T_BigSelfPay",
    "op_beyond_big": "T_BeyondBig",
    "op_bc_pay": "T_BCPay",
    "op_jc_pay": "T_JCPay",
    "op_official_pay": "T_OfficalPay",
    "op_self_pay_1": "T_SelfPay1",
    "op_self_pay_all": "T_SelfPayAll",
    "op_person_count_pay": "T_PersonCountPay",
    "op_cash_pay": "T_CashPay",
    # ── Issue #80 居民扩展渠道列（o_Trade）：大病保险支付/民政救助支付观测值 ──
    "op_bigill_pay": "T_BigillPay",  # 大病保险支付（居民门诊大额封顶后渠道，240914 组实证）
    "op_civil_pay": "NT_CivilPay",  # 民政救助支付（国家平台列；5975/6969 实证，8000 年度封顶）
    "op_retire_officer_pay": "RETIRE_OFFICER_PAY",
    "op_retire_officer_flag": "RETIRE_OFFICER_FLAG",
    # ── Issue #78 门诊交易费用明细（o_FeeItem）。候选映射，待黄金样本确认（设计 §16 P0）──
    "opf_line_id": "ItemId",  # 行键候选
    "opf_item_name": "ItemName",
    "opf_trade_no": "T_TradeNo",
    "opf_item_type": "ItemType",  # 0=药品；其余取值语义待确认
    "opf_item_code": "ItemCode",
    "opf_fee_type": "FeeType",
    "opf_unit_price": "UnitPrice",
    "opf_count": "Count",
    "opf_fee": "Fee",
    "opf_fee_in": "FeeIn",
    "opf_fee_out": "FeeOut",
    "opf_self_pay_2": "SelfPay2",
    "opf_medic_l": "MEDIC_L",  # 明细行实际先行自付比例（>0 时为结算事实，决策记录 D18）
    "opf_sp_scale": "SP_SCALE",  # 明细行结算时限价（>0 时为结算事实，决策记录 D17）
    # 费用发生日期列：实测 o_FeeItem 无独立发生日期列（2026-09-28 真实库 schema 核实），
    # 置空 = 该列不进入 SELECT，组装层降级用交易日期并留痕
    "opf_fee_date": "",
    # ── Issue #78 药品目录（yb_ypzdml）。列名已经真实库 schema 核实（2026-09-28）──
    "cat_drug_special_marker": "tsbyybz",
    "cat_svc_special_marker": "tsbbz",
    "cat_drug_code": "ypbm",
    "cat_drug_effective": "sxrq",
    "cat_drug_expiry": "jzrq",
    "cat_drug_sflb": "sflb",
    "cat_drug_self_pay_ratio": "zfbl",  # 原自付比例列
    "cat_drug_a_ypbs": "A_ypbs",  # 集采标识（实测为大写 A_ 前缀）
    "cat_drug_a_mzxj": "A_mzxj",  # 门诊限价（A_zyxj 住院限价本流程不使用，不映射）
    "cat_drug_a_xbbl": "A_xbbl",  # 超限价自付比例：增量/最终语义未确认，保留原值不编码公式
    "cat_drug_ypfl": "ypfl",  # 药品分类（16/6 自制剂候选）
    "cat_drug_bzjg": "bzjg",  # 自制剂标准价格
    # 自制剂所属机构列：实测 yb_ypzdml 无此列（2026-09-28），置空 → 组装层按 None 处理
    "cat_drug_preparation_hospital": "",
    # ── Issue #78 诊疗/服务设施目录（yb_xzzlfwxm）。列名已经真实库 schema 核实 ──
    "cat_svc_code": "xmbm",
    "cat_svc_effective": "sxrq",
    "cat_svc_expiry": "jzrq",
    "cat_svc_sfxmdj": "sfxmdj",  # 收费项目等级：1 无自付/2 有自付/3 全自付
    "cat_svc_self_pay_ratio": "zfbl",  # 自付比例列
    # 单价限额列：xb（2026-09-28 schema 核实漏报；2026-10-13 复核确认存在，561 行 xb>0，
    # 含医事服务费限额 40/60——Issue #80 居民医事服务费通道分解依赖）
    "cat_svc_unit_price_limit": "xb",
    # ── Issue #78 机构表（m_institution）。连接键已经真实库 schema 核实（2026-09-28）──
    "ins_code": "H_CODE",
    "ins_h_level": "H_LEVEL",
    "ins_h_type": "H_TYPE",  # 医院类型（字典 k80：04=社区卫生站 06=村卫生室，决策记录 D9）
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
    "outpatient_trade_fee_table",
    "inpatient_fee_table",
    "outpatient_fee_table",
    "registration_table",
    "drug_catalog_table",
    "service_catalog_table",
    "material_catalog_table",
    "institution_table",
)


class RecordQueryMapping(BaseModel):
    """单数据源的记录查询映射。columns 支持部分覆盖（与默认合并）。"""

    model_config = ConfigDict(frozen=True)

    dialect: RecordQueryDialect = RecordQueryDialect.MSSQL
    inpatient_settlement_table: str = "dbo.yb_zyjyxx"
    outpatient_settlement_table: str = "dbo.yb_mzjyxx"
    outpatient_trade_table: str = "dbo.o_Trade"
    # Issue #78 费用分解：门诊交易明细表（候选映射，待黄金样本确认，设计 §16 P0）
    outpatient_trade_fee_table: str = "dbo.o_FeeItem"
    inpatient_fee_table: str = "dbo.yb_zyfymx"
    outpatient_fee_table: str = "dbo.yb_mzfymx"
    registration_table: str = "dbo.yb_brdjxx"
    # Issue #78 费用分解：目录与机构表（候选映射，待黄金样本确认，设计 §16 P0/P1）
    drug_catalog_table: str = "dbo.yb_ypzdml"
    service_catalog_table: str = "dbo.yb_xzzlfwxm"
    # 材料是否完整包含在 yb_xzzlfwxm 待确认，先同表（设计 §5.2）
    material_catalog_table: str = "dbo.yb_xzzlfwxm"
    institution_table: str = "dbo.m_institution"
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


def mapping_fingerprint(mapping: RecordQueryMapping) -> str:
    """映射内容哈希（映射版本标识）：方言 + 全部表名 + 合并后列映射的 sha256。"""
    import hashlib
    import json

    payload = {
        "dialect": mapping.dialect.value,
        "tables": {t: getattr(mapping, t) for t in _TABLES},
        "columns": mapping.resolved_columns(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
