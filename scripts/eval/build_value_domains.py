"""Issue #78 值域配置生成器：bjyb 字典表 + 需求规格说明书码表 → value_domains.yaml。

数据来源（只读）：
- bjyb SQL Server 院内字典表 yb_zdfl（分类）/ yb_zdxm（代码项）；
- docs/specs/北京市医疗保障信息平台支付方式管理子系统用户需求规格说明书 - mz.docx
  尾部"码表说明"章节（表格145 险种类型 / 表格146 人员类别含在职退休归类 /
  表格149 医疗类别 / 表格151 支付类型），提取件：scripts/eval/issue78_docx_code_tables.json；
- 语义注册中心已确认的院内 P_FundType 解析（院内险种码表不在 yb_zdfl 中）。

产出：src/adapters/data_supply/value_domains.yaml
- 原始 code→name 映射逐字来自来源，不加工；
- 派生分组（在职/退休归类、社区机构判定、收费类别→自付档）单独标注
  status: candidate，签核前内核不得据此静默生效。

跑法：uv run python scripts/eval/build_value_domains.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402

OUT_PATH = PROJECT_ROOT / "src" / "adapters" / "data_supply" / "value_domains.yaml"
DOCX_TABLES_PATH = Path(__file__).parent / "issue78_docx_code_tables.json"

#: 院内字典表取数清单：flid → (域名, 用途说明)
DICT_DOMAINS = {
    "k10": ("item_type", "o_FeeItem.ItemType 项目类型"),
    "230": ("fee_category", "收费类别（yb_ypzdml.sflb / o_FeeItem.FeeType）"),
    "240": ("service_item_level", "收费项目等级（yb_xzzlfwxm.sfxmdj）"),
    "280": ("drug_class", "药品分类（yb_ypzdml.ypfl）"),
    "290": ("person_type", "医保参保人员类别（o_Trade.PN_PersonType）"),
    "300": ("cure_type", "医疗类别（o_Trade.T_CureType）"),
    "310": ("hospital_level", "医院等级（m_institution.H_LEVEL）"),
    "k40": ("reversal_flag", "红冲标志（o_Trade 冲正/退费相关列）"),
    "k80": ("hospital_type", "医院类型（m_institution.H_TYPE）"),
    "190": ("outpatient_special_flag", "普通门诊特殊标识"),
}


def _fetch_dict_domains(conn) -> dict:
    """yb_zdfl/yb_zdxm → {域名: {代码: 名称}}。sybz<>1 的停用项保留并标注。"""
    cur = conn.cursor()
    domains: dict[str, dict] = {}
    for flid, (name, desc) in DICT_DOMAINS.items():
        cur.execute("SELECT bm, mc, sybz FROM yb_zdxm WHERE flid=? ORDER BY bm", [flid])
        entries = {}
        disabled = {}
        for bm, mc, sybz in cur.fetchall():
            code = str(bm).strip()
            entries[code] = str(mc).strip()
            if sybz != 1:
                disabled[code] = True
        domain: dict = {
            "description": desc,
            "source": f"bjybdb.yb_zdxm flid={flid}",
            "values": entries,
        }
        if disabled:
            domain["disabled_codes"] = sorted(disabled)
        domains[name] = domain
    return domains


def _load_docx_tables() -> dict:
    return json.loads(DOCX_TABLES_PATH.read_text(encoding="utf-8"))


def _docx_code_name(rows: list[list[str]]) -> dict[str, str]:
    """docx 表格行 → {代码: 名称}（跳过表头与说明行，只取前两列）。"""
    out: dict[str, str] = {}
    for row in rows:
        if len(row) >= 2 and row[0].strip().isdigit():
            out[row[0].strip()] = row[1].strip()
    return out


def _docx_person_grouping(rows: list[list[str]]) -> dict[str, str]:
    """表格146 → {人员类别编码: 在职|退休}（第三列归类）。"""
    out: dict[str, str] = {}
    for row in rows:
        if len(row) >= 3 and row[0].strip().isdigit() and row[2].strip() in ("在职", "退休"):
            out[row[0].strip()] = row[2].strip()
    return out


def main() -> int:
    conn = get_semantic_data_source().open_connection("bjybdb")
    try:
        domains = _fetch_dict_domains(conn)
    finally:
        conn.close()

    docx = _load_docx_tables()

    # 险种：院内 o_Trade.P_FundType 码表不在 yb_zdfl，院内代码经语义注册中心确认；
    # 文档表格145 为国家平台三位代码，与院内代码不通用，仅存档备查
    domains["insurance_type_hospital"] = {
        "description": "院内险种（o_Trade.P_FundType），码表不在 yb_zdfl，经语义注册中心解析确认",
        "source": "语义注册中心码表（2026-09-28 实测解析）",
        "values": {
            "3": "城镇职工",
            "31": "离休统筹",
            "32": "公疗医照",
            "33": "征地超转",
            "80": "军休干部",
            "91": "城镇居民",
            "92": "城乡居民",
            "93": "城乡居民（学生儿童）",
            "999": "国家平台险种",
        },
    }
    domains["insurance_type_national"] = {
        "description": "险种类型（国家平台三位代码，文档表格145；与院内 P_FundType 代码不通用，仅存档）",
        "source": "需求规格说明书-mz.docx 码表说明 表格145",
        "values": _docx_code_name(docx["insurance_type_doc145"]),
    }
    domains["medical_category_national"] = {
        "description": "医疗类别（国家平台三位代码，文档表格149；与院内 T_CureType 代码不通用，仅存档）",
        "source": "需求规格说明书-mz.docx 码表说明 表格149",
        "values": _docx_code_name(docx["medical_category_doc149"]),
    }

    # 生产数据中出现但字典未覆盖的代码（如实记录，不猜测语义）
    unresolved = {
        "cure_type": {
            "description": "o_Trade.T_CureType 生产值中字典（flid=300）未覆盖的代码，语义待确认",
            "unresolved_codes": ["17", "18", "19"],
            "observed_counts": {"17": 96, "18": 94, "19": 281},
            "note": "字典 300 仅含 11/12/15/16/21/31/61/91；且 11/15 在字典中 sybz=0（停用标记），"
                    "生产仍在用——字典停用标记与生产使用不一致，需用户裁决",
        },
        "service_item_level": {
            "description": "yb_xzzlfwxm.sfxmdj 生产值中字典（flid=240）未覆盖的取值",
            "unresolved_codes": ["0", ""],
            "observed_counts": {"0": 6, "": 8230},
            "note": "空值与 '0' 均按未知处理（内核 SFXMDJ_EMPTY/SFXMDJ_UNKNOWN_VALUE 已 fail-closed）",
        },
    }

    # 派生分组（解释性内容，一律 candidate，签核前不得进内核静默生效）
    person_grouping = _docx_person_grouping(docx["person_type_doc146"])
    derived = {
        "person_employment_group": {
            "description": "人员类别 → 在职/退休 归类（决定起付 1800/1300 与比例档）",
            "source": "需求规格说明书 表格146 归类列",
            "status": "candidate",
            "values": person_grouping,
            "note": "院内 290 码表编码与文档 146 编码部分不一致（如院内 81=退休人员（1）"
                    "文档无此码）；未列入归类的院内代码按未知处理，不默认在职",
        },
        "item_type_to_catalog_kind": {
            "description": "o_FeeItem.ItemType → 目录类别（解锁非药品明细分解的关键映射）",
            "source": "院内字典 k10 名称直译",
            "status": "candidate",
            "values": {"0": "drug", "1": "service", "2": "service", "3": "material"},
            "note": "1=诊疗项目/2=服务设施 均查 yb_xzzlfwxm；3=耗材 查材料目录"
                    "（材料是否完整在 yb_xzzlfwxm 仍待确认）",
        },
        "community_institution_rule": {
            "description": "社区机构判定（社区 90% 比例档适用条件）",
            "source": "m_institution.H_TYPE（字典 k80）+ H_LEVEL（字典 310）实测推断",
            "status": "candidate",
            "values": {"community_h_types": ["04", "06"]},
            "note": "k80：04=社区卫生站、06=村卫生室；H_LEVEL=14 实测含义为「未评级」而非社区，"
                    "内核既有 14=社区 候选假设错误，以此为准（待签核）",
        },
        "fee_category_self_pay_group": {
            "description": "收费类别（230）→ 自付档（无自付/有自付/全自付）候选归组",
            "source": "字典 230 名称推断",
            "status": "candidate",
            "values": {
                "no_self_pay": "名称含「甲类」，或 0301 复方可报/0302 单方可报",
                "partial_self_pay": "名称含「乙类」",
                "full_self_pay": "名称含「其它类」",
            },
            "note": "纯名称推断，乙类实际先行自付比例以目录 zfbl 列为准；"
                    "草药「复方可报/单方可报」的门诊报销口径需用户确认",
        },
    }

    doc = {
        "meta": {
            "name": "Issue #78 值域配置（院内字典 + 需求规格说明书码表）",
            "generated_at": "2026-09-28",
            "generator": "scripts/eval/build_value_domains.py",
            "sources": [
                "bjybdb.yb_zdfl / yb_zdxm（院内字典，sybz=1 为启用）",
                "docs/specs/北京市医疗保障信息平台支付方式管理子系统用户需求规格说明书 - mz.docx 码表说明章节",
                "语义注册中心（院内 P_FundType 解析）",
            ],
            "discipline": "values 为来源逐字映射；derived 为解释性分组，status=candidate "
                          "签核前内核不得据此静默生效；unresolved 如实记录未覆盖代码",
        },
        "domains": domains,
        "unresolved": unresolved,
        "derived": derived,
    }
    OUT_PATH.write_text(
        yaml.dump(doc, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    print(f"写入 {OUT_PATH}")
    print(f"domains: {len(domains)} 个；derived: {len(derived)} 组；unresolved: {len(unresolved)} 项")
    for name, d in domains.items():
        print(f"  {name}: {len(d['values'])} 个代码")
    return 0


if __name__ == "__main__":
    sys.exit(main())
