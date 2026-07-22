"""
Tests for UnifiedRouter — 统一的评分制技能路由。

测试分类：
  ① _compute_keyword_score — 评分函数单元测试
  ② route_question_ranked — 排序与过滤
  ③ route_question_best — 最佳匹配与阈值
  ④ SkillMatch — 数据类行为
  ⑤ 真实技能评分验证

注意：
  - _compute_keyword_score 是纯函数，无需依赖全局状态
  - route_question_ranked / route_question_best 依赖 get_loader()
  - 隔离测试使用 importable_skills_dir fixture
"""

import json
from pathlib import Path

import pytest
import yaml

from src.skill_infra.unified_router import (
    SkillMatch,
    _compute_keyword_score,
    route_question_ranked,
    route_question_best,
)
from src.skill_infra.skill_loader import LoadedSkill, SkillLoader, get_loader
import src.skill_infra.skill_loader as sl_mod


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════

def _make_skill(
    skill_id: str = "test_skill",
    name: str = "Test",
    keywords: list[str] | None = None,
    exclusions: list[str] | None = None,
) -> LoadedSkill:
    """快速构建 LoadedSkill（无需文件系统）。"""
    return LoadedSkill(
        skill_id=skill_id,
        skill_name=name,
        assembler=object(),
        manifest={},
        include_keywords=keywords or [],
        excluded_intents=exclusions or [],
    )


# ═══════════════════════════════════════════════════════════════════
# ① _compute_keyword_score — 评分函数单元测试
# ═══════════════════════════════════════════════════════════════════

class TestComputeKeywordScore:
    """_compute_keyword_score() 评分函数正确性。"""

    def test_exact_match_gives_positive_score(self):
        """问题完整匹配关键词返回正分。"""
        skill = _make_skill(keywords=["统筹自付"])
        score, matched = _compute_keyword_score("统筹自付", skill)
        assert score > 0.0
        assert matched == ["统筹自付"]

    def test_partial_keyword_match(self):
        """问题包含部分关键词返回正分。"""
        skill = _make_skill(keywords=["统筹自付", "起付线", "大额自付"])
        score, matched = _compute_keyword_score("我的统筹自付怎么算", skill)
        assert score > 0.0
        assert "统筹自付" in matched

    def test_no_match_returns_zero(self):
        skill = _make_skill(keywords=["统筹自付", "起付线"])
        score, matched = _compute_keyword_score("今天天气怎么样", skill)
        assert score == 0.0
        assert matched == []

    def test_empty_keywords_returns_zero(self):
        skill = _make_skill(keywords=[])
        score, matched = _compute_keyword_score("任何问题", skill)
        assert score == 0.0
        assert matched == []

    def test_empty_question_returns_zero(self):
        skill = _make_skill(keywords=["统筹自付"])
        score, matched = _compute_keyword_score("", skill)
        assert score == 0.0
        assert matched == []

    def test_whitespace_question_returns_zero(self):
        skill = _make_skill(keywords=["统筹自付"])
        score, matched = _compute_keyword_score("   ", skill)
        assert score == 0.0
        assert matched == []

    def test_exclusion_penalizes_confidence(self):
        """排除词匹配后 confidence × 0.3。"""
        skill = _make_skill(keywords=["医保", "报销"], exclusions=["自费"])
        score_no_exclusion, _ = _compute_keyword_score("医保相关", skill)
        score_with_exclusion, _ = _compute_keyword_score("自费医保", skill)
        assert score_with_exclusion == pytest.approx(score_no_exclusion * 0.3, rel=0.01)

    def test_exclusion_no_penalty_when_not_matched(self):
        """不匹配排除词时正常评分。"""
        skill = _make_skill(keywords=["医保"], exclusions=["自费"])
        score, matched = _compute_keyword_score("医保报销", skill)
        assert score > 0.0

    def test_empty_exclusions(self):
        """空排除列表不影响评分。"""
        skill = _make_skill(keywords=["医保"], exclusions=[])
        score, matched = _compute_keyword_score("医保", skill)
        assert score > 0.0
        assert matched == ["医保"]

    def test_case_insensitive_matching(self):
        """关键词匹配不区分大小写。"""
        skill = _make_skill(keywords=["MEDICAL", "Insurance"])
        score, matched = _compute_keyword_score("medical insurance claim", skill)
        assert score > 0.0
        assert "medical" in [kw.lower() for kw in matched]

    def test_confidence_finite(self):
        """confidence 值应为有限浮点数。"""
        import math
        skill = _make_skill(keywords=["统筹自付", "起付线"])
        score, _ = _compute_keyword_score("统筹自付", skill)
        assert isinstance(score, float)
        assert math.isfinite(score)


# ═══════════════════════════════════════════════════════════════════
# ② route_question_ranked — 排序与过滤
# ═══════════════════════════════════════════════════════════════════

class TestRouteQuestionRanked:
    """route_question_ranked() 排序和过滤行为。"""

    def test_returns_sorted_by_confidence(self):
        """返回结果按 confidence 降序排列。"""
        results = route_question_ranked("统筹自付")
        assert len(results) >= 1
        for i in range(len(results) - 1):
            assert results[i].confidence >= results[i + 1].confidence

    def test_policy_fee_is_top_for_medical_question(self):
        results = route_question_ranked("统筹自付")
        assert results[0].skill_id == "settlement_explain_skill"

    def test_returns_skillmatch_objects(self):
        results = route_question_ranked("起付线")
        assert all(isinstance(r, SkillMatch) for r in results)

    def test_min_confidence_excludes_low_matches(self):
        """min_confidence 阈值过滤低分匹配。"""
        results_all = route_question_ranked("统筹自付", min_confidence=0.0)
        results_filtered = route_question_ranked("统筹自付", min_confidence=0.5)
        assert len(results_filtered) <= len(results_all)

    def test_empty_question_returns_empty(self):
        assert route_question_ranked("") == []

    def test_no_match_returns_empty(self):
        assert route_question_ranked("QQ群年wwwe") == []

    def test_confidence_values_are_finite(self):
        """confidence 值应为有限浮点数。"""
        import math
        results = route_question_ranked("统筹自付")
        for r in results:
            assert math.isfinite(r.confidence)

    def test_matched_keywords_filled(self):
        results = route_question_ranked("统筹自付")
        assert len(results[0].matched_keywords) > 0


# ═══════════════════════════════════════════════════════════════════
# ③ route_question_best — 最佳匹配与阈值
# ═══════════════════════════════════════════════════════════════════

class TestRouteQuestionBest:
    """route_question_best() 返回最佳 skill_id 或 None。"""

    def test_returns_string_for_match(self):
        result = route_question_best("统筹自付怎么算")
        assert isinstance(result, str)
        assert result == "settlement_explain_skill"

    def test_returns_none_for_no_match(self):
        assert route_question_best("今天天气怎么样") is None

    def test_returns_none_for_empty(self):
        assert route_question_best("") is None

    def test_below_threshold_returns_none(self):
        """低于默认阈值 0.1 应返回 None。"""
        assert route_question_best("FileNotFoundError") is None
        assert route_question_best("阿") is None


class TestRouteQuestionBestIsolated:
    """隔离环境中测试 route_question_best 的阈值行为。"""

    @pytest.fixture
    def thin_skill_loader(self, importable_skills_dir):
        """创建一个仅含少量关键词的 importable skill。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill("thin_skill", intents=["SQL", "database"])

        saved = sl_mod._loader
        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        sl_mod._loader = loader
        yield loader
        sl_mod._loader = saved

    def test_match_above_threshold(self, thin_skill_loader):
        """匹配分数 ≥ 0.1 时返回 skill_id。"""
        result = route_question_best("SQL query")
        assert result == "thin_skill"

    def test_below_threshold_returns_none(self, thin_skill_loader):
        """匹配分数 < 0.1 时返回 None。"""
        result = route_question_best("S")
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# ④ SkillMatch — 数据类行为
# ═══════════════════════════════════════════════════════════════════

class TestSkillMatchExtended:
    """SkillMatch 的额外行为验证。"""

    def test_equality(self):
        m1 = SkillMatch("s", "n", 0.5, ["kw"])
        m2 = SkillMatch("s", "n", 0.5, ["kw"])
        assert m1 == m2

    def test_ordering(self):
        """SkillMatch 可通过 confidence 排序。"""
        matches = [
            SkillMatch("a", "A", 0.3),
            SkillMatch("b", "B", 0.9),
            SkillMatch("c", "C", 0.5),
        ]
        sorted_m = sorted(matches, key=lambda m: m.confidence, reverse=True)
        assert [m.skill_id for m in sorted_m] == ["b", "c", "a"]

    def test_to_dict_roundtrip(self):
        m = SkillMatch("test", "Test", 0.75, ["kw1", "kw2"], "keyword")
        d = m.to_dict()
        restored = SkillMatch(**d)
        assert restored == m

    def test_repr(self):
        m = SkillMatch("test", "Test", 0.5)
        r = repr(m)
        assert "test" in r
        assert "0.5" in r


# ═══════════════════════════════════════════════════════════════════
# ⑤ 真实技能评分验证
# ═══════════════════════════════════════════════════════════════════

class TestRealSkillScoring:
    """用真实 settlement_explain_skill 验证评分行为。"""

    def test_tongchou_zifu_high_confidence(self):
        """统筹自付作为完整词匹配 → confidence > 0.1（路由阈值）。"""
        results = route_question_ranked("统筹自付")
        top = results[0]
        assert top.skill_id == "settlement_explain_skill"
        assert top.confidence > 0.1

    def test_complex_question_still_matches(self):
        """长复合问句仍能返回 settlement_explain_skill。"""
        question = "我这次住院的统筹自付为什么这么多，起付线是多少"
        result = route_question_best(question)
        assert result == "settlement_explain_skill"

    def test_short_question_matches(self):
        result = route_question_best("起付线")
        assert result == "settlement_explain_skill"

    def test_confidence_positive_for_matching_question(self):
        """匹配的问题给出正置信度。"""
        results = route_question_ranked("统筹自付")
        assert results[0].confidence > 0.0

    def test_more_keywords_in_question_gives_positive_score(self):
        """包含更多关键词的问题给出正分。"""
        r1 = route_question_ranked("统筹自付")
        r2 = route_question_ranked("起付线")
        r3 = route_question_ranked("统筹自付起付线报销比例")
        assert r1[0].confidence > 0.0
        assert r2[0].confidence > 0.0
        assert r3[0].confidence > 0.0
