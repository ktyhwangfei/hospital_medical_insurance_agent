"""数据模型内存存储 — 开发/测试（USE_MEMORY_STORAGE=1）。"""
from __future__ import annotations

from src.domain.data_model.models import (
    DataModel,
    DataModelConflictError,
    DataModelMapping,
    DataModelNotFoundError,
)


class InMemoryDataModelStorage:
    def __init__(self) -> None:
        self._models: dict[str, DataModel] = {}
        self._mappings: dict[tuple[str, str, str], DataModelMapping] = {}

    def create_model(self, model: DataModel) -> DataModel:
        if model.model_code in self._models:
            raise DataModelConflictError(f"数据模型 {model.model_code} 已存在")
        self._models[model.model_code] = model.model_copy(deep=True)
        return model.model_copy(deep=True)

    def get_model(self, model_code: str) -> DataModel | None:
        model = self._models.get(model_code)
        return model.model_copy(deep=True) if model else None

    def list_models(self) -> list[DataModel]:
        return [m.model_copy(deep=True) for _, m in sorted(self._models.items())]

    def update_model(self, model: DataModel, expected_revision: int) -> DataModel:
        current = self._models.get(model.model_code)
        if current is None:
            raise DataModelNotFoundError(model.model_code)
        if current.revision != expected_revision:
            raise DataModelConflictError(
                f"数据模型版本冲突: 期望 {expected_revision}，实际 {current.revision}"
            )
        self._models[model.model_code] = model.model_copy(deep=True)
        return model.model_copy(deep=True)

    def delete_model(self, model_code: str, expected_revision: int) -> None:
        current = self._models.get(model_code)
        if current is None:
            raise DataModelNotFoundError(model_code)
        if current.revision != expected_revision:
            raise DataModelConflictError(
                f"数据模型版本冲突: 期望 {expected_revision}，实际 {current.revision}"
            )
        del self._models[model_code]
        self._mappings = {k: v for k, v in self._mappings.items() if k[0] != model_code}

    def upsert_mapping(
        self, mapping: DataModelMapping, expected_revision: int | None
    ) -> DataModelMapping:
        key = (mapping.model_code, mapping.field_code, mapping.source_id)
        current = self._mappings.get(key)
        if current is not None and expected_revision is not None and current.revision != expected_revision:
            raise DataModelConflictError(
                f"映射版本冲突: 期望 {expected_revision}，实际 {current.revision}"
            )
        self._mappings[key] = mapping.model_copy(deep=True)
        return mapping.model_copy(deep=True)

    def list_mappings(self, model_code: str) -> list[DataModelMapping]:
        return [
            m.model_copy(deep=True)
            for k, m in sorted(self._mappings.items())
            if k[0] == model_code
        ]

    def get_mapping(
        self, model_code: str, field_code: str, source_id: str
    ) -> DataModelMapping | None:
        mapping = self._mappings.get((model_code, field_code, source_id))
        return mapping.model_copy(deep=True) if mapping else None

    def delete_mapping(
        self, model_code: str, field_code: str, source_id: str, expected_revision: int
    ) -> None:
        key = (model_code, field_code, source_id)
        current = self._mappings.get(key)
        if current is None:
            raise DataModelNotFoundError(f"{model_code}.{field_code}@{source_id}")
        if current.revision != expected_revision:
            raise DataModelConflictError(
                f"映射版本冲突: 期望 {expected_revision}，实际 {current.revision}"
            )
        del self._mappings[key]
