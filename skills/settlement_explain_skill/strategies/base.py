"""
BaseStrategy — 费用解释策略抽象基类。

每个费用项（统筹自付、起付线、大额自付等）拥有独立的 Strategy 子类。
Strategy 负责：definition、policy_queries、answer、
calculation_trace、warnings、completeness。

assembler.py 不再包含解释逻辑，仅做分发。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 延迟导入避免启动时依赖未就绪
_MAKE_LLM_READABLE = None


@dataclass
class StrategyResult:
    """Strategy 执行的标准输出。"""
    definition: dict
    answer: str
    calculation_trace: dict
    policy_queries: list[Any]
    warnings: list[str]
    completeness: dict
    target_fee_item: str = "pooling_self_pay"
    target_field: str = "basic_pooling_self_pay"


class BaseFeeStrategy(ABC):
    """费用解释策略基类。"""

    fee_item: str = ""
    fee_label: str = ""
    fee_field: str = ""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self._configs: dict[str, Any] = {}

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        import yaml
        if filename not in self._configs:
            path = self.config_dir / filename
            if path.exists():
                self._configs[filename] = yaml.safe_load(path.read_text(encoding="utf-8"))
            else:
                self._configs[filename] = {}
        return self._configs[filename]

    # ── 统一字段访问 ─────────────────────────────────────────

    # ── 抽象方法 ─────────────────────────────────────────────

    @abstractmethod
    def build_definition(self) -> dict:
        """返回 definition dict（name, plain_text, excludes）。"""
        ...

    @abstractmethod
    def build_policy_queries(self) -> list[Any]:
        """返回 StructuredPolicyQuery 列表。"""
        ...

    @abstractmethod
    def build_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        """生成面向当前院端经办角色的单一解释。"""
        ...

    @abstractmethod
    def build_calculation_trace(
        self, ctx: Any, evidence: list[dict]
    ) -> dict:
        """生成计算链路。"""
        ...

    @abstractmethod
    def build_warnings(self, ctx: Any, policy_status: str) -> list[str]:
        """生成警告信息。"""
        ...

    @abstractmethod
    def build_completeness(
        self, ctx: Any, evidence: list[dict]
    ) -> dict:
        """判断解释完整性。"""
        ...

    def execute(
        self, ctx: Any, evidence: list[dict], policy_status: str,
    ) -> StrategyResult:
        """执行完整策略（委托给各个 build_* 方法）。

        Args:
            ctx: 结算上下文（属性式访问）
            evidence: 政策证据列表
            policy_status: 政策匹配状态

        Returns:
            StrategyResult
        """
        # YAML 结构化查询（语义层动态查询路径已退役，统一走 YAML）
        policy_queries = self.build_policy_queries()

        return StrategyResult(
            definition=self.build_definition(),
            answer=self.build_answer(ctx, evidence, policy_status),
            calculation_trace=self.build_calculation_trace(ctx, evidence),
            policy_queries=policy_queries,
            warnings=self.build_warnings(ctx, policy_status),
            completeness=self.build_completeness(ctx, evidence),
            target_fee_item=self.fee_item,
            target_field=self.fee_field,
        )

    @staticmethod
    def _fmt_money(value: Any) -> str:
        if value is None or value == "" or (isinstance(value, (int, float)) and value == 0):
            return "未获取"
        try:
            return f"{float(value):,.2f}"
        except (ValueError, TypeError):
            return "未获取"

    @staticmethod
    def _clean_policy_excerpt(text: str) -> str:
        import re
        cleaned = re.sub(r"\n?\{[^}]*\}[\s\S]*$", "", text).strip()
        cleaned = re.sub(r"\n{2,}", "\n", cleaned)
        cleaned = "\n".join(line.strip() for line in cleaned.split("\n") if line.strip())
        return cleaned

    @staticmethod
    def _make_llm_context(ctx: Any) -> str:
        """将结算上下文转换为 LLM 可读的自然语言描述。

        可被各 Strategy 的 build_* 方法用来生成 LLM prompt 中嵌入的上下文信息。
        委托给 semantic_utils.make_llm_readable 实现。

        Args:
            ctx: 结算上下文对象（支持 IndicatorContext 或属性式访问）

        Returns:
            LLM 可读的自然语言描述字符串
        """
        global _MAKE_LLM_READABLE
        if _MAKE_LLM_READABLE is None:
            from .semantic_utils import make_llm_readable as _fn
            _MAKE_LLM_READABLE = _fn
        return _MAKE_LLM_READABLE(ctx)
