"""Issue #33 路由/拒答最小实现 T1：三判据守卫 + 路由函数单元测试。

对应 docs/issue33-router-dispatch.md：
- 三判据（时间/版本、地域、范围）各 ≥3 条：正常命中 / 阈值边缘 / 空输入与异常值
- 路由函数：A 直接 structured、B 路由 structured、C 拒答、结构化漏空→拒答；audit 位写对
- 条件1：broad 兜底分支产出空 + 有 audit 记录，绝不回落 broad 自由检索
"""

from types import SimpleNamespace

from src.runtime.policy_qa import broad_query_router
from src.runtime.policy_qa.broad_query_router import (
    EMPTY_QUESTION_REFUSAL_MESSAGE,
    REGION_REFUSAL_MESSAGE,
    ROUTING_MIN_CONFIDENCE,
    SCOPE_REFUSAL_MESSAGE,
    STRUCTURED_MISS_REFUSAL_MESSAGE,
    TIME_VERSION_REFUSAL_MESSAGE,
    BroadRouteDecision,
    check_region_criterion,
    check_scope_criterion,
    check_time_version_criterion,
    route_broad_question,
)


def _fake_retrieve(evidence_scores: list[float]):
    """构造返回指定分数证据的 structured_retrieve 假实现。"""

    def _retrieve(decision: BroadRouteDecision):
        return SimpleNamespace(
            selected_evidence=[SimpleNamespace(score=s) for s in evidence_scores]
        )

    return _retrieve


class TestTimeVersionCriterion:
    """时间/版本判据：语料全 published+expiry=9999，不存在其他时间档实体。"""

    def test_hits_repealed_year(self):
        assert check_time_version_criterion("2023年废止的门诊政策还有效吗", current_year=2026) == "time_version"

    def test_hits_draft(self):
        assert check_time_version_criterion("门诊统筹新规草案什么时候实施", current_year=2026) == "time_version"

    def test_hits_future_relative_year(self):
        assert check_time_version_criterion("明年的门诊报销比例会调整吗", current_year=2026) == "time_version"

    def test_boundary_last_year_vs_this_year(self):
        """阈值边缘：'去年'拒、'今年'不拒；显式年份非当年拒、当年不拒。"""
        assert check_time_version_criterion("去年的门诊报销比例是多少", current_year=2026) == "time_version"
        assert check_time_version_criterion("今年的门诊报销比例是多少", current_year=2026) is None
        assert check_time_version_criterion("2025年的门诊政策", current_year=2026) == "time_version"
        assert check_time_version_criterion("2026年的门诊政策", current_year=2026) is None

    def test_empty_and_none_input(self):
        """空输入与异常值：判据函数本身不抛错，返回 None（拒答由路由层处理）。"""
        assert check_time_version_criterion("", current_year=2026) is None
        assert check_time_version_criterion(None, current_year=2026) is None
        assert check_time_version_criterion("政策", current_year=2026) is None


class TestRegionCriterion:
    """地域判据：明确非本统筹区拒；异地'备案流程'类不拒、异地'比例/待遇'拒。"""

    def test_hits_other_city(self):
        assert check_region_criterion("上海职工医保门诊报销比例") == "region_out_of_scope"
        assert check_region_criterion("广州医保怎么用") == "region_out_of_scope"

    def test_hits_remote_benefit_ratio(self):
        assert check_region_criterion("异地就医报销比例是多少") == "region_out_of_scope"
        assert check_region_criterion("异地支付的待遇标准") == "region_out_of_scope"

    def test_remote_process_question_allowed(self):
        """异地'备案流程'类（语料可答）不属于拒答对象。"""
        assert check_region_criterion("异地就医备案流程是什么") is None
        assert check_region_criterion("异地转诊怎么办理") is None

    def test_local_question_allowed(self):
        assert check_region_criterion("北京门诊报销比例") is None

    def test_empty_and_none_input(self):
        assert check_region_criterion("") is None
        assert check_region_criterion(None) is None


class TestScopeCriterion:
    """范围判据：住院术语在 #33（门诊+通用）范围纪律之外 → 拒，不落 broad。"""

    def test_hits_inpatient_segment(self):
        assert check_scope_criterion("住院分段支付比例是多少") == "scope_inpatient"

    def test_hits_inpatient_generic(self):
        assert check_scope_criterion("住院报销怎么算") == "scope_inpatient"
        assert check_scope_criterion("职工医保住院起付线是多少") == "scope_inpatient"

    def test_outpatient_question_allowed(self):
        assert check_scope_criterion("门诊报销比例是多少") is None
        assert check_scope_criterion("门特待遇标准") is None

    def test_empty_and_none_input(self):
        assert check_scope_criterion("") is None
        assert check_scope_criterion(None) is None


class TestRouteBroadQuestion:
    """路由函数：A/B/C 分流 + 结构化漏空回落确定性拒答 + audit 位。"""

    def test_route_a_specific_question_to_structured(self):
        decision = route_broad_question(
            "在职职工门诊三级医院报销比例是多少",
            structured_retrieve=_fake_retrieve([1.0]),
            current_year=2026,
        )
        assert decision.landing == "A"
        assert decision.route == "structured"
        assert decision.refusal_reason == ""
        queries = decision.structured_queries
        assert len(queries) == 1
        assert queries[0].filters["insu_type"] == "城镇职工基本医疗保险"
        assert queries[0].filters["med_type"] == "门诊-普通门急诊"
        assert queries[0].filters["rule_type"] == "支付比例"

    def test_route_b_broad_in_domain_defaults_insu_all(self):
        """B：无险种限定时不过滤险种（职工/居民 all），不造 broad 词面召回。"""
        decision = route_broad_question(
            "门诊报销比例是多少",
            structured_retrieve=_fake_retrieve([1.0]),
            current_year=2026,
        )
        assert decision.landing == "B"
        assert decision.route == "structured"
        assert "insu_type" not in decision.structured_queries[0].filters
        assert decision.structured_queries[0].filters["med_type"] == "门诊-普通门急诊"

    def test_route_b_action_cap_maps_to_cap_rule_type(self):
        decision = route_broad_question(
            "医保门诊最高限额是多少",
            structured_retrieve=_fake_retrieve([1.0]),
            current_year=2026,
        )
        assert decision.landing == "B"
        assert decision.structured_queries[0].filters["rule_type"] == "封顶线"

    def test_route_c_time_refusal(self):
        decision = route_broad_question("去年的门诊政策还有效吗", current_year=2026)
        assert decision.landing == "C"
        assert decision.route == "refuse"
        assert decision.refusal_reason == "time_version"
        assert decision.refusal_message == TIME_VERSION_REFUSAL_MESSAGE
        assert "未收录" in decision.refusal_message
        assert decision.structured_queries == []

    def test_route_c_region_refusal(self):
        decision = route_broad_question("上海医保门诊报销比例", current_year=2026)
        assert decision.landing == "C"
        assert decision.route == "refuse"
        assert decision.refusal_reason == "region_out_of_scope"
        assert decision.refusal_message == REGION_REFUSAL_MESSAGE
        assert "不适用" in decision.refusal_message

    def test_route_c_scope_refusal(self):
        decision = route_broad_question("北京职工医保住院怎么报销", current_year=2026)
        assert decision.landing == "C"
        assert decision.route == "refuse"
        assert decision.refusal_reason == "scope_inpatient"
        assert decision.refusal_message == SCOPE_REFUSAL_MESSAGE
        assert "暂未收录" in decision.refusal_message

    def test_route_c_without_retrieve_callable_still_refuses(self):
        """C 判在检索之前拦截，不需要 structured_retrieve 也不触碰检索。"""
        def _boom(_decision):
            raise AssertionError("C 判拒答不得触发结构化检索")

        decision = route_broad_question(
            "2023年废止的门诊政策", structured_retrieve=_boom, current_year=2026
        )
        assert decision.route == "refuse"

    def test_structured_miss_falls_back_to_refusal_not_broad(self):
        """结构化候选为空 → 确定性拒答（诚实），绝不回落 broad 自由检索。"""
        decision = route_broad_question(
            "门诊报销比例是多少",
            structured_retrieve=_fake_retrieve([]),
            current_year=2026,
        )
        assert decision.landing == "B"
        assert decision.route == "refuse"
        assert decision.refusal_reason == "structured_miss"
        assert decision.refusal_message == STRUCTURED_MISS_REFUSAL_MESSAGE
        assert "未检索到" in decision.refusal_message
        assert decision.evidence == []

    def test_structured_low_confidence_falls_back_to_refusal(self):
        """最高置信 < 拒答阈 → 同样回落确定性拒答。"""
        decision = route_broad_question(
            "门诊报销比例是多少",
            structured_retrieve=_fake_retrieve([ROUTING_MIN_CONFIDENCE - 0.1]),
            current_year=2026,
        )
        assert decision.route == "refuse"
        assert decision.refusal_reason == "structured_miss"

    def test_structured_queries_carry_question_as_search_text(self):
        """路由查询挂 search_text=原问题，激活 structured 内置 BM25 重排（排序修复）。"""
        decision = route_broad_question("门诊报销比例是多少", current_year=2026)
        assert decision.structured_queries[0].search_text == "门诊报销比例是多少"

    def test_evidence_relevance_filter_drops_noise(self, monkeypatch):
        """低相关噪声（缴费/划入类比例）被过滤，证据按问题相关性排序并截断。"""
        monkeypatch.setattr(
            broad_query_router,
            "_cosine_similarities",
            lambda _q, _texts: [0.80, 0.66, 0.70],
        )
        question = "门诊报销比例是多少"
        noise = SimpleNamespace(
            score=1.0, source_text="35周岁以上不满45周岁的职工按本人月缴费工资基数的1%划入个人账户"
        )
        relevant_a = SimpleNamespace(score=1.0, source_text="门诊统筹基金支付85%，个人支付15%")
        relevant_b = SimpleNamespace(score=1.0, source_text="门诊统筹基金支付90%，个人支付10%")
        decision = route_broad_question(
            question,
            structured_retrieve=lambda _d: SimpleNamespace(
                selected_evidence=[noise, relevant_a, relevant_b]
            ),
            current_year=2026,
        )
        assert decision.route == "structured"
        texts = [ev.source_text for ev in decision.evidence]
        # 噪声被相关性过滤剔除，相关证据保留且排在前面
        assert noise.source_text not in texts
        assert relevant_a.source_text in texts
        assert relevant_b.source_text in texts

    def test_evidence_low_semantic_floor_refuses(self, monkeypatch):
        """候选池整体语义不相关（向量最高分低于地板）→ 诚实拒答，不硬答。"""
        monkeypatch.setattr(
            broad_query_router,
            "_cosine_similarities",
            lambda _q, _texts: [0.50, 0.45],
        )
        decision = route_broad_question(
            "异地就医备案流程是什么",
            structured_retrieve=lambda _d: SimpleNamespace(
                selected_evidence=[
                    SimpleNamespace(score=1.0, source_text="门诊大额医疗互助资金报销比例调整为70%"),
                    SimpleNamespace(score=1.0, source_text="统筹基金支付85%，个人支付15%"),
                ]
            ),
            current_year=2026,
        )
        assert decision.route == "refuse"
        assert decision.refusal_reason == "low_relevance"
        assert decision.evidence == []

    def test_evidence_relevance_no_lexical_signal_keeps_evidence(self, monkeypatch):
        """问题与证据零词面重叠（纯语义命中）时不误杀：保留证据，避免过度拒答。"""
        monkeypatch.setattr(
            broad_query_router,
            "_cosine_similarities",
            lambda _q, _texts: [0.90],
        )
        decision = route_broad_question(
            "门诊待遇怎么样",
            structured_retrieve=lambda _d: SimpleNamespace(
                selected_evidence=[
                    SimpleNamespace(score=1.0, source_text="统筹基金按规定比例支付医疗费用")
                ]
            ),
            current_year=2026,
        )
        assert decision.route == "structured"
        assert len(decision.evidence) == 1

    def test_evidence_embedding_unavailable_degrades_to_bm25(self, monkeypatch):
        """embedding 不可用时降级 BM25-only：不做语义地板裁决，行为与旧版一致。"""
        monkeypatch.setattr(
            broad_query_router, "_cosine_similarities", lambda _q, _texts: None
        )
        decision = route_broad_question(
            "门诊报销比例是多少",
            structured_retrieve=lambda _d: SimpleNamespace(
                selected_evidence=[
                    SimpleNamespace(score=1.0, source_text="门诊统筹基金支付85%，个人支付15%")
                ]
            ),
            current_year=2026,
        )
        assert decision.route == "structured"
        assert len(decision.evidence) == 1

    def test_structured_hit_returns_evidence(self):
        decision = route_broad_question(
            "门诊报销比例是多少",
            structured_retrieve=_fake_retrieve([1.0]),
            current_year=2026,
        )
        assert decision.route == "structured"
        assert len(decision.evidence) == 1

    def test_broad_fallback_kept_closed_by_default(self):
        """条件1：罕见 broad 兜底第一版默认关闭——不产出答案，落 audit 记录。"""
        decision = route_broad_question("医保基金是怎么管理的", current_year=2026)
        assert decision.landing == "broad-kept-closed"
        assert decision.route == "broad_kept_closed"
        assert decision.evidence == []
        assert decision.refusal_message
        assert decision.audit["landing"] == "broad-kept-closed"

    def test_empty_question_refused(self):
        decision = route_broad_question("", current_year=2026)
        assert decision.landing == "C"
        assert decision.route == "refuse"
        assert decision.refusal_reason == "empty_question"
        assert decision.refusal_message == EMPTY_QUESTION_REFUSAL_MESSAGE

        decision_none = route_broad_question(None, current_year=2026)
        assert decision_none.route == "refuse"
        assert decision_none.refusal_reason == "empty_question"

    def test_audit_landing_written_for_each_route(self):
        """audit 位：A/B/C/broad-kept-closed 四落点写对（条件1 要求 broad 有记录）。"""
        records = []
        route_broad_question(
            "在职职工门诊报销比例",
            structured_retrieve=_fake_retrieve([1.0]),
            audit_sink=records.append,
            current_year=2026,
        )
        route_broad_question(
            "门诊最高限额",
            structured_retrieve=_fake_retrieve([1.0]),
            audit_sink=records.append,
            current_year=2026,
        )
        route_broad_question("住院怎么报销", audit_sink=records.append, current_year=2026)
        route_broad_question("医保基金是怎么管理的", audit_sink=records.append, current_year=2026)

        assert [r["landing"] for r in records] == ["A", "B", "C", "broad-kept-closed"]
        for record in records:
            assert set(record) >= {"question", "landing", "route", "refusal_reason", "evidence_count"}

    def test_default_audit_sink_does_not_raise(self):
        """未注入 audit_sink 时使用默认日志 sink，不抛错。"""
        decision = route_broad_question("医保基金是怎么管理的", current_year=2026)
        assert decision.audit["landing"] == "broad-kept-closed"


class TestRouterEvidenceGrounding:
    """加固④（2026-09-04 验收表 #7-#10 固化）：rule_type 兜底硬过滤拆除、
    推断维度进重排加权、路由候选池放大。对应用户验收表第 2 步 A/B 向四用例。"""

    def test_uninferred_rule_type_omits_hard_filter(self):
        """推断不出规则类型时不得兜底 rule_type=支付比例硬过滤（备案流程类否则候选池被清空）。"""
        decision = route_broad_question("异地就医备案流程是什么", current_year=2026)
        assert decision.route == "structured"
        assert decision.landing == "B"
        assert "rule_type" not in decision.structured_queries[0].filters

    def test_router_query_enlarges_candidate_pool(self):
        """路由候选池放大喂重排：期望规则此前在 top-K=20 截断阶段丢失（70% 规则实证）。"""
        decision = route_broad_question("在职职工门诊三级医院报销比例是多少", current_year=2026)
        assert decision.structured_queries[0].top_k >= 50

    def test_rerank_dimension_match_beats_broad_lexical(self):
        """维度精确匹配（三级/在职职工/职工/门诊/支付比例）应压过词面宽泛的大额互助规则。"""
        rule_70 = SimpleNamespace(
            score=1.0,
            source_text="统筹基金支付70%，个人支付30%。",
            insu_type="城镇职工基本医疗保险",
            med_type="门诊-普通门急诊",
            hosp_lv="三级",
            psn_type="在职职工",
            rule_type="支付比例",
        )
        noise = SimpleNamespace(
            score=1.0,
            source_text="门诊大额医疗互助资金报销比例调整为80%",
            insu_type="城镇职工基本医疗保险",
            med_type="门诊-普通门急诊",
            hosp_lv="一级",
            psn_type="",
            rule_type="支付比例",
        )
        monkey_cosine = [0.80, 0.82]  # 噪声词面更宽，向量略高：纯相关性会选错
        import src.runtime.policy_qa.broad_query_router as router_mod

        original = router_mod._cosine_similarities
        router_mod._cosine_similarities = lambda _q, _t: monkey_cosine
        try:
            decision = route_broad_question(
                "在职职工门诊三级医院报销比例是多少",
                structured_retrieve=lambda _d: SimpleNamespace(
                    selected_evidence=[noise, rule_70]
                ),
                current_year=2026,
            )
        finally:
            router_mod._cosine_similarities = original
        assert decision.route == "structured"
        assert decision.evidence[0].source_text == "统筹基金支付70%，个人支付30%。"

    def test_rerank_empty_dimension_neutral_not_penalized(self):
        """hosp_lv 为空的通用规则不得因问题提到三级而被惩罚到错配规则之后。"""
        generic = SimpleNamespace(
            score=1.0,
            source_text="参保人员医疗费用按规定比例支付",
            insu_type="",
            med_type="",
            hosp_lv="",
            psn_type="",
            rule_type="支付比例",
        )
        wrong_lv = SimpleNamespace(
            score=1.0,
            source_text="二级医疗机构相关支付规定",
            insu_type="",
            med_type="",
            hosp_lv="二级",
            psn_type="",
            rule_type="支付比例",
        )
        import src.runtime.policy_qa.broad_query_router as router_mod

        original = router_mod._cosine_similarities
        router_mod._cosine_similarities = lambda _q, _t: [0.80, 0.78]
        try:
            decision = route_broad_question(
                "三级医院门诊报销比例是多少",
                structured_retrieve=lambda _d: SimpleNamespace(
                    selected_evidence=[wrong_lv, generic]
                ),
                current_year=2026,
            )
        finally:
            router_mod._cosine_similarities = original
        assert decision.route == "structured"
        assert decision.evidence[0].source_text == generic.source_text

    def test_remote_process_question_surfaces_process_evidence(self):
        """验收 #10：备案流程类问题召回流程类证据（rule_type 硬过滤拆除后由重排把关）。"""
        process_rule = SimpleNamespace(
            score=1.0,
            source_text="参保人员跨省异地就医前应在参保地经办机构办理备案手续",
            insu_type="城乡居民基本医疗保险",
            med_type="",
            hosp_lv="",
            psn_type="",
            rule_type="适用范围",
        )
        noise = SimpleNamespace(
            score=1.0,
            source_text="在本市社区卫生服务机构以外的其他定点医疗机构就医，门诊大额医疗互助资金报销比例调整为70%",
            insu_type="城镇职工基本医疗保险",
            med_type="门诊-普通门急诊",
            hosp_lv="无等级",
            psn_type="",
            rule_type="支付比例",
        )
        import src.runtime.policy_qa.broad_query_router as router_mod

        original = router_mod._cosine_similarities
        router_mod._cosine_similarities = lambda _q, _t: [0.85, 0.70]
        try:
            decision = route_broad_question(
                "异地就医备案流程是什么",
                structured_retrieve=lambda _d: SimpleNamespace(
                    selected_evidence=[noise, process_rule]
                ),
                current_year=2026,
            )
        finally:
            router_mod._cosine_similarities = original
        assert decision.route == "structured"
        texts = [ev.source_text for ev in decision.evidence]
        assert process_rule.source_text in texts
        assert noise.source_text not in texts
