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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    _DEFAULT_EFFECTIVE_DATE,
    _DEFAULT_EXPIRY_DATE,
    _DEFAULT_POLICY_VERSION,
    _DEFAULT_PUBLISH_STATUS,
    _DEFAULT_REGION,
    POLICY_RULES_V2_COLLECTION,
)

# Issue #25 适用性字段 → 默认值工厂
_APPLICABILITY_FIELDS = {
    "region": lambda _rule: _DEFAULT_REGION,
    "effective_date": lambda _rule: _DEFAULT_EFFECTIVE_DATE,
    "expiry_date": lambda _rule: _DEFAULT_EXPIRY_DATE,
    "publish_status": lambda _rule: _DEFAULT_PUBLISH_STATUS,
    "policy_version": lambda _rule: _DEFAULT_POLICY_VERSION,
    "is_remote": lambda _rule: False,
}


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
    """生产 Milvus 规则存储适配器（操作 policy_rules_v2）。"""

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
        from src.runtime.policy_qa.policy_rules_search import OUTPUT_FIELDS, unpack_detail

        rows = self.client.query(
            collection_name=self.collection_name,
            filter='rule_id != ""',
            output_fields=OUTPUT_FIELDS,
            limit=limit,
        )
        for r in rows:
            unpack_detail(r)
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

    def __init__(self, store: RuleStorePort) -> None:
        self._store = store

    def propose(self) -> list[BackfillProposal]:
        """扫描存储，为缺失适用性字段的规则生成回填提议。"""
        rules = self._store.list_rules()
        proposals: list[BackfillProposal] = []
        for rule in rules:
            rid = rule.get("rule_id")
            if not rid:
                continue
            for field_name, default_factory in _APPLICABILITY_FIELDS.items():
                if _is_empty(rule.get(field_name)):
                    proposed = default_factory(rule)
                    proposals.append(BackfillProposal(
                        rule_id=rid,
                        field_name=field_name,
                        old_value=rule.get(field_name),
                        proposed_value=proposed,
                        confidence="system_default",
                        reason=f"字段缺失，使用系统默认值 {proposed!r}",
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
