"""规则知识源 Milvus 适配器（MVU-3 生产接线）。

把 ``RuleKnowledgePort`` 对接到当前 release 的 ``policy_rules_v2`` collection，
为答案验证提供确定性的规则原文/结构化值比对来源。

fail-closed 约定：
- Milvus 不可达或 collection 不存在 → 工厂返回 None，验证器按
  ``blocked_by_evaluator`` 处理，绝不伪造通过；
- ``find_similar_rules`` 未接入向量（运行时不加载 embedding 模型），返回空列表，
  引用真实性四级关联在向量级一律 fail-closed 为 ``CITATION_EXCERPT_NOT_FOUND``。
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    RuleKnowledgePort,
    RuleRecord,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    source_text_hash,
)

logger = logging.getLogger(__name__)

# policy_rules_v2 collection（与 runtime/policy_qa/policy_rules_search.COLLECTION_NAME 一致；
# 此处独立声明避免 knowledge 层反向依赖 runtime 层）
DEFAULT_RULES_COLLECTION = "policy_rules_v2"

# 输出字段：核心维度固定列 + detail dynamic 字段（值是 FieldTrace dict，需解包）
_CORE_FIELDS = (
    "rule_id", "fact_id", "doc_id",
    "rule_type", "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
)
_DETAIL_FIELDS = (
    "payment_ratio", "deductible_amount", "cap_amount", "amount_band",
    "time_period", "admission_order", "priority", "rule_value", "source_text",
)
_OUTPUT_FIELDS = list(_CORE_FIELDS) + list(_DETAIL_FIELDS)

# LIKE 检索针长度：取归一化文本前缀作为 Milvus LIKE 候选召回，精确包含判定由验证器完成
_NEEDLE_LENGTH = 24


def _unpack_detail(entity: dict[str, Any]) -> dict[str, Any]:
    """detail 字段落 dynamic field，值是 FieldTrace dict，解包为裸 value。

    与 runtime/policy_qa/policy_rules_search.unpack_detail 同语义（此处独立实现，
    保持 knowledge 层不反向依赖 runtime 层）。
    """
    for field in _DETAIL_FIELDS:
        value = entity.get(field)
        if isinstance(value, dict) and "value" in value:
            entity[field] = value.get("value")
    return entity


def _like_needle(text: str) -> str:
    """从原始文本截取 LIKE 检索针。

    检索针用于匹配 Milvus 中**未归一化**的 source_text，因此只做空白折叠、
    不做 NFKC（NFKC 会把「。」兼容映射为「.」，导致检索针永远召不回原文）。
    LIKE 通配符（%/_）本身可能是政策原文内容（如「15%」），转义方言不可靠，
    因此按通配符切段并取最长连续段作为检索针；精确包含判定由验证器双侧
    归一化后完成，召回率损失可忽略。
    """
    collapsed = " ".join(str(text or "").split()).rstrip(".…").replace('"', "")
    if not collapsed:
        return ""
    needle = collapsed[:_NEEDLE_LENGTH]
    segments = re.split(r"[%_]+", needle)
    return max(segments, key=len, default="")


def _to_rule_record(entity: dict[str, Any]) -> RuleRecord:
    """Milvus 实体 → RuleRecord（source_text_hash 现场计算，与证据侧 hash 语义一致）。"""
    _unpack_detail(entity)
    source_text = str(entity.get("source_text") or "")
    return RuleRecord(
        rule_id=str(entity.get("rule_id") or ""),
        policy_id=str(entity.get("doc_id") or ""),
        source_text=source_text,
        source_text_hash=source_text_hash(source_text) if source_text else "",
        rule_value=str(entity.get("rule_value") or ""),
        payment_ratio=str(entity.get("payment_ratio") or ""),
        amount_band=str(entity.get("amount_band") or ""),
        psn_type=str(entity.get("psn_type") or ""),
    )


class MilvusRuleKnowledgePort:
    """policy_rules_v2 的规则知识源适配器（Milvus scalar query，不依赖向量）。"""

    def __init__(
        self,
        client: Any | None = None,
        *,
        host: str = "127.0.0.1",
        port: str = "19530",
        collection_name: str = DEFAULT_RULES_COLLECTION,
    ) -> None:
        if client is None:
            from pymilvus import MilvusClient

            client = MilvusClient(uri=f"http://{host}:{port}")
        self._client = client
        self._collection_name = collection_name

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def has_collection(self) -> bool:
        """探测 collection 是否存在（工厂 fail-closed 判定用）。"""
        return self._collection_name in (self._client.list_collections() or [])

    def get_rule_by_id(self, rule_id: str) -> RuleRecord | None:
        if not rule_id:
            return None
        records = self._query(f'rule_id == "{rule_id}"', limit=5)
        return records[0] if records else None

    def find_rules_by_text(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        needle = _like_needle(text)
        if not needle:
            return []
        return self._query(f'source_text like "%{needle}%"', limit=limit)

    def find_rules_by_title(self, title: str, *, limit: int = 5) -> list[RuleRecord]:
        # v2 collection 无独立 title 列；公开引用 title 是 source_text 截断，
        # 元数据约束级退化为原文 LIKE 候选召回（精确包含判定由验证器完成）。
        return self.find_rules_by_text(title, limit=limit)

    def find_similar_rules(self, text: str, *, limit: int = 5) -> list[RuleRecord]:
        # 向量候选发现未接入（运行时不加载 embedding 模型）；返回空 → 验证器 fail-closed
        return []

    def _query(self, expr: str, *, limit: int) -> list[RuleRecord]:
        raw = self._client.query(
            collection_name=self._collection_name,
            filter=expr,
            output_fields=_OUTPUT_FIELDS,
            limit=limit,
        )
        return [_to_rule_record(dict(record)) for record in raw or []]


_port_singleton: MilvusRuleKnowledgePort | None = None
_port_probed = False
_port_lock = threading.Lock()


def get_rule_knowledge_port() -> RuleKnowledgePort | None:
    """规则知识源工厂：Milvus 不可达 / collection 缺失时返回 None（fail-closed）。

    探测结果进程内缓存；测试用 ``reset_rule_knowledge_port_cache`` 重置。
    """
    global _port_singleton, _port_probed
    with _port_lock:
        if _port_probed:
            return _port_singleton
        try:
            from src.config.production import MILVUS_HOST, MILVUS_PORT
            from src.knowledge_extension.rule_explanation.release_resolver import (
                resolve_rules_collection,
            )

            # Issue #33 P0-1：经统一 resolver 跟随 active release，验证来源与 Runtime 读路径一致
            candidate = MilvusRuleKnowledgePort(
                host=MILVUS_HOST,
                port=str(MILVUS_PORT),
                collection_name=resolve_rules_collection(MILVUS_HOST, str(MILVUS_PORT)),
            )
            _port_singleton = candidate if candidate.has_collection() else None
            if _port_singleton is None:
                logger.warning(
                    "[ANSWER-VERIFY] rules collection unavailable, "
                    "answer verification will be blocked_by_evaluator"
                )
        except Exception as exc:
            logger.warning(f"[ANSWER-VERIFY] rule knowledge source unreachable: {exc}")
            _port_singleton = None
        _port_probed = True
        return _port_singleton


def get_rule_knowledge_port_for_collection(
    collection_name: str,
) -> RuleKnowledgePort | None:
    """按候选 release 的规则 collection 构造知识源，Milvus 不可达时返回 None。"""
    try:
        from src.config.production import MILVUS_HOST, MILVUS_PORT

        candidate = MilvusRuleKnowledgePort(
            host=MILVUS_HOST,
            port=str(MILVUS_PORT),
            collection_name=collection_name,
        )
        if candidate.has_collection():
            return candidate
        logger.warning(
            "[ANSWER-VERIFY] release rules collection unavailable: %s",
            collection_name,
        )
        return None
    except Exception as exc:
        logger.warning(
            "[ANSWER-VERIFY] release rule knowledge source unreachable: %s", exc
        )
        return None


def reset_rule_knowledge_port_cache() -> None:
    """清空工厂缓存（仅测试使用）。"""
    global _port_singleton, _port_probed
    with _port_lock:
        _port_singleton = None
        _port_probed = False
