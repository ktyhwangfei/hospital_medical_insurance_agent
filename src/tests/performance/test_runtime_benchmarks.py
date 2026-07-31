"""Runtime 性能基准测试（评估报告阶段三 3.2）

验证标准：
- Memory 操作平均耗时 < 10ms
- ContextComposer.compose 平均耗时 < 50ms

说明：
- 本文件为微基准（进程内直测），不依赖运行中的后端服务，
  与 Locust 压测（scenarios/，HTTP 级）互补。
- 采用多轮迭代取平均值，避免单次计时抖动导致误判。
- 运行：python -m pytest src/tests/performance/test_runtime_benchmarks.py -v -s
"""

import time
from datetime import UTC, datetime
from statistics import mean

from src.data_platform.storage.memory.in_memory import InMemoryMemoryStore
from src.runtime.context_composer.composer import ContextComposer
from src.runtime.memory.manager import MemoryManager
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType

# 评估报告阶段三 3.2 的性能阈值（毫秒）
MEMORY_OP_THRESHOLD_MS = 10
COMPOSER_THRESHOLD_MS = 50

# 迭代次数：足够平滑计时抖动
ITERATIONS = 300


def _make_memory(memory_id: str, session_id: str, importance: float = 0.5) -> BusinessMemory:
    """构造基准测试用业务记忆（含典型规模快照）。"""
    now = datetime.now(UTC).isoformat()
    return BusinessMemory(
        memory_id=memory_id,
        session_id=session_id,
        type=MemoryType.SETTLEMENT,
        ref_id=f"ref-{memory_id}",
        object_snapshot={
            "settlement_id": f"setl-{memory_id}",
            "total_amount": 12345.67,
            "insurance_pay": 8000.00,
            "self_pay": 4345.67,
            "hospital": "市第一人民医院",
            "dept": "心血管内科",
        },
        importance=importance,
        expire_policy=ExpirePolicy.TOPIC,
        last_used_at=now,
        created_at=now,
    )


def _timed(fn, iterations: int = ITERATIONS) -> float:
    """计时辅助：执行 fn iterations 次，返回平均耗时（毫秒）。"""
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return mean(samples)


def test_memory_crud_operations_under_10ms():
    """Memory 基础操作（save/get/list）平均耗时 < 10ms。"""
    store = InMemoryMemoryStore()
    session_id = "bench-session"
    # 预置 50 条记忆，模拟真实会话规模
    for i in range(50):
        store.save(_make_memory(f"m-{i}", session_id))

    avg_save = _timed(lambda: store.save(_make_memory("m-bench", session_id)))
    avg_get = _timed(lambda: store.get("m-bench"))
    avg_list = _timed(lambda: store.list_by_session(session_id))
    avg_delete = _timed(lambda: store.delete("m-bench"))

    print(
        f"\n[基准] Memory save={avg_save:.3f}ms get={avg_get:.3f}ms "
        f"list(50条)={avg_list:.3f}ms delete={avg_delete:.3f}ms "
        f"(阈值 {MEMORY_OP_THRESHOLD_MS}ms)"
    )
    assert avg_save < MEMORY_OP_THRESHOLD_MS, f"save 平均 {avg_save:.2f}ms ≥ {MEMORY_OP_THRESHOLD_MS}ms"
    assert avg_get < MEMORY_OP_THRESHOLD_MS, f"get 平均 {avg_get:.2f}ms ≥ {MEMORY_OP_THRESHOLD_MS}ms"
    assert avg_list < MEMORY_OP_THRESHOLD_MS, f"list 平均 {avg_list:.2f}ms ≥ {MEMORY_OP_THRESHOLD_MS}ms"
    assert avg_delete < MEMORY_OP_THRESHOLD_MS, f"delete 平均 {avg_delete:.2f}ms ≥ {MEMORY_OP_THRESHOLD_MS}ms"


def test_memory_manager_operations_under_10ms():
    """MemoryManager 典型操作组合（upsert 覆盖 + get_or_resolve + 过期扫描）平均 < 10ms。"""
    store = InMemoryMemoryStore()
    manager = MemoryManager(store)
    session_id = "bench-session"
    manager.upsert(_make_memory("m-bench", session_id))

    def _manager_ops():
        manager.upsert(_make_memory("m-bench", session_id, importance=0.8))
        manager.get_or_resolve(session_id, MemoryType.SETTLEMENT, "ref-m-bench")
        manager.expire_by_time(session_id)

    avg = _timed(_manager_ops)

    print(f"\n[基准] MemoryManager 组合操作={avg:.3f}ms (阈值 {MEMORY_OP_THRESHOLD_MS}ms)")
    assert avg < MEMORY_OP_THRESHOLD_MS, f"MemoryManager 组合操作平均 {avg:.2f}ms ≥ {MEMORY_OP_THRESHOLD_MS}ms"


def test_context_composer_under_50ms():
    """Composer 在典型规模（60 条记忆 + 推理链）下 compose 平均耗时 < 50ms。"""
    composer = ContextComposer()
    session_id = "bench-session"
    # 20 高优先级 + 30 中优先级 + 10 低优先级，模拟真实会话记忆规模
    memories = (
        [_make_memory(f"m-high-{i}", session_id, importance=0.8) for i in range(20)]
        + [_make_memory(f"m-mid-{i}", session_id, importance=0.5) for i in range(30)]
        + [_make_memory(f"m-low-{i}", session_id, importance=0.2) for i in range(10)]
    )
    reasoning_chain = [f"[fact] 推理步骤 {i}" for i in range(5)]

    avg = _timed(lambda: composer.compose(memories, reasoning_chain=reasoning_chain))

    print(f"\n[基准] Composer.compose(60条记忆+5步推理链)={avg:.3f}ms (阈值 {COMPOSER_THRESHOLD_MS}ms)")
    assert avg < COMPOSER_THRESHOLD_MS, f"compose 平均 {avg:.2f}ms ≥ {COMPOSER_THRESHOLD_MS}ms"
