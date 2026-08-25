class TestExtractSegmentRatios:
    """测试 _extract_segment_ratios 对真实 Milvus 数据结构的解析。"""

    def _make_real_evidence(self):
        """构造与真实 Milvus 返回结构一致的测试数据。"""
        return [
            {
                "source_text": "1. 起付标准至3万元的部分，统筹基金支付85%，职工支付15%；\n{\"ratio\": 0.85}",
                "rule_type": "支付比例",
                "psn_type": "",
                "amount_band": "nan",
                "rule_tags": ["支付比例", "城镇职工基本医疗保险", "住院-普通住院", "三级医院", "全部"],
                "rule_value": "{\"ratio\": 0.85}",
            },
            {
                "source_text": "2. 超过3万元至4万元的部分，统筹基金支付90%，职工支付10%；\n{\"ratio\": 0.9}",
                "rule_type": "支付比例",
                "psn_type": "",
                "amount_band": "nan",
                "rule_tags": ["支付比例", "城镇职工基本医疗保险", "住院-普通住院", "三级医院", "全部"],
                "rule_value": "{\"ratio\": 0.9}",
            },
            {
                "source_text": "3. 超过4万元的部分，统筹基金支付95%，职工支付5%。\n{\"ratio\": 0.95}",
                "rule_type": "支付比例",
                "psn_type": "",
                "amount_band": "nan",
                "rule_tags": ["支付比例", "城镇职工基本医疗保险", "住院-普通住院", "三级医院", "全部"],
                "rule_value": "{\"ratio\": 0.95}",
            },
            {
                "source_text": "（四）退休人员个人支付比例为职工支付比例的60%。但基本医疗保险统筹基金按照比例支付的最高数额不得超过本规定第十三条规定的最高支付限额。",
                "rule_type": "计算公式",
                "psn_type": "",
                "amount_band": "nan",
                "rule_tags": ["计算公式", "城镇职工基本医疗保险", "住院-普通住院", "nan", "退休人员"],
                "rule_value": "{\"expression\": \"retiree_personal_payment_ratio = employee_personal_payment_ratio * 0.6\", \"target\": \"retiree_personal_payment_ratio\", \"base\": \"employee_personal_payment_ratio\", \"operator\": \"*\", \"multiplier\": 0.6}",
            },
        ]

    def test_detects_3_employee_segments(self):
        """3 条支付比例证据应解析出 3 个分段。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios(self._make_real_evidence())
        assert len(seg["employee"]) == 3

    def test_detects_retiree_rule_with_empty_psn_type(self):
        """退休规则证据的 psn_type 为空时，应通过 source_text/rule_tags 多源检测。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios(self._make_real_evidence())
        assert seg["retiree"] is not None, "退休人员 60% 规则未被检测到（psn_type 为空时的多源检测失败）"
        assert seg["retiree"]["ratio"] == 60

    def test_has_complete_is_true_with_4_evidence(self):
        """4 条证据（3 段比例 + 退休公式）时 has_complete 必须为 True。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios(self._make_real_evidence())
        assert seg["has_complete"] is True, f"has_complete 应为 True，实际: {seg}"

    def test_retiree_segments_calculated_correctly(self):
        """退休人员分段比例应正确计算：15%×60%=9%, 10%×60%=6%, 5%×60%=3%。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios(self._make_real_evidence())
        assert seg["retiree"] is not None
        retiree_segs = seg["retiree"]["segments"]
        assert len(retiree_segs) == 3
        assert retiree_segs[0] == 9  # 15 * 60 / 100 = 9
        assert retiree_segs[1] == 6  # 10 * 60 / 100 = 6
        assert retiree_segs[2] == 3  # 5 * 60 / 100 = 3

    def test_empty_evidence_returns_not_complete(self):
        """空证据列表应返回 has_complete=False。"""
        from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import PoolingSelfPayStrategy
        from pathlib import Path as _Path
        _strat = PoolingSelfPayStrategy(_Path("skills/settlement_explain_skill/strategies/pooling_self_pay"))
        seg = _strat._extract_segment_ratios([])
        assert seg["has_complete"] is False
        assert seg["retiree"] is None


class TestPolicyQATurnId:
    """服务端 qa_turn_id 全链路：task 主键、result、done、history 共享同一服务端 ID。"""

    def test_record_qa_task_uses_server_qa_turn_id(self):
        """record_qa_task 必须以服务端 qa_turn_id 作为 task 主键，不再根据问题正文计算。"""
        from src.runtime.policy_qa.persistence import record_qa_task
        from src.runtime.task_closure.service import get_task

        qa_turn_id = "qat_01JTEST000000000000000001"
        saved = record_qa_task(
            qa_turn_id=qa_turn_id,
            workflow_id="wf-1",
            session_id="session-1",
            user_id="user-1",
            tenant_id="tenant-1",
            question="起付线怎么计算",
            output={
                "answer_excerpt": "按年度累计计算",
                "selected_skill_id": "deductible",
            },
        )
        assert saved == qa_turn_id
        task = get_task(qa_turn_id)
        assert task is not None
        assert task["task_id"] == qa_turn_id
        assert task["output_data"]["selected_skill_id"] == "deductible"
        # 内部 input 不再保存原始患者问题正文，仅保留脱敏摘要
        assert "question" not in task["input_data"]
        assert task["input_data"]["question_excerpt"]
        assert task["input_data"]["tenant_id"] == "tenant-1"

    def test_record_qa_task_is_idempotent_on_same_turn_id(self):
        """同一 qa_turn_id 重复记录不会产生第二个主键。"""
        from src.runtime.policy_qa.persistence import record_qa_task

        first = record_qa_task(
            qa_turn_id="qat_idem_1",
            workflow_id="wf-idem",
            session_id="sess-idem",
            user_id="user-1",
            tenant_id="tenant-1",
            question="统筹自付怎么算",
            output={"answer_excerpt": "分段计算", "selected_skill_id": "settlement_explain_skill"},
        )
        second = record_qa_task(
            qa_turn_id="qat_idem_1",
            workflow_id="wf-idem",
            session_id="sess-idem",
            user_id="user-1",
            tenant_id="tenant-1",
            question="统筹自付怎么算",
            output={"answer_excerpt": "分段计算", "selected_skill_id": "settlement_explain_skill"},
        )
        assert first == second == "qat_idem_1"
