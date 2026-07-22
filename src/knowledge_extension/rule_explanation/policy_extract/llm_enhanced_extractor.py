"""
大模型增强的值域提取器

使用大模型能力：
1. 识别新的同义词/简称
2. 验证现有值域定义的准确性
3. 从政策原文中发现新的值域
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from .domain_definitions import DomainConfig, ValueDefinition, VALUE_DOMAIN_RULES
from .value_domain_extractor import ValueDomainExtractor, ValueOccurrence, DomainExtractionResult

logger = logging.getLogger(__name__)


@dataclass
class SynonymSuggestion:
    """同义词建议"""
    standard_name: str  # 标准名称
    new_aliases: List[str]  # 建议新增的同义词
    confidence: float  # 置信度
    evidence: str  # 依据


@dataclass
class DomainSuggestion:
    """值域建议"""
    field_name: str  # 字段名
    new_values: List[Dict[str, Any]]  # 建议新增的值域
    confidence: float  # 置信度


class LLMEnhancedExtractor:
    """
    大模型增强的值域提取器
    
    功能：
    1. 使用基础提取器进行初步提取
    2. 调用大模型识别新的同义词
    3. 调用大模型发现新的值域
    4. 合并结果
    """
    
    def __init__(
        self,
        rules: Optional[Dict[str, DomainConfig]] = None,
        model_gateway=None
    ):
        """
        初始化提取器
        
        Args:
            rules: 值域规则配置
            model_gateway: 模型服务网关实例（可选）
        """
        self.rules = rules or VALUE_DOMAIN_RULES
        self.base_extractor = ValueDomainExtractor(self.rules)
        self.model_gateway = model_gateway
    
    def extract_with_synonym_discovery(
        self,
        text: str,
        discover_synonyms: bool = True
    ) -> Dict[str, DomainExtractionResult]:
        """
        提取值域并发现新的同义词
        
        Args:
            text: 政策原文文本
            discover_synonyms: 是否发现新的同义词
            
        Returns:
            提取结果字典
        """
        # 基础提取
        results = self.base_extractor.extract_from_text(text)
        
        if discover_synonyms and self.model_gateway:
            # 使用大模型发现新的同义词
            suggestions = self._discover_synonyms(text, results)
            
            # 应用建议（需要人工审核）
            for suggestion in suggestions:
                logger.info(f"发现新同义词建议: {suggestion}")
        
        return results
    
    def _discover_synonyms(
        self,
        text: str,
        current_results: Dict[str, DomainExtractionResult]
    ) -> List[SynonymSuggestion]:
        """
        使用大模型发现新的同义词
        
        Args:
            text: 政策原文文本
            current_results: 当前提取结果
            
        Returns:
            同义词建议列表
        """
        if not self.model_gateway:
            return []
        
        suggestions = []
        
        # 构建 prompt
        prompt = self._build_synonym_discovery_prompt(text, current_results)
        
        try:
            # 调用大模型
            response = self.model_gateway.generate(prompt)
            
            # 解析响应
            parsed = self._parse_synonym_response(response)
            suggestions.extend(parsed)
            
        except Exception as e:
            logger.error(f"调用大模型失败: {e}")
        
        return suggestions
    
    def _build_synonym_discovery_prompt(
        self,
        text: str,
        current_results: Dict[str, DomainExtractionResult]
    ) -> str:
        """
        构建同义词发现的 prompt
        
        Args:
            text: 政策原文文本
            current_results: 当前提取结果
            
        Returns:
            prompt 字符串
        """
        # 截取文本片段（避免太长）
        text_sample = text[:5000] if len(text) > 5000 else text
        
        # 构建当前已知值域的描述
        known_values_desc = []
        for field_name, result in current_results.items():
            values_desc = [v.standard_name for v in result.values[:5]]  # 只显示前5个
            known_values_desc.append(f"- {result.field_name_cn}({field_name}): {', '.join(values_desc)}")
        
        known_values_text = '\n'.join(known_values_desc)
        
        prompt = f"""你是一个医保政策专家。请分析以下政策原文，找出可能的同义词或简称。

## 当前已知的值域
{known_values_text}

## 政策原文片段
{text_sample}

## 任务
1. 识别政策原文中出现的同义词、简称、别称
2. 将它们对应到已知的标准值域
3. 如果发现新的值域，也请指出

## 输出格式
请以JSON格式输出，包含以下字段：
```json
{{
  "synonyms": [
    {{
      "field_name": "字段名",
      "standard_name": "标准名称",
      "new_aliases": ["新发现的同义词1", "新发现的同义词2"],
      "confidence": 0.9,
      "evidence": "在原文中的依据"
    }}
  ],
  "new_values": [
    {{
      "field_name": "字段名",
      "standard_name": "标准名称",
      "abbreviation": "简称",
      "category": "分类",
      "confidence": 0.8,
      "evidence": "在原文中的依据"
    }}
  ]
}}
```

请只输出JSON，不要其他内容。"""
        
        return prompt
    
    def _parse_synonym_response(self, response: str) -> List[SynonymSuggestion]:
        """
        解析大模型的同义词发现响应
        
        Args:
            response: 大模型响应文本
            
        Returns:
            同义词建议列表
        """
        suggestions = []
        
        try:
            # 尝试提取 JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                data = json.loads(json_str)
                
                # 解析同义词建议
                for item in data.get("synonyms", []):
                    suggestion = SynonymSuggestion(
                        standard_name=item.get("standard_name", ""),
                        new_aliases=item.get("new_aliases", []),
                        confidence=item.get("confidence", 0.5),
                        evidence=item.get("evidence", "")
                    )
                    suggestions.append(suggestion)
                    
        except Exception as e:
            logger.error(f"解析大模型响应失败: {e}")
        
        return suggestions
    
    def discover_new_domains(
        self,
        text: str
    ) -> List[DomainSuggestion]:
        """
        使用大模型发现新的值域
        
        Args:
            text: 政策原文文本
            
        Returns:
            值域建议列表
        """
        if not self.model_gateway:
            return []
        
        suggestions = []
        
        # 构建 prompt
        prompt = self._build_domain_discovery_prompt(text)
        
        try:
            # 调用大模型
            response = self.model_gateway.generate(prompt)
            
            # 解析响应
            parsed = self._parse_domain_response(response)
            suggestions.extend(parsed)
            
        except Exception as e:
            logger.error(f"调用大模型失败: {e}")
        
        return suggestions
    
    def _build_domain_discovery_prompt(self, text: str) -> str:
        """
        构建值域发现的 prompt
        
        Args:
            text: 政策原文文本
            
        Returns:
            prompt 字符串
        """
        # 截取文本片段
        text_sample = text[:5000] if len(text) > 5000 else text
        
        # 当前已有的字段
        known_fields = list(self.rules.keys())
        known_fields_text = ', '.join(known_fields)
        
        prompt = f"""你是一个医保政策专家。请分析以下政策原文，发现可能需要新增的值域字段。

## 当前已有的字段
{known_fields_text}

## 政策原文片段
{text_sample}

## 任务
1. 识别政策原文中出现的重要分类维度
2. 判断是否需要新增值域字段
3. 如果需要，提供建议的字段名和值域

## 输出格式
请以JSON格式输出：
```json
{{
  "new_domains": [
    {{
      "field_name": "建议的字段名（英文）",
      "field_name_cn": "中文字段名",
      "description": "字段描述",
      "values": [
        {{
          "standard_name": "标准名称",
          "abbreviation": "简称",
          "category": "分类"
        }}
      ],
      "confidence": 0.8,
      "evidence": "在原文中的依据"
    }}
  ]
}}
```

请只输出JSON，不要其他内容。"""
        
        return prompt
    
    def _parse_domain_response(self, response: str) -> List[DomainSuggestion]:
        """
        解析大模型的值域发现响应
        
        Args:
            response: 大模型响应文本
            
        Returns:
            值域建议列表
        """
        suggestions = []
        
        try:
            # 尝试提取 JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                data = json.loads(json_str)
                
                # 解析值域建议
                for item in data.get("new_domains", []):
                    suggestion = DomainSuggestion(
                        field_name=item.get("field_name", ""),
                        new_values=item.get("values", []),
                        confidence=item.get("confidence", 0.5)
                    )
                    suggestions.append(suggestion)
                    
        except Exception as e:
            logger.error(f"解析大模型响应失败: {e}")
        
        return suggestions
    
    def apply_synonym_suggestions(
        self,
        suggestions: List[SynonymSuggestion],
        auto_apply: bool = False
    ) -> Dict[str, DomainConfig]:
        """
        应用同义词建议到规则配置
        
        Args:
            suggestions: 同义词建议列表
            auto_apply: 是否自动应用（否则返回建议供人工审核）
            
        Returns:
            更新后的规则配置
        """
        # TODO: 实现同义词建议的应用逻辑
        # 这里需要更新 self.rules 中的 ValueDefinition.aliases
        
        if auto_apply:
            for suggestion in suggestions:
                if suggestion.confidence >= 0.8:  # 高置信度才自动应用
                    # 查找对应的值域定义
                    for field_name, config in self.rules.items():
                        for value_def in config.values:
                            if value_def.standard_name == suggestion.standard_name:
                                # 添加新的同义词
                                for alias in suggestion.new_aliases:
                                    if alias not in value_def.aliases:
                                        value_def.aliases.append(alias)
                                        logger.info(f"自动添加同义词: {suggestion.standard_name} <- {alias}")
        
        return self.rules
    
    def save_suggestions(
        self,
        synonym_suggestions: List[SynonymSuggestion],
        domain_suggestions: List[DomainSuggestion],
        output_path: str
    ):
        """
        保存建议到文件
        
        Args:
            synonym_suggestions: 同义词建议
            domain_suggestions: 值域建议
            output_path: 输出文件路径
        """
        data = {
            "synonym_suggestions": [
                {
                    "standard_name": s.standard_name,
                    "new_aliases": s.new_aliases,
                    "confidence": s.confidence,
                    "evidence": s.evidence
                }
                for s in synonym_suggestions
            ],
            "domain_suggestions": [
                {
                    "field_name": s.field_name,
                    "new_values": s.new_values,
                    "confidence": s.confidence
                }
                for s in domain_suggestions
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"建议已保存至: {output_path}")
