"""政策问答 Runtime 增强桥

将会话级 Runtime 能力接入政策问答流式管线：
- ContextPlanner：规划上下文需求，检测话题/业务主体切换
- MemoryManager：沉淀结算/政策/对话记忆，支撑连续追问
- ReasoningStateManager：维护推理链，满足"来源可追溯"安全约束

设计原则：增强失败绝不阻塞主流式响应（所有公共方法内部捕获异常并降级）。
对应 SSE 事件契约见 docs/steering/医保Agent-Runtime设计-V1.0-评估报告.md 与本模块 docstring：

    event: context_need    — 每轮一次，规划结果（含 subject_changed / must_query_semantic）
    event: memory_update   — 每次记忆写入，payload 为精简记忆卡
    event: reasoning_step  — 每个推理步骤，含 claim / kind / source_memory_ids
    result 事件附加字段     — reasoning_chain / reasoning_steps / memory_count
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from src.runtime.context.models import RuntimeContext, Turn
from src.runtime.intent.models import IntentResult
from src.runtime.intent.planner import ContextPlanner
from src.runtime.memory.manager import MemoryManager
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType
from src.runtime.reasoning.manager import ReasoningStateManager

logger = logging.getLogger(__name__)

# 政策问答场景的意图标识（用于 ContextPlanner 的话题切换检测与类型映射）
_POLICY_QA_INTENT = "policy_qa_fee_decomposition"

# 记忆重要度与过期策略约定
_SETTLEMENT_IMPORTANCE = 0.9   # 当前业务实体：最高优先级
_POLICY_IMPORTANCE = 0.8       # 政策依据：跨话题保留
_CONVERSATION_IMPORTANCE = 0.6  # 对话摘要：跨话题保留

# 记忆快照中最多保留的标量字段数（防止快照膨胀）
_MAX_SNAPSHOT_FIELDS = 8
_MAX_SNAPSHOT_VALUE_LEN = 64


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_memory_id() -> str:
    return f"m-{uuid.uuid4().hex[:12]}"


# 话题推导规则：问题关键词 → 顶栏话题标签（优先级从高到低）
_TOPIC_RULES: list[tuple[tuple[str, ...], str]] = [
    (("起付线", "门槛费", "门槛"), "起付线"),
    (("统筹自付", "自付", "统筹支付", "报销比例", "报销多少"), "统筹自付/报销"),
    (("大额", "封顶线", "最高支付限额"), "大额/封顶"),
    (("个人应负", "个人负担", "个人总支付"), "个人负担"),
    (("医保外", "自费", "不在医保"), "医保外费用"),
    (("住院费用", "费用构成", "费用分解", "费用明细", "总费用"), "费用构成"),
    (("药品", "药"), "药品费用"),
]


def _derive_topic(question: str) -> str | None:
    """从问题关键词推导话题标签（供顶栏锚点展示）。"""
    for keywords, label in _TOPIC_RULES:
        if any(kw in question for kw in keywords):
            return label
    return None


def _pick_snapshot_fields(detail: dict[str, Any]) -> dict[str, Any]:
    """从步骤 detail 中挑选小规模标量字段作为记忆快照。"""
    snapshot: dict[str, Any] = {}
    for key, value in detail.items():
        if len(snapshot) >= _MAX_SNAPSHOT_FIELDS:
            break
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        if isinstance(value, str) and len(value) > _MAX_SNAPSHOT_VALUE_LEN:
            continue
        snapshot[key] = value
    return snapshot


def _memory_card(memory: BusinessMemory) -> dict[str, Any]:
    """将记忆转换为 SSE 传输的精简卡片。

    snapshot 为 record_step 时经 _pick_snapshot_fields 挑选的小规模标量
    （≤8 字段、值 ≤64 字符），不含完整快照，防泄漏；前端据此展示业务值。
    """
    return {
        "memory_id": memory.memory_id,
        "type": memory.type.value,
        "ref_id": memory.ref_id,
        "importance": memory.importance,
        "expire_policy": memory.expire_policy.value,
        "version": memory.version,
        "snapshot_keys": list(memory.object_snapshot.keys()),
        "snapshot": dict(memory.object_snapshot),
    }


class PolicyQARuntimeBridge:
    """政策问答 Runtime 增强桥（无状态门面，状态由注入的 Manager 持有）"""

    def __init__(
        self,
        memory_manager: MemoryManager,
        reasoning_manager: ReasoningStateManager,
        planner: ContextPlanner,
    ):
        self._memory = memory_manager
        self._reasoning = reasoning_manager
        self._planner = planner

    # ── 轮次开始：上下文规划 ─────────────────────────────────────

    def prepare_turn(
        self,
        *,
        session_id: str,
        question: str,
        settlement_id: str,
        user_id: str = "",
        role: str = "",
    ) -> dict[str, Any] | None:
        """规划本轮上下文需求，返回 context_need 事件 payload。

        副作用：检测到业务主体切换时，按 TOPIC 策略清理过期记忆。
        失败时返回 None（降级：不影响主流程）。
        """
        try:
            context = self._build_context(session_id, question, user_id, role)
            intent_result = IntentResult(
                intent=_POLICY_QA_INTENT,
                confidence=1.0,
                entities={"settlement_id": settlement_id} if settlement_id else {},
                raw_message=question,
            )
            need = self._planner.plan(intent_result, context)

            # 主体切换：清理 TOPIC 记忆，防止旧上下文污染新主体的回答
            if need.subject_changed:
                expired = self._memory.expire_on_topic_change(session_id, new_topic="subject_switch")
                logger.info(
                    f"[RUNTIME-BRIDGE] 主体切换，清理 {expired} 条 TOPIC 记忆 (session={session_id})"
                )

            return {
                "session_id": session_id,
                "settlement_id": settlement_id or None,
                "topic": _derive_topic(question),
                "object_types": need.object_types,
                "memory_ids": need.memory_ids,
                "must_query_semantic": need.must_query_semantic,
                "topic_changed": need.topic_changed,
                "subject_changed": need.subject_changed,
            }
        except Exception as e:
            logger.warning(f"[RUNTIME-BRIDGE] prepare_turn 降级: {e}")
            return None

    def last_skill_id(self, session_id: str, settlement_id: str) -> str | None:
        """返回同一结算单上一轮成功使用的 Skill。"""
        try:
            memories = self._memory.get_by_session_and_type(
                session_id, MemoryType.CONVERSATION
            )
            if not memories:
                return None
            snapshot = memories[0].object_snapshot
            if snapshot.get("last_settlement_id") != settlement_id:
                return None
            skill_id = str(snapshot.get("last_skill_id") or "").strip()
            return skill_id or None
        except Exception as e:
            logger.warning(f"[RUNTIME-BRIDGE] last_skill_id 降级: {e}")
            return None

    # ── 步骤完成：沉淀记忆与推理 ─────────────────────────────────

    def record_step(
        self,
        *,
        session_id: str,
        step: str,
        detail: dict[str, Any],
        settlement_id: str = "",
    ) -> list[tuple[str, dict[str, Any]]]:
        """步骤完成时写入记忆与推理步骤，返回待发送的 (event_type, payload) 列表。

        失败时返回空列表（降级）。
        """
        events: list[tuple[str, dict[str, Any]]] = []
        try:
            if step in ("settlement_query", "query_sql_data"):
                events.extend(self._on_settlement_query(session_id, detail, settlement_id))
            elif step in ("policy_rule_search", "structured_policy_query", "search_policy_rules"):
                events.extend(self._on_policy_search(session_id, detail))
            elif step == "calculate_explanation":
                events.extend(self._on_calculate(session_id, detail))
            elif step == "answer_generation":
                events.extend(self._on_answer(session_id))
        except Exception as e:
            logger.warning(f"[RUNTIME-BRIDGE] record_step({step}) 降级: {e}")
            return []
        return events

    def _on_settlement_query(
        self, session_id: str, detail: dict[str, Any], settlement_id: str
    ) -> list[tuple[str, dict[str, Any]]]:
        """结算数据获取完成：写入 SETTLEMENT 记忆 + fact 推理步。"""
        ref_id = settlement_id or str(detail.get("settlement_id") or "")
        snapshot = _pick_snapshot_fields(detail)
        if ref_id:
            snapshot.setdefault("settlement_id", ref_id)
        memory = self._upsert_memory(
            session_id=session_id,
            type=MemoryType.SETTLEMENT,
            ref_id=ref_id or None,
            snapshot=snapshot,
            importance=_SETTLEMENT_IMPORTANCE,
            expire_policy=ExpirePolicy.TOPIC,
        )
        step = self._reasoning.add_step(
            session_id,
            claim=f"已获取结算单 {ref_id or '未知'} 的结算数据",
            kind="fact",
            confidence=0.95,
            source_memory_ids=[memory.memory_id],
        )
        return [
            ("memory_update", {"action": "upsert", "memory": _memory_card(memory)}),
            ("reasoning_step", step.model_dump()),
        ]

    def _on_policy_search(
        self, session_id: str, detail: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        """政策检索完成：写入 POLICY 记忆 + fact 推理步。"""
        rules_count = detail.get("rules_count", 0)
        try:
            rules_count = int(rules_count)
        except (TypeError, ValueError):
            rules_count = 0
        filters = detail.get("policy_filters", [])
        memory = self._upsert_memory(
            session_id=session_id,
            type=MemoryType.POLICY,
            ref_id=None,  # 政策记忆按类型单条聚合（upsert 会覆盖同 ref_id=None 的旧记忆）
            snapshot={"rules_count": rules_count, "policy_filters": filters[:_MAX_SNAPSHOT_FIELDS] if isinstance(filters, list) else []},
            importance=_POLICY_IMPORTANCE,
            expire_policy=ExpirePolicy.STICKY,
        )
        step = self._reasoning.add_step(
            session_id,
            claim=f"检索到 {rules_count} 条相关政策规则",
            kind="fact",
            confidence=0.85,
            source_memory_ids=[memory.memory_id],
        )
        return [
            ("memory_update", {"action": "upsert", "memory": _memory_card(memory)}),
            ("reasoning_step", step.model_dump()),
        ]

    def _on_calculate(
        self, session_id: str, detail: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        """分段计算完成：记录带真实金额的 inference 推理步（业务化 claim）。"""
        settlement_memories = self._memory.get_by_session_and_type(session_id, MemoryType.SETTLEMENT)
        source_ids = [m.memory_id for m in settlement_memories[:1]]

        # 从步骤 detail 提取真实金额，生成业务化推理 claim（防御性取值）
        treatment = (detail or {}).get("treatment", {}) if isinstance(detail, dict) else {}
        if not isinstance(treatment, dict):
            treatment = {}
        try:
            pooling_self_pay = float(treatment.get("pooling_self_pay", 0) or 0)
            deductible = float(treatment.get("deductible", 0) or 0)
            major_self_pay = float(treatment.get("major_self_pay", 0) or 0)
            if pooling_self_pay or deductible or major_self_pay:
                claim = (
                    f"待遇分段计算：统筹自付 {pooling_self_pay:,.2f} 元，"
                    f"起付线 {deductible:,.2f} 元，大额自付 {major_self_pay:,.2f} 元"
                )
            else:
                claim = "完成待遇分段计算（起付线/统筹/大额分段自付）"
        except (TypeError, ValueError):
            claim = "完成待遇分段计算（起付线/统筹/大额分段自付）"

        step = self._reasoning.add_step(
            session_id,
            claim=claim,
            kind="inference",
            confidence=0.9,
            source_memory_ids=source_ids,
        )
        return [("reasoning_step", step.model_dump())]

    def _on_answer(self, session_id: str) -> list[tuple[str, dict[str, Any]]]:
        """答案生成完成：记录结论性 inference 推理步。"""
        settlement_memories = self._memory.get_by_session_and_type(session_id, MemoryType.SETTLEMENT)
        policy_memories = self._memory.get_by_session_and_type(session_id, MemoryType.POLICY)
        source_ids = [m.memory_id for m in (settlement_memories[:1] + policy_memories[:1])]
        step = self._reasoning.add_step(
            session_id,
            claim="已生成结算政策解释",
            kind="inference",
            confidence=0.8,
            source_memory_ids=source_ids,
        )
        return [("reasoning_step", step.model_dump())]

    # ── 轮次收尾：推理链快照 + 对话记忆更新 ──────────────────────

    def finalize_turn(
        self,
        *,
        session_id: str,
        question: str,
        skill_id: str = "",
        settlement_id: str = "",
    ) -> dict[str, Any]:
        """返回 result 事件的 Runtime 附加字段，并更新 CONVERSATION 记忆。

        失败时返回空 dict（降级）。
        """
        try:
            chain = self._reasoning.get_chain(session_id)
            snapshot = {
                "last_intent": _POLICY_QA_INTENT,
                "last_question": question[:_MAX_SNAPSHOT_VALUE_LEN],
                "turn_count": len(chain),
            }
            if skill_id:
                snapshot["last_skill_id"] = skill_id
            if settlement_id:
                snapshot["last_settlement_id"] = settlement_id
            self._upsert_memory(
                session_id=session_id,
                type=MemoryType.CONVERSATION,
                ref_id=None,
                snapshot=snapshot,
                importance=_CONVERSATION_IMPORTANCE,
                expire_policy=ExpirePolicy.STICKY,
            )
            return {
                "reasoning_chain": self._reasoning.get_chain_summary(session_id),
                "reasoning_steps": [s.model_dump() for s in chain],
                "memory_count": len(self._memory.get_by_session(session_id)),
            }
        except Exception as e:
            logger.warning(f"[RUNTIME-BRIDGE] finalize_turn 降级: {e}")
            return {}

    # ── 内部辅助 ─────────────────────────────────────────────────

    def _build_context(
        self, session_id: str, question: str, user_id: str, role: str
    ) -> RuntimeContext:
        """构建 RuntimeContext，对话轮次从 CONVERSATION 记忆恢复（用于话题切换检测）。"""
        turns: list[Turn] = []
        conv_memories = self._memory.get_by_session_and_type(session_id, MemoryType.CONVERSATION)
        if conv_memories:
            last_intent = conv_memories[0].object_snapshot.get("last_intent")
            last_question = conv_memories[0].object_snapshot.get("last_question", "")
            if last_intent:
                turns.append(Turn(role="human", message=str(last_question), intent=str(last_intent)))

        return RuntimeContext(
            request_id=f"req-{uuid.uuid4().hex[:8]}",
            workflow_id="",
            user_id=user_id or "demo",
            role=role or "cashier",
            message=question,
            intent=_POLICY_QA_INTENT,
            intent_confidence=1.0,
            requested_at=_now_iso(),
            session_id=session_id,
            conversation_turns=turns,
        )

    def _upsert_memory(
        self,
        *,
        session_id: str,
        type: MemoryType,
        ref_id: str | None,
        snapshot: dict[str, Any],
        importance: float,
        expire_policy: ExpirePolicy,
    ) -> BusinessMemory:
        """构造并 upsert 一条业务记忆。"""
        now = _now_iso()
        memory = BusinessMemory(
            memory_id=_new_memory_id(),
            session_id=session_id,
            type=type,
            ref_id=ref_id,
            object_snapshot=snapshot,
            importance=importance,
            confidence=0.9,
            expire_policy=expire_policy,
            last_used_at=now,
            created_at=now,
        )
        return self._memory.upsert(memory)


# ── 模块级单例（懒加载，便于测试替换）────────────────────────────

_bridge: PolicyQARuntimeBridge | None = None


def get_runtime_bridge() -> PolicyQARuntimeBridge:
    """获取政策问答 Runtime 增强桥单例。"""
    global _bridge
    if _bridge is None:
        from src.data_platform.storage.memory.factory import create_memory_store

        memory_manager = MemoryManager(create_memory_store())
        reasoning_manager = ReasoningStateManager()
        planner = ContextPlanner(memory_manager=memory_manager)
        _bridge = PolicyQARuntimeBridge(memory_manager, reasoning_manager, planner)
    return _bridge
