"""数据目录 PG 活库冒烟 — issue #38。

只读验证生产装配（语义注册表 + 治理/落地库只读面 + discovery 字段释义）
在真实 PostgreSQL 上成立：
- 三级资产可搜索（活库已 seed 的 mzjyxx 对象/指标能命中）
- SLA 看板与批次表实测一致（catalog 输出的最近批次 == 直查批次表的行）
- 血缘可溯源到数据批次与语义版本
不写入任何表。
环境依赖: PostgreSQL（127.0.0.1:5432/hospital_mcp，与生产同构）；不可用时整组 skip。
"""
from __future__ import annotations

import pytest

from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.postgresql.outpatient_store import OutpatientPostgresStore
from src.runtime.catalog.service import build_default_catalog_service


def _pg_ready() -> bool:
    try:
        client = PostgreSQLClient()
        client.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_ready(), reason="PostgreSQL 不可用，跳过活库冒烟")


@pytest.fixture(scope="module")
def service():
    return build_default_catalog_service()


class TestLiveCatalog:
    def test_seeded_object_searchable(self, service):
        result = service.search("结算", limit=50)
        assert result.total >= 1
        assert any(
            i.asset_type == "object" and i.asset_id == "mzjyxx" for i in result.items
        )

    def test_sla_batches_match_batch_table(self, service):
        # 验收口径：血缘与 SLA 数据与批次表实测一致
        board = service.get_sla()
        direct = OutpatientPostgresStore().list_recent_batches(limit=10)
        if not direct:
            pytest.skip("活库暂无同步批次，跳过批次一致性断言")
        expected = [b.batch_id for b in direct]
        assert [b.batch_id for b in board.recent_batches] == expected
        for catalog_row, direct_row in zip(board.recent_batches, direct):
            assert catalog_row.source_id == direct_row.source_id
            assert catalog_row.row_count == direct_row.row_count
            assert catalog_row.quality_status == direct_row.quality_summary.get("status")

    def test_metric_lineage_reaches_batches_and_versions(self, service):
        metrics = service.search("自付", asset_type="metric", limit=10)
        if not metrics.items:
            pytest.skip("活库未命中自付类指标，跳过血缘断言")
        lineage = service.get_lineage("metric", metrics.items[0].asset_id)
        datasets = lineage.datasets or []
        projection = [d for d in datasets if d.datasource_id == "outpatient_postgres"]
        if projection:
            assert lineage.batches, "落地库指标血缘必须溯源到数据批次"
            assert lineage.sources == ["outpatient_postgres"]
        # 语义版本：对象已发布则血缘必带版本
        if lineage.versions:
            assert lineage.versions[0].version

    def test_live_batches_table_readonly(self, service):
        """目录读批次不影响批次表（无写路径）。"""
        before = PostgreSQLClient().execute(
            "SELECT count(*) AS n FROM outpatient_sync_batches"
        )[0]["n"]
        service.get_sla()
        service.get_lineage("object", "mzjyxx")
        after = PostgreSQLClient().execute(
            "SELECT count(*) AS n FROM outpatient_sync_batches"
        )[0]["n"]
        assert after == before
