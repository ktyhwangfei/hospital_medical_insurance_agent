from src.knowledge_extension.assets.models import (
    AssetQuery,
    AssetRepositorySnapshot,
    AssetWriteResult,
    IndexStatus,
    KnowledgeAsset,
    KnowledgeAssetStatus,
    KnowledgeAssetType,
    KnowledgeChunk,
)
from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus, VisibilityScope


class InMemoryKnowledgeAssetRepository:
    def __init__(self, assets: list[KnowledgeAsset], chunks: list[KnowledgeChunk]):
        self._assets = {asset.asset_id: asset.model_copy(deep=True) for asset in assets}
        self._chunks = {chunk.chunk_id: chunk.model_copy(deep=True) for chunk in chunks}
        self._audit_events: list[AuditSummary] = []

    @property
    def audit_events(self) -> list[AuditSummary]:
        return self.list_audit_events()

    def list_audit_events(self) -> list[AuditSummary]:
        return [event.model_copy(deep=True) for event in self._audit_events]

    def add_asset(self, asset: KnowledgeAsset) -> AssetWriteResult:
        existing = self._assets.get(asset.asset_id)
        if existing and existing.version == asset.version and existing.status is KnowledgeAssetStatus.PUBLISHED:
            self._audit_events.append(AuditSummary(event_type="knowledge_asset_duplicate_version", summary={"asset_id": asset.asset_id}))
            return AssetWriteResult(
                status=KnowledgeExtensionStatus.VERSION_MISMATCH,
                reason="duplicate_published_version",
                user_message="重复的已发布知识资产版本不能覆盖",
                asset_id=asset.asset_id,
            )
        if asset.status is KnowledgeAssetStatus.PUBLISHED and self._has_duplicate_published_business_key(asset):
            self._audit_events.append(AuditSummary(event_type="knowledge_asset_duplicate_business_key", summary={"asset_id": asset.asset_id, "version": asset.version}))
            return AssetWriteResult(
                status=KnowledgeExtensionStatus.VERSION_MISMATCH,
                reason="duplicate_published_business_key",
                user_message="重复的已发布知识资产业务版本不能写入",
                asset_id=asset.asset_id,
            )
        self._assets[asset.asset_id] = asset.model_copy(deep=True)
        self._audit_events.append(AuditSummary(event_type="knowledge_asset_added", summary={"asset_id": asset.asset_id}))
        return AssetWriteResult(status=KnowledgeExtensionStatus.SUCCESS, reason="created", user_message="知识资产已保存", asset_id=asset.asset_id)

    def add_chunk(self, chunk: KnowledgeChunk) -> AssetWriteResult:
        self._chunks[chunk.chunk_id] = chunk.model_copy(deep=True)
        self._audit_events.append(AuditSummary(event_type="knowledge_chunk_added", summary={"chunk_id": chunk.chunk_id}))
        return AssetWriteResult(status=KnowledgeExtensionStatus.SUCCESS, reason="created", user_message="知识切片已保存", asset_id=chunk.asset_id)

    def get_asset(self, asset_id: str) -> KnowledgeAsset | None:
        asset = self._assets.get(asset_id)
        if asset is None:
            return None
        return asset.model_copy(deep=True)

    def list_assets(self, query: AssetQuery) -> list[KnowledgeAsset]:
        result = []
        for asset in self._assets.values():
            if not query.include_inactive and asset.status is not KnowledgeAssetStatus.PUBLISHED:
                self._audit_events.append(AuditSummary(event_type="knowledge_asset_filtered", summary={"asset_id": asset.asset_id, "reason": asset.status.value}))
                continue
            if query.asset_types and asset.asset_type not in query.asset_types:
                continue
            if not asset.visibility.allows(query.role, query.tenant_id, query.campus_id):
                self._audit_events.append(AuditSummary(event_type="knowledge_asset_filtered", summary={"asset_id": asset.asset_id, "reason": "visibility"}))
                continue
            result.append(asset.model_copy(deep=True))
        return result

    def list_chunks(self, query: AssetQuery) -> list[KnowledgeChunk]:
        visible_assets = {asset.asset_id for asset in self.list_assets(query)}
        result = []
        for chunk in self._chunks.values():
            if chunk.asset_id not in visible_assets:
                continue
            if query.scenario and query.scenario not in chunk.scenario_tags:
                continue
            if query.asset_types and chunk.asset_type not in query.asset_types:
                continue
            if not chunk.visibility.allows(query.role, query.tenant_id, query.campus_id):
                self._audit_events.append(AuditSummary(event_type="knowledge_chunk_filtered", summary={"chunk_id": chunk.chunk_id, "reason": "visibility"}))
                continue
            result.append(chunk.model_copy(deep=True))
        return result

    def snapshot(self) -> AssetRepositorySnapshot:
        return AssetRepositorySnapshot(
            assets=[asset.model_copy(deep=True) for asset in self._assets.values()],
            chunks=[chunk.model_copy(deep=True) for chunk in self._chunks.values()],
            audit_events=[event.model_copy(deep=True) for event in self._audit_events],
        )

    def _has_duplicate_published_business_key(self, candidate: KnowledgeAsset) -> bool:
        return any(
            asset.asset_id != candidate.asset_id
            and asset.status is KnowledgeAssetStatus.PUBLISHED
            and asset.asset_type is candidate.asset_type
            and asset.source == candidate.source
            and asset.title == candidate.title
            and asset.version == candidate.version
            for asset in self._assets.values()
        )


def build_default_asset_repository() -> InMemoryKnowledgeAssetRepository:
    officer_scope = VisibilityScope(roles={"medical_insurance_officer", "admin"}, tenant_ids={"tenant-a"}, campus_ids={"north"})
    clinical_scope = VisibilityScope(roles={"medical_insurance_officer", "doctor", "admin"})
    assets = [
        KnowledgeAsset(asset_id="asset-policy-001", asset_type=KnowledgeAssetType.POLICY, title="医保结算政策说明", summary="结算异常处理政策", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, effective_date="2026-01-01", imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-error-code-001", asset_type=KnowledgeAssetType.ERROR_CODE, title="医保错误码知识", summary="错误码解释", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-audit-rule-001", asset_type=KnowledgeAssetType.AUDIT_RULE, title="出院前审核规则", summary="审核规则说明", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-appeal-template-001", asset_type=KnowledgeAssetType.APPEAL_TEMPLATE, title="拒付申诉模板", summary="申诉材料模板", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-internal-policy-001", asset_type=KnowledgeAssetType.INTERNAL_POLICY, title="院内医保运营制度", summary="内部制度", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, imported_at="2026-05-04T00:00:00Z", visibility=officer_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-expired-001", asset_type=KnowledgeAssetType.POLICY, title="过期政策", summary="过期政策", source="init", version="2025.1", status=KnowledgeAssetStatus.EXPIRED, imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.REBUILD_REQUIRED),
    ]
    chunks = [
        KnowledgeChunk(chunk_id="chunk-policy-001", asset_id="asset-policy-001", asset_version="2026.1", title="医保结算政策说明", asset_type=KnowledgeAssetType.POLICY, section="结算异常", text="医保结算异常需核对交易状态、收费状态和错误码含义。", summary="结算异常处理", tags={"settlement", "error_code"}, scenario_tags={"settlement_exception"}, visibility=clinical_scope, locator="policy#1"),
        KnowledgeChunk(chunk_id="chunk-rule-001", asset_id="asset-audit-rule-001", asset_version="2026.1", title="出院前审核规则", asset_type=KnowledgeAssetType.AUDIT_RULE, section="事前审核", text="出院前应核对事前审核风险、DRG/DIP 风险和病案首页完整性。", summary="出院前质控", tags={"pre_audit", "drg_dip", "medical_record"}, scenario_tags={"pre_discharge_qc"}, visibility=clinical_scope, locator="rule#1"),
    ]
    return InMemoryKnowledgeAssetRepository(assets, chunks)
