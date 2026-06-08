"""
医保政策问答RAG系统 - 字典标准化服务

基于 raw/数据模型1.xlsx 字典 sheet 页，建立同义词 → 标准值的映射
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# 默认字典路径
DEFAULT_DICT_PATH = Path(__file__).parent.parent.parent.parent / "raw" / "数据模型1.xlsx"


class DictionaryNormalizer:
    """
    字典标准化服务
    
    从 Excel 字典 sheet 读取同义词映射，将非标准值转换为标准值
    """

    def __init__(self, dict_path: str | Path | None = None):
        self.dict_path = Path(dict_path) if dict_path else DEFAULT_DICT_PATH
        self._synonym_to_standard: dict[str, dict[str, str]] = {}  # {类型: {同义词: 标准值}}
        self._standard_values: dict[str, set[str]] = {}  # {类型: {标准值集合}}
        self._load_dictionary()

    def _load_dictionary(self) -> None:
        """从 Excel 加载字典"""
        try:
            if not self.dict_path.exists():
                logger.warning(f"字典文件不存在: {self.dict_path}")
                return

            df = pd.read_excel(self.dict_path, sheet_name='字典')
            
            for _, row in df.iterrows():
                category = str(row.get('类型', '')).strip()
                standard_value = str(row.get('值', row.get('标准值', ''))).strip()  # 列名是 '值'，兼容旧列名 '标准值'
                synonyms_str = str(row.get('同义词', '')).strip()
                
                if not category or not standard_value or standard_value == 'nan':
                    continue
                
                # 初始化
                if category not in self._synonym_to_standard:
                    self._synonym_to_standard[category] = {}
                    self._standard_values[category] = set()
                
                # 添加标准值本身
                self._synonym_to_standard[category][standard_value] = standard_value
                self._standard_values[category].add(standard_value)
                
                # 添加同义词
                if synonyms_str and synonyms_str != 'nan':
                    synonyms = [s.strip() for s in synonyms_str.split('&') if s.strip()]
                    for synonym in synonyms:
                        self._synonym_to_standard[category][synonym] = standard_value
            
            logger.info(f"加载字典完成: {len(self._synonym_to_standard)} 个类型")
            for category, mappings in self._synonym_to_standard.items():
                logger.info(f"  {category}: {len(mappings)} 个映射")
                
        except Exception as e:
            logger.exception(f"加载字典失败: {e}")

    def normalize(self, category: str, value: str) -> str:
        """
        将非标准值转换为标准值
        
        Args:
            category: 类型（如 "险种类别"、"人群标签"）
            value: 原始值
            
        Returns:
            标准值（如果找不到映射，返回原值）
        """
        if not value or value == 'nan':
            return value
        
        value = value.strip()
        category_mappings = self._synonym_to_standard.get(category, {})
        
        # 精确匹配
        if value in category_mappings:
            return category_mappings[value]
        
        # 模糊匹配（包含关系）
        for synonym, standard in category_mappings.items():
            if synonym in value or value in synonym:
                return standard
        
        # 未找到映射，返回原值
        logger.debug(f"未找到 {category} 的映射: {value}")
        return value

    def normalize_insurance_type(self, value: str) -> str:
        """标准化险种类别"""
        return self.normalize("险种类别", value)

    def normalize_medical_type(self, value: str) -> str:
        """标准化医疗类别"""
        return self.normalize("医疗类别", value)

    def normalize_hospital_level(self, value: str) -> str:
        """标准化医疗机构等级"""
        return self.normalize("医疗机构等级", value)

    def normalize_population(self, value: str) -> str:
        """标准化人群标签"""
        return self.normalize("人群标签", value)

    def get_standard_values(self, category: str) -> set[str]:
        """获取某个类型的所有标准值"""
        return self._standard_values.get(category, set())

    def get_all_mappings(self) -> dict[str, dict[str, str]]:
        """获取所有映射关系"""
        return self._synonym_to_standard.copy()


# 全局单例
_normalizer: DictionaryNormalizer | None = None


def get_normalizer() -> DictionaryNormalizer:
    """获取全局标准化服务实例"""
    global _normalizer
    if _normalizer is None:
        _normalizer = DictionaryNormalizer()
    return _normalizer
