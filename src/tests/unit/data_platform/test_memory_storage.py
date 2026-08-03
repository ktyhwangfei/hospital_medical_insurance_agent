"""Memory 存储单元测试（data_platform/storage/memory）

对应评估报告任务 1.7 / 3.3 验证标准：
- UT: MemoryStore Protocol 内存实现 CRUD
- UT: 配 USE_MEMORY_STORAGE 回退（灰度切换）
"""

from datetime import UTC, datetime

from src.data_platform.storage.memory.factory import create_memory_store
from src.data_platform.storage.memory.in_memory import InMemoryMemoryStore
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType


def _make_memory(
    memory_id: str = "m-001",
    session_id: str = "sess-001",
    type: MemoryType = MemoryType.SETTLEMENT,
) -> BusinessMemory:
    """构造测试用业务记忆。"""
    now = datetime.now(UTC).isoformat()
    return BusinessMemory(
        memory_id=memory_id,
        session_id=session_id,
        type=type,
        ref_id="setl-001",
        expire_policy=ExpirePolicy.TOPIC,
        last_used_at=now,
        created_at=now,
    )


def test_in_memory_store_crud():
    """内存实现完整 CRUD。"""
    store = InMemoryMemoryStore()
    store.save(_make_memory())

    assert store.get("m-001") is not None
    assert store.get("m-404") is None
    assert len(store.list_by_session("sess-001")) == 1
    assert store.list_by_session("sess-404") == []

    # 更新（同 ID 覆盖）
    updated = _make_memory()
    updated.object_snapshot = {"amount": 200}
    store.save(updated)
    stored = store.get("m-001")
    assert stored is not None
    assert stored.object_snapshot == {"amount": 200}

    # 删除
    assert store.delete("m-001") is True
    assert store.delete("m-001") is False
    assert store.get("m-001") is None


def test_in_memory_store_list_by_session_and_type():
    """按会话 + 类型过滤（StrEnum 与字符串等值比较）。"""
    store = InMemoryMemoryStore()
    store.save(_make_memory(memory_id="m-1", type=MemoryType.SETTLEMENT))
    store.save(_make_memory(memory_id="m-2", type=MemoryType.PATIENT))

    result = store.list_by_session_and_type("sess-001", "settlement")

    assert [m.memory_id for m in result] == ["m-1"]


def test_in_memory_store_delete_by_session():
    """按会话批量删除。"""
    store = InMemoryMemoryStore()
    store.save(_make_memory(memory_id="m-1"))
    store.save(_make_memory(memory_id="m-2"))
    store.save(_make_memory(memory_id="m-3", session_id="sess-002"))

    assert store.delete_by_session("sess-001") == 2
    assert store.get("m-3") is not None


def test_in_memory_store_delete_by_session_and_type():
    """按会话 + 类型批量删除。"""
    store = InMemoryMemoryStore()
    store.save(_make_memory(memory_id="m-1", type=MemoryType.SETTLEMENT))
    store.save(_make_memory(memory_id="m-2", type=MemoryType.PATIENT))

    assert store.delete_by_session_and_type("sess-001", "settlement") == 1
    assert store.get("m-2") is not None


def test_factory_returns_in_memory_when_env_set(monkeypatch):
    """评估报告任务 3.3：USE_MEMORY_STORAGE=1 时工厂回退内存实现。"""
    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")

    store = create_memory_store()

    assert isinstance(store, InMemoryMemoryStore)


def test_factory_falls_back_to_in_memory_on_postgres_failure(monkeypatch):
    """PostgreSQL 不可用时工厂自动回退内存实现（优雅降级）。"""
    monkeypatch.delenv("USE_MEMORY_STORAGE", raising=False)

    # 模拟 PostgreSQL 存储构造失败
    def _broken_init(self, database_url: str):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "src.data_platform.storage.memory.postgres.PostgresMemoryStore.__init__",
        _broken_init,
    )

    store = create_memory_store()

    assert isinstance(store, InMemoryMemoryStore)


def test_factory_in_memory_store_supports_full_crud(monkeypatch):
    """灰度回退后零功能回归：内存实现支持 MemoryStore 全部端口操作。"""
    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    store = create_memory_store()

    # 走一遍完整 CRUD 验证端口契约不缺失
    store.save(_make_memory(memory_id="m-1"))
    store.save(_make_memory(memory_id="m-2", type=MemoryType.POLICY))
    assert store.get("m-1") is not None
    assert len(store.list_by_session("sess-001")) == 2
    assert len(store.list_by_session_and_type("sess-001", "policy")) == 1
    assert store.delete("m-1") is True
    assert store.delete_by_session_and_type("sess-001", "policy") == 1
    assert store.delete_by_session("sess-001") == 0
