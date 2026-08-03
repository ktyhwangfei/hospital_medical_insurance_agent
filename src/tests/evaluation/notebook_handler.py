"""
Notebook 模式处理器 — 将 Hermes Agent 交互元素映射为评估 Widget。

实现 Hermes Agent 的交互原语到评估 Widget 的映射：
- display(data)     → SummaryCard / MetricsTable（展示评估结果）
- ask(question)     → PerQueryDetail（交互式查询选择）
- track(progress)   → 进度条（长评估时的进度反馈）
- confirm(action)   → BaselineDiff（确认基线保存等操作）

对于平台不支持 Widget 的情况，自动降级为标准事件流。

设计原则：
1. Widget 优先：能用 Widget 就用 Widget
2. 渐进增强：Widget 不可用时降级到文本输出
3. 无侵入：不修改现有评估逻辑，只新增输出层
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .custom_widgets import (
    ANSI,
    RenderBackend,
    SummaryCard,
    MetricsTable,
    PerQueryDetail,
    BaselineDiff,
    ComparisonView,
)
from .output_handler import OutputHandler, detect_output_backend


# ── 进度跟踪 ─────────────────────────────────────────

@dataclass
class ProgressTracker:
    """评估进度追踪器。

    用于 track() 原语。在长评估（如 50 query × 2 modes）中提供实时进度反馈。
    """

    total: int
    current: int = 0
    label: str = "评估中"
    start_time: float = field(default_factory=time.time)
    bar_width: int = 30

    def update(self, n: int = 1, label: str | None = None) -> str:
        """更新进度并返回进度条字符串。"""
        self.current += n
        if label:
            self.label = label
        return self._render()

    def _render(self) -> str:
        pct = min(self.current / self.total, 1.0) if self.total > 0 else 0.0
        filled = int(pct * self.bar_width)
        bar = "█" * filled + "░" * (self.bar_width - filled)

        elapsed = time.time() - self.start_time
        if pct > 0 and self.current > 0:
            eta = elapsed / pct * (1 - pct)
            eta_str = f"ETA {eta:.0f}s"
        else:
            eta_str = ""

        return (
            f"\r{ANSI['cyan']}{self.label}{ANSI['reset']} "
            f"[{ANSI['green']}{bar}{ANSI['reset']}] "
            f"{self.current}/{self.total} "
            f"{pct * 100:.0f}% "
            f"{ANSI['dim']}{eta_str}{ANSI['reset']}"
        )

    def done(self) -> str:
        """完成时输出。"""
        elapsed = time.time() - self.start_time
        return (
            f"\r{ANSI['green']}✓ {self.label} 完成{ANSI['reset']} "
            f"({self.total} 项, {elapsed:.1f}s)"
            + " " * 20
        )


# ── 交互原语 Protocol ──────────────────────────────

class DisplayFn(Protocol):
    """display(data) 原语：展示数据。"""
    def __call__(self, data: Any, *, kind: str = "auto") -> str: ...


class AskFn(Protocol):
    """ask(question, choices) 原语：询问用户。"""
    def __call__(self, question: str, choices: list[str] | None = None) -> str: ...


class TrackFn(Protocol):
    """track(progress) 原语：追踪进度。"""
    def __call__(self, total: int, label: str = "处理中") -> ProgressTracker: ...


class ConfirmFn(Protocol):
    """confirm(action) 原语：确认操作。"""
    def __call__(self, action: str, details: str = "") -> bool: ...


# ── Notebook Handler ─────────────────────────────────

@dataclass
class NotebookHandler:
    """Notebook 模式处理器。

    将评估流程包装为类似 Jupyter Notebook 的交互式体验。

    Usage:
        nb = NotebookHandler()
        nb.display(results, kind="metrics")
        nb.ask("选择要查看的查询", choices=["Q001", "Q002"])
        tracker = nb.track(50, "向量检索评估")
        for i in range(50):
            # ... 评估逻辑 ...
            tracker.update()
    """

    backend: RenderBackend = field(default_factory=detect_output_backend)
    output: OutputHandler = field(default_factory=OutputHandler)
    _history: list[dict[str, Any]] = field(default_factory=list)  # 操作历史

    # ── display ────────────────────────────────────

    def display(self, data: Any, *, kind: str = "auto") -> str:
        """展示评估数据。

        Args:
            data: 评估结果（evaluate_all() 的输出）或其他数据。
            kind: "metrics" / "comparison" / "per_query" / "baseline" / "auto"。
                  auto 时自动检测数据类型。

        Returns:
            渲染后的字符串。
        """
        if kind == "auto":
            kind = self._detect_kind(data)

        rendered = self._render_display(data, kind)
        self._history.append({"op": "display", "kind": kind, "ts": time.time()})
        return rendered

    def _detect_kind(self, data: Any) -> str:
        """自动检测数据类型。"""
        if isinstance(data, dict):
            if "per_query" in data and "summary" in data:
                return "metrics"
            if "left_summary" in data:
                return "comparison"
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if "recall@5" in data[0]:
                return "per_query"
        return "raw"

    def _render_display(self, data: Any, kind: str) -> str:
        """按类型渲染显示。"""
        if kind == "metrics":
            return self.output.render_metrics(data)
        elif kind == "per_query":
            return self.output.render_per_query(data)
        elif kind == "comparison":
            # data 应为 (vector_results, bm25_results) 元组
            if isinstance(data, (list, tuple)) and len(data) == 2:
                return self.output.render_comparison(data[0], data[1])
            return str(data)
        elif kind == "baseline":
            return self.output.render_baseline_diff(data)
        else:
            # 降级：直接打印
            return str(data)

    # ── ask ─────────────────────────────────────────

    def ask(
        self,
        question: str,
        choices: list[str] | None = None,
        *,
        default: str | None = None,
    ) -> str:
        """询问用户并获取响应。

        在终端模式下使用 input() 交互。
        在非交互模式下使用默认值或抛出。

        Args:
            question: 问题文本。
            choices: 可选项列表。
            default: 默认选项。

        Returns:
            用户选择的字符串。
        """
        if choices:
            prompt_parts = [f"\n{ANSI['bold']}{question}{ANSI['reset']}"]
            for i, c in enumerate(choices, 1):
                marker = f"{ANSI['cyan']}[{i}]{ANSI['reset']}"
                prompt_parts.append(f"  {marker} {c}")
            prompt_parts.append(
                f"\n请选择 (1-{len(choices)})"
                + (f" [默认: {default}]" if default else "")
                + ": "
            )
            prompt = "\n".join(prompt_parts)
        else:
            prompt = f"\n{ANSI['bold']}{question}{ANSI['reset']}\n> "

        # 非交互模式降级
        if not sys.stdin.isatty():
            if default:
                return default
            if choices:
                return choices[0]
            return ""

        try:
            response = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            response = ""

        if choices:
            try:
                idx = int(response) - 1
                if 0 <= idx < len(choices):
                    response = choices[idx]
            except ValueError:
                if default:
                    response = default
                elif response == "" and choices:
                    response = choices[0]

        self._history.append({
            "op": "ask",
            "question": question,
            "response": response,
            "ts": time.time(),
        })
        return response

    # ── track ───────────────────────────────────────

    def track(self, total: int, label: str = "评估中") -> ProgressTracker:
        """创建进度追踪器。

        Args:
            total: 总步骤数。
            label: 进度标签。

        Returns:
            ProgressTracker 实例，调用 .update() 更新进度。
        """
        tracker = ProgressTracker(total=total, label=label)

        # 非终端模式不打印进度条
        if not sys.stdout.isatty():
            tracker._render = lambda: ""  # type: ignore[method-assign]

        self._history.append({
            "op": "track",
            "total": total,
            "label": label,
            "ts": time.time(),
        })
        return tracker

    # ── confirm ─────────────────────────────────────

    def confirm(self, action: str, details: str = "") -> bool:
        """确认操作。

        例如：确认保存基线、确认删除等。

        Args:
            action: 操作描述。
            details: 补充详情。

        Returns:
            True 如果用户确认。
        """
        msg = (
            f"\n{ANSI['yellow']}{ANSI['bold']}⚠ 确认操作{ANSI['reset']}\n"
            f"  {action}\n"
        )
        if details:
            msg += f"  {ANSI['dim']}{details}{ANSI['reset']}\n"
        msg += f"\n确认？[y/N] "

        # 非交互模式默认不确认
        if not sys.stdin.isatty():
            return False

        try:
            response = input(msg).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False

        confirmed = response in ("y", "yes", "是")
        self._history.append({
            "op": "confirm",
            "action": action,
            "confirmed": confirmed,
            "ts": time.time(),
        })
        return confirmed

    # ── 便捷：批量评估 ──────────────────────────────

    def run_evaluation_pipeline(
        self,
        queries: list[dict],
        vector_retriever,
        bm25_retriever=None,
        *,
        check_baseline: bool = True,
    ) -> str:
        """运行完整评估流水线。

        一键执行：向量评估 → BM25 评估 → 对比 → 逐 query → 基线检查。

        Args:
            queries: eval_queries.yaml 中的查询列表。
            vector_retriever: 向量检索器。
            bm25_retriever: BM25 检索器（可选）。
            check_baseline: 是否检查基线。

        Returns:
            完整报告字符串。
        """
        from .eval_metrics import evaluate_all

        # Phase 1: 向量检索
        tracker = self.track(len(queries), "向量检索评估")
        vector_results = evaluate_all(queries, vector_retriever)
        tracker.update(len(queries))
        print(tracker.done())

        # Phase 2: BM25 检索（可选）
        bm25_results = None
        if bm25_retriever:
            tracker = self.track(len(queries), "BM25 检索评估")
            bm25_results = evaluate_all(queries, bm25_retriever)
            tracker.update(len(queries))
            print(tracker.done())

        # Phase 3: 渲染报告
        report = self.output.render_full_report(
            vector_results=vector_results,
            bm25_results=bm25_results,
            check_baseline=check_baseline,
        )

        self._history.append({
            "op": "pipeline",
            "vector_mode": getattr(vector_retriever, "mode", "?"),
            "bm25_mode": getattr(bm25_retriever, "mode", "?") if bm25_retriever else None,
            "queries": len(queries),
            "ts": time.time(),
        })

        return report

    # ── 历史 ────────────────────────────────────────

    @property
    def history(self) -> list[dict[str, Any]]:
        """操作历史（最近 100 条）。"""
        return self._history[-100:]

    def clear_history(self) -> None:
        """清空操作历史。"""
        self._history.clear()


# ── 便捷函数 ─────────────────────────────────────────

def create_notebook(
    backend: RenderBackend | None = None,
) -> NotebookHandler:
    """创建 NotebookHandler 实例。

    >>> nb = create_notebook()
    >>> nb.display(results)
    """
    return NotebookHandler(backend=backend or detect_output_backend())
