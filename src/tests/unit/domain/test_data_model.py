"""数据模型领域模型与服务测试 — V3.0 Slice 1。

覆盖：结构校验（粒度/重复/依赖/派生角色）、状态机（draft→published→deprecated）、
乐观锁、published 冻结、映射确认流。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.data_platform.storage.data_model.data_model_in_memory import (
    InMemoryDataModelStorage,
)
from src.domain.data_model.models import (
    DataModel,
    DataModelConflictError,
    DataModelField,
    DataModelMapping,
    DataModelNotFoundError,
    DataModelStateInvalidError,
)
from src.runtime.data_governance.modeling.service import DataModelingService


def _field(code: str, role: str = "fact", **kw) -> dict:
    return {"field_code": code, "name": code, "data_type": "decimal", "field_role": role, **kw}


def _model(**kw) -> DataModel:
    payload = {
        "model_code": "dwd_mz_settlement",
        "name": "门诊结算明细模型",
        "layer": "dwd",
        "grain": "trade_no",
        "entity_code": "settlement",
        "owner": "data_governance",
        "fields": [
            _field("trade_no", "identifier", data_type="varchar"),
            _field("pooling_payment"),
            _field("pooling_self_payment"),
        ],
    }
    payload.update(kw)
    return DataModel.model_validate(payload)


def _service() -> DataModelingService:
    return DataModelingService(InMemoryDataModelStorage())


class TestStructureValidation:
    def test_grain_must_be_identifier(self):
        with pytest.raises(ValidationError, match="粒度字段"):
            _model(fields=[_field("trade_no", "fact"), _field("pooling_payment")])

    def test_duplicate_field_code_rejected(self):
        with pytest.raises(ValidationError, match="重复"):
            _model(fields=[
                _field("trade_no", "identifier", data_type="varchar"),
                _field("pooling_payment"),
                _field("pooling_payment"),
            ])

    def test_derived_dependencies_must_exist(self):
        with pytest.raises(ValidationError, match="依赖未在模型内声明"):
            _model(fields=[
                _field("trade_no", "identifier", data_type="varchar"),
                _field("personal_burden", expression="a + b", dependencies=["a", "b"]),
            ])

    def test_expression_only_allowed_on_fact(self):
        with pytest.raises(ValidationError, match="fact"):
            _model(fields=[
                _field("trade_no", "identifier", data_type="varchar"),
                _field("dept", "dimension", data_type="varchar", expression="x"),
            ])


class TestLifecycle:
    def test_create_defaults_to_draft(self):
        model = _service().create_model(_model(status="published"))
        assert model.status == "draft"
        assert model.revision == 1
        assert model.content_hash

    def test_publish_requires_fields_and_roles(self):
        service = _service()
        # 无 identifier：创建时结构 validator 即拦截（粒度必须 identifier）
        with pytest.raises(ValidationError, match="identifier"):
            _model(fields=[_field("pooling_payment")])
        # 空字段：创建合法、发布门槛拦截
        service.create_model(_model(fields=[]))
        with pytest.raises(DataModelStateInvalidError, match="不能为空"):
            service.publish_model("dwd_mz_settlement")

    def test_dimension_only_model_can_publish(self):
        """纯维度/登记类模型（如诊断表）无 fact 属合法形态，允许发布。"""
        service = _service()
        service.create_model(_model(fields=[
            _field("trade_no", "identifier", data_type="varchar"),
            _field("diagnose_name", "dimension", data_type="nvarchar"),
        ]))
        published = service.publish_model("dwd_mz_settlement")
        assert published.status == "published"

    def test_publish_then_deprecate_happy_path(self):
        service = _service()
        service.create_model(_model())
        published = service.publish_model("dwd_mz_settlement")
        assert published.status == "published"
        assert published.version == 2
        deprecated = service.deprecate_model("dwd_mz_settlement")
        assert deprecated.status == "deprecated"

    def test_published_model_frozen(self):
        service = _service()
        service.create_model(_model())
        service.publish_model("dwd_mz_settlement")
        with pytest.raises(DataModelStateInvalidError, match="冻结"):
            service.update_model("dwd_mz_settlement", _model(), expected_revision=2)
        with pytest.raises(DataModelStateInvalidError, match="deprecate"):
            service.delete_model("dwd_mz_settlement", expected_revision=2)

    def test_optimistic_lock(self):
        service = _service()
        service.create_model(_model())
        with pytest.raises(DataModelConflictError):
            service.update_model("dwd_mz_settlement", _model(), expected_revision=99)

    def test_update_not_found(self):
        with pytest.raises(DataModelNotFoundError):
            _service().update_model("nope", _model(), expected_revision=1)


class TestMappingFlow:
    def _published(self) -> DataModelingService:
        service = _service()
        service.create_model(_model())
        return service

    def _mapping(self) -> DataModelMapping:
        return DataModelMapping(
            model_code="dwd_mz_settlement",
            field_code="pooling_payment",
            source_id="bjybdb",
            physical_table="mz_trade",
            physical_column="T_FundPay",
        )

    def test_mapping_field_must_be_declared(self):
        with pytest.raises(DataModelStateInvalidError, match="未在模型"):
            self._published().save_mapping(self._mapping().model_copy(update={"field_code": "ghost"}))

    def test_confirm_flow(self):
        service = self._published()
        saved = service.save_mapping(self._mapping())
        assert saved.status == "draft"
        confirmed = service.confirm_mapping("dwd_mz_settlement", "pooling_payment", "bjybdb")
        assert confirmed.status == "confirmed"
        assert confirmed.revision == 2

    def test_confirmed_mapping_cannot_be_deleted(self):
        service = self._published()
        service.save_mapping(self._mapping())
        service.confirm_mapping("dwd_mz_settlement", "pooling_payment", "bjybdb")
        with pytest.raises(DataModelStateInvalidError, match="已确认"):
            service.delete_mapping("dwd_mz_settlement", "pooling_payment", "bjybdb", expected_revision=2)

    def test_confirm_missing_mapping(self):
        with pytest.raises(DataModelNotFoundError):
            self._published().confirm_mapping("dwd_mz_settlement", "pooling_payment", "ghost")

    def test_save_mapping_preserves_confirmed_status_on_edit(self):
        service = self._published()
        service.save_mapping(self._mapping())
        service.confirm_mapping("dwd_mz_settlement", "pooling_payment", "bjybdb")
        edited = service.save_mapping(self._mapping().model_copy(update={"physical_column": "T_FundPay2"}))
        assert edited.status == "confirmed"
        assert edited.physical_column == "T_FundPay2"
