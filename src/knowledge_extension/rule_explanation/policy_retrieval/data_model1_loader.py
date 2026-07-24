"""
数据模型1加载器 - 将政策规则数据加载到Milvus policy_rules集合

支持两种数据源:
  1. policy_active_rules.xlsx - 已抽取的结构化政策规则(13条)
  2. 通用格式Excel - 列名与policy_rules schema字段名一致

用法:
    # 从policy_active_rules加载
    python -m knowledge_extension.rule_explanation.policy_retrieval.data_model1_loader \\
      --source active_rules \\
      --excel-path ./raw/policy_active_rules.xlsx \\
      --drop-existing

    # 从通用格式加载
    python -m knowledge_extension.rule_explanation.policy_retrieval.data_model1_loader \\
      --source generic \\
      --excel-path ./raw/policy_rules_data.xlsx
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from pymilvus import Collection

from .embedding_provider import get_embedding_provider
from .policy_rules_schema import POLICY_RULES_COLLECTION, connect_milvus, create_policy_rules_collection
from .utils import parse_json_like, safe_str

# ============================================================
# 值域标准化映射
# ============================================================

PSN_TYPE_MAPPING: dict[str, str] = {
    "elderly": "退休",
    "retiree": "退休",
    "working_age": "在职",
    "adult": "在职",
    "student_child": "学生儿童",
    "disabled": "残疾",
    "poor": "困难人群",
    "urban_rural_difficult": "困难人群",
    "urban_and_rural_residents": "城乡居民",
    "all": "全部",
}

HOSP_LEVEL_MAPPING: dict[str, str] = {
    "level_1": "一级医院",
    "level_2": "二级医院",
    "level_3": "三级医院",
    "level1_and_below": "一级医院",
    "level1": "一级医院",
    "level2": "二级医院",
    "level3": "三级医院",
    "primary": "一级及以下",
    "secondary": "二级",
    "tertiary": "三级",
}

RULE_TYPE_MAPPING: dict[str, str] = {
    "deductible": "起付线",
    "payment_ratio": "支付比例",
    "cap": "封顶线",
    "formula": "计算公式",
    "inclusion": "纳入范围",
    "exclusion": "排除范围",
}

MED_TYPE_MAPPING: dict[str, str] = {
    "inpatient": "住院-普通住院",
    "outpatient": "门诊-普通门急诊",
    "major_disease_insurance": "住院-大病保险",
}

INSURANCE_TYPE_MAPPING: dict[str, str] = {
    "urban_rural_resident": "城乡居民基本医疗保险",
    "employee": "城镇职工基本医疗保险",
    "urban_and_rural_residents": "城乡居民基本医疗保险",
    "urban_rural_difficult": "城乡居民基本医疗保险",
}


def standardize_psn_type(population_value: Any) -> str:
    """人群标签标准化:
    - 列表 ["elderly","working_age"] → "退休/在职"
    - 字符串 "student_child" → "学生儿童"
    """
    if population_value is None:
        return "全部"
    if isinstance(population_value, list):
        standardized: list[str] = []
        for p in population_value:
            s = PSN_TYPE_MAPPING.get(str(p).strip(), str(p).strip())
            if s not in standardized:
                standardized.append(s)
        return "/".join(standardized) if standardized else "全部"
    text = str(population_value).strip()
    return PSN_TYPE_MAPPING.get(text, text)


def standardize_hosp_level(level_key: str) -> str:
    """医院等级标准化: level_1 → 一级医院"""
    key = str(level_key).strip()
    return HOSP_LEVEL_MAPPING.get(key, key)


def standardize_rule_type(fact_type: str) -> str:
    """规则类型标准化: deductible → 起付线"""
    key = str(fact_type).strip()
    return RULE_TYPE_MAPPING.get(key, key)


def standardize_med_type(service_type_value: Any) -> str:
    """医疗类别标准化: inpatient → 住院-普通住院"""
    if service_type_value is None:
        return "住院-普通住院"
    text = str(service_type_value).strip()
    return MED_TYPE_MAPPING.get(text, text)


def standardize_insurance_type(policy_title: str, subject_dict: dict[str, Any]) -> str:
    """从政策标题和subject推断险种类别"""
    title = safe_str(policy_title)
    if "城镇职工" in title or "职工基本医疗保险" in title:
        return "城镇职工基本医疗保险"
    if "城乡居民" in title or "居民医保" in title:
        return "城乡居民基本医疗保险"
    # 从subject中的population推断
    pop = subject_dict.get("population", "")
    if isinstance(pop, str):
        ins = INSURANCE_TYPE_MAPPING.get(pop)
        if ins:
            return ins
    return "城乡居民基本医疗保险"


def standardize_admission_order(conditions: list[dict[str, Any]]) -> str:
    """从conditions中提取并标准化住院次数"""
    for cond in conditions or []:
        field = str(cond.get("field", ""))
        if field == "admission_order":
            value = cond.get("value")
            if value == 1:
                return "首次"
            if isinstance(value, (int, float)) and value >= 2:
                return "二次及以上"
            op = str(cond.get("operator", ""))
            if op in (">=", ">") or str(value) in ("2", ">=2"):
                return "二次及以上"
    return ""


def standardize_amount_band(conditions: list[dict[str, Any]]) -> str:
    """从conditions中提取金额分段描述"""
    for cond in conditions or []:
        field = str(cond.get("field", ""))
        if field in ("personal_payment", "amount"):
            operator = cond.get("operator", "")
            value = cond.get("value", "")
            return f"{operator}{value}"
    return ""


def extract_rule_amount(
    fact_type: str,
    value: Any,
    value_map_entry: Any = None,
) -> str:
    """根据规则类型提取金额/比例值"""
    if value_map_entry is not None:
        if isinstance(value_map_entry, dict):
            if "amount" in value_map_entry:
                return str(value_map_entry["amount"])
            if "ratio" in value_map_entry:
                r = value_map_entry["ratio"]
                if isinstance(r, (int, float)):
                    return f"{float(r) * 100:.0f}%"
                return str(r)
        # 标量值
        if fact_type == "payment_ratio":
            r = float(value_map_entry)
            return f"{r * 100:.0f}%"
        return str(value_map_entry)

    if value is None:
        return ""

    if isinstance(value, dict):
        if "amount" in value:
            return str(value["amount"])
        if "ratio" in value:
            r = value["ratio"]
            if isinstance(r, (int, float)):
                return f"{float(r) * 100:.0f}%"
            return str(r)
        return str(value)

    if fact_type == "cap":
        return str(value)

    return str(value)


def build_rule_value(
    fact_type: str,
    value: Any,
    value_map_entry: Any = None,
    formula: dict[str, Any] | None = None,
) -> str:
    """构建规则值(JSON字符串)"""
    if formula is not None:
        return json.dumps(formula, ensure_ascii=False)
    if value_map_entry is not None:
        if isinstance(value_map_entry, dict):
            return json.dumps(value_map_entry, ensure_ascii=False)
        return str(value_map_entry)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if value is not None and not (isinstance(value, float) and pd.isna(value)):
        return str(value)
    return ""


def build_embedding_text(entity: dict[str, Any]) -> str:
    """构建用于向量化的拼接文本"""
    parts: list[str] = []
    pairs = [
        ("规则类型", entity.get("rule_type", "")),
        ("险种", entity.get("insu_type", "")),
        ("人群", entity.get("psn_type", "")),
        ("医疗类别", entity.get("med_type", "")),
        ("医院等级", entity.get("hosp_lv", "")),
        ("住院次数", entity.get("admission_order", "")),
        ("结算方式", entity.get("setl_type", "")),
        ("时间周期", entity.get("time_period", "")),
        ("金额分段", entity.get("amount_band", "")),
        ("规则值", entity.get("rule_value", "")),
    ]
    for label, val in pairs:
        if val:
            parts.append(f"{label}：{val}")
    source = entity.get("source_text", "")
    if source:
        parts.append(f"政策原文：{source}")
    return " | ".join(parts) if parts else ""


def _generate_rule_id(fact_global_id: str, suffix: str = "") -> str:
    """生成规则ID"""
    base = fact_global_id or f"rule_{abs(hash(fact_global_id)) % 10_000_000}"
    return f"{base}_{suffix}" if suffix else base


def _parse_value_map(value_map_json: Any) -> dict[str, Any] | None:
    """解析value_map_json，支持简单dict和raw_value_map嵌套格式"""
    parsed = parse_json_like(value_map_json)
    if parsed is None:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _flatten_raw_value_map(raw_map: dict[str, Any]) -> list[dict[str, Any]]:
    """将raw_value_map嵌套格式展开为 [{level_key, value}, ...]"""
    entries = raw_map.get("raw_value_map", [])
    if not isinstance(entries, list):
        return []
    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sub_conditions = entry.get("sub_conditions", [])
        level_value: str | None = None
        if isinstance(sub_conditions, list):
            for sc in sub_conditions:
                if isinstance(sc, dict) and sc.get("field") == "hospital_level":
                    level_value = sc.get("value")
                    break
        if level_value is None:
            condition = entry.get("condition", {})
            if isinstance(condition, dict) and condition.get("field") == "hospital_level":
                level_value = condition.get("value")
        result.append({
            "level_key": level_value,
            "value": entry.get("value", entry),
        })
    return result


def parse_subject(subject_json: Any) -> dict[str, Any]:
    """安全解析subject_json"""
    parsed = parse_json_like(subject_json, default={})
    return parsed if isinstance(parsed, dict) else {}


def parse_conditions(conditions_json: Any) -> list[dict[str, Any]]:
    """安全解析conditions_json"""
    parsed = parse_json_like(conditions_json, default=[])
    return parsed if isinstance(parsed, list) else []


def _build_policy_id(policy_title: str, policy_doc_no: str) -> str:
    """构建短policy_id"""
    # 尽量从标题中提取政策文号
    if policy_doc_no and policy_doc_no != "nan":
        return safe_str(policy_doc_no)
    # 取标题前20字作为ID
    title = safe_str(policy_title)
    return title[:20] if title else ""


# ============================================================
# DataModel1Loader
# ============================================================


class DataModel1Loader:
    """数据模型1加载器 - 将政策规则数据加载到Milvus policy_rules集合"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: str = "19530",
        embedding_kind: str = "sentence_transformer",
    ):
        self.host = host
        self.port = port
        self.provider = get_embedding_provider(embedding_kind)
        connect_milvus(host=host, port=port)

    def load_from_active_rules(
        self,
        excel_path: str | Path,
        drop_existing: bool = False,
    ) -> int:
        """
        从policy_active_rules.xlsx加载政策规则数据.

        policy_active_rules.xlsx包含13条已抽取的结构化政策规则,
        包含subject_json, conditions_json, value_map_json等字段.

        Args:
            excel_path: Excel文件路径
            drop_existing: 是否删除现有集合重建

        Returns:
            写入Milvus的记录数
        """
        self._ensure_collection(drop_existing)
        df = pd.read_excel(excel_path)
        entities: list[dict[str, Any]] = []

        for idx, row in df.iterrows():
            try:
                row_entities = self._process_active_rules_row(row)
                entities.extend(row_entities)
            except Exception as e:
                print(f"  第{idx}行处理失败: {e}")
                continue

        if not entities:
            print("没有找到可写入的规则数据")
            return 0

        # 构建embedding_text并生成向量
        for entity in entities:
            entity["embedding_text"] = build_embedding_text(entity)

        texts = [e["embedding_text"] for e in entities]
        print(f"正在生成{len(texts)}条规则的embedding向量...")
        vectors = self.provider.encode(texts)

        for i, vec in enumerate(vectors):
            entities[i]["embedding"] = vec

        # 批量写入Milvus
        collection = Collection(POLICY_RULES_COLLECTION)
        self._batch_insert(collection, entities)
        count = collection.num_entities
        print(f"写入完成，共{count}条规则")

        return count

    def load_from_excel(
        self,
        excel_path: str | Path,
        drop_existing: bool = False,
    ) -> int:
        """
        从通用格式Excel加载政策规则数据.

        期望Excel列名与policy_rules schema字段名一致:
          rule_id, fact_id, policy_id, clause_id, source_text,
          insu_type, med_type, hosp_lv, psn_type, setl_type,
          payment_ratio, deductible_amount, cap_amount, time_period,
          admission_order, amount_band, priority, rule_type, rule_value

        Args:
            excel_path: Excel文件路径
            drop_existing: 是否删除现有集合重建

        Returns:
            写入Milvus的记录数
        """
        self._ensure_collection(drop_existing)
        df = pd.read_excel(excel_path)
        entities: list[dict[str, Any]] = []

        for _, row in df.iterrows():
            entity = self._process_generic_row(row)
            if entity:
                entities.append(entity)

        if not entities:
            print("没有找到可写入的规则数据")
            return 0

        # 构建embedding_text并生成向量
        for entity in entities:
            if not entity.get("embedding_text"):
                entity["embedding_text"] = build_embedding_text(entity)

        texts = [e["embedding_text"] for e in entities]
        print(f"正在生成{len(texts)}条规则的embedding向量...")
        vectors = self.provider.encode(texts)

        for i, vec in enumerate(vectors):
            entities[i]["embedding"] = vec

        # 批量写入Milvus
        collection = Collection(POLICY_RULES_COLLECTION)
        self._batch_insert(collection, entities)
        count = collection.num_entities
        print(f"写入完成，共{count}条规则")

        return count

    def _ensure_collection(self, drop_existing: bool) -> None:
        """确保policy_rules集合已创建"""
        create_policy_rules_collection(dim=self.provider.dim, drop_existing=drop_existing)

    def _process_active_rules_row(self, row: pd.Series) -> list[dict[str, Any]]:
        """
        处理policy_active_rules的一行，展开为0-N条规则实体.

        value_map展开规则:
        - 简单格式 {"level_1": 300, "level_2": 800, "level_3": 1300}
          → 每个等级一条规则
        - raw_value_map嵌套格式
          → 按sub_conditions中的hospital_level展开
        - formula类型 → 单条规则, rule_value存公式JSON
        - value_json非空且无value_map → 单条规则
        """
        fact_type = safe_str(row.get("fact_type", ""))
        fact_global_id = safe_str(row.get("fact_global_id", ""))
        source_fact_id = safe_str(row.get("source_fact_id", ""))
        policy_title = safe_str(row.get("policy_title", ""))
        policy_doc_no = safe_str(row.get("policy_doc_no", ""))
        evidence_text = safe_str(row.get("evidence_text", ""))
        raw_priority = row.get("priority_score")

        # 解析JSON字段
        subject = parse_subject(row.get("subject_json"))
        conditions = parse_conditions(row.get("conditions_json"))
        value_json = row.get("value_json")
        value_map = _parse_value_map(row.get("value_map_json"))
        formula = parse_json_like(row.get("formula_json"))

        # 标准化通用字段
        psn_type = standardize_psn_type(subject.get("population"))
        med_type = standardize_med_type(subject.get("service_type"))
        rule_type = standardize_rule_type(fact_type)
        insu_type = standardize_insurance_type(policy_title, subject)
        admission_order = standardize_admission_order(conditions)
        amount_band = standardize_amount_band(conditions)
        priority = str(raw_priority) if pd.notna(raw_priority) else ""
        policy_id = _build_policy_id(policy_title, policy_doc_no)

        # --- 公式类型: 单条 ---
        if formula is not None and isinstance(formula, dict):
            entity = self._build_base_entity(
                fact_global_id=fact_global_id,
                fact_id=source_fact_id,
                policy_id=policy_id,
                clause_id=policy_doc_no,
                source_text=evidence_text,
                insu_type=insu_type,
                med_type=med_type,
                hosp_lv="",
                psn_type=psn_type,
                setl_type="",
                time_period="",
                admission_order=admission_order,
                amount_band=amount_band,
                priority=priority,
                rule_type=rule_type,
            )
            entity["rule_value"] = json.dumps(formula, ensure_ascii=False)
            return [entity]

        # --- 有value_map: 按医院等级展开 ---
        if value_map is not None:
            return self._expand_value_map(
                fact_global_id=fact_global_id,
                fact_id=source_fact_id,
                policy_id=policy_id,
                clause_id=policy_doc_no,
                source_text=evidence_text,
                insu_type=insu_type,
                med_type=med_type,
                psn_type=psn_type,
                fact_type=fact_type,
                rule_type=rule_type,
                admission_order=admission_order,
                amount_band=amount_band,
                priority=priority,
                value_map=value_map,
            )

        # --- 单条(cap/payment_ratio等) ---
        rule_val = build_rule_value(fact_type, value_json)
        entity = self._build_base_entity(
            fact_global_id=fact_global_id,
            fact_id=source_fact_id,
            policy_id=policy_id,
            clause_id=policy_doc_no,
            source_text=evidence_text,
            insu_type=insu_type,
            med_type=med_type,
            hosp_lv="",
            psn_type=psn_type,
            setl_type="",
            time_period="",
            admission_order=admission_order,
            amount_band=amount_band,
            priority=priority,
            rule_type=rule_type,
        )
        entity["rule_value"] = rule_val
        # 按fact_type填充具体金额字段
        self._fill_amount_field(entity, fact_type, value_json)
        return [entity]

    def _expand_value_map(
        self,
        *,
        fact_global_id: str,
        fact_id: str,
        policy_id: str,
        clause_id: str,
        source_text: str,
        insu_type: str,
        med_type: str,
        psn_type: str,
        fact_type: str,
        rule_type: str,
        admission_order: str,
        amount_band: str,
        priority: str,
        value_map: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """将value_map展开为多条规则(每个医院等级一条)"""
        entities: list[dict[str, Any]] = []

        # 判断是否为raw_value_map嵌套格式
        if "raw_value_map" in value_map:
            entries = _flatten_raw_value_map(value_map)
        else:
            entries = [{"level_key": k, "value": v} for k, v in value_map.items()]

        for i, entry in enumerate(entries):
            level_key = entry.get("level_key", "")
            entry_value = entry.get("value", "")
            hosp_lv = standardize_hosp_level(level_key) if level_key else ""

            rule_val = build_rule_value(fact_type, None, entry_value)

            entity = self._build_base_entity(
                fact_global_id=fact_global_id,
                fact_id=fact_id,
                policy_id=policy_id,
                clause_id=clause_id,
                source_text=source_text,
                insu_type=insu_type,
                med_type=med_type,
                hosp_lv=hosp_lv,
                psn_type=psn_type,
                setl_type="",
                time_period="",
                admission_order=admission_order,
                amount_band=amount_band,
                priority=priority,
                rule_type=rule_type,
                suffix=str(i),
            )
            entity["rule_value"] = rule_val
            self._fill_amount_field(entity, fact_type, entry_value)
            entities.append(entity)

        return entities

    def _build_base_entity(
        self,
        *,
        fact_global_id: str,
        fact_id: str,
        policy_id: str,
        clause_id: str,
        source_text: str,
        insu_type: str,
        med_type: str,
        hosp_lv: str,
        psn_type: str,
        setl_type: str,
        time_period: str,
        admission_order: str,
        amount_band: str,
        priority: str,
        rule_type: str,
        suffix: str = "",
    ) -> dict[str, Any]:
        """构建基础实体字典(不含embedding_text和embedding)"""
        rule_id = _generate_rule_id(fact_global_id, suffix) if fact_global_id else ""
        return {
            "rule_id": rule_id,
            "fact_id": fact_id,
            "policy_id": policy_id,
            "clause_id": clause_id,
            "source_text": source_text[:4000] if source_text else "",
            "insu_type": insu_type,
            "med_type": med_type,
            "hosp_lv": hosp_lv,
            "psn_type": psn_type,
            "setl_type": setl_type,
            "payment_ratio": "",
            "deductible_amount": "",
            "cap_amount": "",
            "time_period": time_period,
            "admission_order": admission_order,
            "amount_band": amount_band,
            "priority": priority,
            "rule_type": rule_type,
            "rule_value": "",
            "embedding_text": "",
        }

    def _fill_amount_field(
        self,
        entity: dict[str, Any],
        fact_type: str,
        value: Any,
    ) -> None:
        """根据fact_type填充具体的金额/比例字段"""
        if fact_type == "deductible":
            entity["deductible_amount"] = extract_rule_amount(fact_type, None, value)
        elif fact_type == "payment_ratio":
            entity["payment_ratio"] = extract_rule_amount(fact_type, None, value)
        elif fact_type == "cap":
            entity["cap_amount"] = extract_rule_amount(fact_type, value)

    def _process_generic_row(self, row: pd.Series) -> dict[str, Any] | None:
        """处理通用格式的一行，列名需与schema字段一致"""
        entity: dict[str, Any] = {}
        for field in [
            "rule_id", "fact_id", "policy_id", "clause_id", "source_text",
            "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
            "payment_ratio", "deductible_amount", "cap_amount", "time_period",
            "admission_order", "amount_band", "priority", "rule_type", "rule_value",
        ]:
            val = row.get(field)
            if isinstance(val, str) or isinstance(val, (int, float)):
                entity[field] = safe_str(val) if field != "priority" else str(val)
            elif val is not None and not (isinstance(val, float) and pd.isna(val)):
                entity[field] = str(val)
            else:
                entity[field] = ""
        entity["embedding_text"] = ""
        # 如果rule_id为空则跳过
        if not entity.get("rule_id"):
            return None
        return entity

    def _batch_insert(self, collection: Collection, entities: list[dict[str, Any]], batch_size: int = 512) -> None:
        """批量写入Milvus"""
        if not entities:
            return
        for i in range(0, len(entities), batch_size):
            collection.insert(entities[i:i + batch_size])
        collection.flush()
        collection.load()


# ============================================================
# 命令行入口
# ============================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="数据模型1加载器 - 加载政策规则数据到Milvus policy_rules集合")
    parser.add_argument(
        "--source",
        choices=["active_rules", "generic"],
        default="active_rules",
        help="数据源类型: active_rules (policy_active_rules.xlsx) 或 generic (通用格式)",
    )
    parser.add_argument(
        "--excel-path",
        required=True,
        help="Excel数据文件路径",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Milvus主机地址 (默认: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        default="19530",
        help="Milvus端口 (默认: 19530)",
    )
    parser.add_argument(
        "--embedding-kind",
        default="sentence_transformer",
        choices=["sentence_transformer", "hash"],
        help="Embedding类型 (默认: sentence_transformer)",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="删除现有集合并重建",
    )
    args = parser.parse_args()

    loader = DataModel1Loader(
        host=args.host,
        port=args.port,
        embedding_kind=args.embedding_kind,
    )

    excel_path = Path(args.excel_path)
    if not excel_path.exists():
        print(f"错误: 文件不存在 - {excel_path}")
        return

    if args.source == "active_rules":
        count = loader.load_from_active_rules(excel_path, drop_existing=args.drop_existing)
    else:
        count = loader.load_from_excel(excel_path, drop_existing=args.drop_existing)

    print(f"加载完成，共写入{count}条规则")


if __name__ == "__main__":
    main()
