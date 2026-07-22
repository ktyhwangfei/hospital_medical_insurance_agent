"""
BaseStrategy — 费用解释策略抽象基类。

每个费用项（统筹自付、起付线、大额自付等）拥有独立的 Strategy 子类。
Strategy 负责：definition、policy_queries、patient_answer、office_answer、
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
    patient_answer: str
    office_answer: str
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
        # 运行时上下文（每次 execute() 时设置）
        self._indicator_context: Any = None

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

    def _get(self, ctx: Any, field_name: str, default: Any = 0) -> Any:
        """统一字段取值：兼容 settlement_context 和 IndicatorContext

        当 _indicator_context 存在时，优先从此提取字段值；
        否则回退到 ctx 对象的 getattr。

        Args:
            ctx: 由 execute() 传入的上下文（可能已是 ContextProxy）
            field_name: 字段名（如 "basic_pooling_self_pay"）
            default: 默认值

        Returns:
            字段值
        """
        from .semantic_utils import get_field as _semantic_get_field

        # 如果 ctx 已是 ContextProxy，直接委托 getattr
        if hasattr(ctx, "_settlement_ctx") or hasattr(ctx, "_indicator_ctx"):
            return getattr(ctx, field_name, default)

        # 如果 _indicator_context 存在，使用语义层取值
        if self._indicator_context is not None:
            return _semantic_get_field(self._indicator_context, field_name, default)

        # 兜底：直接 getattr
        return getattr(ctx, field_name, default)

    def _get_normalized_dimension(
        self, ctx: Any, field_name: str, dict_category: str, default: str = ""
    ) -> str:
        """获取并标准化维度值

        从上下文中提取维度原始值，然后使用注册表字典标准化。
        如 insurance_type 的原始值 "310" → "城镇职工基本医疗保险"。

        Args:
            ctx: 结算上下文（或 ContextProxy）
            field_name: 字段名（如 "insurance_type"）
            dict_category: 字典类别（如 "险种类别"）
            default: 标准化失败时的默认值

        Returns:
            标准化后的维度值字符串
        """
        raw = self._get(ctx, field_name, None)
        if raw is None:
            return default

        from .semantic_utils import normalize_dimension_value

        normalized = normalize_dimension_value(raw, dict_category)
        return normalized if normalized else str(raw)

    def _build_dynamic_policy_queries(self) -> list[Any] | None:
        """使用语义层动态构建政策查询（替代 YAML 硬编码）

        子类可覆盖此方法，在 _indicator_context 存在时返回动态查询列表。
        返回 None 表示不使用动态查询，回退到 YAML。
        默认实现返回 None（保持向后兼容）。

        Returns:
            list[StructuredPolicyQuery] 或 None
        """
        return None

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
    def build_patient_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        """生成患者视角解释。"""
        ...

    @abstractmethod
    def build_office_answer(
        self, ctx: Any, evidence: list[dict], policy_status: str
    ) -> str:
        """生成医保办视角解释。"""
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
        indicator_context: Any = None,
    ) -> StrategyResult:
        """执行完整策略（委托给各个 build_* 方法）。

        Args:
            ctx: 结算上下文（属性式访问）
            evidence: 政策证据列表
            policy_status: 政策匹配状态
            indicator_context: 可选的 IndicatorContext，提供语义层增强

        Returns:
            StrategyResult
        """
        from .semantic_utils import ContextProxy

        # 存储 IndicatorContext 供 _get / _get_normalized_dimension 使用
        self._indicator_context = indicator_context

        # 当 IndicatorContext 存在时，包装为 ContextProxy 提供统一访问
        effective_ctx: Any = ctx
        if indicator_context is not None:
            effective_ctx = ContextProxy(ctx, indicator_context)

        # 动态策略查询优先（语义层驱动），回退到 YAML
        dynamic_queries = self._build_dynamic_policy_queries()
        policy_queries = dynamic_queries if dynamic_queries is not None else self.build_policy_queries()

        return StrategyResult(
            definition=self.build_definition(),
            patient_answer=self.build_patient_answer(effective_ctx, evidence, policy_status),
            office_answer=self.build_office_answer(effective_ctx, evidence, policy_status),
            calculation_trace=self.build_calculation_trace(effective_ctx, evidence),
            policy_queries=policy_queries,
            warnings=self.build_warnings(effective_ctx, policy_status),
            completeness=self.build_completeness(effective_ctx, evidence),
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
