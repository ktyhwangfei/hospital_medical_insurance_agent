"""
数据模型1导入器 - 将 Excel 中的语义元数据转化为语义层的 YAML 配置文件

用法:
    # 完整导入（生成 policy_fields.yaml + dictionaries/*.yaml + catalog.yaml）
    python -m src.semantic_layer.datamodel1_importer

    # 仅生成政策字段
    python -m src.semantic_layer.datamodel1_importer --only policy_fields

    # 仅生成字典
    python -m src.semantic_layer.datamodel1_importer --only dictionaries

    # 仅生成医保目录
    python -m src.semantic_layer.datamodel1_importer --only catalog

输入: raw/数据模型1.xlsx (3 sheets: 政策规则表, 字典, 医保目录)
输出:
    indicators/_from_datamodel1/policy_fields.yaml  — 19 个指标定义
    indicators/_from_datamodel1/catalog.yaml        — 医保目录分类
    indicators/dictionaries/insurance_type.yaml     — 险种字典
    indicators/dictionaries/medical_type.yaml       — 医疗类别字典
    indicators/dictionaries/hospital_level.yaml     — 医院等级字典
    indicators/dictionaries/person_type.yaml        — 人群标签字典
    indicators/dictionaries/settlement_type.yaml    — 结算方式字典
"""
import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

from src.config.semantic_layer import (
    AUTO_GENERATED_DIR,
    DATAMODEL1_PATH,
    DICTIONARIES_DIR,
)

logger = logging.getLogger(__name__)

# 配置日志输出
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class DataModel1Importer:
    """
    数据模型1导入器

    读取 raw/数据模型1.xlsx 的三个 Sheet，转化为语义层 YAML 配置。
    每个 Sheet 对应一个维度的元数据：
    - 政策规则表 → 指标定义注册表
    - 字典 → 标准化字典（按类别分组）
    - 医保目录 → 分类体系
    """

    # 政策规则表字段 → 指标分类的映射
    # 基于 19 个字段的语义角色分为四类
    FIELD_CATEGORY_MAP: dict[str, str] = {
        # 标识符 → meta（8个）
        "rule_id": "meta",
        "fact_id": "meta",
        "policy_id": "meta",
        "clause_id": "meta",
        "source_text": "meta",
        "priority": "meta",
        "rule_type": "meta",
        "rule_value": "meta",
        # 维度 → dimension（6个，有字典关联）
        "insu_type": "dimension",
        "med_type": "dimension",
        "hosp_lv": "dimension",
        "psn_type": "dimension",
        "setl_type": "dimension",
        "admission_order": "dimension",
        # 数值 → numeric（3个）
        "payment_ratio": "numeric",
        "deductible_amount": "numeric",
        "cap_amount": "numeric",
        # 条件 → condition（2个）
        "amount_band": "condition",
        "time_period": "condition",
    }

    # 字典 Sheet 的"类型"列值 → YAML 文件名的映射
    DICT_FILE_MAP: dict[str, str] = {
        "险种类别": "insurance_type.yaml",
        "医疗类别": "medical_type.yaml",
        "医疗机构等级": "hospital_level.yaml",
        "人群标签": "person_type.yaml",
        "结算方式": "settlement_type.yaml",
    }

    # 字典类别 → 各系统现有硬编码映射
    # 来源: knowledge_extension/.../data_model1_loader.py 和 semantic_mapping.py
    KNOWN_CROSS_MAPPINGS: dict[str, dict[str, dict[str, str]]] = {
        "人群标签": {
            "data_model1_loader": {
                "elderly": "退休人员",
                "retiree": "退休人员",
                "working_age": "在职职工",
                "adult": "在职职工",
                "student_child": "学生儿童",
                "disabled": "残疾人员",
                "poor": "困难人群",
                "urban_rural_difficult": "困难人群",
                "urban_and_rural_residents": "城乡居民",
                "all": "全部",
            },
            "semantic_mapper": {
                "adult": "在职职工",
                "student_child": "学生儿童",
            },
        },
        "医疗机构等级": {
            "data_model1_loader": {
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
            },
        },
        "险种类别": {
            "data_model1_loader": {
                "employee": "城镇职工基本医疗保险",
                "urban_rural_resident": "城乡居民基本医疗保险",
            },
        },
    }

    def __init__(self, excel_path: str | Path | None = None):
        """初始化导入器

        Args:
            excel_path: 数据模型1.xlsx 的路径，默认使用配置中的 DATAMODEL1_PATH
        """
        self.excel_path = Path(excel_path) if excel_path else Path(DATAMODEL1_PATH)

    # ============================================================
    # 公开接口
    # ============================================================

    def import_all(self) -> None:
        """执行完整导入：政策字段 + 字典 + 医保目录"""
        logger.info(f"开始从 {self.excel_path} 导入语义层元数据...")
        self._import_policy_fields()
        self._import_catalog()
        self._import_dictionaries()
        logger.info("导入完成！")

    def import_policy_fields_only(self) -> None:
        """仅导入政策规则表"""
        self._import_policy_fields()

    def import_dictionaries_only(self) -> None:
        """仅导入字典"""
        self._import_dictionaries()

    def import_catalog_only(self) -> None:
        """仅导入医保目录"""
        self._import_catalog()

    # ============================================================
    # 政策规则表 → policy_fields.yaml
    # ============================================================

    def _import_policy_fields(self) -> None:
        """
        从"政策规则表" Sheet 生成 policy_fields.yaml

        逻辑:
        - 读取每一行，提取 [字段名称, 字段中文名称, 加工类型, 是否嵌套, 说明, 字典]
        - 根据 FIELD_CATEGORY_MAP 确定 category
        - processing_type: "分词" 或 "raw"
        - is_nested: "是" → True, 其他 → False
        - dictionary_ref: 字典列的值（非空时）
        - 生成每个字段的语义标签
        """
        logger.info("正在导入政策规则表...")
        df = pd.read_excel(self.excel_path, sheet_name="政策规则表")
        indicators = []

        for _, row in df.iterrows():
            # 提取字段名称（对应 indicator_id）
            field_name = self._safe_str(row.get("字段名称"))
            if not field_name:
                continue

            # 确定分类
            category = self.FIELD_CATEGORY_MAP.get(field_name, "meta")

            # 提取字段中文名称
            name = self._safe_str(row.get("字段中文名称"), field_name)

            # 提取说明
            description = self._safe_str(row.get("说明"), "")

            # 提取词典引用
            dict_ref = self._safe_str(row.get("字典"))
            if dict_ref == "nan" or not dict_ref:
                dict_ref = None

            # 是否嵌套
            is_nested = self._safe_str(row.get("是否嵌套"), "").strip() == "是"

            # 加工类型
            raw_processing = self._safe_str(row.get("加工类型"), "")
            processing_type = "分词" if raw_processing == "分词" else "raw"

            # 推断值类型
            value_type = self._infer_value_type(field_name, category)

            # 推断单位
            unit = self._infer_unit(field_name)

            # 推断语义标签
            semantic_tags = self._infer_semantic_tags(field_name, category)

            # 组装指标定义
            indicator = {
                "indicator_id": field_name,
                "name": name,
                "description": description,
                "category": category,
                "value_type": value_type,
                "unit": unit,
                "processing_type": processing_type,
                "is_nested": is_nested,
                "dictionary_ref": dict_ref,
                "policy_field": field_name,
                "semantic_tags": semantic_tags,
            }

            # 维度指标默认作为标量过滤和嵌入字段
            if category == "dimension" and dict_ref:
                indicator["use_in_filter"] = True
                indicator["use_in_embedding"] = True
                indicator["embedding_template"] = f"{name}：{{value}}"

            indicators.append(indicator)

        # 组装输出结构
        output = {
            "generated_from": str(self.excel_path),
            "description": "数据模型1 政策规则表 → 指标定义（由 datamodel1_importer.py 自动生成）",
            "total_fields": len(indicators),
            "indicators": indicators,
        }

        # 写入 YAML
        output_dir = Path(AUTO_GENERATED_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "policy_fields.yaml"

        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"✓ 已生成 {output_path}（共 {len(indicators)} 个指标）")

    # ============================================================
    # 字典 Sheet → dictionaries/*.yaml
    # ============================================================

    def _import_dictionaries(self) -> None:
        """
        从"字典" Sheet 生成 dictionaries/*.yaml

        逻辑:
        - 按"类型"列分组（险种类别/医疗类别/医疗机构等级/人群标签/结算方式）
        - 每组生成一个 YAML 文件
        - 每条记录: [类型, 代码, 值, 同义词, 描述]
        - 同义词按 & 分隔
        - 附加 cross_system_mappings（从现有硬编码 dict 提取）
        """
        logger.info("正在导入字典...")
        df = pd.read_excel(self.excel_path, sheet_name="字典")

        # 按"类型"列分组
        groups = df.groupby("类型")

        dict_output_dir = Path(DICTIONARIES_DIR)
        dict_output_dir.mkdir(parents=True, exist_ok=True)

        for category, group_df in groups:
            # 确定输出文件名
            filename = self.DICT_FILE_MAP.get(category)
            if not filename:
                logger.warning(f"  跳过未知字典类别: {category}")
                continue

            entries = []
            for _, row in group_df.iterrows():
                # 处理同义词（& 分隔）
                synonyms_raw = self._safe_str(row.get("同义词"), "")
                if synonyms_raw and synonyms_raw != "nan":
                    synonyms = [s.strip() for s in synonyms_raw.split("&") if s.strip()]
                else:
                    synonyms = []

                # 处理描述
                desc = self._safe_str(row.get("描述"), "")
                if desc == "nan":
                    desc = ""

                # 处理代码
                code = self._safe_str(row.get("代码"))
                if code == "nan" or not code:
                    code = None

                entry = {
                    "standard_value": self._safe_str(row.get("值"), ""),
                    "synonyms": synonyms,
                    "description": desc,
                }
                if code:
                    entry["code"] = code

                entries.append(entry)

            # 提取跨系统映射
            cross_mappings = self._extract_existing_mappings(category)

            # 组装输出
            output = {
                "category": category,
                "description": f"数据模型1 字典 Sheet → {category} 标准化字典",
                "entries": entries,
            }
            if cross_mappings:
                output["cross_system_mappings"] = cross_mappings

            # 写入 YAML
            filepath = dict_output_dir / filename
            with open(filepath, "w", encoding="utf-8") as f:
                yaml.dump(
                    output,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )

            logger.info(f"  ✓ 已生成 {filepath}（共 {len(entries)} 条记录）")

    # ============================================================
    # 医保目录 Sheet → catalog.yaml
    # ============================================================

    def _import_catalog(self) -> None:
        """
        从"医保目录" Sheet 生成 catalog.yaml

        简单逐行透传，每个字段作为分类体系的一个类别。
        """
        logger.info("正在导入医保目录...")
        df = pd.read_excel(self.excel_path, sheet_name="医保目录")

        # 逐列提取数据，每列作为一个类别
        categories = {}
        for col in df.columns:
            col_name = str(col).strip()
            if col_name == "nan" or not col_name:
                continue
            # 提取该列的所有非空值
            values = []
            for _, row in df.iterrows():
                val = self._safe_str(row.get(col_name))
                if val and val != "nan":
                    values.append(val)
            if values:
                categories[col_name] = values

        output = {
            "generated_from": str(self.excel_path),
            "description": "数据模型1 医保目录 Sheet → 分类体系（由 datamodel1_importer.py 自动生成）",
            "categories": categories,
        }

        output_dir = Path(AUTO_GENERATED_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "catalog.yaml"

        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"  ✓ 已生成 {output_path}（共 {len(categories)} 个分类类别）")

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _safe_str(value: object, default: str = "") -> str:
        """安全地将单元格值转为字符串，处理 NaN"""
        if value is None:
            return default
        s = str(value).strip()
        if s == "nan":
            return default
        return s

    @staticmethod
    def _infer_value_type(field_name: str, category: str) -> str:
        """推断字段的值类型"""
        if category == "dimension":
            return "enum"
        if category == "numeric":
            return "float"
        if field_name in ("source_text", "rule_value"):
            return "string"
        return "string"

    @staticmethod
    def _infer_unit(field_name: str) -> str:
        """推断字段的单位"""
        if field_name in ("deductible_amount", "cap_amount"):
            return "元"
        if field_name == "payment_ratio":
            return "%"
        return ""

    @staticmethod
    def _infer_semantic_tags(field_name: str, category: str) -> list[str]:
        """为字段生成语义标签"""
        tag_map: dict[str, list[str]] = {
            "insu_type": ["险种", "医保类型", "分类"],
            "med_type": ["医疗类型", "住院", "门诊", "分类"],
            "hosp_lv": ["医院等级", "分级", "分类"],
            "psn_type": ["人群", "参保人", "分类"],
            "setl_type": ["结算", "付费方式", "分类"],
            "payment_ratio": ["比例", "报销比例", "支付"],
            "deductible_amount": ["起付线", "门槛费", "自付"],
            "cap_amount": ["封顶线", "上限", "限额"],
            "admission_order": ["住院次数", "首次", "二次"],
            "rule_id": ["规则标识"],
            "fact_id": ["事实标识"],
            "policy_id": ["政策标识"],
            "clause_id": ["条款标识"],
            "source_text": ["政策原文", "溯源"],
            "priority": ["优先级"],
            "rule_type": ["规则类型", "分类"],
            "rule_value": ["规则值"],
            "amount_band": ["金额区间", "分段"],
            "time_period": ["时间周期", "年度"],
        }
        return tag_map.get(field_name, [])

    def _extract_existing_mappings(self, category: str) -> dict[str, dict[str, str]]:
        """
        提取各系统现有的硬编码映射

        后续 Phase 可通过 AST 分析自动提取，当前从 KNOWN_CROSS_MAPPINGS 手工维护。
        """
        return self.KNOWN_CROSS_MAPPINGS.get(category, {})


# ============================================================
# CLI 入口
# ============================================================

def main() -> None:
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="数据模型1导入器 - 将 Excel 语义元数据转化为 YAML 配置",
    )
    parser.add_argument(
        "--only",
        choices=["policy_fields", "dictionaries", "catalog"],
        help="仅导入指定部分",
    )
    parser.add_argument(
        "--excel-path",
        default=None,
        help="数据模型1.xlsx 路径（默认使用配置中的 DATAMODEL1_PATH）",
    )

    args = parser.parse_args()

    importer = DataModel1Importer(excel_path=args.excel_path)

    if args.only == "policy_fields":
        importer.import_policy_fields_only()
    elif args.only == "dictionaries":
        importer.import_dictionaries_only()
    elif args.only == "catalog":
        importer.import_catalog_only()
    else:
        importer.import_all()


if __name__ == "__main__":
    main()
