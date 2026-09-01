"""重复单元与单元归属修复测试（迭代 19 反思结论）。

复现缺陷（用户反馈）：
- 单元 n_hI9sUrj0uvBe（退休人员60%）knowledge 缺失、规则值错误。
- 根因：文档含「修改决定 + 修改后正文」两段逐字重复文本 → parse_kept_leaves
  保留两个相同 body 的叶子 → match_leaves 对同一 fact_text 返回 2 个 node_id
  → run_extraction 因「唯一匹配才填」→ unit_id 留空 → 全部 extraction 无归属。

修复目标：
1. parse_kept_leaves 去重时按 body 文本去重（重复段只保留正文路径叶子）。
2. match_leaves 多匹配时优先正文（第四章…）叶子。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
    _leaf_body,
    match_leaves,
    parse_kept_leaves,
)

DOCUMENT_TITLE = "关于修改《规定》的决定"
DOCUMENT_CONTENT = """二、第三十六条修改为：
（四）退休人员个人支付比例为职工支付比例的60%。
第四章 基本医疗保险待遇
第三十六条 在一个结算期内职工和退休人员发生的医疗费用，由基本医疗保险统筹基金和个人按比例分担：
（四）退休人员个人支付比例为职工支付比例的60%。
"""


def _load_document() -> tuple[str, str]:
    return DOCUMENT_CONTENT, DOCUMENT_TITLE


def test_kept_leaves_dedupes_identical_body_across_sections() -> None:
    """重复段（修改决定 + 正文）应只保留一个叶子，不再出现两个相同 body 的单元。"""
    content, title = _load_document()
    _root, _by, all_leaves, kept = parse_kept_leaves(content, title)

    # 统计 body 相同的重复组
    bodies: dict[str, list[str]] = {}
    for leaf in all_leaves:
        body = _leaf_body(leaf)
        bodies.setdefault(body, []).append(leaf.node_id)
    dup_groups = {b: ids for b, ids in bodies.items() if len(ids) > 1}
    assert dup_groups, "预期文档存在重复段（修改决定+正文）"
    # 修复后 kept 中相同 body 的多叶子：仅允许「正文段」重复（如一级/二级医院同比例），
    # 不允许「修改决定段」与正文重复（应只留正文版）。
    kept_bodies: dict[str, int] = {}
    for leaf in kept:
        kept_bodies[_leaf_body(leaf)] = kept_bodies.get(_leaf_body(leaf), 0) + 1
    duplicates_in_kept = {b: c for b, c in kept_bodies.items() if c > 1}
    for body, count in duplicates_in_kept.items():
        # 正文段相同 body 是合法内容（不同条款/子项下比例相同）；
        # 断言这些叶子全部来自正文路径（path 含「第X章」），无修改决定段残留。
        same = [lf for lf in kept if _leaf_body(lf) == body]
        assert len(same) == count
        assert all(
            any("第" in p and "章" in p for p in getattr(lf, "path", []) or [])
            for lf in same
        ), f"kept 中修改决定段重复残留: {body[:40]}"


def test_match_leaves_retiree_60_returns_single_main_text_unit() -> None:
    """「退休人员60%」fact 应唯一匹配正文单元 n_hI9sUrj0uvBe（不再返回 2 个）。"""
    content, title = _load_document()
    _root, _by, _all, kept = parse_kept_leaves(content, title)

    matched = match_leaves("（四）退休人员个人支付比例为职工支付比例的60%。", kept)
    assert len(matched) == 1, f"应唯一匹配，实际 {len(matched)}: {matched}"
    # 应匹配正文单元（path 含「第四章」），而非修改决定单元（path 含「二、…修改为」）
    matched_leaf = next(leaf for leaf in kept if leaf.node_id == matched[0])
    assert any("第四章" in part for part in matched_leaf.path)


def test_run_extraction_assigns_unit_id_for_retiree_fact() -> None:
    """run_extraction 对退休60% fact 应正确填 unit_id（不再留空）。"""
    from unittest.mock import MagicMock

    from src.knowledge_extension.rule_explanation.knowledge_build_models import (
        ExtractionOverride,
    )
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )
    from src.model_service.gateway import ModelGateway
    from src.model_service.models import ModelResponse, TokenUsage

    class _Store:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.document = {
                "doc_id": "doc_1",
                "title": "测试",
                "content_text": (
                    "第一条 退休人员个人支付比例为职工支付比例的60%。"
                ),
            }

        def get_document(self, doc_id: str):
            return self.document

        def update_document(self, doc_id: str, data):  # noqa: ARG002
            return None

        def delete_extractions_by_doc(self, doc_id: str) -> int:  # noqa: ARG002
            return 0

        def batch_create_extractions(self, items: list[dict]) -> int:
            self.created.extend(items)
            return len(items)

    store = _Store()
    orch = PipelineOrchestrator(store=store)

    def fake_generate(self, messages, model_type, scene, max_tokens=None, model_override=None):
        return ModelResponse(
            content='[{"fact_text": "退休人员个人支付比例为职工支付比例的60%。", "rules": []}]',
            model_name="m",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        )

    import src.model_service.gateway as gw

    original = gw.ModelGateway.generate
    gw.ModelGateway.generate = fake_generate  # type: ignore[method-assign]
    try:
        result = orch.run_extraction("doc_1")
    finally:
        gw.ModelGateway.generate = original  # type: ignore[method-assign]

    assert result["success"] is True
    assert len(store.created) == 1
    assert store.created[0]["unit_id"] != "", (
        f"unit_id 不应为空，实际: {store.created[0]!r}"
    )
