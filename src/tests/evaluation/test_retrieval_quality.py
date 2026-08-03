"""
检索质量评估测试 — 需要 Milvus 运行。

覆盖：向量检索 + BM25 检索 两条基线。
Milvus 不可用时自动 skip。
首次运行在 baseline/ 目录生成基线。
"""

import json
import os
import pytest
from pathlib import Path
from .eval_metrics import evaluate_all

BASELINE_DIR = Path(__file__).parent / "baseline"
BASELINE_VECTOR_PATH = BASELINE_DIR / "baseline_vector_v1.json"
BASELINE_BM25_PATH = BASELINE_DIR / "baseline_bm25_v1.json"


# ── 向量检索质量 ─────────────────────────────────────

class TestVectorRetrievalQuality:
    """向量检索（bge-base-zh-v1.5, HNSW+COSINE）质量评估。"""

    def test_each_query_has_results(self, retriever, queries):
        """每个 query 至少返回 1 个结果。"""
        for q in queries:
            results = retriever.search(q["question"], top_k=10)
            assert len(results) > 0, (
                f"Q{q['id']} 返回空结果: '{q['question']}'"
            )

    def test_all_results_have_source(self, retriever, queries):
        """验证结果携带来源追溯（rule_id 或 doc_id）。"""
        for q in queries:
            results = retriever.search(q["question"], top_k=10)
            for hit in results:
                entity = hit.entity
                has_source = entity.get("rule_id") or entity.get("doc_id") or entity.get("fact_id")
                assert has_source, (
                    f"Q{q['id']} 结果缺少来源追溯: entity={entity}"
                )

    def test_recall_at_5_minimum(self, retriever, queries):
        """Recall@5 整体均值 ≥ 0.50（宽松标注下基本门槛）。"""
        results = evaluate_all(queries, retriever)
        avg_recall = results["summary"]["recall@5"]
        per_query_detail = "\n".join(
            f"  {r['id']}: recall@5={r['recall@5']:.2f} mrr={r['mrr']:.2f} "
            f"results={r['result_count']}"
            for r in results["per_query"]
        )
        assert avg_recall >= 0.50, (
            f"Recall@5 均值 {avg_recall:.2f} 低于门槛 0.50\n{per_query_detail}"
        )

    def test_mrr_minimum(self, retriever, queries):
        """MRR 整体均值 ≥ 0.30。"""
        results = evaluate_all(queries, retriever)
        avg_mrr = results["summary"]["mrr"]
        assert avg_mrr >= 0.30, (
            f"MRR 均值 {avg_mrr:.2f} 低于门槛 0.30"
        )

    def test_hit_at_1_minimum(self, retriever, queries):
        """Hit@1 整体均值 ≥ 0.40。"""
        results = evaluate_all(queries, retriever)
        avg_hit1 = results["summary"]["hit@1"]
        assert avg_hit1 >= 0.40, (
            f"Hit@1 均值 {avg_hit1:.2f} 低于门槛 0.40"
        )

    def test_ndcg_at_5_minimum(self, retriever, queries):
        """NDCG@5 整体均值 ≥ 0.40。"""
        results = evaluate_all(queries, retriever)
        avg_ndcg = results["summary"]["ndcg@5"]
        assert avg_ndcg >= 0.40, (
            f"NDCG@5 均值 {avg_ndcg:.2f} 低于门槛 0.40"
        )

    def test_save_baseline(self, retriever, queries):
        """--eval-save-baseline 时保存本轮结果为基线。"""
        if not os.environ.get("EVAL_SAVE_BASELINE"):
            pytest.skip("设置 EVAL_SAVE_BASELINE=1 以保存基线")

        results = evaluate_all(queries, retriever)
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        BASELINE_VECTOR_PATH.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"向量基线已保存: {BASELINE_VECTOR_PATH}")


# ── BM25 检索质量 ────────────────────────────────────

class TestBM25RetrievalQuality:
    """BM25 检索（rank_bm25 Okapi, jieba 分词）质量评估。"""

    def test_each_query_has_results(self, bm25_retriever, queries):
        """每个 query 至少返回 1 个结果。"""
        for q in queries:
            results = bm25_retriever.search(q["question"], top_k=10)
            assert len(results) > 0, (
                f"Q{q['id']} 返回空结果: '{q['question']}'"
            )

    def test_recall_at_5_minimum(self, bm25_retriever, queries):
        """BM25 Recall@5 整体均值 ≥ 0.30（关键词检索天然弱于语义检索）。"""
        results = evaluate_all(queries, bm25_retriever)
        avg_recall = results["summary"]["recall@5"]
        per_query_detail = "\n".join(
            f"  {r['id']}: recall@5={r['recall@5']:.2f} mrr={r['mrr']:.2f}"
            for r in results["per_query"]
        )
        assert avg_recall >= 0.30, (
            f"BM25 Recall@5 均值 {avg_recall:.2f} 低于门槛 0.30\n{per_query_detail}"
        )

    def test_save_baseline(self, bm25_retriever, queries):
        """保存 BM25 基线。"""
        if not os.environ.get("EVAL_SAVE_BASELINE"):
            pytest.skip("设置 EVAL_SAVE_BASELINE=1 以保存基线")

        results = evaluate_all(queries, bm25_retriever)
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        BASELINE_BM25_PATH.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"BM25 基线已保存: {BASELINE_BM25_PATH}")


# ── 检索对比 ─────────────────────────────────────────

class TestRetrievalComparison:
    """向量 vs BM25 vs RRF 混合 对比评估。"""

    def test_vector_vs_bm25_summary(self, retriever, bm25_retriever, queries):
        """输出两种检索模式的对比汇总。"""
        vec_results = evaluate_all(queries, retriever)
        bm25_results = evaluate_all(queries, bm25_retriever)

        from .output_handler import OutputHandler
        handler = OutputHandler()
        print(handler.render_comparison(vec_results, bm25_results))

        assert True  # always pass, informational only

    def test_hybrid_rrf_quality(self, retriever, bm25_retriever, queries):
        """RRF 融合检索整体均值 ≥ 0.35（宽松标注下门槛）。"""
        from .eval_metrics import evaluate_hybrid
        results = evaluate_hybrid(queries, retriever, bm25_retriever,
                                  top_k=10, rrf_k=60)
        avg_recall = results["summary"]["recall@5"]
        avg_mrr = results["summary"]["mrr"]
        per_query_detail = "\n".join(
            f"  {r['id']}: recall@5={r['recall@5']:.2f} mrr={r['mrr']:.2f}"
            for r in results["per_query"]
        )
        print(f"\n[Hybrid RRF] Recall@5={avg_recall:.3f} MRR={avg_mrr:.3f}")
        print(per_query_detail)
        assert avg_recall >= 0.35, (
            f"RRF Recall@5 均值 {avg_recall:.2f} 低于门槛 0.35\n{per_query_detail}"
        )

    def test_hybrid_vs_vector_comparison(self, retriever, bm25_retriever, queries):
        """对比展示：向量 / BM25 / RRF 三项指标。

        输出三者并排比较表，无硬断言（信息性测试）。
        """
        from .eval_metrics import evaluate_all, evaluate_hybrid

        vec = evaluate_all(queries, retriever)
        bm25 = evaluate_all(queries, bm25_retriever)
        hybrid = evaluate_hybrid(queries, retriever, bm25_retriever)

        metrics = ["recall@5", "mrr", "hit@1", "ndcg@5", "map@10"]
        print("\n" + "=" * 68)
        print(f"{'Metric':<14} {'Vector':>10} {'BM25':>10} {'Hybrid(RRF)':>14} {'Best':>10}")
        print("-" * 68)
        for m in metrics:
            v = vec["summary"][m]
            b = bm25["summary"][m]
            h = hybrid["summary"][m]
            best = max(v, b, h)
            best_label = ("vector" if v == best else "bm25" if b == best else "hybrid")
            print(f"{m:<14} {v:>10.4f} {b:>10.4f} {h:>14.4f} {best_label:>10}")
        print("=" * 68)
        assert True

    def test_notebook_mode_report(self, retriever, bm25_retriever, queries):
        """Notebook 模式：完整评估报告（Widget 渲染）。"""
        from .notebook_handler import NotebookHandler
        nb = NotebookHandler()
        report = nb.run_evaluation_pipeline(
            queries=queries,
            vector_retriever=retriever,
            bm25_retriever=bm25_retriever,
            check_baseline=False,  # 首次运行无基线
        )
        print(report)
        assert True


# ── Widget 直测 ──────────────────────────────────────

class TestWidgetsDirect:
    """Widget 组件直测 — 不依赖 Milvus。"""

    def test_metrics_table_terminal(self):
        """终端模式下 MetricsTable 正常渲染。"""
        from .custom_widgets import MetricsTable
        w = MetricsTable(
            backend="terminal",
            title="测试",
            summary={"recall@5": 0.75, "mrr": 0.60, "hit@1": 0.50, "ndcg@5": 0.65},
            retriever_mode="vector",
        )
        out = w.render()
        assert "recall@5" in out
        assert "0.750" in out
        print(out)

    def test_comparison_view_terminal(self):
        """终端模式下 ComparisonView 正常渲染。"""
        from .custom_widgets import ComparisonView
        w = ComparisonView(
            backend="terminal",
            left_summary={"recall@5": 0.75, "mrr": 0.60},
            right_summary={"recall@5": 0.45, "mrr": 0.35},
        )
        out = w.render()
        assert "recall@5" in out
        assert "向量" in out
        print(out)

    def test_baseline_diff_terminal(self):
        """终端模式下 BaselineDiff 正常渲染。"""
        from .custom_widgets import BaselineDiff
        w = BaselineDiff(
            backend="terminal",
            current_summary={"recall@5": 0.72, "mrr": 0.58},
            baseline_summary={"recall@5": 0.75, "mrr": 0.60},
        )
        out = w.render()
        assert "退化" in out or "通过" in out
        print(out)

    def test_summary_card_terminal(self):
        """终端模式下 SummaryCard 正常渲染。"""
        from .custom_widgets import SummaryCard
        w = SummaryCard(
            backend="terminal",
            total_queries=50,
            avg_recall_at_5=0.75,
            avg_mrr=0.60,
            avg_ndcg_at_5=0.65,
            retriever_mode="vector",
            passed_count=42,
        )
        out = w.render()
        assert "vector" in out
        print(out)

    def test_output_handler_full_report(self, retriever, bm25_retriever, queries):
        """OutputHandler 完整报告渲染。"""
        from .output_handler import OutputHandler
        from .eval_metrics import evaluate_all

        vec_results = evaluate_all(queries, retriever)
        bm25_results = evaluate_all(queries, bm25_retriever)

        handler = OutputHandler(backend="terminal")
        report = handler.render_full_report(vec_results, bm25_results)
        assert "recall@5" in report
        print(report)

    def test_notebook_display_and_ask(self):
        """NotebookHandler display + ask 原语。"""
        from .notebook_handler import NotebookHandler
        nb = NotebookHandler(backend="text")

        # display
        out = nb.display({"summary": {"recall@5": 0.8, "mrr": 0.7}, "per_query": []})
        assert "recall@5" in out

        # ask (非交互模式降级)
        result = nb.ask("选择查询", choices=["Q001", "Q002"], default="Q001")
        assert result == "Q001"


# ── 回归测试 ─────────────────────────────────────────

class TestRetrievalRegression:
    """与基线对比 — 防止检索质量退化。"""

    def test_vector_no_regression_vs_baseline(self, retriever, queries):
        """当前向量检索指标不低于基线 - 0.05。"""
        if not BASELINE_VECTOR_PATH.exists():
            pytest.skip(f"基线不存在 ({BASELINE_VECTOR_PATH})，先运行 --eval-save-baseline")

        baseline = json.loads(BASELINE_VECTOR_PATH.read_text(encoding="utf-8"))
        current = evaluate_all(queries, retriever)

        for metric in ["recall@5", "mrr", "hit@1", "ndcg@5"]:
            current_val = current["summary"].get(metric, 0)
            baseline_val = baseline["summary"].get(metric, 0)
            assert current_val >= baseline_val - 0.05, (
                f"向量 {metric} 退化: baseline={baseline_val:.3f} → "
                f"current={current_val:.3f}"
            )

    def test_bm25_no_regression_vs_baseline(self, bm25_retriever, queries):
        """当前 BM25 检索指标不低于基线 - 0.05。"""
        if not BASELINE_BM25_PATH.exists():
            pytest.skip(f"基线不存在 ({BASELINE_BM25_PATH})，先运行 --eval-save-baseline")

        baseline = json.loads(BASELINE_BM25_PATH.read_text(encoding="utf-8"))
        current = evaluate_all(queries, bm25_retriever)

        for metric in ["recall@5", "mrr", "hit@1", "ndcg@5"]:
            current_val = current["summary"].get(metric, 0)
            baseline_val = baseline["summary"].get(metric, 0)
            assert current_val >= baseline_val - 0.05, (
                f"BM25 {metric} 退化: baseline={baseline_val:.3f} → "
                f"current={current_val:.3f}"
            )
