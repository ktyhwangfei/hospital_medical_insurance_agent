"""
值域提取器
从政策原文中提取标准化的值域信息

核心功能：
1. 支持同义词/简称合并统计
2. 长模式优先匹配，避免误匹配
3. 支持大模型辅助识别
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from .domain_definitions import DomainConfig, ValueDefinition, VALUE_DOMAIN_RULES


@dataclass
class ValueOccurrence:
    """值域出现记录"""
    standard_name: str  # 标准名称
    abbreviation: str  # 推荐简称
    category: str  # 分类
    description: str  # 描述
    total_occurrences: int  # 合并后的总出现次数
    matched_patterns: Dict[str, int] = field(default_factory=dict)  # 各匹配模式的次数


@dataclass
class DomainExtractionResult:
    """值域提取结果"""
    field_name: str
    field_name_cn: str
    description: str
    values: List[ValueOccurrence]


class ValueDomainExtractor:
    """
    值域提取器
    
    核心设计：
    - 每个值域定义包含多个 aliases（同义词/变体）
    - 匹配时，所有 aliases 的出现次数合并到同一个 standard_name
    - 长模式优先匹配，避免短模式误匹配
    """
    
    def __init__(self, rules: Optional[Dict[str, DomainConfig]] = None):
        """
        初始化提取器
        
        Args:
            rules: 值域规则配置，默认使用内置规则
        """
        self.rules = rules or VALUE_DOMAIN_RULES
    
    def _build_pattern_index(self, config: DomainConfig) -> List[Tuple[str, re.Pattern, ValueDefinition]]:
        """
        构建模式索引，按模式长度降序排列（长模式优先匹配）
        
        Returns:
            [(alias, compiled_pattern, value_definition), ...]
        """
        pattern_index = []
        
        for value_def in config.values:
            for alias in value_def.aliases:
                # 编译正则，使用中文友好的模式
                try:
                    # 对于纯中文文本，直接使用字符串匹配
                    pattern = re.compile(re.escape(alias))
                    pattern_index.append((alias, pattern, value_def))
                except re.error:
                    continue
        
        # 按模式长度降序排列，长模式优先匹配
        pattern_index.sort(key=lambda x: len(x[0]), reverse=True)
        
        return pattern_index
    
    def extract_from_text(self, text: str) -> Dict[str, DomainExtractionResult]:
        """
        从文本中提取值域
        
        核心逻辑：
        1. 遍历每个字段的值域定义
        2. 对每个值域的所有 aliases 进行匹配
        3. 合并同一值域下所有 aliases 的出现次数
        4. 按出现次数排序
        
        Args:
            text: 政策原文文本
            
        Returns:
            提取结果字典
        """
        results = {}
        
        for field_name, config in self.rules.items():
            # 构建模式索引
            pattern_index = self._build_pattern_index(config)
            
            # 记录已匹配的位置，避免重复计数
            matched_positions: Set[int] = set()
            
            # 记录每个标准值域的出现次数
            value_counts: Dict[str, ValueOccurrence] = {}
            
            # 长模式优先匹配
            for alias, pattern, value_def in pattern_index:
                matches = list(pattern.finditer(text))
                
                for match in matches:
                    # 检查是否与已匹配位置重叠
                    match_positions = set(range(match.start(), match.end()))
                    if match_positions & matched_positions:
                        continue  # 跳过重叠匹配
                    
                    # 记录匹配
                    matched_positions |= match_positions
                    
                    # 累加到对应的标准值域
                    if value_def.standard_name not in value_counts:
                        value_counts[value_def.standard_name] = ValueOccurrence(
                            standard_name=value_def.standard_name,
                            abbreviation=value_def.abbreviation,
                            category=value_def.category,
                            description=value_def.description,
                            total_occurrences=0,
                            matched_patterns={}
                        )
                    
                    occurrence = value_counts[value_def.standard_name]
                    occurrence.total_occurrences += 1
                    occurrence.matched_patterns[alias] = occurrence.matched_patterns.get(alias, 0) + 1
            
            # 按出现次数排序
            sorted_values = sorted(
                value_counts.values(),
                key=lambda x: x.total_occurrences,
                reverse=True
            )
            
            results[field_name] = DomainExtractionResult(
                field_name=field_name,
                field_name_cn=config.field_name_cn,
                description=config.description,
                values=sorted_values
            )
        
        return results
    
    def extract_from_excel(
        self,
        file_path: str,
        text_column: str = "full_context_text"
    ) -> Dict[str, DomainExtractionResult]:
        """
        从 Excel 文件中提取值域
        
        Args:
            file_path: Excel 文件路径
            text_column: 包含文本的列名
            
        Returns:
            提取结果字典
        """
        df = pd.read_excel(file_path)
        
        if text_column not in df.columns:
            raise ValueError(f"列 '{text_column}' 不存在于文件中")
        
        # 合并所有文本
        texts = df[text_column].dropna().tolist()
        all_text = '\n'.join([str(t) for t in texts])
        
        return self.extract_from_text(all_text)
    
    def to_dict(self, results: Dict[str, DomainExtractionResult]) -> dict:
        """
        将结果转换为字典格式
        
        Args:
            results: 提取结果
            
        Returns:
            字典格式的结果
        """
        output = {}
        for field_name, result in results.items():
            output[field_name] = {
                "field_name": result.field_name,
                "field_name_cn": result.field_name_cn,
                "description": result.description,
                "values": [
                    {
                        "standard_name": v.standard_name,
                        "abbreviation": v.abbreviation,
                        "category": v.category,
                        "description": v.description,
                        "total_occurrences": v.total_occurrences,
                        "matched_patterns": v.matched_patterns
                    }
                    for v in result.values
                ]
            }
        return output
    
    def to_json(self, results: Dict[str, DomainExtractionResult], indent: int = 2) -> str:
        """
        将结果转换为 JSON 格式
        
        Args:
            results: 提取结果
            indent: 缩进空格数
            
        Returns:
            JSON 字符串
        """
        import json
        return json.dumps(self.to_dict(results), ensure_ascii=False, indent=indent)
    
    def get_standard_values(
        self,
        results: Dict[str, DomainExtractionResult],
        min_occurrences: int = 1
    ) -> Dict[str, List[str]]:
        """
        获取标准化值域列表
        
        Args:
            results: 提取结果
            min_occurrences: 最小出现次数阈值
            
        Returns:
            字段名到标准值域列表的映射
        """
        standard_values = {}
        for field_name, result in results.items():
            values = [
                v.standard_name
                for v in result.values
                if v.total_occurrences >= min_occurrences
            ]
            standard_values[field_name] = values
        return standard_values
    
    def get_abbreviations(
        self,
        results: Dict[str, DomainExtractionResult]
    ) -> Dict[str, Dict[str, str]]:
        """
        获取简称映射
        
        Args:
            results: 提取结果
            
        Returns:
            字段名到 {标准名: 简称} 映射
        """
        abbreviations = {}
        for field_name, result in results.items():
            mapping = {
                v.standard_name: v.abbreviation
                for v in result.values
            }
            abbreviations[field_name] = mapping
        return abbreviations
    
    def explain_extraction(
        self,
        text: str,
        field_name: str
    ) -> Dict[str, any]:
        """
        解释提取过程，用于调试
        
        Args:
            text: 文本
            field_name: 字段名
            
        Returns:
            提取过程的详细信息
        """
        if field_name not in self.rules:
            return {"error": f"字段 {field_name} 不存在"}
        
        config = self.rules[field_name]
        pattern_index = self._build_pattern_index(config)
        
        explanation = {
            "field_name": field_name,
            "field_name_cn": config.field_name_cn,
            "text_length": len(text),
            "pattern_matches": []
        }
        
        for alias, pattern, value_def in pattern_index:
            matches = list(pattern.finditer(text))
            if matches:
                explanation["pattern_matches"].append({
                    "alias": alias,
                    "standard_name": value_def.standard_name,
                    "match_count": len(matches),
                    "match_positions": [(m.start(), m.end()) for m in matches[:5]]  # 只显示前5个
                })
        
        return explanation
