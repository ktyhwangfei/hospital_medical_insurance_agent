"""语义映射存储层 + 服务层 单元测试"""

import pytest

from src.data_platform.storage.semantic_mapping.factory import (
    create_semantic_mapping_storage,
)
from src.data_platform.storage.semantic_mapping.in_memory import (
    InMemorySemanticMappingStorage,
)
from src.domain.indicator.models import SemanticMapping
from src.knowledge_extension.semantic_mapping.service import SemanticMappingService


# ── Fixtures ──

@pytest.fixture
def storage():
    """内存存储实例（自动通过 USE_MEMORY_STORAGE=1 或直接构造）"""
    return InMemorySemanticMappingStorage()


@pytest.fixture
def service(storage):
    """服务层实例"""
    return SemanticMappingService(storage)


@pytest.fixture
def sample_mapping():
    """样例映射：三甲医院 → 三级"""
    return SemanticMapping(
        mapping_id="hosp_lv_001",
        category="hospital_level",
        raw_value="三甲医院",
        normalized_value="三级",
        synonyms=["三甲", "三级甲等"],
        confidence=1.0,
        source="manual",
        enabled=True,
        description="医院等级映射",
    )


# ── 存储层测试 ──

class TestInMemoryStorage:
    def test_save_and_get(self, storage, sample_mapping):
        storage.save_mapping(sample_mapping)
        result = storage.get_mapping("hosp_lv_001")
        assert result is not None
        assert result.raw_value == "三甲医院"
        assert result.normalized_value == "三级"

    def test_get_nonexistent(self, storage):
        assert storage.get_mapping("nonexistent") is None

    def test_list_all(self, storage, sample_mapping):
        storage.save_mapping(sample_mapping)
        m2 = SemanticMapping(
            mapping_id="insu_001",
            category="insurance_type",
            raw_value="职工医保",
            normalized_value="城镇职工基本医疗保险",
        )
        storage.save_mapping(m2)
        all_mappings = storage.list_mappings()
        assert len(all_mappings) == 2

    def test_list_filtered(self, storage, sample_mapping):
        storage.save_mapping(sample_mapping)
        storage.save_mapping(
            SemanticMapping(
                mapping_id="insu_001",
                category="insurance_type",
                raw_value="职工医保",
                normalized_value="城镇职工",
            )
        )
        filtered = storage.list_mappings(category="hospital_level")
        assert len(filtered) == 1
        assert filtered[0].category == "hospital_level"

    def test_delete(self, storage, sample_mapping):
        storage.save_mapping(sample_mapping)
        assert storage.delete_mapping("hosp_lv_001") is True
        assert storage.get_mapping("hosp_lv_001") is None

    def test_delete_nonexistent(self, storage):
        assert storage.delete_mapping("nonexistent") is False

    def test_lookup_exact_match(self, storage, sample_mapping):
        storage.save_mapping(sample_mapping)
        result = storage.lookup("hospital_level", "三甲医院")
        assert result == "三级"

    def test_lookup_synonym_match(self, storage, sample_mapping):
        storage.save_mapping(sample_mapping)
        result = storage.lookup("hospital_level", "三级甲等")
        assert result == "三级"

    def test_lookup_no_match(self, storage, sample_mapping):
        storage.save_mapping(sample_mapping)
        result = storage.lookup("hospital_level", "社区医院")
        assert result is None

    def test_lookup_disabled(self, storage, sample_mapping):
        sample_mapping.enabled = False
        storage.save_mapping(sample_mapping)
        result = storage.lookup("hospital_level", "三甲医院")
        assert result is None

    def test_bulk_save(self, storage):
        mappings = [
            SemanticMapping(mapping_id=f"test_{i}", category="test", raw_value=f"raw_{i}", normalized_value=f"norm_{i}")
            for i in range(5)
        ]
        count = storage.bulk_save(mappings)
        assert count == 5
        assert len(storage.list_mappings()) == 5

    def test_health(self, storage):
        health = storage.health()
        assert health.status == "healthy"
        assert health.total_mappings == 0

    def test_deep_copy_isolation(self, storage, sample_mapping):
        """验证 model_copy(deep=True) 防止外部修改"""
        storage.save_mapping(sample_mapping)
        # 修改原始对象不应影响存储中的副本
        sample_mapping.raw_value = "modified"
        result = storage.get_mapping("hosp_lv_001")
        assert result.raw_value == "三甲医院"  # 未受影响


# ── 服务层测试 ──

class TestSemanticMappingService:
    def test_create_mapping(self, service, sample_mapping):
        result = service.create_mapping(sample_mapping)
        assert result.mapping_id == "hosp_lv_001"
        assert result.created_at != ""
        assert result.updated_at != ""

    def test_create_duplicate_raises(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        with pytest.raises(ValueError, match="已存在"):
            service.create_mapping(sample_mapping)

    def test_get_mapping(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        result = service.get_mapping("hosp_lv_001")
        assert result is not None
        assert result.normalized_value == "三级"

    def test_list_mappings(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        mappings = service.list_mappings()
        assert len(mappings) == 1

    def test_update_mapping(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        updated = service.update_mapping("hosp_lv_001", {"normalized_value": "三级医院", "description": "更新后"})
        assert updated.normalized_value == "三级医院"
        assert updated.description == "更新后"

    def test_update_nonexistent_raises(self, service):
        with pytest.raises(ValueError, match="不存在"):
            service.update_mapping("nonexistent", {"normalized_value": "x"})

    def test_delete_mapping(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        assert service.delete_mapping("hosp_lv_001") is True
        assert service.get_mapping("hosp_lv_001") is None

    def test_lookup(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        result = service.lookup("hospital_level", "三级甲等")  # 同义词
        assert result == "三级"

    def test_import_from_dicts(self, service):
        data = [
            {"mapping_id": "imp_1", "category": "test", "raw_value": "a", "normalized_value": "A"},
            {"mapping_id": "imp_2", "category": "test", "raw_value": "b", "normalized_value": "B"},
        ]
        result = service.import_from_dicts(data)
        assert result["imported"] == 2
        assert result["skipped"] == 0
        assert len(result["errors"]) == 0

    def test_import_skips_duplicates(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        data = [
            {"mapping_id": "hosp_lv_001", "category": "hospital_level", "raw_value": "三甲医院", "normalized_value": "三级"},
            {"mapping_id": "new_1", "category": "test", "raw_value": "x", "normalized_value": "X"},
        ]
        result = service.import_from_dicts(data)
        assert result["imported"] == 1
        assert result["skipped"] == 1

    def test_export_to_dicts(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        result = service.export_to_dicts()
        assert len(result) == 1
        assert result[0]["mapping_id"] == "hosp_lv_001"

    def test_get_stats(self, service, sample_mapping):
        service.create_mapping(sample_mapping)
        service.create_mapping(
            SemanticMapping(
                mapping_id="insu_001", category="insurance_type",
                raw_value="职工医保", normalized_value="城镇职工", source="imported"
            )
        )
        stats = service.get_stats()
        assert stats["total"] == 2
        assert stats["by_category"]["hospital_level"] == 1
        assert stats["by_category"]["insurance_type"] == 1
        assert stats["by_source"]["manual"] == 1
        assert stats["by_source"]["imported"] == 1


# ── 领域模型测试 ──

class TestDomainModels:
    def test_semantic_mapping_creation(self):
        m = SemanticMapping(
            mapping_id="test_001",
            category="hospital_level",
            raw_value="二甲",
            normalized_value="二级",
        )
        assert m.mapping_id == "test_001"
        assert m.synonyms == []
        assert m.confidence == 1.0
        assert m.source == "manual"
        assert m.enabled is True

    def test_semantic_mapping_with_synonyms(self):
        m = SemanticMapping(
            mapping_id="test_002",
            category="service_type",
            raw_value="门诊",
            normalized_value="outpatient",
            synonyms=["普通门诊", "门急诊"],
        )
        assert len(m.synonyms) == 2
        assert "普通门诊" in m.synonyms
