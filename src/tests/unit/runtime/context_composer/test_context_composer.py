"""Context Composer 单元测试

对应评估报告任务 1.4 / 2.2 验证标准：
- UT: compose 排序 + 预算分配
- UT: 超长上下文正确摘要
"""

from datetime import UTC, datetime

from src.runtime.context_composer.budget import TokenBudget
from src.runtime.context_composer.composer import ContextComposer
from src.runtime.context_composer.models import LLMContext, MemoryBrief
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType


def _make_memory(
    memory_id: str,
    importance: float,
    type: MemoryType = MemoryType.SETTLEMENT,
    ref_id: str = "setl-001",
    snapshot: dict | None = None,
) -> BusinessMemory:
    """构造测试用业务记忆。"""
    now = datetime.now(UTC).isoformat()
    return BusinessMemory(
        memory_id=memory_id,
        session_id="sess-001",
        type=type,
        ref_id=ref_id,
        object_snapshot=snapshot or {"amount": 100},
        importance=importance,
        expire_policy=ExpirePolicy.TOPIC,
        last_used_at=now,
        created_at=now,
    )


def test_token_budget_allocation():
    """预算按比例分配，总和不超过总预算。"""
    budget = TokenBudget(1000)
    alloc = budget.allocate()

    assert alloc["session_summary"] == 50
    assert alloc["current_entity"] == 300
    assert alloc["related_entities"] == 200
    assert alloc["reasoning_chain"] == 150
    assert alloc["conversation"] == 200
    assert alloc["reserve"] == 100
    assert sum(alloc.values()) <= 1000


def test_token_budget_default_total():
    """默认预算 4000。"""
    assert TokenBudget().total == 4000


def test_estimate_tokens_chinese_and_english():
    """中文按 1.5 token/字，英文按 0.25 token/字估算。"""
    budget = TokenBudget()
    # 纯英文 100 字符 ≈ 25 token
    assert budget.estimate_tokens("a" * 100) == 25
    # 纯中文 10 字 = 15 token
    assert budget.estimate_tokens("中" * 10) == 15
    # 中文比英文 token 密度高
    assert budget.estimate_tokens("中" * 10) > budget.estimate_tokens("a" * 10)


def test_compose_sorts_by_importance():
    """compose 输出按 importance 降序排列。"""
    composer = ContextComposer()
    memories = [
        _make_memory("m-low", importance=0.4),
        _make_memory("m-high", importance=0.9, ref_id="setl-002"),
        _make_memory("m-mid", importance=0.5, ref_id="setl-003"),
    ]

    result = composer.compose(memories)

    assert isinstance(result, LLMContext)
    importances = [m.importance for m in result.selected_memories]
    assert importances == sorted(importances, reverse=True)


def test_compose_high_priority_full_snapshot():
    """高优先级记忆（> 0.7）全量放入：摘要包含快照全部字段。"""
    composer = ContextComposer()
    snapshot = {"amount": 100, "name": "张三", "hospital": "市一院", "dept": "心内科"}
    memories = [_make_memory("m-high", importance=0.9, snapshot=snapshot)]

    result = composer.compose(memories)

    assert len(result.selected_memories) == 1
    summary = result.selected_memories[0].summary
    for key in snapshot:
        assert f"{key}=" in summary


def test_compose_medium_priority_summarized():
    """中优先级记忆（0.3 < x <= 0.7）摘要放入：仅保留前 3 个关键字段。"""
    composer = ContextComposer()
    snapshot = {"f1": "a", "f2": "b", "f3": "c", "f4": "d"}
    memories = [_make_memory("m-mid", importance=0.5, snapshot=snapshot)]

    result = composer.compose(memories)

    summary = result.selected_memories[0].summary
    assert "f1=" in summary and "f3=" in summary
    assert "f4=" not in summary


def test_compose_low_priority_skipped():
    """低优先级记忆（<= 0.3）丢弃，不进入 LLM Context。"""
    composer = ContextComposer()
    memories = [
        _make_memory("m-low", importance=0.2),
        _make_memory("m-high", importance=0.9, ref_id="setl-002"),
    ]

    result = composer.compose(memories)

    ids = [m.memory_id for m in result.selected_memories]
    assert "m-low" not in ids
    assert "m-high" in ids


def test_compose_medium_skipped_when_over_budget():
    """超出实体预算的中优先级记忆：压缩后仍超则跳过（摘要而非截断）。"""
    # 极小预算：current_entity(30%) + related_entities(20%) = 5 token
    composer = ContextComposer(token_budget=10)
    memories = [
        _make_memory("m-high", importance=0.9),
        _make_memory("m-mid", importance=0.5, ref_id="setl-002",
                     snapshot={"amount": 100, "name": "张三", "extra": "yyyy"}),
    ]

    result = composer.compose(memories)

    ids = [m.memory_id for m in result.selected_memories]
    assert "m-mid" not in ids


def test_compose_reasoning_chain_truncated_when_over_budget():
    """推理链超出 15% 预算时保留最近 3 步。"""
    composer = ContextComposer()  # 默认预算 4000，推理链预算 600 token
    # 每步 500 个英文字符 ≈ 125 token，10 步 ≈ 1250 token > 600
    long_chain = [f"step-{i} " + "x" * 500 for i in range(10)]

    result = composer.compose([], reasoning_chain=long_chain)

    assert len(result.reasoning_so_far) == 3
    assert result.reasoning_so_far[0].startswith("step-7")


def test_compose_returns_budget_usage():
    """LLMContext 携带预算使用量与总量。"""
    composer = ContextComposer(token_budget=2000)
    memories = [_make_memory("m-high", importance=0.9)]

    result = composer.compose(memories, session_summary="会话摘要")

    assert result.token_budget_total == 2000
    assert result.token_budget_used > 0
    assert result.session_summary == "会话摘要"


def test_memory_brief_model():
    """MemoryBrief 模型字段契约。"""
    brief = MemoryBrief(memory_id="m-1", type="settlement", summary="s", importance=0.8)
    assert brief.memory_id == "m-1"
    assert brief.importance == 0.8


def test_llm_context_defaults():
    """LLMContext 默认值契约。"""
    ctx = LLMContext()
    assert ctx.session_summary == ""
    assert ctx.selected_memories == []
    assert ctx.reasoning_so_far == []
    assert ctx.token_budget_used == 0
