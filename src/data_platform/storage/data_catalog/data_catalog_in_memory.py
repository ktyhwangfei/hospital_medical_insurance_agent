"""数据目录资产内存存储（USE_MEMORY_STORAGE=1 回退 / 单元测试）。"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from src.domain.data_catalog.models import CatalogAsset, CatalogAssetType


class InMemoryDataCatalogStorage:
    """进程内数据目录资产存储。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, CatalogAsset] = {}
        self._id_by_key: dict[str, str] = {}

    def upsert_asset(self, asset: CatalogAsset) -> CatalogAsset:
        with self._lock:
            existing_id = self._id_by_key.get(asset.asset_key)
            if existing_id is not None:
                # 保留原 asset_id 与 created_at，整体替换内容
                current = self._by_id[existing_id]
                asset = asset.model_copy(
                    update={
                        "asset_id": existing_id,
                        "created_at": current.created_at,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
                self._by_id[existing_id] = asset
                return asset
            self._by_id[asset.asset_id] = asset
            self._id_by_key[asset.asset_key] = asset.asset_id
            return asset

    def get_asset(self, asset_id: str) -> CatalogAsset | None:
        with self._lock:
            return self._by_id.get(asset_id)

    def list_assets(
        self,
        *,
        asset_type: CatalogAssetType | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CatalogAsset]:
        with self._lock:
            items = list(self._by_id.values())
        if asset_type is not None:
            items = [a for a in items if a.asset_type == asset_type]
        if keyword:
            kw = keyword.lower()
            items = [
                a
                for a in items
                if kw in a.name.lower()
                or kw in a.description.lower()
                or kw in a.asset_key.lower()
            ]
        items.sort(key=lambda a: (a.asset_type.value, a.name, a.asset_id))
        return items[offset : offset + limit]

    def delete_assets_except(self, keep_keys: list[str]) -> int:
        keep = set(keep_keys)
        with self._lock:
            stale = [a for a in self._by_id.values() if a.asset_key not in keep]
            for asset in stale:
                del self._by_id[asset.asset_id]
                del self._id_by_key[asset.asset_key]
            return len(stale)
