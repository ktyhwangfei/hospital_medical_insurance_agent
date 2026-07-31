"""BusinessMemory 模型单元测试

对应评估报告任务 1.2 验证标准：UT: CRUD（模型层字段与枚举）。
"""

from datetime import UTC, datetime

from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType


def _make_memory(**overrides) -> BusinessMemory:
    """构造测试用业务记忆，允许按字段覆盖。"""
    now = datetime.now(UTC).isoformat()
    defaults = {
        "memory_id": "m-001",
        "session_id": "sess-001",
        "type": MemoryType.SETTLEMENT,
        "ref_id": "setl-001",
        "object_snapshot": {"amount": 100},
        "last_used_at": now,
        "created_at": now,
    }
    defaults.update(overrides)
    return BusinessMemory(**defaults)


def test_memory_type_enum_values():
    """记忆类型枚举覆盖语义层业务对象。"""
    assert MemoryType.PATIENT == "patient"
    assert MemoryType.SETTLEMENT == "settlement"
    assert MemoryType.POLICY == "policy"
    assert MemoryType.CONVERSATION == "conversation"
    # StrEnum 可直接与字符串比较
    assert MemoryType.VISIT == "visit"


def test_expire_policy_contains_time():
    """过期策略包含 TIME（评估报告 §5.1：30 分钟无活动自动失效）。"""
    assert ExpirePolicy.SESSION == "session"
    assert ExpirePolicy.TOPIC == "topic"
    assert ExpirePolicy.STICKY == "sticky"
    assert ExpirePolicy.TIME == "time"


def test_business_memory_defaults():
    """默认字段：importance/confidence 0.5、TOPIC 策略、version 1。"""
    memory = _make_memory()
    assert memory.importance == 0.5
    assert memory.confidence == 0.5
    assert memory.expire_policy == ExpirePolicy.TOPIC
    assert memory.version == 1
    assert memory.relations == []


def test_business_memory_has_version_field():
    """评估报告 §5.2：BusinessMemory 必须有 version 字段用于刷新检测。"""
    memory = _make_memory(version=3)
    assert memory.version == 3


def test_business_memory_serialization_roundtrip():
    """模型可序列化/反序列化（存储层 JSON 化的前提）。"""
    memory = _make_memory(relations=["m-002"], importance=0.9)
    data = memory.model_dump(mode="json")
    restored = BusinessMemory.model_validate(data)
    assert restored.memory_id == memory.memory_id
    assert restored.type == MemoryType.SETTLEMENT
    assert restored.expire_policy == ExpirePolicy.TOPIC
    assert restored.relations == ["m-002"]
    assert restored.object_snapshot == {"amount": 100}
