"""
数据访问工厂
根据配置创建数据存储实例
"""
import logging
import os

logger = logging.getLogger(__name__)


def create_data_store():
    """创建数据存储实例"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    print(f"[STARTUP] factory.create_data_store: USE_MEMORY_STORAGE={use_memory}", flush=True)

    if not use_memory:
        try:
            print("[STARTUP] factory.create_data_store: 尝试 PostgreSQL...", flush=True)
            from src.data_platform.data_access.postgres import PostgresDataStore
            store = PostgresDataStore()
            print("[STARTUP] factory.create_data_store: PostgresDataStore 实例化完成，播种数据...", flush=True)
            store.seed_data()  # 确保种子数据已加载
            print("[STARTUP] factory.create_data_store: PostgreSQL 数据存储就绪", flush=True)
            return store
        except Exception as e:
            print(f"[STARTUP] factory.create_data_store: PostgreSQL 失败, 回退内存 — {e}", flush=True)

    from src.data_platform.data_access.in_memory import build_sample_store
    print("[STARTUP] factory.create_data_store: 使用内存存储", flush=True)
    return build_sample_store()
