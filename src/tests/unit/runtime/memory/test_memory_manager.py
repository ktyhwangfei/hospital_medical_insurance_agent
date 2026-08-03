"""MemoryManager 单元测试

对应评估报告任务 1.3 / 2.5 验证标准：
- UT: CRUD + 过期策略
- UT: ExpirePolicy.TIME 30 分钟无活动自动失效
"""

from datetime import UTC, datetime, timedelta

from src.data_platform.storage.memory.in_memory import InMemoryMemoryStore
from src.runtime.context.models import RuntimeContext
from src.runtime.memory.manager import MemoryManager
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType


def _make_memory(
    memory_id: str = "m-001",
    session_id: str = "sess-001",
    type: MemoryType = MemoryType.SETTLEMENT,
    ref_id: str | None = "setl-001",
    importance: float = 0.5,
    expire_policy: ExpirePolicy = ExpirePolicy.TOPIC,
    last_used_at: str | None = None,
    snapshot: dict | None = None,
    version: int = 1,
) -> BusinessMemory:
    """构造测试用业务记忆。"""
    now = datetime.now(UTC).isoformat()
    return BusinessMemory(
        memory_id=memory_id,
        session_id=session_id,
        type=type,
        ref_id=ref_id,
        object_snapshot=snapshot or {"amount": 100},
        importance=importance,
        expire_policy=expire_policy,
        version=version,
        last_used_at=last_used_at or now,
        created_at=now,
    )


def _make_manager() -> tuple[MemoryManager, InMemoryMemoryStore]:
    store = InMemoryMemoryStore()
    return MemoryManager(store, time_expire_minutes=30), store


def test_upsert_and_get():
    """新增记忆后可按 ID / 会话 / 类型查询。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory())

    assert manager.get("m-001") is not None
    assert len(manager.get_by_session("sess-001")) == 1
    assert len(manager.get_by_session_and_type("sess-001", MemoryType.SETTLEMENT)) == 1
    assert manager.get_by_session_and_type("sess-001", MemoryType.POLICY) == []


def test_upsert_replaces_same_object_memory():
    """同 session + type + ref_id 的记忆被覆盖：保留 memory_id 与 created_at。"""
    manager, _ = _make_manager()
    first = manager.upsert(_make_memory(snapshot={"amount": 100}))
    second = manager.upsert(
        _make_memory(memory_id="m-999", snapshot={"amount": 200})
    )

    # 覆盖后仍只有一条记忆，且沿用原 memory_id
    assert second.memory_id == first.memory_id == "m-001"
    assert second.created_at == first.created_at
    stored = manager.get("m-001")
    assert stored is not None
    assert stored.object_snapshot == {"amount": 200}
    assert len(manager.get_by_session("sess-001")) == 1


def test_get_or_resolve():
    """ref_id 精确匹配；未提供时返回该类型第一条。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(memory_id="m-001", ref_id="setl-001"))
    manager.upsert(_make_memory(memory_id="m-002", ref_id="setl-002"))

    resolved = manager.get_or_resolve("sess-001", MemoryType.SETTLEMENT, "setl-002")
    assert resolved is not None
    assert resolved.memory_id == "m-002"
    assert manager.get_or_resolve("sess-001", MemoryType.SETTLEMENT, "setl-404") is None
    assert manager.get_or_resolve("sess-001", MemoryType.SETTLEMENT) is not None
    assert manager.get_or_resolve("sess-001", MemoryType.DRUG) is None


def test_expire_by_policy_only_removes_matching():
    """按策略清除：仅删除指定策略的记忆。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(memory_id="m-topic", expire_policy=ExpirePolicy.TOPIC))
    manager.upsert(_make_memory(memory_id="m-sticky", ref_id="setl-002", expire_policy=ExpirePolicy.STICKY))

    count = manager.expire_by_policy("sess-001", ExpirePolicy.TOPIC)

    assert count == 1
    assert manager.get("m-topic") is None
    assert manager.get("m-sticky") is not None


def test_expire_on_topic_change():
    """话题切换时清除 TOPIC 策略记忆，STICKY 保留。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(memory_id="m-topic", expire_policy=ExpirePolicy.TOPIC))
    manager.upsert(_make_memory(memory_id="m-sticky", ref_id="setl-002", expire_policy=ExpirePolicy.STICKY))

    count = manager.expire_on_topic_change("sess-001", new_topic="qc")

    assert count == 1
    assert manager.get("m-sticky") is not None


def test_expire_by_time_removes_stale_time_policy_memories():
    """评估报告任务 2.5：TIME 策略记忆超过 30 分钟无活动自动失效。"""
    manager, _ = _make_manager()
    stale_time = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    fresh_time = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    manager.upsert(_make_memory(
        memory_id="m-stale", expire_policy=ExpirePolicy.TIME, last_used_at=stale_time,
    ))
    manager.upsert(_make_memory(
        memory_id="m-fresh", ref_id="setl-002",
        expire_policy=ExpirePolicy.TIME, last_used_at=fresh_time,
    ))
    manager.upsert(_make_memory(
        memory_id="m-topic-old", ref_id="setl-003",
        expire_policy=ExpirePolicy.TOPIC, last_used_at=stale_time,
    ))

    count = manager.expire_by_time("sess-001")

    # 仅 TIME 策略且超期的记忆被清除
    assert count == 1
    assert manager.get("m-stale") is None
    assert manager.get("m-fresh") is not None
    # TOPIC 策略即使超期也不受 TIME 清理影响
    assert manager.get("m-topic-old") is not None


def test_expire_by_time_ignores_unparseable_timestamp():
    """last_used_at 解析失败时保守处理：不过期。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(
        memory_id="m-bad", expire_policy=ExpirePolicy.TIME, last_used_at="not-a-date",
    ))

    assert manager.expire_by_time("sess-001") == 0
    assert manager.get("m-bad") is not None


def test_invalidate_object():
    """按对象类型失效：删除指定 session + type 的全部记忆。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(memory_id="m-001"))
    manager.upsert(_make_memory(memory_id="m-002", type=MemoryType.PATIENT, ref_id="p-1"))

    count = manager.invalidate_object("sess-001", MemoryType.SETTLEMENT.value)

    assert count == 1
    assert manager.get("m-001") is None
    assert manager.get("m-002") is not None


def test_compress_removes_low_importance_non_sticky():
    """压缩：删除 importance < 0.3 的非 STICKY 记忆。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(memory_id="m-low", importance=0.1))
    manager.upsert(_make_memory(memory_id="m-high", ref_id="setl-002", importance=0.9))
    manager.upsert(_make_memory(
        memory_id="m-low-sticky", ref_id="setl-003",
        importance=0.1, expire_policy=ExpirePolicy.STICKY,
    ))

    manager.compress("sess-001")

    assert manager.get("m-low") is None
    assert manager.get("m-high") is not None
    # STICKY 即使低重要性也保留
    assert manager.get("m-low-sticky") is not None


def test_compress_respects_keep_types():
    """压缩时 keep_types 指定的类型保留。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(
        memory_id="m-low-policy", type=MemoryType.POLICY, ref_id="pol-1", importance=0.1,
    ))

    manager.compress("sess-001", keep_types=[MemoryType.POLICY])

    assert manager.get("m-low-policy") is not None


def test_refresh_increments_version():
    """评估报告 §5.2：刷新快照时 version +1。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(version=1))

    stored = manager.get("m-001")
    assert stored is not None
    updated = manager.refresh(stored, {"amount": 300})

    assert updated.version == 2
    assert updated.object_snapshot == {"amount": 300}


def test_replay_session_returns_session_memories():
    """会话恢复：仅返回指定会话的记忆。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(memory_id="m-001"))
    manager.upsert(_make_memory(memory_id="m-other", session_id="sess-002"))

    replayed = manager.replay_session("sess-001")

    assert [m.memory_id for m in replayed] == ["m-001"]


def _make_context(session_id: str | None = "sess-001") -> RuntimeContext:
    """构造最小 RuntimeContext。"""
    return RuntimeContext(
        request_id="req-1",
        workflow_id="wf-1",
        user_id="u-1",
        role="cashier",
        message="查询结算",
        intent="settlement_exception_guidance",
        intent_confidence=0.9,
        requested_at=datetime.now(UTC).isoformat(),
        session_id=session_id,
    )


def test_build_context_memories_sorted_by_importance():
    """注入 RuntimeContext 的记忆按 importance + recency 降序。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory(memory_id="m-low", importance=0.4))
    manager.upsert(_make_memory(memory_id="m-high", ref_id="setl-002", importance=0.9))

    memories = manager.build_context_memories(_make_context())

    assert [m.memory_id for m in memories] == ["m-high", "m-low"]


def test_build_context_memories_without_session_returns_empty():
    """无 session_id 时不注入记忆。"""
    manager, _ = _make_manager()
    manager.upsert(_make_memory())

    assert manager.build_context_memories(_make_context(session_id=None)) == []


def test_build_context_memories_triggers_time_expire():
    """构建上下文前先清理超期 TIME 记忆。"""
    manager, _ = _make_manager()
    stale = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
    manager.upsert(_make_memory(
        memory_id="m-stale", expire_policy=ExpirePolicy.TIME, last_used_at=stale,
    ))

    memories = manager.build_context_memories(_make_context())

    assert memories == []
    assert manager.get("m-stale") is None
