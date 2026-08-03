"""
输出处理器 — 将评估结果路由到对应的 Widget 渲染。

职责：
1. 接收 evaluate_all() 的输出
2. 根据上下文选择合适的 Widget
3. 处理 Widget 不支持时的降级策略
4. 管理输出模式（terminal / html / text）
"""
from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .custom_widgets import (
    Widget,
    MetricsTable,
    ComparisonView,
    PerQueryDetail,
    BaselineDiff,
    SummaryCard,
    RenderBackend,
    get_widget,
)

# ── 输出模式检测 ─────────────────────────────────────

def detect_output_backend() -> RenderBackend:
    """检测当前运行环境的输出后端。

    - Jupyter / IPython → html
    - 设置了 EVAL_OUTPUT_HTML → html
    - 标准终端 → terminal
    - 管道/重定向 → text
    """
    if os.environ.get("EVAL_OUTPUT_HTML"):
        return "html"

    try:
        from IPython import get_ipython
        if get_ipython() is not None:
            return "html"
    except ImportError:
        pass

    if not os.isatty(1):  # stdout 不是终端
        return "text"

    # 检查是否支持 ANSI（Windows 旧终端可能不支持）
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return "text"

    return "terminal"


# ── 输出处理器 ───────────────────────────────────────

@dataclass
class OutputHandler:
    """评估结果输出处理器。

    封装评估结果 → Widget 渲染的完整流程。

    Usage:
        handler = OutputHandler()
        results = evaluate_all(queries, retriever)
        print(handler.render_metrics(results))
    """

    backend: RenderBackend = field(default_factory=detect_output_backend)
    base_dir: Path | None = None  # baseline 目录

    def __post_init__(self):
        if self.base_dir is None:
            self.base_dir = Path(__file__).parent / "baseline"

    # ── 高层渲染方法 ──────────────────────────────

    def render_metrics(self, results: dict[str, Any]) -> str:
        """渲染指标汇总表（带概览卡片）。"""
        summary = results.get("summary", {})
        per_query = results.get("per_query", [])

        card = SummaryCard(
            backend=self.backend,
            total_queries=len(per_query),
            avg_recall_at_5=summary.get("recall@5", 0.0),
            avg_mrr=summary.get("mrr", 0.0),
            avg_ndcg_at_5=summary.get("ndcg@5", 0.0),
            retriever_mode=summary.get("retriever_mode", "unknown"),
            passed_count=sum(
                1 for r in per_query if r.get("recall@5", 0.0) >= 0.3
            ),
        )

        table = MetricsTable(
            backend=self.backend,
            title="检索质量评估",
            summary=summary,
            by_difficulty=summary.get("by_difficulty", {}),
            by_rule_type=summary.get("by_rule_type", {}),
            retriever_mode=summary.get("retriever_mode", "unknown"),
        )

        return card.render() + "\n" + table.render()

    def render_comparison(
        self,
        vector_results: dict[str, Any],
        bm25_results: dict[str, Any],
    ) -> str:
        """渲染向量 vs BM25 对比视图。"""
        comp = ComparisonView(
            backend=self.backend,
            left_label="向量检索 (bge-base-zh-v1.5)",
            right_label="BM25 检索 (Okapi + jieba)",
            left_summary=vector_results.get("summary", {}),
            right_summary=bm25_results.get("summary", {}),
        )
        return comp.render()

    def render_per_query(self, results: dict[str, Any], sort_by: str = "recall@5") -> str:
        """渲染逐 query 详情。"""
        detail = PerQueryDetail(
            backend=self.backend,
            per_query=results.get("per_query", []),
            sort_by=sort_by,
            ascending=True,
        )
        return detail.render()

    def render_baseline_diff(
        self,
        current_results: dict[str, Any],
        baseline_name: str = "baseline_vector_v1.json",
        tolerance: float = 0.05,
    ) -> str:
        """渲染基线差异视图。"""
        baseline_path = self.base_dir / baseline_name if self.base_dir else None

        if not baseline_path or not baseline_path.exists():
            return f"[skip] 基线文件不存在: {baseline_path}"

        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

        diff = BaselineDiff(
            backend=self.backend,
            current_summary=current_results.get("summary", {}),
            baseline_summary=baseline.get("summary", {}),
            tolerance=tolerance,
        )
        return diff.render()

    def render_full_report(
        self,
        vector_results: dict[str, Any],
        bm25_results: dict[str, Any] | None = None,
        check_baseline: bool = False,
    ) -> str:
        """渲染完整评估报告。

        包含：概览 → 指标汇总 → 对比（如有 BM25）→ 逐 query → 基线检查。
        """
        parts: list[str] = []

        # 1. 向量检索概览 + 指标
        parts.append(self.render_metrics(vector_results))

        # 2. BM25 对比
        if bm25_results:
            parts.append(self.render_comparison(vector_results, bm25_results))

        # 3. 逐 query 详情（低召回优先）
        parts.append(
            f"\n{'─' * 60}\n"
            f"  📋 向量检索 - 逐 Query 分析（低召回优先）\n"
            f"{'─' * 60}"
        )
        parts.append(self.render_per_query(vector_results, sort_by="recall@5"))

        if bm25_results:
            parts.append(self.render_per_query(bm25_results, sort_by="recall@5"))

        # 4. 基线检查
        if check_baseline:
            parts.append(self.render_baseline_diff(vector_results))
            if bm25_results:
                parts.append(
                    self.render_baseline_diff(bm25_results, "baseline_bm25_v1.json")
                )

        return "\n".join(parts)

    # ── Widget 路由 ───────────────────────────────

    def render_widget(self, widget_name: str, **kwargs: Any) -> str:
        """按名称渲染指定 Widget。

        Args:
            widget_name: 注册的 Widget 名称（metrics_table / comparison_view ...）
            **kwargs: 传递给 Widget 构造函数的参数

        Returns:
            渲染后的字符串

        Raises:
            ValueError: Widget 不存在或不支持当前后端
        """
        widget_cls = get_widget(widget_name)
        if widget_cls is None:
            raise ValueError(
                f"未知 Widget: {widget_name}。可用: {list(get_widget.__globals__.get('_WIDGET_REGISTRY', {}).keys())}"
            )

        widget = widget_cls(backend=self.backend, **kwargs)

        if not widget.supports_backend(self.backend):
            # 降级到 text
            widget.backend = "text"

        return widget.render()

    # ── 便捷方法 ──────────────────────────────────

    @staticmethod
    def print_report(
        vector_results: dict[str, Any],
        bm25_results: dict[str, Any] | None = None,
        backend: RenderBackend | None = None,
    ) -> None:
        """快捷方法：打印完整评估报告到 stdout。"""
        handler = OutputHandler(
            backend=backend or detect_output_backend()
        )
        print(handler.render_full_report(vector_results, bm25_results))
