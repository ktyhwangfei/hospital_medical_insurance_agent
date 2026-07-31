"""Token 预算分配策略

超出预算时，摘要（summarize）而非截断（truncate），保证语义不丢。
"""


class TokenBudget:
    """Token 预算分配器"""

    DEFAULT_BUDGET = 4000  # 默认预算（可配置）

    # 预算分配比例
    ALLOCATION = {
        "session_summary": 0.05,      # 5%  会话摘要
        "current_entity": 0.30,       # 30% 当前业务实体
        "related_entities": 0.20,     # 20% 相关实体
        "reasoning_chain": 0.15,      # 15% 推理链
        "conversation": 0.20,         # 20% 对话历史
        "reserve": 0.10,              # 10% 预留
    }

    def __init__(self, total: int | None = None):
        self.total = total or self.DEFAULT_BUDGET

    def allocate(self) -> dict[str, int]:
        """按预设比例分配预算。"""
        return {k: int(self.total * v) for k, v in self.ALLOCATION.items()}

    def estimate_tokens(self, text: str) -> int:
        """粗略估算文本的 token 数（中文字符按 1.5 token/字，英文按 0.25 token/字）。"""
        # 简化估算：中文字符范围
        cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - cn_chars
        return int(cn_chars * 1.5 + other_chars * 0.25)
