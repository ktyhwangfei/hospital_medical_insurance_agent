"""
Issue #25 存量适用性字段回填服务（提议者-审核者模型）。

对现有 policy_rules_v2 规则中缺失的适用性字段：
- region
- effective_date
- expiry_date
- publish_status
- policy_version
- is_remote

系统自动提议默认值，经人工确认后再写回存储。不确认则不修改 Runtime 数据。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)

from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    _DEFAULT_EFFECTIVE_DATE,
    _DEFAULT_EXPIRY_DATE,
    _DEFAULT_POLICY_VERSION,
    _DEFAULT_PUBLISH_STATUS,
    _DEFAULT_REGION,
    POLICY_RULES_V2_COLLECTION,
    _normalize_date,
)

# Issue #25 适用性字段
_APPLICABILITY_FIELDS = (
    "region",
    "effective_date",
    "expiry_date",
    "publish_status",
    "policy_version",
    "is_remote",
)


def _is_empty(value: Any) -> bool:
    """判断字段值是否为空（需回填）。"""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        return value.strip() == ""
    return False


@dataclass(frozen=True)
class BackfillProposal:
    """单条规则单个字段的回填提议。"""

    rule_id: str
    field_name: str
    old_value: Any
    proposed_value: Any
    confidence: str = "system_default"  # 来源：system_default / doc_metadata / inference
    reason: str = ""


@dataclass(frozen=True)
class BackfillApplication:
    """人工确认后的回填应用记录。"""

    rule_id: str
    field_name: str
    applied_value: Any
    reviewed_by: str
    reviewed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RuleStorePort(Protocol):
    """规则存储端口：查询与更新。"""

    def list_rules(self, limit: int = 10000) -> list[dict[str, Any]]: ...
    def update_rules(self, entities: list[dict[str, Any]]) -> int: ...


class DocumentStorePort(Protocol):
    """文档元数据存储端口：按 doc_id 读取政策文档元数据。"""

    def get_metadata(self, doc_id: str) -> dict[str, Any]: ...


class InMemoryDocumentStore:
    """测试用内存文档元数据存储。"""

    def __init__(self, metadata: dict[str, dict[str, Any]] | None = None) -> None:
        self._metadata = metadata or {}

    def get_metadata(self, doc_id: str) -> dict[str, Any]:
        return dict(self._metadata.get(doc_id, {}))


class PipelineDocumentStore:
    """生产环境：从 pipeline_store 读取政策文档元数据。"""

    def __init__(self, store: Any | None = None) -> None:
        self._store = store

    def get_metadata(self, doc_id: str) -> dict[str, Any]:
        if self._store is None:
            from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

            self._store = PipelineStore()
        doc = self._store.get_document(doc_id)
        if not doc:
            return {}
        return {
            "policy_region": doc.get("policy_region", ""),
            "effective_date": doc.get("effective_date", ""),
            "publish_date": doc.get("publish_date", ""),
            "document_date": doc.get("document_date", ""),
            "abolition_date": doc.get("abolition_date", ""),
            "validity": doc.get("validity", ""),
        }


class InMemoryRuleStore:
    """测试与本地评估使用的内存规则存储。"""

    def __init__(self, entities: list[dict[str, Any]] | None = None) -> None:
        self._entities: dict[str, dict[str, Any]] = {}
        for e in (entities or []):
            rid = e.get("rule_id")
            if rid:
                self._entities[rid] = dict(e)

    def list_rules(self, limit: int = 10000) -> list[dict[str, Any]]:
        return [dict(e) for e in list(self._entities.values())[:limit]]

    def update_rules(self, entities: list[dict[str, Any]]) -> int:
        count = 0
        for e in entities:
            rid = e.get("rule_id")
            if rid:
                self._entities[rid] = dict(e)
                count += 1
        return count


class MilvusRuleStore:
    """生产 Milvus 规则存储适配器（操作 policy_rules_v2 或候选 release collection）。"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: str = "19530",
        collection_name: str = POLICY_RULES_V2_COLLECTION,
    ) -> None:
        from pymilvus import MilvusClient

        self.client = MilvusClient(uri=f"http://{host}:{port}")
        self.collection_name = collection_name

    def list_rules(self, limit: int = 10000) -> list[dict[str, Any]]:
        from src.runtime.policy_qa.policy_rules_search import OUTPUT_FIELDS

        # update_rules 是 delete+insert，这里必须取回完整行（含 vector 等固定列），
        # 否则写回会丢失向量导致检索不可用；detail 字段保留 FieldTrace 原样回写，溯源不丢。
        output_fields = OUTPUT_FIELDS + [
            "vector", "schema_version", "amount_band_min", "amount_band_max",
        ]
        rows = self.client.query(
            collection_name=self.collection_name,
            filter='rule_id != ""',
            output_fields=output_fields,
            limit=limit,
        )
        return rows

    def update_rules(self, entities: list[dict[str, Any]]) -> int:
        if not entities:
            return 0
        # Milvus 先删后插实现 upsert（保留 vector 等未变更字段）
        pks = [str(e.get("rule_id")) for e in entities if e.get("rule_id")]
        if pks:
            self.client.delete(
                collection_name=self.collection_name,
                ids=pks,
            )
        self.client.insert(
            collection_name=self.collection_name,
            data=entities,
        )
        return len(entities)


class ApplicabilityBackfillService:
    """适用性字段回填服务：扫描 → 提议 → 人工确认 → 应用。"""

    def __init__(
        self,
        store: RuleStorePort,
        document_store: DocumentStorePort | None = None,
    ) -> None:
        self._store = store
        self._document_store = document_store

    def _fetch_doc_metadata(self, doc_id: str) -> dict[str, Any]:
        if self._document_store is None or not doc_id:
            return {}
        try:
            return self._document_store.get_metadata(doc_id)
        except Exception as exc:
            logger.warning("[ApplicabilityBackfill] 读取文档 %s 元数据失败: %s", doc_id, exc)
            return {}

    def _propose_field_value(
        self,
        field_name: str,
        meta: dict[str, Any],
    ) -> tuple[Any, str, str]:
        """返回 (提议值, confidence, reason)。"""
        region = str(meta.get("policy_region") or "").strip()
        effective = (
            _normalize_date(meta.get("effective_date"))
            or _normalize_date(meta.get("publish_date"))
            or _normalize_date(meta.get("document_date"))
        )
        abolition = _normalize_date(meta.get("abolition_date"))
        validity = str(meta.get("validity") or "").strip().lower()

        if field_name == "region":
            if region:
                return region, "doc_metadata", f"来自文档 policy_region={region}"
            return _DEFAULT_REGION, "system_default", f"字段缺失，使用系统默认值 {_DEFAULT_REGION!r}"

        if field_name == "effective_date":
            if effective:
                return effective, "doc_metadata", "来自文档 effective_date/publish_date/document_date"
            return _DEFAULT_EFFECTIVE_DATE, "system_default", f"字段缺失，使用系统默认值 {_DEFAULT_EFFECTIVE_DATE!r}"

        if field_name == "expiry_date":
            if abolition:
                return abolition, "doc_metadata", f"来自文档 abolition_date={abolition}"
            return _DEFAULT_EXPIRY_DATE, "system_default", f"字段缺失，使用系统默认值 {_DEFAULT_EXPIRY_DATE!r}"

        if field_name == "publish_status":
            if validity == "invalid":
                return "revoked", "doc_metadata", "文档 validity=invalid，标记为 revoked"
            if validity == "valid":
                return "published", "doc_metadata", "文档 validity=valid，标记为 published"
            return _DEFAULT_PUBLISH_STATUS, "system_default", f"字段缺失，使用系统默认值 {_DEFAULT_PUBLISH_STATUS!r}"

        if field_name == "policy_version":
            return _DEFAULT_POLICY_VERSION, "system_default", f"字段缺失，使用系统默认值 {_DEFAULT_POLICY_VERSION!r}"

        if field_name == "is_remote":
            return False, "system_default", "字段缺失，使用系统默认值 False"

        return None, "system_default", "字段缺失"

    def propose(self) -> list[BackfillProposal]:
        """扫描存储，为缺失适用性字段的规则生成回填提议。"""
        rules = self._store.list_rules()
        proposals: list[BackfillProposal] = []
        doc_metadata_cache: dict[str, dict[str, Any]] = {}

        for rule in rules:
            rid = rule.get("rule_id")
            if not rid:
                continue

            doc_id = rule.get("doc_id")
            if doc_id and doc_id not in doc_metadata_cache:
                doc_metadata_cache[doc_id] = self._fetch_doc_metadata(doc_id)
            meta = doc_metadata_cache.get(doc_id, {})

            for field_name in _APPLICABILITY_FIELDS:
                if _is_empty(rule.get(field_name)):
                    proposed, confidence, reason = self._propose_field_value(field_name, meta)
                    proposals.append(BackfillProposal(
                        rule_id=rid,
                        field_name=field_name,
                        old_value=rule.get(field_name),
                        proposed_value=proposed,
                        confidence=confidence,
                        reason=reason,
                    ))
        return proposals

    def apply(
        self,
        proposals: list[BackfillProposal],
        reviewed_by: str,
    ) -> tuple[list[BackfillApplication], int]:
        """应用经人工确认的回填提议。返回应用记录与更新条数。

        幂等：同一规则同一字段多次应用以最后一次为准。
        """
        if not reviewed_by.strip():
            raise ValueError("reviewed_by 不能为空，回填必须经人工确认")
        if not proposals:
            return [], 0

        # 按 rule_id 聚合需要更新的字段
        rules = {r["rule_id"]: r for r in self._store.list_rules()}
        updates: dict[str, dict[str, Any]] = {}
        applications: list[BackfillApplication] = []

        for p in proposals:
            entity = rules.get(p.rule_id)
            if entity is None:
                continue
            updates.setdefault(p.rule_id, entity)
            updates[p.rule_id][p.field_name] = p.proposed_value
            applications.append(BackfillApplication(
                rule_id=p.rule_id,
                field_name=p.field_name,
                applied_value=p.proposed_value,
                reviewed_by=reviewed_by,
            ))

        updated_count = self._store.update_rules(list(updates.values()))
        return applications, updated_count

    def validate_gate(self) -> tuple[bool, list[BackfillProposal]]:
        """质量门禁：检查当前存储中是否仍存在缺失适用性字段的 published 规则。

        返回 (通过, 缺失列表)。未通过时应阻断发布并生成 DecisionTask。
        """
        proposals = self.propose()
        # pilot 规则可缺失 region；revoked/draft 规则不进入 Runtime，暂不强制
        blocking = [
            p for p in proposals
            if p.field_name in {"region", "effective_date", "expiry_date", "publish_status"}
        ]
        return (not blocking), blocking
