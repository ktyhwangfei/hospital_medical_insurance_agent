"""ContextPlanner 单元测试

对应评估报告任务 2.1 / 2.6 验证标准：
- 连续追问正确识别所需上下文（Memory 命中/缺失）
- 主体切换检测（"查询张三"→"查询李四"）
"""

from datetime import UTC, datetime

from src.runtime.context.models import RuntimeContext, Turn
from src.runtime.intent.models import IntentResult
from src.runtime.intent.planner import ContextNeed, ContextPlanner
from src.runtime.memory.manager import MemoryManager
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType
from src.data_platform.storage.memory.in_memory import InMemoryMemoryStore


def _make_intent(intent: str = "policy_qa_fee_decomposition", message: str = "解释统筹自付", entities: dict | None = None) -> IntentResult:
    return IntentResult(
        intent=intent,
        confidence=0.9,
        entities=entities or {},
        raw_message=message,
    )


def _make_context(
    message: str = "解释统筹自付",
    intent: str = "policy_qa_fee_decomposition",
    session_id: str | None = "sess-001",
    conversation_turns: list[Turn] | None = None,
) -> RuntimeContext:
    return RuntimeContext(
        request_id="req-1",
        workflow_id="wf-1",
        user_id="u-1",
        role="cashier",
        message=message,
        intent=intent,
        intent_confidence=0.9,
        requested_at=datetime.now(UTC).isoformat(),
        session_id=session_id,
        conversation_turns=conversation_turns or [],
    )


def _make_memory(memory_id: str, session_id: str, type: MemoryType) -> BusinessMemory:
    now = datetime.now(UTC).isoformat()
    return BusinessMemory(
        memory_id=memory_id,
        session_id=session_id,
        type=type,
        ref_id=f"ref-{memory_id}",
        expire_policy=ExpirePolicy.TOPIC,
        last_used_at=now,
        created_at=now,
    )


def test_context_need_defaults():
    """ContextNeed 默认值契约。"""
    need = ContextNeed()
    assert need.object_types == []
    assert need.memory_ids == []
    assert need.must_query_semantic is False
    assert need.topic_changed is False
    assert need.subject_changed is False


def test_plan_resolves_types_from_intent_map():
    """按 INTENT_OBJECT_MAP 解析所需业务对象类型。"""
    planner = ContextPlanner()
    need = planner.plan(_make_intent("policy_qa_fee_decomposition"), _make_context())

    assert set(need.object_types) == {"settlement", "policy", "rule"}


def test_plan_fee_keywords_add_settlement_and_policy():
    """费用关键词（如"统筹自付"）自动追加 SETTLEMENT + POLICY 类型。"""
    planner = ContextPlanner()
    intent = _make_intent("skill_execution", message="统筹自付是怎么算的")
    context = _make_context(message="统筹自付是怎么算的", intent="skill_execution")

    need = planner.plan(intent, context)

    assert "settlement" in need.object_types
    assert "policy" in need.object_types


def test_plan_entities_add_types():
    """实体中的 settlement_id / 消息中的"药"触发对应类型。"""
    planner = ContextPlanner()
    intent = _make_intent("skill_execution", entities={"settlement_id": "s-1"})
    context = _make_context(message="这个药能报销吗", intent="skill_execution")

    need = planner.plan(intent, context)

    assert "settlement" in need.object_types
    assert "drug" in need.object_types


def test_plan_marks_must_query_semantic_when_memory_missing():
    """Memory 缺失所需类型时标记 must_query_semantic=True（下探语义层）。"""
    manager = MemoryManager(InMemoryMemoryStore())
    planner = ContextPlanner(memory_manager=manager)

    need = planner.plan(_make_intent("policy_qa_fee_decomposition"), _make_context())

    assert need.must_query_semantic is True
    assert need.memory_ids == []


def test_plan_hits_existing_memories():
    """Memory 已有所需类型时命中记忆，无需下探语义层。"""
    manager = MemoryManager(InMemoryMemoryStore())
    manager.upsert(_make_memory("m-1", "sess-001", MemoryType.SETTLEMENT))
    manager.upsert(_make_memory("m-2", "sess-001", MemoryType.POLICY))
    manager.upsert(_make_memory("m-3", "sess-001", MemoryType.RULE))
    planner = ContextPlanner(memory_manager=manager)

    need = planner.plan(_make_intent("policy_qa_fee_decomposition"), _make_context())

    assert need.must_query_semantic is False
    assert set(need.memory_ids) == {"m-1", "m-2", "m-3"}


def test_plan_without_memory_manager_skips_memory_check():
    """未注入 MemoryManager 时不做记忆检查（降级行为）。"""
    planner = ContextPlanner(memory_manager=None)

    need = planner.plan(_make_intent("policy_qa_fee_decomposition"), _make_context())

    assert need.must_query_semantic is False
    assert need.memory_ids == []


def test_subject_change_detected_on_query_new_person():
    """评估报告任务 2.6："查询张三"类消息检测出业务主体切换。"""
    planner = ContextPlanner()
    context = _make_context(message="查询张三的费用")

    need = planner.plan(_make_intent(), context)

    assert need.subject_changed is True


def test_subject_change_not_detected_on_normal_message():
    """常规追问（如"为什么这么多"）不判定为主体切换。"""
    planner = ContextPlanner()
    context = _make_context(message="为什么这么多")

    need = planner.plan(_make_intent(), context)

    assert need.subject_changed is False


def test_subject_change_requires_session():
    """无 session_id 时不检测主体切换。"""
    planner = ContextPlanner()
    context = _make_context(message="查询张三的费用", session_id=None)

    need = planner.plan(_make_intent(), context)

    assert need.subject_changed is False


def test_topic_change_detected_on_intent_change():
    """意图变化判定为话题切换。"""
    planner = ContextPlanner()
    turns = [Turn(role="human", message="查政策", intent="other_policy_topic")]
    context = _make_context(
        intent="policy_qa_fee_decomposition",
        conversation_turns=turns,
    )

    need = planner.plan(_make_intent(), context)

    assert need.topic_changed is True


def test_topic_change_not_detected_on_same_intent():
    """同一意图的连续追问不算话题切换。"""
    planner = ContextPlanner()
    turns = [Turn(role="human", message="解释统筹自付", intent="policy_qa_fee_decomposition")]
    context = _make_context(
        intent="policy_qa_fee_decomposition",
        conversation_turns=turns,
    )

    need = planner.plan(_make_intent(), context)

    assert need.topic_changed is False


def test_topic_change_fee_intents_exempt():
    """费用相关意图之间的切换（policy_qa_fee_decomposition ↔ skill_execution）不算话题切换。"""
    planner = ContextPlanner()
    turns = [Turn(role="human", message="查费用", intent="policy_qa_fee_decomposition")]
    context = _make_context(intent="skill_execution", conversation_turns=turns)

    need = planner.plan(_make_intent(), context)

    assert need.topic_changed is False


def test_topic_change_not_detected_without_turns():
    """无对话历史时不判定话题切换。"""
    planner = ContextPlanner()

    need = planner.plan(_make_intent(), _make_context())

    assert need.topic_changed is False
