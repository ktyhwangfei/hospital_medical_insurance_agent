"""会话级费用分解共享实例缓存单元测试（阶段 A：面板↔聊天同源）。

覆盖：
- 缓存原语：同 (session_id, settlement_id) 命中复用；容量有界 LRU 淘汰；
  并发写线程安全且不超容量；
- policy_qa_routes._decompose_for_session：同键只计算一次且返回同一实例；
  换 settlement_id / 换 session_id → 新键新实例（重新计算）；
  not_configured 不写缓存（门控修复后可重算）；
- FEE_DECOMPOSITION_EVAL_CALIBERS=1 不渗入会话口径（恒 allow_eval_calibers=False）。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from src.runtime.api import policy_qa_routes
from src.runtime.policy_qa.fee_decomposition import integration
from src.runtime.policy_qa.fee_decomposition.integration import (
    DecompositionPresentation,
    WorkbenchDecompositionOutcome,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
)
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    SettlementFactsItem,
    SettlementFactsView,
)


@pytest.fixture(autouse=True)
def clear_cache():
    integration.clear_session_decomposition_cache()
    yield
    integration.clear_session_decomposition_cache()


def _canned_result(trade_no: str = "T001") -> SettlementDecompositionResult:
    return SettlementDecompositionResult(
        settlement_ref=f"settlement:{trade_no}",
        profile=DecompositionProfile(insurance_type="employee", medical_category="outpatient"),
        execution_status="complete",
        reconciliation_status="matched",
        fields=[FieldExplanationModel(
            field_code="T_FeeAll", label="总费用", check_type="detail_aggregation",
            check_status="matched", observed_amount="100.00",
            calculated_amount="100.00", difference="0.00",
            explanation_level="amount_reconciled")],
        coverage=CoverageSummary(
            target_field_count=1, independently_explained_count=0,
            amount_reconciled_count=1, observed_only_count=0),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=True),
    )


def _canned_outcome(trade_no: str = "T001") -> WorkbenchDecompositionOutcome:
    return WorkbenchDecompositionOutcome(
        status="ok", chain="outpatient",
        presentation=DecompositionPresentation(
            result=_canned_result(trade_no),
            summary_text="费用分解：完整解释。",
            summary_source="template",
            settlement_facts=SettlementFactsView(
                chain="outpatient", identifier=trade_no,
                items=[SettlementFactsItem(label="费用总金额", value="100.00")]),
        ),
        profile=("employee", "outpatient"),
        caliber="fail_closed",
    )


class TestCachePrimitives:
    def test_get_miss_returns_none(self):
        assert integration.get_cached_session_decomposition("s1", "T001") is None

    def test_put_then_get_same_key(self):
        outcome = _canned_outcome()
        integration.cache_session_decomposition("s1", "T001", outcome)
        assert integration.get_cached_session_decomposition("s1", "T001") is outcome

    def test_keys_are_session_and_settlement_scoped(self):
        outcome = _canned_outcome()
        integration.cache_session_decomposition("s1", "T001", outcome)
        # 换单 / 换会话都不复用
        assert integration.get_cached_session_decomposition("s1", "T002") is None
        assert integration.get_cached_session_decomposition("s2", "T001") is None

    def test_capacity_evicts_least_recently_used(self, monkeypatch):
        monkeypatch.setattr(integration, "_SESSION_CACHE_CAPACITY", 2)
        integration.cache_session_decomposition("s", "a", _canned_outcome("a"))
        integration.cache_session_decomposition("s", "b", _canned_outcome("b"))
        # 读 a 使其成为最近使用；b 变为最久未用
        assert integration.get_cached_session_decomposition("s", "a") is not None
        integration.cache_session_decomposition("s", "c", _canned_outcome("c"))
        assert integration.get_cached_session_decomposition("s", "b") is None
        assert integration.get_cached_session_decomposition("s", "a") is not None
        assert integration.get_cached_session_decomposition("s", "c") is not None

    def test_concurrent_puts_stay_within_capacity_and_consistent(self):
        def put(i: int):
            integration.cache_session_decomposition(f"s{i % 4}", f"T{i:04d}", _canned_outcome())

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(put, range(200)))
        assert len(integration._session_decomposition_cache) <= integration._SESSION_CACHE_CAPACITY


class TestDecomposeForSession:
    def test_same_session_same_settlement_computes_once(self, monkeypatch):
        calls: list[tuple[str, str]] = []

        def fake(identifier, chain, provider, **_kwargs):
            calls.append((identifier, chain))
            return _canned_outcome(identifier)

        monkeypatch.setattr(policy_qa_routes, "decompose_for_workbench", fake)
        first = policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        second = policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        assert calls == [("T001", "outpatient")]
        # 同一运行实例（不是重算的同值副本）
        assert first is second

    def test_new_settlement_or_new_session_recomputes(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            policy_qa_routes, "decompose_for_workbench",
            lambda identifier, chain, provider, **_kwargs: calls.append(identifier) or _canned_outcome(identifier),
        )
        policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        policy_qa_routes._decompose_for_session("s1", "T002", "outpatient", object())
        policy_qa_routes._decompose_for_session("s2", "T001", "outpatient", object())
        assert calls == ["T001", "T002", "T001"]

    def test_not_configured_is_not_cached(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            policy_qa_routes, "decompose_for_workbench",
            lambda identifier, chain, provider, **_kwargs: calls.append(identifier)
            or WorkbenchDecompositionOutcome(
                status="not_configured", chain="outpatient",
                missing_env=("FEE_DECOMPOSITION_ROUNDING_MODE",)),
        )
        first = policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        second = policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        assert first.status == "not_configured" and second.status == "not_configured"
        # 门控状态不固化：每次都重新判定
        assert calls == ["T001", "T001"]

    def test_session_path_is_fail_closed_regardless_of_eval_env(self, monkeypatch):
        """FEE_DECOMPOSITION_EVAL_CALIBERS=1 只影响工作台；会话口径恒 fail-closed。"""
        monkeypatch.setenv("FEE_DECOMPOSITION_EVAL_CALIBERS", "1")
        captured: dict = {}

        def fake(identifier, chain, provider, **kwargs):
            captured.update(kwargs)
            return _canned_outcome(identifier)

        monkeypatch.setattr(policy_qa_routes, "decompose_for_workbench", fake)
        policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        assert captured["allow_eval_calibers"] is False

class TestOnlyReusableResultsAreCached:
    """评审问题 7：只缓存可复用结果 + 链路一致才复用。"""

    @staticmethod
    def _outcome(chain: str, execution_status: str = "complete") -> WorkbenchDecompositionOutcome:
        result = _canned_result().model_copy(update={"execution_status": execution_status})
        return WorkbenchDecompositionOutcome(
            status="ok", chain=chain,
            presentation=DecompositionPresentation(
                result=result, summary_text="x", summary_source="template",
                settlement_facts=SettlementFactsView(
                    chain=chain, identifier="T001",
                    items=[SettlementFactsItem(label="费用总金额", value="100.00")])),
            profile=("employee", chain), caliber="fail_closed")

    def test_unavailable_is_not_cached_and_recovers(self, monkeypatch):
        """第一次 unavailable 不写缓存：数据源恢复后同键可重算成功。"""
        outcomes = [self._outcome("outpatient", "unavailable"), self._outcome("outpatient")]
        calls: list[str] = []

        def fake(identifier, chain, provider, **_kwargs):
            calls.append(chain)
            return outcomes[len(calls) - 1]

        monkeypatch.setattr(policy_qa_routes, "decompose_for_workbench", fake)
        first = policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        second = policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        assert first.presentation.result.execution_status == "unavailable"
        assert second.presentation.result.execution_status == "complete"
        assert calls == ["outpatient", "outpatient"]
        # 成功结果此后可复用
        third = policy_qa_routes._decompose_for_session("s1", "T001", "outpatient", object())
        assert third is second
        assert calls == ["outpatient", "outpatient"]

    def test_chain_mismatch_is_a_miss_and_keeps_cached_result(self, monkeypatch):
        """同 session 先 outpatient 失败/成功，再显式 special：链路冲突当未命中重算。"""
        by_chain = {
            "outpatient": self._outcome("outpatient", "unavailable"),
            "special": self._outcome("special"),
        }
        calls: list[str] = []

        def fake(identifier, chain, provider, **_kwargs):
            calls.append(chain)
            return by_chain[chain]

        monkeypatch.setattr(policy_qa_routes, "decompose_for_workbench", fake)
        # 688 这类短登记号：显式传入 outpatient（错误链路）先失败
        policy_qa_routes._decompose_for_session("s1", "688", "outpatient", object())
        corrected = policy_qa_routes._decompose_for_session("s1", "688", "special", object())
        assert corrected.chain == "special"
        assert corrected.presentation.result.execution_status == "complete"
        # 正确链路结果被缓存且不受后续错链路请求污染
        assert policy_qa_routes._decompose_for_session(
            "s1", "688", "special", object()) is corrected
        assert calls == ["outpatient", "special"]
        assert integration.get_cached_session_decomposition("s1", "688") is corrected

    def test_auto_chain_compares_with_normalized_chain(self, monkeypatch):
        """auto 链路先规范化再与缓存实际 chain 比较（长交易号 → outpatient）。"""
        calls: list[str] = []

        def fake(identifier, chain, provider, **_kwargs):
            calls.append(chain)
            return self._outcome("outpatient")

        monkeypatch.setattr(policy_qa_routes, "decompose_for_workbench", fake)
        first = policy_qa_routes._decompose_for_session("s1", "011100030X240311000031", "auto", object())
        second = policy_qa_routes._decompose_for_session(
            "s1", "011100030X240311000031", "outpatient", object())
        assert first is second
        assert calls == ["auto"]
