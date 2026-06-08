"""工具接口协议 — Skill 声明它需要什么能力，Agent 端负责实现。

本文件定义纯接口契约，不依赖任何 Agent 项目内的具体实现。
换一个 Agent 环境时，只要实现了这些 Protocol，calculator.py 就能跑。
"""

from dataclasses import dataclass, field
from typing import Protocol, AsyncIterator


# ── 标准化数据结构 ──────────────────────────────────────────────

@dataclass
class PatientSettlementData:
    """标准化患者结算数据 — 所有 Agent 必须返回此结构"""
    settlement_id: str = ""
    treatment: dict = field(default_factory=dict)
    fee_details: list = field(default_factory=list)
    annual: dict = field(default_factory=dict)
    admission: dict = field(default_factory=dict)
    patient_info: dict = field(default_factory=dict)


@dataclass
class PolicyRule:
    """标准化政策规则"""
    title: str = ""
    clause: str = ""
    evidence_text: str = ""
    matched_reason: str = ""
    rule_type: str = ""
    score: float = 0.0


# ── 工具接口 ────────────────────────────────────────────────────

class SqlQueryTool(Protocol):
    """SQL 数据查询接口"""

    async def query(self, settlement_id: str) -> PatientSettlementData:
        """根据结算ID查询患者结算相关数据"""
        ...


class PolicySearchTool(Protocol):
    """政策规则检索接口"""

    async def search(
        self, query: str, filters: list[str], top_k: int
    ) -> list[PolicyRule]:
        """搜索政策规则，按 filters 过滤规则类型"""
        ...


class LlmExplainTool(Protocol):
    """LLM 解释生成接口"""

    async def generate_stream(self, context: dict) -> AsyncIterator[str]:
        """流式生成解释文本"""
        ...
