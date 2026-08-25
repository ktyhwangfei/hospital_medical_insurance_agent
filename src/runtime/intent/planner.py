"""Context Planner — 上下文规划器

意图识别的增强阶段，负责：
1. 从意图识别结果提取所需业务对象类型
2. 检查 Memory 中是否已有
3. 缺失的标记 must_query_semantic=True
4. 检测业务主体切换（patient_id 变更）

当前仅服务 policy-qa 的结算单上下文规划。
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.runtime.context.models import RuntimeContext
from src.runtime.intent.models import IntentResult
from src.runtime.memory.manager import MemoryManager
from src.runtime.memory.models import BusinessMemory, MemoryType

logger = logging.getLogger(__name__)


class ContextNeed(BaseModel):
    """上下文需求 — 决定需要加载哪些业务对象"""
    object_types: list[str] = Field(default_factory=list)   # 需要哪些 BusinessObject 类型
    memory_ids: list[str] = Field(default_factory=list)     # 优先命中记忆
    must_query_semantic: bool = False                       # 记忆缺失则下探语义层
    reasoning_refs: list[str] = Field(default_factory=list) # 关联推理状态
    topic_changed: bool = False                             # 是否检测到话题切换
    subject_changed: bool = False                           # 是否检测到业务主体切换


class ContextPlanner:
    """上下文规划器

    输入：IntentResult + RuntimeContext（含 session/memory）
    输出：ContextNeed（需要加载哪些业务对象）
    """

    # 意图 → 所需业务对象类型的映射
    INTENT_OBJECT_MAP: dict[str, list[MemoryType]] = {
        "policy_qa_fee_decomposition": [MemoryType.SETTLEMENT, MemoryType.POLICY, MemoryType.RULE],
        "skill_execution": [],  # Skill 自带上下文
    }

    # 费用相关关键词 → 自动添加 SETTLEMENT + POLICY
    FEE_KEYWORDS: set[str] = {
        "统筹自付", "自付", "统筹支付", "报销比例", "起付线", "封顶线",
        "费用分解", "费用明细", "费用构成", "为什么这么多", "怎么算的",
        "大额", "个人应负", "医保外", "医保内", "待遇分解", "自费",
        "报销多少", "能报多少", "报销了多少钱", "花了多少",
    }

    def __init__(self, memory_manager: MemoryManager | None = None):
        self._memory_manager = memory_manager

    def plan(
        self,
        intent_result: IntentResult,
        context: RuntimeContext,
    ) -> ContextNeed:
        """规划当前请求所需的上下文。

        Args:
            intent_result: 意图识别结果
            context: 运行时上下文（含 session_id, patient_id 等）

        Returns:
            ContextNeed：上下文需求描述
        """
        need = ContextNeed()

        # 1. 检测业务主体切换
        if self._detect_subject_change(context):
            need.subject_changed = True
            logger.info(f"Subject change detected for session {context.session_id}")

        # 2. 检测话题切换
        if self._detect_topic_change(context):
            need.topic_changed = True
            logger.info(f"Topic change detected for session {context.session_id}")

        # 3. 根据意图确定所需业务对象类型
        required_types = self._resolve_required_types(intent_result, context)
        need.object_types = [t.value for t in required_types]

        # 4. 检查 Memory 中是否已有
        if context.session_id and self._memory_manager:
            memories = self._memory_manager.get_by_session(context.session_id)
            existing_types = {m.type for m in memories}
            missing_types = set(required_types) - existing_types

            if missing_types:
                need.must_query_semantic = True
                logger.info(
                    f"Missing memory types for session {context.session_id}: "
                    f"{[t.value for t in missing_types]}"
                )

            # 记录已有的记忆 ID
            need.memory_ids = [m.memory_id for m in memories if m.type in required_types]

        return need

    def _detect_subject_change(self, context: RuntimeContext) -> bool:
        """检测业务主体是否切换（patient_id 变更或查询新患者）。

        策略：
        1. 检查当前 patient_id 是否与 conversation_turns 中最近的不同
        2. 检查消息中是否包含"查询 XXX"、"XXX 的费用"等主体切换信号
        3. 检查消息中是否出现新的患者姓名（简单关键词匹配）
        """
        if not context.session_id:
            return False

        # 策略 1：patient_id 变更
        if context.conversation_turns:
            last_patient_id = None
            for turn in reversed(context.conversation_turns):
                # 从 intent_entities 中提取 patient_id
                if turn.intent and "patient_id" in (turn.cited_memory_ids or []):
                    # 简化：通过 memory 关联推断
                    pass
            # 如果当前有 patient_id 且与之前不同（需要 SessionManager 维护历史）
            # 当前简化：不依赖跨轮 patient_id 持久化

        # 策略 2：主体切换信号词
        message = context.message or ""
        subject_change_signals = {
            "查询", "查一下", "看看", "帮我看",
            "换一个人", "另一个", "别的患者", "其他病人",
        }
        if any(signal in message for signal in subject_change_signals):
            # 进一步检查：如果消息中包含与当前 patient_id 不同的标识
            # 简化：只要有切换信号且包含患者相关信息，即认为可能切换
            if "患者" in message or "病人" in message or "人" in message:
                return True

        # 策略 3：名字识别（简化版）
        # 如果消息以"查询"开头且包含 2-4 个中文字符（可能是姓名），视为切换
        if message.startswith("查询") or message.startswith("查一下"):
            # 提取可能的名字（2-4 个连续中文字符）
            import re
            possible_names = re.findall(r'[\u4e00-\u9fff]{2,4}', message)
            if len(possible_names) > 0:
                # 排除常见非人名词（业务词汇及其常见组合）
                non_name_words = {"费用", "结算", "医保", "报销", "住院", "门诊", "药品", "政策",
                                  "住院费用", "费用构成", "费用明细", "结算单", "查询住院",
                                  "报销比例", "统筹自付", "起付线", "个人负担", "门诊费用"}
                for name in possible_names:
                    if name in non_name_words:
                        continue
                    # 名字片段以业务词结尾也视为业务表达（如"查询住院""费用结算"），非人名
                    if any(name.endswith(w) for w in
                           ("费用", "结算", "医保", "报销", "住院", "门诊", "药品", "政策")):
                        continue
                    return True

        return False

    def _detect_topic_change(self, context: RuntimeContext) -> bool:
        """检测话题是否切换。

        通过比较当前意图与上一轮的意图。
        """
        if not context.conversation_turns:
            return False

        # 获取最近一轮的意图
        last_intent = None
        for turn in reversed(context.conversation_turns):
            if turn.intent:
                last_intent = turn.intent
                break

        if last_intent is None:
            return False

        # 意图变化视为话题切换（但同一业务对象上的连续追问不算）
        if last_intent != context.intent:
            # 例外：费用相关意图之间的切换不算话题切换
            fee_intents = {"policy_qa_fee_decomposition", "skill_execution"}
            if last_intent in fee_intents and context.intent in fee_intents:
                return False
            return True

        return False

    def _resolve_required_types(
        self, intent_result: IntentResult, context: RuntimeContext
    ) -> list[MemoryType]:
        """根据意图和消息内容解析所需的业务对象类型。"""
        intent = intent_result.intent

        # 从映射表获取基础类型
        types = list(self.INTENT_OBJECT_MAP.get(intent, []))

        # 费用相关问题自动添加 SETTLEMENT + POLICY
        message = context.message or intent_result.raw_message
        if any(kw in message for kw in self.FEE_KEYWORDS):
            if MemoryType.SETTLEMENT not in types:
                types.append(MemoryType.SETTLEMENT)
            if MemoryType.POLICY not in types:
                types.append(MemoryType.POLICY)

        # 实体中提取类型
        entities = intent_result.entities
        if "settlement_id" in entities or "encounter_id" in entities:
            if MemoryType.SETTLEMENT not in types:
                types.append(MemoryType.SETTLEMENT)
        if "patient_id" in entities or "患者" in message:
            if MemoryType.PATIENT not in types:
                types.append(MemoryType.PATIENT)
        if "drug" in entities or "药" in message:
            if MemoryType.DRUG not in types:
                types.append(MemoryType.DRUG)

        return types
