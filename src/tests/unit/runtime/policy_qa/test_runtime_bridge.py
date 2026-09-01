"""PolicyQARuntimeBridge 单元测试

验证政策问答 Runtime 增强桥：
- prepare_turn：上下文规划事件（记忆缺失下探 / 命中 / 主体切换清理）
- record_step：结算/政策记忆沉淀 + 推理步骤事件
- finalize_turn：推理链快照 + CONVERSATION 记忆更新
- 降级原则：任何内部异常都不影响主流程（返回 None / [] / {}）
"""

from src.data_platform.storage.memory.in_memory import InMemoryMemoryStore
from src.runtime.intent.planner import ContextPlanner
from src.runtime.memory.manager import MemoryManager
from src.runtime.memory.models import MemoryType
from src.runtime.policy_qa.runtime_bridge import PolicyQARuntimeBridge
from src.runtime.reasoning.manager import ReasoningStateManager


def _make_bridge() -> tuple[PolicyQARuntimeBridge, MemoryManager, ReasoningStateManager]:
    memory_manager = MemoryManager(InMemoryMemoryStore())
    reasoning_manager = ReasoningStateManager()
    planner = ContextPlanner(memory_manager=memory_manager)
    return PolicyQARuntimeBridge(memory_manager, reasoning_manager, planner), memory_manager, reasoning_manager


def test_prepare_turn_marks_semantic_query_on_fresh_session():
    """新会话无记忆：must_query_semantic=True，memory_ids 为空。"""
    bridge, _, _ = _make_bridge()

    need = bridge.prepare_turn(
        session_id="s1", question="统筹自付为什么是 4962.67 元？", settlement_id="1671213",
    )

    assert need is not None
    assert need["must_query_semantic"] is True
    assert need["memory_ids"] == []
    assert need["subject_changed"] is False
    assert "settlement" in need["object_types"]


def test_prepare_turn_hits_memory_on_second_turn():
    """第二轮：结算/政策记忆已存在，memory_ids 命中已有记忆。

    注：must_query_semantic 保持 True 是 ContextPlanner 的保守设计——
    policy_qa_fee_decomposition 意图映射 [SETTLEMENT, POLICY, RULE]，
    而 RULE 类型当前不作为记忆沉淀，政策问答每轮本就会下探语义层检索。
    """
    bridge, _, _ = _make_bridge()
    bridge.record_step(
        session_id="s1", step="settlement_query",
        detail={"settlement_id": "1671213", "total_fee": 12000.0}, settlement_id="1671213",
    )
    bridge.record_step(
        session_id="s1", step="structured_policy_query", detail={"rules_count": 3},
    )

    need = bridge.prepare_turn(session_id="s1", question="那起付线呢", settlement_id="1671213")

    assert need is not None
    # 命中上一轮沉淀的结算 + 政策两条记忆
    assert len(need["memory_ids"]) == 2
    assert need["must_query_semantic"] is True  # RULE 类型未沉淀，保守下探


def test_prepare_turn_subject_change_expires_topic_memories():
    """主体切换信号（"查询张三…"）：标记 subject_changed 并清理 TOPIC 记忆。"""
    bridge, memory_manager, _ = _make_bridge()
    bridge.record_step(
        session_id="s1", step="settlement_query",
        detail={"settlement_id": "1671213"}, settlement_id="1671213",
    )

    need = bridge.prepare_turn(session_id="s1", question="查询张三的住院费用", settlement_id="1671213")

    assert need is not None
    assert need["subject_changed"] is True
    # TOPIC 策略的结算记忆已被清理
    assert memory_manager.get_by_session_and_type("s1", MemoryType.SETTLEMENT) == []


def test_record_settlement_step_emits_memory_and_reasoning_events():
    """结算步骤完成：发出 memory_update + reasoning_step 两个事件。"""
    bridge, memory_manager, reasoning_manager = _make_bridge()

    events = bridge.record_step(
        session_id="s1", step="settlement_query",
        detail={"settlement_id": "1671213", "total_fee": 12000.0, "pooling_self_pay": 4962.67},
        settlement_id="1671213",
    )

    event_types = [t for t, _ in events]
    assert event_types == ["memory_update", "reasoning_step"]

    memory_payload = dict(events[0][1])["memory"]
    assert memory_payload["type"] == "settlement"
    assert memory_payload["ref_id"] == "1671213"
    assert memory_payload["expire_policy"] == "topic"
    assert "total_fee" in memory_payload["snapshot_keys"]

    reasoning_payload = dict(events[1][1])
    assert reasoning_payload["kind"] == "fact"
    assert "1671213" in reasoning_payload["claim"]
    assert reasoning_payload["source_memory_ids"] == [memory_payload["memory_id"]]

    # 记忆与推理确实落库
    assert len(memory_manager.get_by_session("s1")) == 1
    assert len(reasoning_manager.get_chain("s1")) == 1


def test_record_policy_step_uses_sticky_policy_memory():
    """政策检索完成：POLICY 记忆为 STICKY 策略（跨话题保留）。"""
    bridge, _, _ = _make_bridge()

    events = bridge.record_step(
        session_id="s1", step="structured_policy_query",
        detail={"rules_count": 5, "policy_filters": ["insu_type=职工"]},
    )

    memory_payload = dict(events[0][1])["memory"]
    assert memory_payload["type"] == "policy"
    assert memory_payload["expire_policy"] == "sticky"
    reasoning_payload = dict(events[1][1])
    assert "5" in reasoning_payload["claim"]


def test_record_calculate_and_answer_steps_link_source_memories():
    """计算/答案生成步骤的推理步关联结算与政策记忆（来源可追溯）。"""
    bridge, _, reasoning_manager = _make_bridge()
    bridge.record_step(session_id="s1", step="settlement_query", detail={}, settlement_id="1671213")
    bridge.record_step(session_id="s1", step="structured_policy_query", detail={"rules_count": 3})

    calc_events = bridge.record_step(session_id="s1", step="calculate_explanation", detail={})
    answer_events = bridge.record_step(session_id="s1", step="answer_generation", detail={})

    calc_step = dict(calc_events[0][1])
    answer_step = dict(answer_events[0][1])
    assert calc_step["kind"] == "inference"
    assert len(calc_step["source_memory_ids"]) == 1
    assert answer_step["kind"] == "inference"
    # 结论步同时关联结算 + 政策记忆
    assert len(answer_step["source_memory_ids"]) == 2
    assert len(reasoning_manager.get_chain("s1")) == 4


def test_record_step_ignores_unknown_steps():
    """非关键步骤不产生事件。"""
    bridge, _, _ = _make_bridge()

    assert bridge.record_step(session_id="s1", step="intent_detection", detail={}) == []


def test_finalize_turn_returns_chain_and_updates_conversation_memory():
    """轮次收尾：返回推理链快照，更新 CONVERSATION 记忆。"""
    bridge, memory_manager, _ = _make_bridge()
    bridge.record_step(session_id="s1", step="settlement_query", detail={}, settlement_id="1671213")

    extra = bridge.finalize_turn(session_id="s1", question="统筹自付怎么算的")

    assert extra["memory_count"] == 2  # SETTLEMENT + CONVERSATION
    assert extra["reasoning_chain"] == ["[fact] 已获取结算单 1671213 的结算数据"]
    assert len(extra["reasoning_steps"]) == 1

    conv = memory_manager.get_by_session_and_type("s1", MemoryType.CONVERSATION)
    assert len(conv) == 1
    assert conv[0].object_snapshot["last_question"] == "统筹自付怎么算的"

    # 第二轮 prepare_turn 能从 CONVERSATION 记忆恢复话题（同意图不算话题切换）
    need = bridge.prepare_turn(session_id="s1", question="那起付线呢", settlement_id="1671213")
    assert need is not None
    assert need["topic_changed"] is False


def test_finalize_turn_remembers_skill_only_for_same_settlement():
    bridge, _, _ = _make_bridge()

    bridge.finalize_turn(
        session_id="s1",
        question="这次门诊结算对不对",
        skill_id="mzsettlement_verify_skill",
        settlement_id="MZ-1",
    )

    assert bridge.last_skill_id("s1", "MZ-1") == "mzsettlement_verify_skill"
    assert bridge.last_skill_id("s1", "MZ-2") is None


def test_memory_upsert_replaces_same_ref_object():
    """同一结算单多次查询：记忆覆盖而非累积（version +1）。"""
    bridge, memory_manager, _ = _make_bridge()
    bridge.record_step(session_id="s1", step="settlement_query", detail={"a": 1}, settlement_id="1671213")
    bridge.record_step(session_id="s1", step="settlement_query", detail={"a": 2}, settlement_id="1671213")

    memories = memory_manager.get_by_session_and_type("s1", MemoryType.SETTLEMENT)
    assert len(memories) == 1
    assert memories[0].version == 1  # upsert 覆盖保留原 memory_id 与 version 字段（refresh 才 +1）
    assert memories[0].object_snapshot["a"] == 2


def test_bridge_degrades_gracefully_on_broken_store():
    """降级原则：存储异常时 prepare/record/finalize 返回安全值，不抛异常。"""
    class BrokenStore:
        def save(self, memory): raise RuntimeError("store down")
        def get(self, memory_id): raise RuntimeError("store down")
        def list_by_session(self, session_id): raise RuntimeError("store down")
        def list_by_session_and_type(self, session_id, type): raise RuntimeError("store down")
        def delete(self, memory_id): raise RuntimeError("store down")
        def delete_by_session(self, session_id): raise RuntimeError("store down")
        def delete_by_session_and_type(self, session_id, type): raise RuntimeError("store down")

    memory_manager = MemoryManager(BrokenStore())
    planner = ContextPlanner(memory_manager=memory_manager)
    bridge = PolicyQARuntimeBridge(memory_manager, ReasoningStateManager(), planner)

    assert bridge.prepare_turn(session_id="s1", question="q", settlement_id="1") is None
    assert bridge.record_step(session_id="s1", step="settlement_query", detail={}) == []
    assert bridge.finalize_turn(session_id="s1", question="q") == {}
