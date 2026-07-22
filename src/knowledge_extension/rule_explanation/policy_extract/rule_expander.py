"""
规则展开器
将组合规则拆分成最小粒度的 fact 规则

例如：
原规则：城乡老年人、劳动年龄内居民首次住院的起付标准为：一级及以下医疗机构300元、二级医疗机构800元、三级医疗机构1300元

展开为 6 个 fact：
1. 城乡老年人 + 一级及以下 + 首次住院 + 300元
2. 城乡老年人 + 二级 + 首次住院 + 800元
3. 城乡老年人 + 三级 + 首次住院 + 1300元
4. 劳动年龄内居民 + 一级及以下 + 首次住院 + 300元
5. 劳动年龄内居民 + 二级 + 首次住院 + 800元
6. 劳动年龄内居民 + 三级 + 首次住院 + 1300元
"""
import itertools
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .value_mapping import (
    normalize_value,
    INSURANCE_SYSTEM_MAP,
    POPULATION_TAGS_MAP,
    HOSPITAL_LEVEL_MAP,
    MEDICAL_CATEGORY_MAP,
)


@dataclass
class FactRule:
    """
    最小粒度的 fact 规则
    
    每个 fact 规则代表一个不可再分的规则单元
    """
    fact_id: str  # 事实ID
    rule_id: str  # 规则ID（关联到原始规则）
    rule_type: str  # 规则类型
    
    # 规则维度（标准化英文键）
    insurance_system: Optional[str] = None  # 参保体系
    population_tag: Optional[str] = None  # 人群标签（单个值，不是数组）
    medical_category: Optional[str] = None  # 医疗类别
    hospital_level: Optional[str] = None  # 医疗机构等级
    admission_order: Optional[int] = None  # 住院次数
    settlement_method: Optional[str] = None  # 结算方式
    catalog_tag: Optional[str] = None  # 目录属性标签
    
    # 规则值
    action_type: Optional[str] = None  # 动作类型
    action_value: Optional[Any] = None  # 动作值
    action_formula: Optional[str] = None  # 动作公式
    
    # 元数据
    evidence_text: Optional[str] = None  # 依据原文
    confidence: float = 1.0  # 置信度
    review_status: str = "pending"  # 审核状态
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "fact_id": self.fact_id,
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "insurance_system": self.insurance_system,
            "population_tag": self.population_tag,
            "medical_category": self.medical_category,
            "hospital_level": self.hospital_level,
            "admission_order": self.admission_order,
            "settlement_method": self.settlement_method,
            "catalog_tag": self.catalog_tag,
            "action_type": self.action_type,
            "action_value": self.action_value,
            "action_formula": self.action_formula,
            "evidence_text": self.evidence_text,
            "confidence": self.confidence,
            "review_status": self.review_status,
        }


@dataclass
class RuleExpansionResult:
    """规则展开结果"""
    original_rule_id: str  # 原始规则ID
    facts: List[FactRule] = field(default_factory=list)  # 展开后的 fact 列表
    expansion_errors: List[str] = field(default_factory=list)  # 展开错误


class RuleExpander:
    """
    规则展开器
    
    将组合规则拆分成最小粒度的 fact 规则
    """
    
    def expand_deductible_rule(
        self,
        rule_id: str,
        populations: List[str],
        hospital_levels: Dict[str, float],
        admission_order: Optional[int] = None,
        insurance_system: Optional[str] = None,
        medical_category: Optional[str] = None,
        evidence_text: Optional[str] = None,
    ) -> RuleExpansionResult:
        """
        展开起付线规则
        
        Args:
            rule_id: 原始规则ID
            populations: 人群标签列表（中文）
            hospital_levels: 医院等级到金额的映射（中文键）
            admission_order: 住院次数
            insurance_system: 参保体系（中文）
            medical_category: 医疗类别（中文）
            evidence_text: 依据原文
            
        Returns:
            展开结果
        """
        result = RuleExpansionResult(original_rule_id=rule_id)
        
        # 标准化人群标签
        normalized_populations = []
        for pop in populations:
            normalized = normalize_value("population_tags", pop)
            if normalized:
                normalized_populations.append(normalized)
            else:
                result.expansion_errors.append(f"无法识别的人群标签: {pop}")
        
        # 标准化医院等级
        normalized_levels = {}
        for level, amount in hospital_levels.items():
            normalized = normalize_value("hospital_level", level)
            if normalized:
                normalized_levels[normalized] = amount
            else:
                result.expansion_errors.append(f"无法识别的医院等级: {level}")
        
        # 标准化参保体系
        normalized_insurance = None
        if insurance_system:
            normalized_insurance = normalize_value("insurance_system", insurance_system)
            if not normalized_insurance:
                result.expansion_errors.append(f"无法识别的参保体系: {insurance_system}")
        
        # 标准化医疗类别
        normalized_medical = None
        if medical_category:
            normalized_medical = normalize_value("medical_category", medical_category)
            if not normalized_medical:
                result.expansion_errors.append(f"无法识别的医疗类别: {medical_category}")
        
        # 标准化住院次数
        normalized_admission = admission_order
        if isinstance(admission_order, str):
            from .value_mapping import ADMISSION_ORDER_MAP
            normalized_admission = ADMISSION_ORDER_MAP.get(admission_order)
        
        # 笛卡尔积展开：人群 × 医院等级
        for pop, (level, amount) in itertools.product(
            normalized_populations, normalized_levels.items()
        ):
            fact = FactRule(
                fact_id=f"fact_{uuid.uuid4().hex[:12]}",
                rule_id=rule_id,
                rule_type="deductible_rule",
                insurance_system=normalized_insurance,
                population_tag=pop,
                medical_category=normalized_medical,
                hospital_level=level,
                admission_order=normalized_admission,
                action_type="set_deductible",
                action_value=amount,
                evidence_text=evidence_text,
            )
            result.facts.append(fact)
        
        return result
    
    def expand_ratio_rule(
        self,
        rule_id: str,
        populations: List[str],
        hospital_ratios: Dict[str, float],
        insurance_system: Optional[str] = None,
        medical_category: Optional[str] = None,
        evidence_text: Optional[str] = None,
    ) -> RuleExpansionResult:
        """
        展开报销比例规则
        
        Args:
            rule_id: 原始规则ID
            populations: 人群标签列表（中文）
            hospital_ratios: 医院等级到比例的映射（中文键）
            insurance_system: 参保体系（中文）
            medical_category: 医疗类别（中文）
            evidence_text: 依据原文
            
        Returns:
            展开结果
        """
        result = RuleExpansionResult(original_rule_id=rule_id)
        
        # 标准化人群标签
        normalized_populations = []
        for pop in populations:
            normalized = normalize_value("population_tags", pop)
            if normalized:
                normalized_populations.append(normalized)
            else:
                result.expansion_errors.append(f"无法识别的人群标签: {pop}")
        
        # 标准化医院等级
        normalized_ratios = {}
        for level, ratio in hospital_ratios.items():
            normalized = normalize_value("hospital_level", level)
            if normalized:
                normalized_ratios[normalized] = ratio
            else:
                result.expansion_errors.append(f"无法识别的医院等级: {level}")
        
        # 标准化参保体系
        normalized_insurance = None
        if insurance_system:
            normalized_insurance = normalize_value("insurance_system", insurance_system)
        
        # 标准化医疗类别
        normalized_medical = None
        if medical_category:
            normalized_medical = normalize_value("medical_category", medical_category)
        
        # 笛卡尔积展开：人群 × 医院等级
        for pop, (level, ratio) in itertools.product(
            normalized_populations, normalized_ratios.items()
        ):
            fact = FactRule(
                fact_id=f"fact_{uuid.uuid4().hex[:12]}",
                rule_id=rule_id,
                rule_type="ratio_rule",
                insurance_system=normalized_insurance,
                population_tag=pop,
                medical_category=normalized_medical,
                hospital_level=level,
                action_type="set_ratio",
                action_value=ratio,
                evidence_text=evidence_text,
            )
            result.facts.append(fact)
        
        return result
    
    def expand_cap_rule(
        self,
        rule_id: str,
        populations: List[str],
        cap_amount: float,
        insurance_system: Optional[str] = None,
        medical_category: Optional[str] = None,
        evidence_text: Optional[str] = None,
    ) -> RuleExpansionResult:
        """
        展开封顶线规则
        
        Args:
            rule_id: 原始规则ID
            populations: 人群标签列表（中文）
            cap_amount: 封顶金额
            insurance_system: 参保体系（中文）
            medical_category: 医疗类别（中文）
            evidence_text: 依据原文
            
        Returns:
            展开结果
        """
        result = RuleExpansionResult(original_rule_id=rule_id)
        
        # 标准化人群标签
        normalized_populations = []
        for pop in populations:
            normalized = normalize_value("population_tags", pop)
            if normalized:
                normalized_populations.append(normalized)
            else:
                result.expansion_errors.append(f"无法识别的人群标签: {pop}")
        
        # 标准化参保体系
        normalized_insurance = None
        if insurance_system:
            normalized_insurance = normalize_value("insurance_system", insurance_system)
        
        # 标准化医疗类别
        normalized_medical = None
        if medical_category:
            normalized_medical = normalize_value("medical_category", medical_category)
        
        # 每个人群一个 fact
        for pop in normalized_populations:
            fact = FactRule(
                fact_id=f"fact_{uuid.uuid4().hex[:12]}",
                rule_id=rule_id,
                rule_type="cap_rule",
                insurance_system=normalized_insurance,
                population_tag=pop,
                medical_category=normalized_medical,
                action_type="set_cap",
                action_value=cap_amount,
                evidence_text=evidence_text,
            )
            result.facts.append(fact)
        
        return result
    
    def expand_rule_from_dict(self, rule_data: Dict[str, Any]) -> RuleExpansionResult:
        """
        从字典展开规则
        
        Args:
            rule_data: 规则字典，包含：
                - rule_id: 规则ID
                - rule_type: 规则类型
                - populations: 人群标签列表
                - hospital_levels: 医院等级映射（可选）
                - cap_amount: 封顶金额（可选）
                - admission_order: 住院次数（可选）
                - insurance_system: 参保体系（可选）
                - medical_category: 医疗类别（可选）
                - evidence_text: 依据原文（可选）
                
        Returns:
            展开结果
        """
        rule_type = rule_data.get("rule_type", "")
        
        if rule_type == "deductible_rule":
            return self.expand_deductible_rule(
                rule_id=rule_data.get("rule_id", ""),
                populations=rule_data.get("populations", []),
                hospital_levels=rule_data.get("hospital_levels", {}),
                admission_order=rule_data.get("admission_order"),
                insurance_system=rule_data.get("insurance_system"),
                medical_category=rule_data.get("medical_category"),
                evidence_text=rule_data.get("evidence_text"),
            )
        elif rule_type == "ratio_rule":
            return self.expand_ratio_rule(
                rule_id=rule_data.get("rule_id", ""),
                populations=rule_data.get("populations", []),
                hospital_ratios=rule_data.get("hospital_ratios", {}),
                insurance_system=rule_data.get("insurance_system"),
                medical_category=rule_data.get("medical_category"),
                evidence_text=rule_data.get("evidence_text"),
            )
        elif rule_type == "cap_rule":
            return self.expand_cap_rule(
                rule_id=rule_data.get("rule_id", ""),
                populations=rule_data.get("populations", []),
                cap_amount=rule_data.get("cap_amount", 0),
                insurance_system=rule_data.get("insurance_system"),
                medical_category=rule_data.get("medical_category"),
                evidence_text=rule_data.get("evidence_text"),
            )
        else:
            result = RuleExpansionResult(original_rule_id=rule_data.get("rule_id", ""))
            result.expansion_errors.append(f"不支持的规则类型: {rule_type}")
            return result
