"""模型路由配置 — 门户运行时所需，管理 CRUD 已移除。

路由解析顺序（见 router.py::ModelRouter.resolve）：
  1. 精确匹配 (scene, model_type) → model_name
  2. 回退到 (default, model_type) → model_name
  3. 全部未命中 → 抛 ModelRouteError

通用生产调用使用 model_type="llm"，活跃场景显式路由到 deepseek-chat；
默认路由仅兼容未知场景，默认模型可由环境变量 MODEL_NAME 覆盖（如本地 Ollama：MODEL_NAME=qwen2.5:1.5b）。
Skill AI 编写使用受控的 model_type="reasoning"，固定解析到 deepseek-chat。
"""

import os


class ModelType:
    """模型类型常量，供 router 测试使用。"""

    LLM = "llm"
    EMBEDDING = "embedding"


# 回退链：当主模型不可用时依次尝试
FALLBACK_CHAINS: dict = {}

# 默认 LLM 模型（生产 deepseek-chat；本地可用 MODEL_NAME 覆盖为 Ollama 模型）
_DEFAULT_LLM = os.getenv("MODEL_NAME", "deepseek-chat")

# 模型参数（temperature, max_tokens 等）
MODEL_PARAMS: dict = {
    "deepseek-chat": {"temperature": 0.1, "max_tokens": 4096},
    "qwen2.5:1.5b": {"temperature": 0.1, "max_tokens": 4096},
    "text-embedding-3-small": {"temperature": 0.0, "max_tokens": 1},
}

# 路由表：(scene, model_type) → model_name
ROUTING_TABLE: dict = {
    ("default", "llm"): _DEFAULT_LLM,
    ("default", "embedding"): "text-embedding-3-small",
    # Skill AI 编写、结构修复和优化共用受控 reasoning 路由。
    ("skill_authoring", "reasoning"): "deepseek-chat",
    # 活跃业务场景显式路由（Policy QA / 技能路由 / 费用解释 / 政策提取）
    ("skill_routing", "llm"): "deepseek-chat",
    ("policy_qa", "llm"): "deepseek-chat",
    ("fee_explanation", "llm"): "deepseek-chat",
    ("policy_fact_extraction", "llm"): "deepseek-chat",
}
