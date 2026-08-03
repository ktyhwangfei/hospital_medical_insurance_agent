"""候选政策知识版本的 Milvus collection 对构建边界。"""
from __future__ import annotations

from typing import Any, Literal, Protocol

from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease
from src.knowledge_extension.rule_explanation.quality_store import PolicyQualityStore

CollectionKind = Literal["facts", "rules"]


class ReleaseIndexBackend(Protocol):
    def create(self, kind: CollectionKind, collection_name: str) -> None: ...
    def insert(
        self, kind: CollectionKind, collection_name: str, records: list[dict[str, Any]]
    ) -> None: ...
    def load(self, collection_name: str) -> None: ...
    def is_healthy(self, collection_name: str) -> bool: ...


class ReleaseIndexBuilder:
    """必须把 facts/rules 作为不可拆分的一对完成构建和健康检查。"""

    def __init__(self, store: PolicyQualityStore, backend: ReleaseIndexBackend) -> None:
        self._store = store
        self._backend = backend

    def build(
        self,
        release_id: str,
        *,
        facts: list[dict[str, Any]],
        rules: list[dict[str, Any]],
    ) -> KnowledgeRelease:
        release = self._store.get_release(release_id)
        if release is None:
            raise ValueError(f"候选版本不存在: {release_id}")
        if release.status != "building":
            raise ValueError(f"仅 building 版本可以构建索引: {release.status}")

        self._backend.create("facts", release.facts_collection)
        self._backend.create("rules", release.rules_collection)
        self._backend.insert("facts", release.facts_collection, facts)
        self._backend.insert("rules", release.rules_collection, rules)
        self._backend.load(release.facts_collection)
        self._backend.load(release.rules_collection)
        healthy = all((
            self._backend.is_healthy(release.facts_collection),
            self._backend.is_healthy(release.rules_collection),
        ))
        if not healthy:
            raise RuntimeError("候选版本 collection 对健康检查失败")
        return self._store.save_release(release.model_copy(update={"status": "ready"}))


class MilvusReleaseIndexBackend:
    """复用现有可参数化 schema helper 的生产 Milvus adapter。"""

    def __init__(self, alias: str = "default") -> None:
        self._alias = alias
        self._collections: dict[str, Any] = {}

    def create(self, kind: CollectionKind, collection_name: str) -> None:
        if kind == "facts":
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
                create_policy_facts_collection,
            )

            collection = create_policy_facts_collection(
                alias=self._alias, collection_name=collection_name
            )
        else:
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
                create_policy_rules_v2_collection,
            )

            collection = create_policy_rules_v2_collection(
                alias=self._alias, collection_name=collection_name
            )
        self._collections[collection_name] = collection

    def insert(
        self,
        kind: CollectionKind,
        collection_name: str,
        records: list[dict[str, Any]],
    ) -> None:
        collection = self._collections[collection_name]
        if kind == "facts":
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
                upsert_facts,
            )

            upsert_facts(collection, records)
        else:
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
                upsert_rules,
            )

            upsert_rules(collection, records)

    def load(self, collection_name: str) -> None:
        self._collections[collection_name].load()

    def is_healthy(self, collection_name: str) -> bool:
        from pymilvus import utility

        return bool(utility.has_collection(collection_name, using=self._alias))
