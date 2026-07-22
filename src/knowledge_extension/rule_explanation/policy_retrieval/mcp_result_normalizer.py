"""
MCP结果标准化器

将MCP工具查询返回的JSON结果标准化为policy_rules字段格式，
使得标准化后的结果可以用于Milvus高级搜索(标量过滤)。

使用场景:
- MCP工具查询患者信息后，将返回结果中的险种/医疗类别/医院等级等
  标准化为数据模型1.xlsx中定义的标准值域
- 标准化后的字段可以直接作为Milvus标量过滤条件

设计原则:
- 三层映射：字段名映射 → 值域标准化 → 代码值映射
- 配置化：支持YAML配置文件加载映射规则
- 渐进增强：默认内置常用映射，复杂映射通过外部配置扩展
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class McpResultNormalizer:
    """
    MCP结果标准化器

    将MCP查询返回的JSON结果标准化为policy_rules字段格式。
    标准化后的结果可用于Milvus标量过滤和向量检索。

    使用示例::

        normalizer = McpResultNormalizer()
        result = normalizer.normalize({
            "insurance_type": "城镇职工基本医疗保险",
            "hospital_level": "三级"
        })
        # result == {"insu_type": "城镇职工", "hosp_lv": "三级医院"}
    """

    # MCP字段 → policy_rules字段映射
    # key: MCP返回的原始字段名（全大写/驼峰/下划线）
    # value: policy_rules中定义的标准化字段名
    FIELD_MAPPING: dict[str, str] = {
        # 险种类别
        "insurance_type": "insu_type",
        "insurance_system": "insu_type",
        "fund_type": "insu_type",
        "INSURANCE_TYPE": "insu_type",
        "FUND_TYPE": "insu_type",

        # 医疗类别
        "medical_type": "med_type",
        "medical_category": "med_type",
        "service_type": "med_type",
        "yllb": "med_type",
        "YLLB": "med_type",
        "MEDICAL_TYPE": "med_type",

        # 医院等级
        "hospital_level": "hosp_lv",
        "hospital_grade": "hosp_lv",
        "HOSPITAL_LEVEL": "hosp_lv",
        "HOSPITAL_GRADE": "hosp_lv",

        # 人群标签
        "person_type": "psn_type",
        "population": "psn_type",
        "person_category": "psn_type",
        "PER_TYPE": "psn_type",
        "PERSON_TYPE": "psn_type",

        # 结算方式
        "settlement_type": "setl_type",
        "payment_method": "setl_type",
        "SETTLEMENT_TYPE": "setl_type",
    }

    # 值域标准化映射
    # key: policy_rules目标字段名
    # value: {来源值 → 标准值} 映射字典
    VALUE_MAPPING: dict[str, dict[str, str]] = {
        "insu_type": {
            # 职工医保变体
            "职工基本医疗保险": "城镇职工",
            "城镇职工基本医疗保险": "城镇职工",
            "城镇职工医保": "城镇职工",
            "职工医保": "城镇职工",
            "职工": "城镇职工",
            # 居民医保变体
            "城乡居民基本医疗保险": "城乡居民",
            "城乡居民医保": "城乡居民",
            "居民基本医疗保险": "城乡居民",
            "居民医保": "城乡居民",
            "居民": "城乡居民",
            "城镇居民": "城乡居民",
            # 特殊人群
            "离休统筹": "离休人员",
            "离休人员": "离休人员",
            "离休": "离休人员",
            "公疗医照": "医照人员",
            "医照人员": "医照人员",
            "公费医疗": "医照人员",
            "征地超转人员": "超转人员",
            "超转人员": "超转人员",
            "超转": "超转人员",
            "生育保险": "生育保险",
            "生育": "生育保险",
            "大病保险": "大病保险",
            "大病": "大病保险",
        },
        "med_type": {
            # 住院
            "普通住院": "住院-普通住院",
            "住院-普通住院": "住院-普通住院",
            "住院": "住院-普通住院",
            "住院治疗": "住院-普通住院",
            "单病种住院": "住院-单病种",
            "住院-单病种": "住院-单病种",
            "日间手术": "住院-日间手术",
            "住院-日间手术": "住院-日间手术",
            "日间病房": "住院-日间手术",
            # 门诊
            "普通门诊": "门诊-普通门急诊",
            "门诊-普通门急诊": "门诊-普通门急诊",
            "门诊-普通门诊": "门诊-普通门急诊",
            "门诊": "门诊-普通门急诊",
            "门（急）诊": "门诊-普通门急诊",
            "门急诊": "门诊-普通门急诊",
            "门诊慢特病": "门诊-一般门特",
            "门诊特殊病": "门诊-一般门特",
            "门诊慢性病": "门诊-一般门特",
            "门诊-一般门特": "门诊-一般门特",
            "门慢": "门诊-一般门特",
            "门特": "门诊-一般门特",
            # 急诊
            "急诊": "门诊-急诊留观",
            "门诊-急诊留观": "门诊-急诊留观",
            "急诊抢救": "门诊-急诊留观",
            "急诊留观": "门诊-急诊留观",
            "留观": "门诊-急诊留观",
        },
        "hosp_lv": {
            "三级": "三级医院",
            "三级医院": "三级医院",
            "三级定点医疗机构": "三级医院",
            "三级医疗机构": "三级医院",
            "三甲": "三级医院",
            "三乙": "三级医院",
            "二级": "二级医院",
            "二级医院": "二级医院",
            "二级定点医疗机构": "二级医院",
            "二级医疗机构": "二级医院",
            "二乙": "二级医院",
            "二甲": "二级医院",
            "一级": "一级医院",
            "一级医院": "一级医院",
            "一级定点医疗机构": "一级医院",
            "一级及以下": "一级医院",
            "一级及以下定点医疗机构": "一级医院",
            "社区": "社区",
            "社区卫生服务中心": "社区",
            "社区卫生服务站": "社区",
            "基层": "社区",
            "基层医疗机构": "社区",
        },
        "psn_type": {
            # 职工
            "在职职工": "在职",
            "在职": "在职",
            "在职人员": "在职",
            "退休人员": "退休",
            "退休": "退休",
            "退休职工": "退休",
            "灵活就业人员": "灵活就业",
            "灵活就业": "灵活就业",
            # 离休
            "离休": "离休",
            "离休人员": "离休",
            # 居民
            "学生儿童": "学生儿童",
            "学生": "学生儿童",
            "儿童": "学生儿童",
            "少年儿童": "学生儿童",
            "在校学生": "学生儿童",
            "成年居民": "居民（成年）",
            "城乡老年人": "居民（老年）",
            "老年人": "居民（老年）",
            "老年居民": "居民（老年）",
            "劳动年龄内居民": "居民（成年）",
            "劳动年龄居民": "居民（成年）",
            "未成年人": "居民（未成年）",
            "未成年居民": "居民（未成年）",
            # 困难人群
            "特困供养人员": "困难人群",
            "特困": "困难人群",
            "低保": "困难人群",
            "最低生活保障人员": "困难人群",
            "低收入": "困难人群",
            "低收入救助人员": "困难人群",
            "残疾": "困难人群",
            "残疾人": "困难人群",
        },
        "setl_type": {
            "按项目付费": "按项目付费",
            "项目付费": "按项目付费",
            "按病种付费": "DRG",
            "DRG付费": "DRG",
            "DRG": "DRG",
            "DIP付费": "DIP",
            "DIP": "DIP",
            "按床日付费": "床日定额",
            "床日定额": "床日定额",
            "单病种付费": "单病种",
            "单病种": "单病种",
            "按人头付费": "按人头付费",
            "总额预付": "总额预付",
        },
    }

    # 代码值映射（医保系统常用的数字/编码 → 标准值）
    # 这些映射通常从数据模型1.xlsx的"值域"sheet中提取
    # key: policy_rules目标字段名
    # value: {编码 → 标准值} 映射字典
    CODE_MAPPING: dict[str, dict[str, str]] = {
        "insu_type": {
            "310": "城镇职工",
            "320": "城乡居民",
            "330": "离休人员",
            "340": "超转人员",
            "350": "医照人员",
            "360": "生育保险",
        },
        "med_type": {
            "11": "门诊-普通门急诊",
            "12": "门诊-一般门特",
            "13": "门诊-急诊留观",
            "21": "住院-普通住院",
            "22": "住院-单病种",
            "23": "住院-日间手术",
        },
        "hosp_lv": {
            "1": "三级医院",
            "2": "二级医院",
            "3": "一级医院",
            "4": "社区",
            "A": "三级医院",
            "B": "二级医院",
            "C": "一级医院",
        },
        "psn_type": {
            "1": "在职",
            "2": "退休",
            "3": "离休",
            "4": "学生儿童",
            "5": "居民（成年）",
            "6": "居民（老年）",
            "7": "居民（未成年）",
            "8": "困难人群",
        },
    }

    def __init__(
        self,
        mapping_yaml: str | Path | None = None,
    ):
        """
        初始化标准化器

        Args:
            mapping_yaml: YAML配置文件路径，用于加载自定义映射规则
                          YAML格式示例::

                              field_mapping:
                                custom_field: insu_type
                              value_mapping:
                                insu_type:
                                  新农合: 城乡居民
                              code_mapping:
                                insu_type:
                                  "410": 城乡居民
        """
        # 内部映射表（从FIELD_MAPPING/VALUE_MAPPING/CODE_MAPPING深拷贝初始化）
        self._field_map: dict[str, str] = dict(self.FIELD_MAPPING)
        self._value_map: dict[str, dict[str, str]] = {
            field: dict(mapping) for field, mapping in self.VALUE_MAPPING.items()
        }
        self._code_map: dict[str, dict[str, str]] = {
            field: dict(mapping) for field, mapping in self.CODE_MAPPING.items()
        }

        if mapping_yaml:
            self.load_mapping_from_yaml(mapping_yaml)

    # ============================================================
    # 核心标准化方法
    # ============================================================

    def normalize(self, mcp_result: dict[str, Any]) -> dict[str, str]:
        """
        标准化MCP结果

        将MCP工具返回的原始JSON结果中的字段名和值域
        都转换为policy_rules标准格式。

        Args:
            mcp_result: MCP工具返回的原始JSON结果字典

        Returns:
            标准化后的dict，字段名和值域都符合policy_rules标准。
            仅包含能映射到policy_rules标准字段的条目。

        Examples:
            >>> normalizer = McpResultNormalizer()
            >>> normalizer.normalize({"insurance_type": "城镇职工基本医疗保险", "hospital_level": "三级"})
            {'insu_type': '城镇职工', 'hosp_lv': '三级医院'}

            >>> normalizer.normalize({"fund_type": "310", "yllb": "21", "PER_TYPE": "退休人员"})
            {'insu_type': '城镇职工', 'med_type': '住院-普通住院', 'psn_type': '退休'}
        """
        if not mcp_result:
            return {}

        normalized: dict[str, str] = {}

        for raw_field, raw_value in mcp_result.items():
            # 跳过空值
            if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
                continue

            # 字段名映射：MCP字段 → policy_rules标准字段
            target_field = self._map_field_name(raw_field)
            if target_field is None:
                # 该字段不在映射表中，跳过
                continue

            # 值域标准化
            str_value = str(raw_value).strip()
            standard_value = self.normalize_values(target_field, str_value)

            normalized[target_field] = standard_value

        return normalized

    def normalize_values(self, field: str, raw_value: Any) -> str:
        """
        值域标准化

        将MCP返回的原始值（中文名称或编码）标准化为policy_rules标准值域。

        标准化优先级:
        1. VALUE_MAPPING中的直接映射（中文变体 → 标准值）
        2. CODE_MAPPING中的编码映射（数字/编码 → 标准值）
        3. 无映射时返回原始值（pass-through）

        Args:
            field: 目标字段名（insu_type/med_type/hosp_lv/psn_type/setl_type）
            raw_value: MCP返回的原始值（字符串、数字或编码）

        Returns:
            标准化后的值域字符串

        Examples:
            >>> normalizer = McpResultNormalizer()
            >>> normalizer.normalize_values("insu_type", "职工基本医疗保险")
            '城镇职工'
            >>> normalizer.normalize_values("insu_type", "310")
            '城镇职工'
            >>> normalizer.normalize_values("med_type", "21")
            '住院-普通住院'
        """
        if raw_value is None:
            return ""

        str_value = str(raw_value).strip()
        if not str_value:
            return ""

        # 优先级1: VALUE_MAPPING直接映射
        value_map = self._value_map.get(field, {})
        if str_value in value_map:
            return value_map[str_value]

        # 优先级2: CODE_MAPPING编码映射
        code_map = self._code_map.get(field, {})
        if str_value in code_map:
            return code_map[str_value]

        # 优先级3: 无映射时返回原始值
        return str_value

    # ============================================================
    # 过滤表达式生成
    # ============================================================

    def get_policy_rules_expr(self, mcp_result: dict[str, Any]) -> str:
        """
        从MCP结果生成Milvus标量过滤表达式

        将标准化后的字段组合成Milvus标量过滤表达式，
        用于在Milvus向量检索时进行标量条件过滤。

        Args:
            mcp_result: MCP工具返回的原始JSON结果

        Returns:
            Milvus标量过滤表达式字符串。
            多个条件用"and"连接。
            值用双引号包裹（Milvus字符串字面量格式）。

        Examples:
            >>> normalizer = McpResultNormalizer()
            >>> normalizer.get_policy_rules_expr({"fund_type": "310", "hospital_level": "3"})
            'insu_type == "城镇职工" and hosp_lv == "三级医院"'

        注意:
            - 返回空字符串表示无条件（全量检索）
            - 值中的双引号会被转义
            - Milvus标量过滤语法: field == "value"
        """
        normalized = self.normalize(mcp_result)
        if not normalized:
            return ""

        conditions: list[str] = []
        for field, value in normalized.items():
            # 值中的双引号需要转义
            safe_value = value.replace('"', '\\"')
            conditions.append(f'{field} == "{safe_value}"')

        return " and ".join(conditions)

    # ============================================================
    # 嵌入文本生成
    # ============================================================

    def build_embedding_text(self, normalized: dict[str, str]) -> str:
        """
        从标准化结果构建向量检索用的embedding_text

        将标准化后的字段拼接为自然语言文本，
        用于Milvus向量相似度检索。

        Args:
            normalized: normalizer.normalize()的返回结果

        Returns:
            可用于向量化的文本字符串。
            格式: "险种：城镇职工 | 医疗类别：住院-普通住院 | ..."

        Examples:
            >>> normalizer = McpResultNormalizer()
            >>> result = normalizer.normalize({"fund_type": "310", "yllb": "21"})
            >>> normalizer.build_embedding_text(result)
            '险种：城镇职工 | 医疗类别：住院-普通住院'
        """
        if not normalized:
            return ""

        # 字段 → 中文标签映射
        field_labels: dict[str, str] = {
            "insu_type": "险种",
            "med_type": "医疗类别",
            "hosp_lv": "医院等级",
            "psn_type": "人群标签",
            "setl_type": "结算方式",
        }

        parts: list[str] = []
        for field, value in normalized.items():
            label = field_labels.get(field, field)
            if value:
                parts.append(f"{label}：{value}")

        return " | ".join(parts)

    # ============================================================
    # 配置加载与动态扩展
    # ============================================================

    def load_mapping_from_yaml(self, yaml_path: str | Path) -> None:
        """
        从YAML配置文件加载映射规则

        YAML文件格式::

            # 字段名映射：MCP字段 → policy_rules字段
            field_mapping:
              custom_field1: insu_type
              custom_field2: hosp_lv

            # 值域标准化映射：原始值 → 标准值
            value_mapping:
              insu_type:
                新农合: 城乡居民
                新型农村合作医疗: 城乡居民

            # 代码值映射：编码 → 标准值
            code_mapping:
              med_type:
                "31": 住院-普通住院
                "32": 住院-单病种

        Args:
            yaml_path: YAML配置文件的路径

        Raises:
            FileNotFoundError: 配置文件不存在
            RuntimeError: PyYAML未安装或YAML格式错误
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"映射配置文件不存在: {yaml_path}")

        text = path.read_text(encoding="utf-8")

        try:
            import yaml
        except ImportError as e:
            raise RuntimeError("读取YAML配置文件需要安装PyYAML: pip install pyyaml") from e

        try:
            config = yaml.safe_load(text)
        except Exception as e:
            raise RuntimeError(f"YAML配置文件格式错误: {e}") from e

        if not config or not isinstance(config, dict):
            return

        # 加载字段名映射
        field_mapping = config.get("field_mapping")
        if isinstance(field_mapping, dict):
            for mcp_field, policy_field in field_mapping.items():
                if isinstance(mcp_field, str) and isinstance(policy_field, str):
                    self.add_field_mapping(mcp_field, policy_field)

        # 加载值域标准化映射
        value_mapping = config.get("value_mapping")
        if isinstance(value_mapping, dict):
            for field, mappings in value_mapping.items():
                if isinstance(field, str) and isinstance(mappings, dict):
                    for raw_value, standard_value in mappings.items():
                        if isinstance(raw_value, str) and isinstance(standard_value, str):
                            self.add_value_mapping(field, raw_value, standard_value)

        # 加载代码值映射
        code_mapping = config.get("code_mapping")
        if isinstance(code_mapping, dict):
            for field, mappings in code_mapping.items():
                if isinstance(field, str) and isinstance(mappings, dict):
                    for code, standard_value in mappings.items():
                        code_str = str(code)
                        if isinstance(standard_value, str):
                            self.add_value_mapping(field, code_str, standard_value)
                            # 同时写入_code_map以供优先级区分
                            if field not in self._code_map:
                                self._code_map[field] = {}
                            self._code_map[field][code_str] = standard_value

    def add_field_mapping(self, mcp_field: str, policy_field: str) -> None:
        """
        动态添加字段映射

        注册MCP返回的字段名到policy_rules标准字段名的映射关系。

        Args:
            mcp_field: MCP返回的原始字段名
            policy_field: policy_rules标准字段名（如 insu_type/med_type/hosp_lv/psn_type/setl_type）
        """
        self._field_map[mcp_field] = policy_field

    def add_value_mapping(self, policy_field: str, raw_value: str, standard_value: str) -> None:
        """
        动态添加值域映射

        注册某个字段的原始值到标准值的映射关系。

        Args:
            policy_field: policy_rules标准字段名
            raw_value: MCP返回的原始值（中文名称或编码）
            standard_value: 标准化的值域
        """
        if policy_field not in self._value_map:
            self._value_map[policy_field] = {}
        self._value_map[policy_field][raw_value] = standard_value

    # ============================================================
    # 内部方法
    # ============================================================

    def _map_field_name(self, raw_field: str) -> str | None:
        """
        将MCP返回的原始字段名映射为policy_rules标准字段名

        Args:
            raw_field: MCP返回的原始字段名

        Returns:
            标准化后的字段名，如果找不到映射则返回None
        """
        # 精确匹配
        if raw_field in self._field_map:
            return self._field_map[raw_field]

        # 全大写匹配（如 "PER_TYPE" → "psn_type"）
        upper_field = raw_field.upper()
        if upper_field in self._field_map:
            return self._field_map[upper_field]

        # 全小写匹配（如 "per_type" → "psn_type"）
        lower_field = raw_field.lower()
        if lower_field in self._field_map:
            return self._field_map[lower_field]

        # 去掉下划线后匹配（如 "PER_TYPE" → "PERTYPE"）
        no_underscore = raw_field.replace("_", "").replace("-", "")
        if no_underscore in self._field_map:
            return self._field_map[no_underscore]

        upper_no_underscore = no_underscore.upper()
        if upper_no_underscore in self._field_map:
            return self._field_map[upper_no_underscore]

        lower_no_underscore = no_underscore.lower()
        if lower_no_underscore in self._field_map:
            return self._field_map[lower_no_underscore]

        return None
