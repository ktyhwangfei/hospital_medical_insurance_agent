"""数据模型建模服务 — 架构设计 V3.0 §4（数据治理体系 · 数据建模阶段）。

生命周期：draft → published → deprecated（终态）。
published 模型结构冻结：不可再编辑字段、不可删除，只可退役（与 Flow 发布证据同理）。
映射确认流：draft → confirmed，仅 confirmed 映射参与物化（Slice 2 消费）。
"""
from __future__ import annotations

from src.data_platform.storage.data_model.data_model_ports import DataModelStorage
from src.domain.data_model.models import (
    DataModel,
    DataModelMapping,
    DataModelNotFoundError,
    DataModelStateInvalidError,
    DataModelStatus,
    MappingStatus,
    compute_model_content_hash,
    utc_now_iso,
    validate_for_publish,
)


class DataModelingService:
    def __init__(self, storage: DataModelStorage) -> None:
        self._storage = storage

    # ── 模型 CRUD ──────────────────────────────────────────────────

    def create_model(self, model: DataModel) -> DataModel:
        # 同 code 重建仅限 deprecated（退出消费后允许重开）；draft/published 占用即拒
        existing = self._storage.get_model(model.model_code)
        if existing is not None and existing.status is not DataModelStatus.DEPRECATED:
            from src.domain.data_model.models import DataModelConflictError

            raise DataModelConflictError(f"数据模型 {model.model_code} 已存在")
        draft = model.model_copy(deep=True, update={
            "status": DataModelStatus.DRAFT,
            "version": 1,
            "revision": 1,
        })
        draft.content_hash = compute_model_content_hash(draft)
        draft.created_at = utc_now_iso()
        draft.updated_at = draft.created_at
        if existing is not None and existing.status is DataModelStatus.DEPRECATED:
            # 重建：删除旧 deprecated 文档（映射外键级联清掉），再建新草稿
            self._storage.delete_model(model.model_code, existing.revision)
        return self._storage.create_model(draft)

    def get_model(self, model_code: str) -> DataModel:
        model = self._storage.get_model(model_code)
        if model is None:
            raise DataModelNotFoundError(model_code)
        return model

    def list_models(self) -> list[DataModel]:
        return self._storage.list_models()

    def update_model(
        self, model_code: str, model: DataModel, expected_revision: int
    ) -> DataModel:
        current = self.get_model(model_code)
        if model.model_code != model_code:
            raise DataModelStateInvalidError(
                f"model_code 不可变更：{model.model_code} != {model_code}"
            )
        if current.status is not DataModelStatus.DRAFT:
            raise DataModelStateInvalidError(
                f"{current.status.value} 模型结构冻结，不可编辑；published 模型请退役后重建"
            )
        updated = model.model_copy(deep=True, update={
            "status": DataModelStatus.DRAFT,
            "revision": current.revision + 1,
            "created_at": current.created_at,
            "updated_at": utc_now_iso(),
        })
        updated.content_hash = compute_model_content_hash(updated)
        return self._storage.update_model(updated, expected_revision)

    def delete_model(self, model_code: str, expected_revision: int) -> None:
        current = self.get_model(model_code)
        if current.status is not DataModelStatus.DRAFT:
            raise DataModelStateInvalidError(
                f"{current.status.value} 模型存在发布事实，只能 deprecate，不能删除"
            )
        self._storage.delete_model(model_code, expected_revision)

    # ── 生命周期 ────────────────────────────────────────────────────

    def submit_review(self, model_code: str) -> DataModel:
        """draft → pending_review：发布前必经评审（治理动作有治理）。"""
        current = self.get_model(model_code)
        if current.status is not DataModelStatus.DRAFT:
            raise DataModelStateInvalidError(
                f"submit-review 仅允许 draft，当前 {current.status.value}"
            )
        validate_for_publish(current)
        submitted = current.model_copy(deep=True, update={
            "status": DataModelStatus.PENDING_REVIEW,
            "revision": current.revision + 1,
            "updated_at": utc_now_iso(),
        })
        submitted.content_hash = compute_model_content_hash(submitted)
        return self._storage.update_model(submitted, current.revision)

    def publish_model(self, model_code: str) -> DataModel:
        current = self.get_model(model_code)
        if current.status is not DataModelStatus.PENDING_REVIEW:
            raise DataModelStateInvalidError(
                f"publish 仅允许 pending_review，当前 {current.status.value}（请先提交评审）"
            )
        validate_for_publish(current)
        published = current.model_copy(deep=True, update={
            "status": DataModelStatus.PUBLISHED,
            "version": current.version + 1,
            "revision": current.revision + 1,
            "updated_at": utc_now_iso(),
        })
        published.content_hash = compute_model_content_hash(published)
        return self._storage.update_model(published, current.revision)

    def deprecate_model(self, model_code: str) -> DataModel:
        current = self.get_model(model_code)
        if current.status is not DataModelStatus.PUBLISHED:
            raise DataModelStateInvalidError(
                f"deprecate 仅允许 published，当前 {current.status.value}"
            )
        deprecated = current.model_copy(deep=True, update={
            "status": DataModelStatus.DEPRECATED,
            "revision": current.revision + 1,
            "updated_at": utc_now_iso(),
        })
        deprecated.content_hash = compute_model_content_hash(deprecated)
        return self._storage.update_model(deprecated, current.revision)

    # ── 多源映射 ────────────────────────────────────────────────────

    def save_mapping(self, mapping: DataModelMapping) -> DataModelMapping:
        model = self.get_model(mapping.model_code)
        if mapping.field_code not in {f.field_code for f in model.fields}:
            raise DataModelStateInvalidError(
                f"字段 '{mapping.field_code}' 未在模型 {mapping.model_code} 声明"
            )
        current = self._storage.get_mapping(
            mapping.model_code, mapping.field_code, mapping.source_id
        )
        now = utc_now_iso()
        to_save = mapping.model_copy(deep=True, update={
            "status": MappingStatus.DRAFT if current is None else current.status,
            "revision": 1 if current is None else current.revision + 1,
            "updated_at": now,
        })
        return self._storage.upsert_mapping(
            to_save, None if current is None else current.revision
        )

    def confirm_mapping(
        self, model_code: str, field_code: str, source_id: str
    ) -> DataModelMapping:
        current = self._storage.get_mapping(model_code, field_code, source_id)
        if current is None:
            raise DataModelNotFoundError(f"{model_code}.{field_code}@{source_id}")
        confirmed = current.model_copy(deep=True, update={
            "status": MappingStatus.CONFIRMED,
            "revision": current.revision + 1,
            "updated_at": utc_now_iso(),
        })
        return self._storage.upsert_mapping(confirmed, current.revision)

    def list_mappings(self, model_code: str) -> list[DataModelMapping]:
        self.get_model(model_code)
        return self._storage.list_mappings(model_code)

    def delete_mapping(
        self, model_code: str, field_code: str, source_id: str, expected_revision: int
    ) -> None:
        current = self._storage.get_mapping(model_code, field_code, source_id)
        if current is None:
            raise DataModelNotFoundError(f"{model_code}.{field_code}@{source_id}")
        if current.status is MappingStatus.CONFIRMED:
            raise DataModelStateInvalidError("已确认映射不可删除，请先修改为新映射")
        self._storage.delete_mapping(model_code, field_code, source_id, expected_revision)
