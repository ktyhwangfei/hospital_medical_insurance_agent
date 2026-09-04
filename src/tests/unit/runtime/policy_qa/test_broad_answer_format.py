"""Issue #33 宽泛问题回答格式：按人群分组 + 出处标注（加固⑤）。

面向用户以职工/居民两大人群为主：回答必须分组呈现且每条标注来源
（险种·规则类型·施行年份），与政策原文的严谨表述习惯对齐。
"""

from src.runtime.api.policy_qa_routes import (
    _fallback_broad_answer,
    _source_attribution,
)


def _ev(source_text: str, insu_type: str, rule_type: str = "支付比例", effective_date: str = "2001-04-01"):
    return {
        "source_text": source_text,
        "insu_type": insu_type,
        "rule_type": rule_type,
        "effective_date": effective_date,
        "title": source_text,
        "score": 1.0,
    }


class TestSourceAttribution:
    def test_attribution_insu_ruletype_year(self):
        attr = _source_attribution(
            _ev("统筹基金支付70%，个人支付30%。", "城镇职工基本医疗保险", effective_date="2001-04-01")
        )
        assert "职工医保" in attr
        assert "支付比例" in attr
        assert "2001年施行" in attr

    def test_attribution_resident_short_name(self):
        attr = _source_attribution(_ev("起付标准以上支付55%", "城乡居民基本医疗保险"))
        assert attr.startswith("居民医保")

    def test_attribution_empty_date_omits_year(self):
        attr = _source_attribution(_ev("按标注比例执行。", "", effective_date=""))
        assert "施行" not in attr


class TestFallbackBroadAnswer:
    def test_fallback_groups_by_insu_with_employee_first(self):
        """回答按险种分组呈现：职工医保在前、居民医保在后，两组都必须出现。"""
        answer = _fallback_broad_answer(
            [
                _ev("统筹基金支付70%，个人支付30%。", "城镇职工基本医疗保险"),
                _ev("起付标准以上支付55%", "城乡居民基本医疗保险"),
                _ev("统筹基金支付60%，个人支付40%。", "城镇职工基本医疗保险"),
            ]
        )
        assert "【职工医保】" in answer
        assert "【居民医保】" in answer
        assert answer.index("【职工医保】") < answer.index("【居民医保】")
        # 分组内条目带出处标注
        assert answer.count("出处：") == 3
        assert "职工医保·支付比例（2001年施行）" in answer

    def test_fallback_empty_evidence_safe(self):
        answer = _fallback_broad_answer([])
        assert "未检索到" in answer
