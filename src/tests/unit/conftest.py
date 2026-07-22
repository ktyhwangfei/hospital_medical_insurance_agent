"""
unit conftest — 确保使用内存存储，避免 PostgreSQL 连接超时
"""
import os
os.environ["USE_MEMORY_STORAGE"] = "1"
