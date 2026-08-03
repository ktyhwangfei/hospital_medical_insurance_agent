"""
Skill 能力矩阵匹配度测试（T1 单元）。

覆盖：
- skill_manifest.yaml 声明的 (business_action, business_object) 在 VALID_ACTION_OBJECT_PAIRS 白名单中
- SkillLoader 加载的所有 skill 均通过白名单校验
- 关键词覆盖基本检查
- 输出无 forbidden tokens
"""

import pytest
from src.domain.common.actions import (
    BusinessAction, BusinessObject, is_valid_action_object,
)
from src.skill_infra.skill_loader import get_loader
from skills.settlement_explain_skill.strategies.registry import list_strategies, get_strategy

# skill_manifest.yaml 中定义的 forbidden_output 模式
FORBIDDEN_OUTPUT_PATTERNS = [
    "if t.",
    "undefined",
    '"null"',
    "None",
    '"NaN"',
    '{"ratio"',
    "embedding_text",
    "Milvus score",
]


class TestManifestWhiteList:
    """manifest 声明的 Action-Object 组合在能力矩阵白名单中。"""

    def test_settlement_explain_skill_in_whitelist(self):
        """settlement_explain_skill 的 (explain, settlement) 应在白名单中。"""
        loader = get_loader()
        skill = loader.get("settlement_explain_skill")
        assert skill is not None, "settlement_explain_skill 未被 SkillLoader 加载"
        action = BusinessAction(skill.business_action)
        obj = BusinessObject(skill.business_object)
        assert is_valid_action_object(action, obj), (
            f"({skill.business_action}, {skill.business_object}) 不在能力矩阵白名单中"
        )

    def test_all_loaded_skills_valid(self):
        """所有 SkillLoader 加载的 skill 都应在白名单中。"""
        loader = get_loader()
        for skill_id in loader.get_all():
            skill = loader.get(skill_id)
            if skill.business_action and skill.business_object:
                action = BusinessAction(skill.business_action)
                obj = BusinessObject(skill.business_object)
                assert is_valid_action_object(action, obj), (
                    f"Skill '{skill_id}': ({skill.business_action}, "
                    f"{skill.business_object}) 不在能力矩阵白名单中"
                )

    def test_business_action_is_valid_enum(self):
        """manifest 声明的 business_action 是有效的 BusinessAction 枚举值。"""
        loader = get_loader()
        for skill_id in loader.get_all():
            skill = loader.get(skill_id)
            if skill.business_action:
                assert skill.business_action in BusinessAction.__members__.values(), (
                    f"Skill '{skill_id}': business_action='{skill.business_action}' "
                    f"不是有效的 BusinessAction"
                )

    def test_business_object_is_valid_enum(self):
        """manifest 声明的 business_object 是有效的 BusinessObject 枚举值。"""
        loader = get_loader()
        for skill_id in loader.get_all():
            skill = loader.get(skill_id)
            if skill.business_object:
                assert skill.business_object in BusinessObject.__members__.values(), (
                    f"Skill '{skill_id}': business_object='{skill.business_object}' "
                    f"不是有效的 BusinessObject"
                )


class TestKeywordCoverage:
    """关键词覆盖基本检查。"""

    def test_supported_intents_not_empty(self):
        """supported_intents 不应为空。"""
        loader = get_loader()
        skill = loader.get("settlement_explain_skill")
        assert skill.include_keywords, "supported_intents 为空"
        assert len(skill.include_keywords) >= 10, (
            f"supported_intents 只有 {len(skill.include_keywords)} 个词，预期 ≥ 10"
        )

    def test_common_user_questions_hit(self):
        """常见用户问题应命中关键词。"""
        loader = get_loader()
        skill = loader.get("settlement_explain_skill")
        keywords = skill.include_keywords

        # 这些常见问题至少命中 1 个关键词
        test_questions = [
            ("我的统筹自付怎么这么多", True),    # 应命中"统筹自付"
            ("起付线是什么意思", True),          # 应命中"起付线"
            ("报销比例怎么算", True),             # 应命中"报销比例"
            ("门槛费是多少", True),               # 应命中"门槛费"
        ]

        for question, should_hit in test_questions:
            hit = any(kw in question for kw in keywords)
            if should_hit:
                assert hit, (
                    f"问题 '{question}' 未命中任何关键词，"
                    f"supported_intents={keywords}"
                )


class TestOutputNoForbiddenTokens:
    """输出不包含 forbidden tokens（模板代码泄漏检查）。"""

    @pytest.mark.parametrize("fee_item", list_strategies())
    def test_patient_answer_no_forbidden(self, fee_item, settlement_context, mock_evidence):
        """patient_answer 不应包含 forbidden tokens。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        for pattern in FORBIDDEN_OUTPUT_PATTERNS:
            assert pattern not in result.patient_answer, (
                f"{fee_item}.patient_answer 包含禁止内容: '{pattern}'"
            )

    @pytest.mark.parametrize("fee_item", list_strategies())
    def test_office_answer_no_forbidden(self, fee_item, settlement_context, mock_evidence):
        """office_answer 不应包含 forbidden tokens。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        for pattern in FORBIDDEN_OUTPUT_PATTERNS:
            assert pattern not in result.office_answer, (
                f"{fee_item}.office_answer 包含禁止内容: '{pattern}'"
            )


class TestRegistry:
    """Strategy registry 基础测试。"""

    def test_list_strategies_returns_all_6(self):
        strategies = list_strategies()
        assert len(strategies) == 6
        expected = {
            "pooling_self_pay", "deductible", "large_amount_self_pay",
            "out_of_scope", "pooling_payment", "personal_total_pay",
        }
        assert set(strategies) == expected

    def test_get_strategy_returns_same_instance(self):
        """get_strategy() 应返回同一实例（缓存）。"""
        s1 = get_strategy("pooling_self_pay")
        s2 = get_strategy("pooling_self_pay")
        assert s1 is s2, "get_strategy() 应返回缓存的同一实例"
