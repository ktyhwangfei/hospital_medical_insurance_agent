"""模型路由配置 — 门户运行时所需，管理 CRUD 已移除。

路由解析顺序（见 router.py::ModelRouter.resolve）：
  1. 精确匹配 (scene, model_type) → model_name
  2. 回退到 (default, model_type) → model_name
  3. 全部未命中 → 抛 ModelRouteError

所有现有生产调用均使用 model_type="llm"，活跃场景显式路由到 deepseek-chat；
默认路由仅兼容未知场景。
"""


class ModelType:
    """模型类型常量，供 router 测试使用。"""
    LLM = "llm"
    EMBEDDING = "embedding"


# 回退链：当主模型不可用时依次尝试
FALLBACK_CHAINS: dict = {}

# 模型参数（temperature, max_tokens 等）
MODEL_PARAMS: dict = {
    "deepseek-chat": {"temperature": 0.1, "max_tokens": 4096},
    "text-embedding-3-small": {"temperature": 0.0, "max_tokens": 1},
}

# 路由表：(scene, model_type) → model_name
ROUTING_TABLE: dict = {
    ("default", "llm"): "deepseek-chat",
    ("default", "embedding"): "text-embedding-3-small",
    ("intent_recognition", "llm"): "deepseek-chat",
    ("skill_routing", "llm"): "deepseek-chat",
    ("policy_qa", "llm"): "deepseek-chat",
    ("fee_explanation", "llm"): "deepseek-chat",
    ("policy_fact_extraction", "llm"): "deepseek-chat",
}
