"""
交互式输出组件 — 评估结果的可视化 Widget。

支持三种渲染后端：
- terminal: ANSI 颜色 + Unicode 表格边框
- html:     HTML/CSS（供 Jupyter / Web 前端使用）
- text:     纯文本（降级 fallback）

Widget 类型：
- MetricsTable:     指标汇总表（Recall@k / MRR / Hit@k / NDCG@k）
- ComparisonView:   向量 vs BM25 对比视图
- PerQueryDetail:   逐 query 详情（可展开）
- BaselineDiff:     基线回归差异视图
- SummaryCard:      评估概览卡片
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

# ── 配色方案 ─────────────────────────────────────────

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "bg_red": "\033[41m",
    "bg_green": "\033[42m",
    "bg_yellow": "\033[43m",
}

RenderBackend = Literal["terminal", "html", "text"]


# ── 工具函数 ─────────────────────────────────────────

def _bar(value: float, width: int = 20, max_val: float = 1.0) -> str:
    """生成比例条。"""
    filled = int(min(value / max_val, 1.0) * width)
    if value >= 0.8:
        color = ANSI["green"]
    elif value >= 0.5:
        color = ANSI["yellow"]
    else:
        color = ANSI["red"]
    bar = "█" * filled + "░" * (width - filled)
    return f"{color}{bar}{ANSI['reset']}"


def _color_value(value: float, thresholds: tuple[float, float] = (0.5, 0.8)) -> str:
    """根据阈值着色数值。"""
    if value >= thresholds[1]:
        return f"{ANSI['green']}{value:.3f}{ANSI['reset']}"
    elif value >= thresholds[0]:
        return f"{ANSI['yellow']}{value:.3f}{ANSI['reset']}"
    else:
        return f"{ANSI['red']}{value:.3f}{ANSI['reset']}"


def _delta_str(current: float, baseline: float) -> str:
    """差异字符串（带符号和颜色）。"""
    delta = current - baseline
    if delta >= 0.01:
        return f"{ANSI['green']}+{delta:.3f}{ANSI['reset']}"
    elif delta >= -0.01:
        return f" {delta:.3f}"
    else:
        return f"{ANSI['red']}{delta:.3f}{ANSI['reset']}"


# ── Widget 基类 ──────────────────────────────────────

@dataclass
class Widget:
    """所有 Widget 的基类。"""

    backend: RenderBackend = "terminal"

    def render(self) -> str:
        """渲染为本后端格式。"""
        raise NotImplementedError

    def supports_backend(self, backend: RenderBackend) -> bool:
        """检查是否支持某后端。"""
        return True  # 默认全部支持


# ── 指标汇总表 ───────────────────────────────────────

@dataclass
class MetricsTable(Widget):
    """检索指标汇总表。

    展示 Recall@1/3/5/10, MRR, Hit@1/3, NDCG@5/10, Precision@5。
    支持按维度分组（by_difficulty, by_rule_type）。
    """

    title: str = "检索质量评估"
    summary: dict[str, float] = field(default_factory=dict)
    by_difficulty: dict[str, dict[str, float]] = field(default_factory=dict)
    by_rule_type: dict[str, dict[str, float]] = field(default_factory=dict)
    retriever_mode: str = "unknown"

    def render(self) -> str:
        if self.backend == "text":
            return self._render_text()
        return self._render_terminal()

    def _render_terminal(self) -> str:
        lines: list[str] = []
        lines.append(f"\n{ANSI['bold']}{'═' * 60}{ANSI['reset']}")
        lines.append(f"{ANSI['bold']}{ANSI['cyan']}  {self.title}{ANSI['reset']}")
        lines.append(f"  模式: {ANSI['magenta']}{self.retriever_mode}{ANSI['reset']}")
        lines.append(f"{ANSI['bold']}{'═' * 60}{ANSI['reset']}\n")

        # 主指标
        main_metrics = ["recall@5", "recall@10", "mrr", "hit@1", "ndcg@5"]
        lines.append(f"  {'指标':<14} {'数值':>8}   {'比例条'}")
        lines.append(f"  {'─' * 14} {'─' * 8}   {'─' * 22}")
        for m in main_metrics:
            val = self.summary.get(m, 0.0)
            bar = _bar(val)
            cv = _color_value(val)
            lines.append(f"  {m:<14} {cv:>16}   {bar}")
        lines.append("")

        # 按难度
        if self.by_difficulty:
            lines.append(f"  {ANSI['bold']}按难度分组:{ANSI['reset']}")
            for diff in ["easy", "medium", "hard"]:
                if diff in self.by_difficulty:
                    d = self.by_difficulty[diff]
                    rec5 = d.get("recall@5", 0.0)
                    lines.append(
                        f"    {diff:<8} recall@5={_color_value(rec5)}  "
                        f"mrr={_color_value(d.get('mrr', 0.0))}  "
                        f"ndcg@5={_color_value(d.get('ndcg@5', 0.0))}"
                    )
            lines.append("")

        # 按 rule_type
        if self.by_rule_type:
            lines.append(f"  {ANSI['bold']}按规则类型分组:{ANSI['reset']}")
            for rt, d in self.by_rule_type.items():
                rec5 = d.get("recall@5", 0.0)
                lines.append(
                    f"    {rt:<12} recall@5={_color_value(rec5)}  "
                    f"mrr={_color_value(d.get('mrr', 0.0))}"
                )

        lines.append(f"\n{ANSI['bold']}{'═' * 60}{ANSI['reset']}")
        return "\n".join(lines)

    def _render_text(self) -> str:
        lines = [f"\n{'=' * 60}", f"  {self.title}  [{self.retriever_mode}]", f"{'=' * 60}"]
        for m in ["recall@5", "recall@10", "mrr", "hit@1", "ndcg@5"]:
            val = self.summary.get(m, 0.0)
            lines.append(f"  {m:<14} {val:.3f}")
        return "\n".join(lines)


# ── 对比视图 ─────────────────────────────────────────

@dataclass
class ComparisonView(Widget):
    """向量 vs BM25 对比视图。

    并排展示两种检索模式的指标差异。
    """

    left_label: str = "向量检索"
    right_label: str = "BM25 检索"
    left_summary: dict[str, float] = field(default_factory=dict)
    right_summary: dict[str, float] = field(default_factory=dict)

    def render(self) -> str:
        if self.backend == "text":
            return self._render_text()
        return self._render_terminal()

    def _render_terminal(self) -> str:
        lines: list[str] = []
        lines.append(f"\n{ANSI['bold']}{'═' * 70}{ANSI['reset']}")
        lines.append(
            f"{ANSI['bold']}{ANSI['cyan']}  {self.left_label}  vs  {self.right_label}"
            f"{ANSI['reset']}"
        )
        lines.append(f"{'═' * 70}\n")

        metrics = ["recall@5", "recall@10", "mrr", "hit@1", "ndcg@5", "ndcg@10"]
        lines.append(
            f"  {'指标':<14} {self.left_label:>10} {self.right_label:>10} {'差异':>10}  {'胜出'}"
        )
        lines.append(f"  {'─' * 14} {'─' * 10} {'─' * 10} {'─' * 10}  {'─' * 6}")

        for m in metrics:
            lv = self.left_summary.get(m, 0.0)
            rv = self.right_summary.get(m, 0.0)
            delta = lv - rv
            winner = (
                f"{ANSI['blue']}← 向量{ANSI['reset']}" if delta > 0.01
                else f"{ANSI['magenta']}BM25 →{ANSI['reset']}" if delta < -0.01
                else "≈ 持平"
            )
            lines.append(
                f"  {m:<14} {lv:>10.3f} {rv:>10.3f} "
                f"{_delta_str(lv, rv):>16}  {winner}"
            )

        lines.append(f"\n{'═' * 70}")
        return "\n".join(lines)

    def _render_text(self) -> str:
        lines = [f"\n{'=' * 60}", f"  {self.left_label}  vs  {self.right_label}"]
        for m in ["recall@5", "mrr", "hit@1", "ndcg@5"]:
            lv = self.left_summary.get(m, 0.0)
            rv = self.right_summary.get(m, 0.0)
            lines.append(f"  {m:<14} L={lv:.3f}  R={rv:.3f}  Δ={lv - rv:+.3f}")
        return "\n".join(lines)


# ── 逐 Query 详情 ───────────────────────────────────

@dataclass
class PerQueryDetail(Widget):
    """逐查询详情视图。

    展示每个 query 的完整指标，支持按排序/筛选。
    """

    per_query: list[dict[str, Any]] = field(default_factory=list)
    sort_by: str = "recall@5"
    ascending: bool = True
    highlight_below: float = 0.3  # 低于此值高亮警告

    def render(self) -> str:
        if self.backend == "text":
            return self._render_text()
        return self._render_terminal()

    def _render_terminal(self) -> str:
        sorted_q = sorted(
            self.per_query,
            key=lambda r: r.get(self.sort_by, 0.0),
            reverse=not self.ascending,
        )

        lines: list[str] = []
        lines.append(f"\n{ANSI['bold']}逐 Query 详情 (按 {self.sort_by} 排序){ANSI['reset']}")
        lines.append(
            f"  {'ID':<6} {'难度':<8} {'类型':<10} "
            f"{'R@5':>6} {'MRR':>6} {'H@1':>6} {'N@5':>6}  {'问题'}"
        )
        lines.append(f"  {'─' * 6} {'─' * 8} {'─' * 10} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 6}  {'─' * 28}")

        for r in sorted_q:
            rec5 = r.get("recall@5", 0.0)
            warn = rec5 < self.highlight_below
            prefix = f"{ANSI['bg_red']}" if warn else ""

            q_text = r.get("question", "")[:28]
            lines.append(
                f"  {r['id']:<6} {r.get('difficulty', '?'):<8} "
                f"{r.get('rule_type', '?'):<10} "
                f"{_color_value(rec5):>16} "
                f"{_color_value(r.get('mrr', 0.0)):>16} "
                f"{_color_value(r.get('hit@1', 0.0)):>16} "
                f"{_color_value(r.get('ndcg@5', 0.0)):>16}  "
                f"{prefix}{q_text}{ANSI['reset'] if warn else ''}"
            )

        # 统计
        low_count = sum(1 for r in sorted_q if r.get("recall@5", 0.0) < self.highlight_below)
        if low_count:
            lines.append(
                f"\n  {ANSI['yellow']}⚠ {low_count} 个 query 的 Recall@5 < "
                f"{self.highlight_below}{ANSI['reset']}"
            )

        return "\n".join(lines)

    def _render_text(self) -> str:
        lines = [f"\n逐 Query 详情:"]
        for r in self.per_query:
            lines.append(
                f"  {r['id']} {r.get('difficulty','?'):8} "
                f"R@5={r.get('recall@5',0):.2f} MRR={r.get('mrr',0):.2f} "
                f"H@1={r.get('hit@1',0):.2f} | {r.get('question','')[:40]}"
            )
        return "\n".join(lines)


# ── 基线差异视图 ─────────────────────────────────────

@dataclass
class BaselineDiff(Widget):
    """基线回归差异视图。

    对比当前结果与保存的基线，高亮退化指标。
    """

    current_summary: dict[str, float] = field(default_factory=dict)
    baseline_summary: dict[str, float] = field(default_factory=dict)
    tolerance: float = 0.05  # 容忍阈值

    def render(self) -> str:
        if self.backend == "text":
            return self._render_text()
        return self._render_terminal()

    def _render_terminal(self) -> str:
        metrics = ["recall@5", "recall@10", "mrr", "hit@1", "ndcg@5"]
        regressions = 0

        lines: list[str] = []
        lines.append(f"\n{ANSI['bold']}基线回归检查 (容忍 ±{self.tolerance}){ANSI['reset']}")
        lines.append(f"  {'指标':<14} {'基线':>8} {'当前':>8} {'差异':>10}  {'状态'}")
        lines.append(f"  {'─' * 14} {'─' * 8} {'─' * 8} {'─' * 10}  {'─' * 8}")

        for m in metrics:
            baseline = self.baseline_summary.get(m, 0.0)
            current = self.current_summary.get(m, 0.0)
            delta = current - baseline

            if delta >= -self.tolerance:
                status = f"{ANSI['green']}✓ 通过{ANSI['reset']}"
            else:
                status = f"{ANSI['red']}✗ 退化{ANSI['reset']}"
                regressions += 1

            lines.append(
                f"  {m:<14} {baseline:>8.3f} {current:>8.3f} "
                f"{_delta_str(current, baseline):>16}  {status}"
            )

        if regressions == 0:
            lines.append(f"\n  {ANSI['green']}{ANSI['bold']}✓ 全部指标通过回归检查{ANSI['reset']}")
        else:
            lines.append(
                f"\n  {ANSI['red']}{ANSI['bold']}✗ {regressions} 个指标出现退化{ANSI['reset']}"
            )

        return "\n".join(lines)

    def _render_text(self) -> str:
        lines = [f"\n基线回归检查:"]
        for m in ["recall@5", "mrr", "ndcg@5"]:
            b = self.baseline_summary.get(m, 0.0)
            c = self.current_summary.get(m, 0.0)
            status = "PASS" if c >= b - self.tolerance else "REGRESSION"
            lines.append(f"  {m}: baseline={b:.3f} current={c:.3f} {status}")
        return "\n".join(lines)


# ── 评估概览卡片 ─────────────────────────────────────

@dataclass
class SummaryCard(Widget):
    """评估概览卡片 — 顶部摘要。

    一行显示：总 query 数、通过数、平均 Recall@5、MRR、模式。
    """

    total_queries: int = 0
    avg_recall_at_5: float = 0.0
    avg_mrr: float = 0.0
    avg_ndcg_at_5: float = 0.0
    retriever_mode: str = "unknown"
    passed_count: int = 0

    def render(self) -> str:
        if self.backend == "text":
            return (
                f"[{self.retriever_mode}] queries={self.total_queries} "
                f"R@5={self.avg_recall_at_5:.2f} MRR={self.avg_mrr:.2f} "
                f"NDCG@5={self.avg_ndcg_at_5:.2f} passed={self.passed_count}"
            )

        r5_color = (
            ANSI["green"] if self.avg_recall_at_5 >= 0.5
            else ANSI["yellow"] if self.avg_recall_at_5 >= 0.3
            else ANSI["red"]
        )
        return (
            f"{ANSI['bold']}┌{'─' * 58}┐{ANSI['reset']}\n"
            f"{ANSI['bold']}│{ANSI['reset']} "
            f"模式: {ANSI['magenta']}{self.retriever_mode}{ANSI['reset']}  "
            f"查询: {ANSI['cyan']}{self.total_queries}{ANSI['reset']}  "
            f"通过: {ANSI['green']}{self.passed_count}{ANSI['reset']}"
            f"{' ' * (58 - 20 - len(self.retriever_mode) - len(str(self.total_queries)) - len(str(self.passed_count)))}"
            f"{ANSI['bold']}│{ANSI['reset']}\n"
            f"{ANSI['bold']}│{ANSI['reset']} "
            f"R@5={r5_color}{self.avg_recall_at_5:.3f}{ANSI['reset']}  "
            f"MRR={_color_value(self.avg_mrr)}  "
            f"NDCG@5={_color_value(self.avg_ndcg_at_5)}"
            f"{' ' * 20}"
            f"{ANSI['bold']}│{ANSI['reset']}\n"
            f"{ANSI['bold']}└{'─' * 58}┘{ANSI['reset']}"
        )


# ── Widget 注册表 ────────────────────────────────────

_WIDGET_REGISTRY: dict[str, type[Widget]] = {
    "metrics_table": MetricsTable,
    "comparison_view": ComparisonView,
    "per_query_detail": PerQueryDetail,
    "baseline_diff": BaselineDiff,
    "summary_card": SummaryCard,
}


def get_widget(name: str) -> type[Widget] | None:
    """获取已注册的 Widget 类。"""
    return _WIDGET_REGISTRY.get(name)


def register_widget(name: str, widget_cls: type[Widget]) -> None:
    """注册自定义 Widget。"""
    _WIDGET_REGISTRY[name] = widget_cls


def list_widgets() -> list[str]:
    """列出所有已注册的 Widget 名称。"""
    return list(_WIDGET_REGISTRY.keys())
