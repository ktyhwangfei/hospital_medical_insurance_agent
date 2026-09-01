"""语义发现只允许使用数据治理中心的受控连接。"""
import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.data_platform.outpatient_governance import ConnectionStatus, OutpatientDataSource
from src.runtime.discovery import service
from src.runtime.discovery.service import run_discovery


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _source(status=ConnectionStatus.HEALTHY):
    return OutpatientDataSource(
        source_id="bjybdb", hospital_code="H001", hospital_name="示例医院",
        name="门诊医保库", host="secret-host", database="bjybdb", username="readonly",
        credential_id="credential.bjybdb", credential_configured=True,
        connection_status=status, created_at=NOW, updated_at=NOW,
    )


class _GovernanceService:
    def __init__(self, source=None):
        self.source = source or _source()
        self.connection = object()

    def list_sources(self):
        return [self.source]

    def open_source_connection(self, source_id):
        assert source_id == self.source.source_id
        return self.connection


def test_run_discovery_uses_controlled_connection_without_connection_fields(monkeypatch):
    governance = _GovernanceService()
    captured = {}

    def fake_scan(cfg, store=None, connection=None):
        captured.update(cfg)
        assert connection is governance.connection
        return {"tables": ["o_Trade"], "fields": [{
            "field_name": "T_TradeDate", "table_name": "o_Trade",
            "data_type": "datetime", "non_null_rate": 1.0,
        }], "table_statuses": []}

    monkeypatch.setattr(service, "scan_sqlserver", fake_scan)
    result = run_discovery(
        datasource_id="bjybdb", sample_limit=5000, governance_service=governance,
    )

    assert result["fields"][0]["datasource_id"] == "bjybdb"
    assert captured == {"schema": "dbo", "sample_limit": 5000}
    assert not ({"host", "user", "password", "database"} & captured.keys())


def test_run_discovery_rejects_unhealthy_controlled_source():
    with pytest.raises(ValueError, match="连接健康"):
        run_discovery(
            datasource_id="bjybdb",
            governance_service=_GovernanceService(_source(ConnectionStatus.ERROR)),
        )


def test_discovery_request_forbids_legacy_source_config():
    from src.runtime.api.semantic_routes import DiscoveryScanRequest

    with pytest.raises(ValidationError):
        DiscoveryScanRequest.model_validate({
            "datasource_id": "bjybdb",
            "source_config": {"sqlserver": {"password": "must-not-persist"}},
        })


def test_scan_task_persists_only_controlled_source_id(monkeypatch):
    from src.runtime.api import semantic_routes

    captured = {}

    class Store:
        def create_task(self, task_id, config, sample_limit):
            captured.update(config)

    monkeypatch.setattr(semantic_routes, "_get_discovery_store", lambda: Store())
    request = semantic_routes.DiscoveryScanRequest(datasource_id="bjybdb", sample_limit=1000)
    asyncio.run(semantic_routes.start_discovery_scan(request))

    assert captured == {"datasource_id": "bjybdb", "scope": "全部已接入表"}
    assert "password" not in str(captured).lower()
