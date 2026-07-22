"""Session 存储服务单元测试"""

import pytest
from src.data_platform.storage.session.in_memory import InMemorySessionStorage
from src.data_platform.storage.session.ports import SessionStorage
from src.domain.session.models import Session


class TestInMemorySessionStorage:
    """测试内存 Session 存储"""

    @pytest.fixture
    def store(self) -> InMemorySessionStorage:
        return InMemorySessionStorage()

    def test_create_session(self, store: InMemorySessionStorage):
        session = store.create_or_update_session("sess-1", "user-1", "cashier")
        assert session.session_id == "sess-1"
        assert session.user_id == "user-1"
        assert session.role == "cashier"
        assert session.created_at != ""
        assert session.last_active != ""

    def test_create_session_without_role(self, store: InMemorySessionStorage):
        session = store.create_or_update_session("sess-2", "user-2")
        assert session.role == ""

    def test_update_session_refreshes_last_active(self, store: InMemorySessionStorage):
        s1 = store.create_or_update_session("sess-3", "user-3", "patient")
        import time
        time.sleep(0.1)
        s2 = store.create_or_update_session("sess-3", "user-3", "patient")
        assert s2.last_active > s1.last_active
        assert s2.created_at == s1.created_at  # created_at 不变

    def test_get_session(self, store: InMemorySessionStorage):
        store.create_or_update_session("sess-4", "user-4", "doctor")
        found = store.get_session("sess-4")
        assert found is not None
        assert found.user_id == "user-4"

    def test_get_session_not_found(self, store: InMemorySessionStorage):
        assert store.get_session("nonexistent") is None

    def test_list_sessions_by_user(self, store: InMemorySessionStorage):
        store.create_or_update_session("sess-5", "user-a", "cashier")
        store.create_or_update_session("sess-6", "user-a", "doctor")
        store.create_or_update_session("sess-7", "user-b", "patient")

        user_a_sessions = store.list_sessions_by_user("user-a")
        assert len(user_a_sessions) == 2
        assert all(s.user_id == "user-a" for s in user_a_sessions)

        user_b_sessions = store.list_sessions_by_user("user-b")
        assert len(user_b_sessions) == 1
        assert user_b_sessions[0].user_id == "user-b"

    def test_list_sessions_by_user_empty(self, store: InMemorySessionStorage):
        assert store.list_sessions_by_user("no-such-user") == []

    def test_list_all_sessions(self, store: InMemorySessionStorage):
        store.create_or_update_session("sess-8", "user-c", "cashier")
        store.create_or_update_session("sess-9", "user-d", "patient")
        all_sessions = store.list_sessions()
        assert len(all_sessions) >= 2

    def test_list_sessions_pagination(self, store: InMemorySessionStorage):
        for i in range(10):
            store.create_or_update_session(f"sess-p{i}", f"user-{i}", "cashier")
        
        page1 = store.list_sessions(limit=5, offset=0)
        assert len(page1) == 5
        
        page2 = store.list_sessions(limit=5, offset=5)
        assert len(page2) == 5
        
        # 不应有重叠
        ids1 = {s.session_id for s in page1}
        ids2 = {s.session_id for s in page2}
        assert ids1.isdisjoint(ids2)

    def test_health(self, store: InMemorySessionStorage):
        store.create_or_update_session("sess-h", "user-h", "doctor")
        health = store.health()
        assert health.status.value == "healthy"
        assert health.session_count >= 1

    def test_conforms_to_protocol(self, store: InMemorySessionStorage):
        """验证 InMemorySessionStorage 符合 SessionStorage Protocol"""
        # Python Protocol 是结构性子类型，不需要显式继承
        # 运行时通过方法签名验证
        assert hasattr(store, "create_or_update_session")
        assert hasattr(store, "get_session")
        assert hasattr(store, "list_sessions_by_user")
        assert hasattr(store, "list_sessions")
        assert hasattr(store, "health")


class TestSessionDomainModel:
    """测试 Session 领域模型"""

    def test_create_session_with_defaults(self):
        from src.domain.session.models import create_session
        session = create_session("sess-d1", "user-d1", "cashier")
        assert session.session_id == "sess-d1"
        assert session.user_id == "user-d1"
        assert session.role == "cashier"
        assert session.created_at != ""
        assert session.last_active != ""

    def test_session_serialization(self):
        session = Session(
            session_id="sess-s1",
            user_id="user-s1",
            role="patient",
            created_at="2026-06-18T10:00:00",
            last_active="2026-06-18T10:05:00",
        )
        d = session.model_dump()
        assert d["session_id"] == "sess-s1"
        assert d["user_id"] == "user-s1"
        assert d["role"] == "patient"
