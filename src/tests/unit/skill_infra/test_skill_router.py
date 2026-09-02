"""
Tests for SkillRouter — 将用户问题路由到对应 skill。

测试分类：
  ① route_question — 关键词匹配路由（使用真实 skills 目录）
  ② route_question — 边界条件（空/无关）
  ③ route_question_with_scores — 排序评分
  ④ get_assembler — assembler 获取
  ⑤ list_skills — 技能列表
  ⑥ SkillMatch — 数据结构
  ⑦ 隔离环境（importable temp skills）
"""

import json
from pathlib import Path

import pytest
import yaml

from src.skill_infra.skill_router import (
    route_question,
    route_question_with_scores,
    get_assembler,
    list_skills,
)
from src.skill_infra.unified_router import SkillMatch, route_question_best, route_question_ranked
from src.skill_infra.skill_loader import SkillLoader

import src.skill_infra.skill_loader as sl_mod


# ═══════════════════════════════════════════════════════════════════
# ① route_question — 关键词匹配路由（真实 skills）
# ═══════════════════════════════════════════════════════════════════

class TestRouteQuestion:
    """route_question() 基于评分返回最佳 skill_id。"""

    def test_matches_tongchou_zifu(self):
        """"统筹自付" → settlement_explain_skill。"""
        result = route_question("我的统筹自付为什么这么多")
        assert result == "settlement_explain_skill"

    def test_matches_qifu_xian(self):
        """起付线 → settlement_explain_skill。"""
        result = route_question("起付线是怎么计算的")
        assert result == "settlement_explain_skill"

    def test_matches_dae_zifu(self):
        """大额自付 → settlement_explain_skill。"""
        result = route_question("大额自付是什么意思")
        assert result == "settlement_explain_skill"

    def test_matches_tongchou_zhifu(self):
        """统筹支付 → settlement_explain_skill。"""
        result = route_question("统筹支付是怎么算的")
        assert result == "settlement_explain_skill"

    def test_matches_baoxiao_bili(self):
        """报销比例 → settlement_explain_skill。"""
        result = route_question("报销比例是多少")
        assert result == "settlement_explain_skill"

    def test_matches_weishenme_zhemeduo(self):
        """"为什么这么多" → settlement_explain_skill。"""
        result = route_question("为什么统筹自付这么多")
        assert result == "settlement_explain_skill"

    @pytest.mark.parametrize("question", ["部分项目预退费分析", "这笔费用做退费试算"])
    def test_draft_outpatient_pre_refund_skill_is_not_routable(self, question):
        assert route_question(question) != "outpatient_pre_refund_analysis_skill"


# ═══════════════════════════════════════════════════════════════════
# ② route_question — 边界条件（空/无关）
# ═══════════════════════════════════════════════════════════════════

class TestRouteQuestionEdgeCases:
    """route_question() 边界条件应返回 None。"""

    def test_empty_string(self):
        assert route_question("") is None

    def test_whitespace_only(self):
        assert route_question("   ") is None

    def test_unrelated_question(self):
        """无关问题返回 None。"""
        assert route_question("今天天气怎么样") is None

    def test_english_only(self):
        assert route_question("hello world this is a test") is None

    def test_numbers_only(self):
        assert route_question("123456") is None

    def test_noise_chars(self):
        assert route_question("!@#$%^&*()") is None


# ═══════════════════════════════════════════════════════════════════
# ③ route_question_with_scores — 排序评分
# ═══════════════════════════════════════════════════════════════════

class TestRouteQuestionWithScores:
    """route_question_with_scores() 返回排序后的评分列表。"""

    def test_returns_list_of_skillmatch(self):
        """返回 list[SkillMatch] 类型。"""
        results = route_question_with_scores("统筹自付怎么算")
        assert isinstance(results, list)
        assert len(results) >= 1
        assert isinstance(results[0], SkillMatch)

    def test_top_match_is_settlement_explain_skill(self):
        results = route_question_with_scores("统筹自付")
        assert results[0].skill_id == "settlement_explain_skill"
        assert results[0].confidence > 0.0

    def test_results_sorted_by_confidence_desc(self):
        """按 confidence 降序排列。"""
        results = route_question_with_scores("统筹自付")
        for i in range(len(results) - 1):
            assert results[i].confidence >= results[i + 1].confidence

    def test_matched_keywords_are_present(self):
        results = route_question_with_scores("统筹自付")
        match = results[0]
        assert len(match.matched_keywords) > 0
        assert match.match_method == "keyword"

    def test_min_confidence_filters_results(self):
        results_0 = route_question_with_scores("统筹自付", min_confidence=0.0)
        results_high = route_question_with_scores("统筹自付", min_confidence=0.5)
        assert len(results_0) >= len(results_high)

    def test_no_match_returns_empty_list(self):
        results = route_question_with_scores("今天天气怎么样")
        assert results == []

    def test_empty_string_returns_empty_list(self):
        results = route_question_with_scores("")
        assert results == []


# ═══════════════════════════════════════════════════════════════════
# ④ get_assembler — assembler 获取
# ═══════════════════════════════════════════════════════════════════

class TestGetAssembler:
    """get_assembler() 返回正确的 assembler 实例。"""

    def test_returns_assembler_for_known_skill(self):
        assembler = get_assembler("settlement_explain_skill")
        assert assembler is not None
        assert hasattr(assembler, "execute")
        assert hasattr(assembler, "build_policy_queries")

    def test_returns_none_for_unknown(self):
        assert get_assembler("nonexistent_skill_xyz") is None

    def test_assembler_execute_returns_result(self):
        """返回的 assembler 可以调用 execute。"""
        assembler = get_assembler("settlement_explain_skill")
        result = assembler.execute(
            settlement_context=object(),
            policy_evidence=[],
            policy_status="no_policy_matched",
            target_fee_item="pooling_self_pay",
        )
        assert result is not None


# ═══════════════════════════════════════════════════════════════════
# ⑤ list_skills — 技能列表
# ═══════════════════════════════════════════════════════════════════

class TestListSkills:
    """list_skills() 返回结构正确的技能列表。"""

    def test_returns_list_of_dicts(self):
        skills = list_skills()
        assert isinstance(skills, list)
        assert len(skills) >= 1
        assert isinstance(skills[0], dict)

    def test_contains_required_keys(self):
        skills = list_skills()
        required_keys = {"skill_id", "skill_name", "include_keywords", "excluded_intents"}
        for skill in skills:
            assert required_keys.issubset(skill.keys())

    def test_includes_settlement_explain_skill(self):
        skills = list_skills()
        skill_ids = [s["skill_id"] for s in skills]
        assert "settlement_explain_skill" in skill_ids

    def test_include_keywords_are_list(self):
        skills = list_skills()
        fee_skill = next(s for s in skills if s["skill_id"] == "settlement_explain_skill")
        assert isinstance(fee_skill["include_keywords"], list)
        assert len(fee_skill["include_keywords"]) > 0
        assert "统筹自付" in fee_skill["include_keywords"]


# ═══════════════════════════════════════════════════════════════════
# ⑥ SkillMatch — 数据结构
# ═══════════════════════════════════════════════════════════════════

class TestSkillMatch:
    """SkillMatch 数据类及其 to_dict()。"""

    def test_to_dict_returns_correct_structure(self):
        match = SkillMatch(
            skill_id="test_skill",
            skill_name="测试技能",
            confidence=0.85,
            matched_keywords=["关键词A", "关键词B"],
            match_method="keyword",
        )
        d = match.to_dict()
        assert d["skill_id"] == "test_skill"
        assert d["skill_name"] == "测试技能"
        assert d["confidence"] == 0.85
        assert d["matched_keywords"] == ["关键词A", "关键词B"]
        assert d["match_method"] == "keyword"

    def test_to_dict_default_values(self):
        match = SkillMatch(skill_id="s", skill_name="n")
        d = match.to_dict()
        assert d["confidence"] == 0.0
        assert d["matched_keywords"] == []
        assert d["match_method"] == "keyword"

    def test_to_dict_serializable(self):
        """to_dict() 返回 JSON 可序列化。"""
        match = SkillMatch(
            skill_id="s",
            skill_name="n",
            confidence=0.5,
            matched_keywords=["kw"],
        )
        json_str = json.dumps(match.to_dict(), ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed["skill_id"] == "s"
        assert parsed["confidence"] == 0.5


# ═══════════════════════════════════════════════════════════════════
# ⑦ 隔离环境（importable temp skills）
# ═══════════════════════════════════════════════════════════════════

class TestRouteQuestionIsolated:
    """在 importable 临时目录中测试路由逻辑的隔离性。"""

    @pytest.fixture
    def isolated_skills(self, importable_skills_dir):
        """创建两个 importable 的 temp skill 并替换全局 singleton。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill("fee_skill", intents=["统筹自付", "起付线", "报销比例"])
        create_skill("weather_skill", intents=["天气", "温度", "下雨"])

        saved = sl_mod._loader
        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        sl_mod._loader = loader
        yield loader
        sl_mod._loader = saved

    def test_route_to_fee_skill(self, isolated_skills):
        assert route_question("统筹自付怎么算") == "fee_skill"

    def test_route_to_weather_skill(self, isolated_skills):
        assert route_question("今天天气怎么样") == "weather_skill"

    def test_no_match_returns_none(self, isolated_skills):
        assert route_question("与关键词完全无关的内容") is None

    def test_route_question_with_scores_isolated(self, isolated_skills):
        results = route_question_with_scores("统筹自付")
        assert len(results) >= 1
        assert results[0].skill_id == "fee_skill"

    def test_list_skills_isolated(self, isolated_skills):
        skills = list_skills()
        skill_ids = {s["skill_id"] for s in skills}
        assert "fee_skill" in skill_ids
        assert "weather_skill" in skill_ids

    def test_get_assembler_isolated(self, isolated_skills):
        assert get_assembler("fee_skill") is not None
        assert get_assembler("weather_skill") is not None
        assert get_assembler("nonexistent") is None


class TestExcludedIntents:
    """excluded_intents 降权逻辑在路由中的体现。"""

    @pytest.fixture
    def exclusion_skills(self, importable_skills_dir):
        """创建一个带排除词的 skill。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill("exclusion_skill", intents=["医保", "报销"], exclusions=["自费"])

        saved = sl_mod._loader
        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        sl_mod._loader = loader
        yield loader
        sl_mod._loader = saved

    def test_excluded_intent_lowers_confidence(self, exclusion_skills):
        """排除词降低置信度，但不阻断路由。"""
        results_normal = route_question_ranked("医保相关", min_confidence=0.0)
        assert len(results_normal) > 0
        normal_conf = results_normal[0].confidence

        results_excluded = route_question_ranked("自费医保", min_confidence=0.0)
        assert len(results_excluded) > 0
        excluded_conf = results_excluded[0].confidence

        assert excluded_conf < normal_conf

    def test_exclusion_does_not_block_completely(self, exclusion_skills):
        """排除词仅降权（×0.3），不阻断匹配。"""
        results = route_question_ranked("医保自费项目", min_confidence=0.0)
        assert len(results) > 0
