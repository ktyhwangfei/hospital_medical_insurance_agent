"""
检索评估 conftest — 提供 EvalRetriever fixture。

需要 pymilvus + 运行中的 Milvus 服务。
Milvus 不可用时 pytest skip 所有评估测试。
"""
import pytest


@pytest.fixture(scope="module")
def retriever():
    """创建 EvalRetriever（向量模式）。

    Milvus 必须运行在 127.0.0.1:19530。
    不可用时自动 skip。
    """
    try:
        from pymilvus import connections
        connections.connect(host="127.0.0.1", port="19530", timeout=5)
        connections.disconnect("default")
    except Exception as e:
        pytest.skip(f"Milvus 不可用: {e}")

    try:
        from src.tests.evaluation.eval_retriever import EvalRetriever
        return EvalRetriever(host="127.0.0.1", port="19530", mode="vector")
    except Exception as e:
        pytest.skip(f"EvalRetriever 初始化失败: {e}")


@pytest.fixture(scope="module")
def bm25_retriever():
    """创建 EvalRetriever（BM25 模式）。

    需要 rank_bm25 库（pip install rank-bm25）。
    不可用时自动 skip。
    """
    try:
        from pymilvus import connections
        connections.connect(host="127.0.0.1", port="19530", timeout=5)
        connections.disconnect("default")
    except Exception as e:
        pytest.skip(f"Milvus 不可用: {e}")

    try:
        import rank_bm25  # noqa: F401
    except ImportError:
        pytest.skip("rank-bm25 未安装 (pip install rank-bm25)")

    try:
        from src.tests.evaluation.eval_retriever import EvalRetriever
        return EvalRetriever(host="127.0.0.1", port="19530", mode="bm25")
    except Exception as e:
        pytest.skip(f"BM25 EvalRetriever 初始化失败: {e}")


@pytest.fixture(scope="module")
def queries():
    """加载 eval_queries.yaml。"""
    import yaml
    from pathlib import Path

    path = Path(__file__).parent / "eval_queries.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["queries"]


@pytest.fixture(scope="module")
def hybrid_results(retriever, bm25_retriever, queries):
    """RRF 融合评估（仅当向量 + BM25 都可用时）。"""
    from .eval_metrics import evaluate_hybrid
    return evaluate_hybrid(queries, retriever, bm25_retriever, top_k=10, rrf_k=60)
