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


class TestFormatBroadEvidence:
    def test_dedupes_identical_source_text(self):
        """完全重复的 source_text 只保留一条，避免答案出现 3/4 完全相同的条目。"""
        from src.runtime.api.policy_qa_routes import _format_broad_evidence

        answer = _format_broad_evidence(
            [
                _ev("统筹基金支付90%，个人支付10%。", "城镇职工基本医疗保险"),
                _ev("统筹基金支付90%，个人支付10%。", "城镇职工基本医疗保险"),
            ]
        )
        # 两条去重后只剩一条
        assert answer.count("统筹基金支付90%") == 1

    def test_includes_context_dimensions(self):
        """规则后补充医疗类别/医院等级/人员类别，解决'只有比例没有背景'。"""
        from src.runtime.api.policy_qa_routes import _format_broad_evidence

        answer = _format_broad_evidence(
            [
                {
                    **_ev("统筹基金支付70%，个人支付30%。", "城镇职工基本医疗保险"),
                    "med_type": "门诊-普通门急诊",
                    "hosp_lv": "三级医院",
                    "psn_type": "在职职工",
                },
            ]
        )
        assert "适用：门诊-普通门急诊 / 三级医院 / 在职职工" in answer


class TestDocEnrichment:
    def test_enrich_evidence_adds_title_and_excerpt(self, monkeypatch):
        from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore
        from src.runtime.api import policy_qa_routes

        def _fake_get_document(self, doc_id: str):
            return {
                "title": "北京市基本医疗保险规定",
                "content_text": "在本市定点医疗机构就医的在职职工，门诊医疗费用统筹基金支付60%，个人支付40%。",
            }

        monkeypatch.setattr(PipelineStore, "get_document", _fake_get_document)
        enriched = policy_qa_routes._enrich_broad_evidence_with_docs(
            [{**_ev("统筹基金支付60%，个人支付40%。", "城镇职工基本医疗保险"), "doc_id": "doc_001"}]
        )
        assert enriched[0]["doc_title"] == "北京市基本医疗保险规定"
        assert "统筹基金支付60%" in enriched[0]["doc_excerpt"]

    def test_format_includes_doc_title(self):
        from src.runtime.api.policy_qa_routes import _format_broad_evidence

        answer = _format_broad_evidence(
            [
                {
                    "source_text": "统筹基金支付60%，个人支付40%。",
                    "insu_type": "城镇职工基本医疗保险",
                    "rule_type": "支付比例",
                    "effective_date": "2001-04-01",
                    "doc_title": "北京市基本医疗保险规定",
                }
            ]
        )
        assert "北京市基本医疗保险规定" in answer


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
