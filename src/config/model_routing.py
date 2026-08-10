"""模型路由配置 — 门户运行时所需，管理 CRUD 已移除。

路由解析顺序（见 router.py::ModelRouter.resolve）：
  1. 精确匹配 (scene, model_type) → model_name
  2. 回退到 (default, model_type) → model_name
  3. 全部未命中 → 抛 ModelRouteError

通用生产调用使用 model_type="llm"；Skill AI 编写使用受控的
model_type="reasoning"。两者当前都解析到 deepseek-chat。
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
    # fee_explanation 场景显式路由（PoolingSelfPayStrategy._generate_via_llm 使用）
    ("fee_explanation", "llm"): "deepseek-chat",
    # Skill AI 编写、结构修复和优化共用受控 reasoning 路由。
    ("skill_authoring", "reasoning"): "deepseek-chat",
}
