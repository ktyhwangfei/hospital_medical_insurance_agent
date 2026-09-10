"""候选政策知识版本的 Milvus collection 对构建边界。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from src.knowledge_extension.rule_explanation.change_set_models import KnowledgeChangeSet
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileStep,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    CompilationTraceStore,
)
from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease
from src.knowledge_extension.rule_explanation.quality_store import PolicyQualityStore

CollectionKind = Literal["facts", "rules"]
PublicationRecord = tuple[str, str, str, CanonicalRule]


class ReleaseIndexBackend(Protocol):
    def read_all(
        self, kind: CollectionKind, collection_name: str
    ) -> list[dict[str, Any]]: ...
    def create(self, kind: CollectionKind, collection_name: str) -> None: ...
    def insert(
        self, kind: CollectionKind, collection_name: str, records: list[dict[str, Any]]
    ) -> None: ...
    def load(self, collection_name: str) -> None: ...
    def is_healthy(self, collection_name: str) -> bool: ...


class WorkbenchReadPort(Protocol):
    def list_documents(self) -> Any: ...
    def get_document(self, doc_id: str) -> Any: ...


class EmbeddingPort(Protocol):
    @property
    def dim(self) -> int: ...
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class KnowledgeWorkbenchReleaseSource:
    """把当前审核通过的 Unit×Knowledge 快照转换为候选索引记录。"""

    def __init__(self, workbench: WorkbenchReadPort, provider: EmbeddingPort) -> None:
        self._workbench = workbench
        self._provider = provider

    def records(
        self, change_set: KnowledgeChangeSet
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[PublicationRecord],
    ]:
        from src.knowledge_extension.rule_explanation.policy_retrieval.policy_ingestion import (
            build_ingest_records,
        )

        facts: list[dict[str, Any]] = []
        rules: list[dict[str, Any]] = []
        publications: list[PublicationRecord] = []
        extracted_at = datetime.now(timezone.utc).isoformat()
        for item in change_set.items:
            canonical = item.canonical_rule
            if canonical is None or item.compile_run_id is None:
                raise ValueError(f"变更项 {item.item_id} 缺少规范规则或编译运行")
            if item.compilation_status not in {"PASS", "WARN"}:
                raise ValueError(
                    f"变更项 {item.item_id} 编译状态为 {item.compilation_status}，不可发布"
                )
            # 2026-09：fact_text 必须用包含区分字段的完整业务句生成，
            # 不能沿用旧的 business_sentence（可能丢失医院等级、金额区间等维度）。
            from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
                _sentence,
            )

            source_text = str((item.after or {}).get("source_text") or "")
            rule = self._runtime_rule(canonical, source_text)
            fact_text = _sentence(rule)
            fact_records, rule_records = build_ingest_records(
                [{
                    "fact_text": fact_text,
                    "rules": [rule],
                    "unit_id": item.unit_id,
                    "unit_source_text": source_text,
                }],
                doc_id=item.doc_id,
                provider=self._provider,
                extracted_at=extracted_at,
            )
            facts.extend(fact_records)
            rules.extend(rule_records)
            publications.append((
                item.compile_run_id,
                str((item.after or {}).get("extraction_id") or "")
                or self._extraction_id(canonical),
                item.doc_id,
                canonical,
            ))
        if not facts or not rules:
            raise ValueError("没有可构建候选版本的审核通过知识")
        return facts, rules, publications

    @staticmethod
    def _runtime_rule(rule: CanonicalRule, source_text: str) -> dict[str, Any]:
        payload = dict(rule.conditions)
        if "hospital_level" in payload:
            payload["hosp_lv"] = payload.pop("hospital_level")
        payload.update({
            "rule_id": rule.rule_id,
            "rule_type": (
                {"deductible": "起付线", "cap": "封顶线"}.get(rule.subject)
                or (
                    "支付比例"
                    if rule.subject == "payment_ratio"
                    or rule.subject.endswith(("_payment_ratio", "_reimbursement_ratio"))
                    else rule.subject
                )
            ),
            "psn_type": rule.population or "",
            "source_text": source_text,
        })
        for name, value in rule.result.items():
            if name == "ratio":
                if rule.subject == "personal_payment_ratio":
                    field = "personal_payment_ratio"
                elif rule.subject == "payment_ratio" or rule.subject.endswith(
                    ("_payment_ratio", "_reimbursement_ratio")
                ):
                    field = "payment_ratio"
                else:
                    field = rule.subject
                payload[field] = value
            elif name == "amount":
                field = rule.subject if rule.subject.endswith("_amount") else f"{rule.subject}_amount"
                payload[field] = value
            else:
                payload[name] = value
        return payload

    @staticmethod
    def _extraction_id(rule: CanonicalRule) -> str:
        for evidence in rule.evidence:
            if evidence.startswith("extraction:"):
                return evidence.removeprefix("extraction:")
        raise ValueError(f"规范规则 {rule.rule_id} 缺少 extraction_id")


class ReleaseIndexBuilder:
    """必须把 facts/rules 作为不可拆分的一对完成构建和健康检查。"""

    def __init__(
        self,
        store: PolicyQualityStore,
        backend: ReleaseIndexBackend,
        trace_store: CompilationTraceStore | None = None,
    ) -> None:
        self._store = store
        self._backend = backend
        self._traces = trace_store

    def build(
        self,
        release_id: str,
        *,
        facts: list[dict[str, Any]],
        rules: list[dict[str, Any]],
        publications: list[PublicationRecord] | None = None,
    ) -> KnowledgeRelease:
        release = self._store.get_release(release_id)
        if release is None:
            raise ValueError(f"候选版本不存在: {release_id}")
        if release.status != "building":
            raise ValueError(f"仅 building 版本可以构建索引: {release.status}")

        active = self._store.get_active_release()
        if (
            active is not None
            and active.release_id != release_id
            and hasattr(self._backend, "read_all")
        ):
            facts = _merge_records(
                "fact_id",
                self._backend.read_all("facts", "policy_facts"),
                self._backend.read_all("facts", active.facts_collection),
                facts,
            )
            rules = _merge_records(
                "rule_id",
                self._backend.read_all("rules", "policy_rules_v2"),
                self._backend.read_all("rules", active.rules_collection),
                rules,
            )

        # 发布门禁：同一维度键（险种×人群×医疗类别×医院等级×金额区间×规则类型）
        # 不允许冲突比例——LLM 产候选，代码做验收，冲突必须回上游修复而不是带病发布。
        from src.knowledge_extension.rule_explanation.extraction_validators import (
            check_key_uniqueness,
        )

        key_conflicts = [
            issue for issue in check_key_uniqueness(rules) if issue.level == "ERROR"
        ]
        if key_conflicts:
            raise ValueError(
                "候选版本存在维度键冲突，禁止构建: "
                + "; ".join(issue.message for issue in key_conflicts[:5])
            )

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
        publications = publications or []
        if publications and self._traces is None:
            raise RuntimeError("候选版本缺少编译轨迹存储")
        # 同一编译运行只记录一个确定性的发布步骤，逐规则血缘可安全续写。
        publications_by_run: dict[str, list[PublicationRecord]] = {}
        for publication in publications:
            publications_by_run.setdefault(publication[0], []).append(publication)
        for run_id in sorted(publications_by_run):
            run_publications = publications_by_run[run_id]
            rule_ids = sorted({record[3].rule_id for record in run_publications})
            self._traces.append_step(run_id, CompileStep(
                step_id=f"{run_id}_publish_{release_id}",
                run_id=run_id,
                sequence_no=8,
                stage="PUBLISH",
                status="PASS",
                input_payload={"release_id": release_id, "rule_ids": rule_ids},
                output_payload={
                    "facts_collection": release.facts_collection,
                    "rules_collection": release.rules_collection,
                },
                started_at=release.created_at,
                finished_at=release.created_at,
            ))
            for _, extraction_id, document_id, rule in sorted(
                run_publications, key=lambda record: record[3].rule_id
            ):
                self._traces.save_lineage(
                    rule=rule,
                    run_id=run_id,
                    extraction_id=extraction_id,
                    document_id=document_id,
                    release_id=release_id,
                )
        return self._store.save_release(release.model_copy(update={
            "status": "ready",
            "build_error": None,
        }))


class MilvusReleaseIndexBackend:
    """复用现有可参数化 schema helper 的生产 Milvus adapter。"""

    def __init__(self, alias: str = "default") -> None:
        self._alias = alias
        self._collections: dict[str, Any] = {}

    def read_all(
        self, kind: CollectionKind, collection_name: str
    ) -> list[dict[str, Any]]:
        from pymilvus import Collection, connections, utility

        if not connections.has_connection(self._alias):
            from src.config.production import MILVUS_HOST, MILVUS_PORT

            connections.connect(
                alias=self._alias, host=MILVUS_HOST, port=str(MILVUS_PORT)
            )
        if not utility.has_collection(collection_name, using=self._alias):
            return []
        collection = Collection(collection_name, using=self._alias)
        collection.load()
        iterator = collection.query_iterator(expr="", output_fields=["*"])
        records: list[dict[str, Any]] = []
        try:
            while batch := iterator.next():
                records.extend(dict(item) for item in batch)
        finally:
            iterator.close()
        return records

    def create(self, kind: CollectionKind, collection_name: str) -> None:
        if kind == "facts":
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
                create_policy_facts_collection,
            )

            collection = create_policy_facts_collection(
                alias=self._alias, collection_name=collection_name, drop_existing=True
            )
        else:
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
                create_policy_rules_v2_collection,
            )

            collection = create_policy_rules_v2_collection(
                alias=self._alias, collection_name=collection_name, drop_existing=True
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


def _merge_records(
    identity: str, *groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for record in group:
            key = str(record.get(identity) or "")
            if key:
                merged[key] = record
    return list(merged.values())
