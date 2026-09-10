"""政策表格条款解析测试 — #39 吸并 #24（借鉴 RagFlow 表格切片策略）。

覆盖：块识别 / 表头启发 / 网格对齐 / 单元格定位单元 / RagFlow 风格行组切片 /
leaf_match 单元格分层匹配 / run_extraction 引用定位到表格单元格。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
    collect_cell_units,
    match_cell_units,
    parse_kept_leaves,
)
from src.knowledge_extension.rule_explanation.policy_struct.table_parser import (
    build_cell_units,
    find_table_blocks,
    parse_table_block,
    slice_table_for_retrieval,
)

TABLE_DOC = """第十条 门诊起付标准和支付比例按下列标准执行：
医疗机构等级 | 起付标准（元） | 支付比例
一级及以下定点医疗机构 | 100 | 55%
二级及以上定点医疗机构 | 550 | 50%
第十一条 本办法自2026年1月1日起执行，有效期三年。
"""


# ── 块识别与网格解析 ──


def test_find_table_blocks_detects_consecutive_pipe_lines() -> None:
    lines = TABLE_DOC.split("\n")
    blocks = find_table_blocks(lines)
    assert blocks == [(1, 4)], f"应识别第 1-3 行为表格块，实际 {blocks}"


def test_lone_pipe_line_is_not_table() -> None:
    lines = ["正文里提到比例 | 但只有一行", "另一段正文"]
    assert find_table_blocks(lines) == []


def test_parse_table_block_splits_header_and_data_rows() -> None:
    lines = TABLE_DOC.split("\n")
    table = parse_table_block(lines, 1, 4)
    assert table.header == ["医疗机构等级", "起付标准（元）", "支付比例"]
    assert table.data_rows == [
        ["一级及以下定点医疗机构", "100", "55%"],
        ["二级及以上定点医疗机构", "550", "50%"],
    ]


def test_parse_table_block_pads_ragged_rows() -> None:
    # 合并单元格产生的参差行右侧补空对齐
    lines = ["项目 | 金额 | 备注", "甲 | 100", "乙 | 200 | 含附加"]
    table = parse_table_block(lines, 0, 3)
    assert all(len(r) == 3 for r in table.data_rows)
    assert table.data_rows[0] == ["甲", "100", ""]


def test_headerless_table_keeps_all_rows_as_data() -> None:
    # 首行数字占比高（全为金额）→ 不当表头
    lines = ["100 | 90%", "550 | 50%"]
    table = parse_table_block(lines, 0, 2)
    assert table.header == []
    assert len(table.data_rows) == 2


# ── 单元格定位单元 ──


def test_build_cell_units_emits_locators_with_headers() -> None:
    units = build_cell_units("n_test", TABLE_DOC.split("\n"))
    by_locator = {u.locator: u for u in units}
    cell = by_locator["n_test#r0c1"]
    assert cell.value == "100"
    assert cell.column_header == "起付标准（元）"
    assert cell.row_header == "一级及以下定点医疗机构"
    assert cell.row_text == "一级及以下定点医疗机构 | 100 | 55%"
    # 首列单元格的行表头即自身值
    assert by_locator["n_test#r0c0"].value == "一级及以下定点医疗机构"


def test_build_cell_units_skips_empty_cells() -> None:
    lines = ["项目 | 金额", "甲 | "]
    units = build_cell_units("n_x", lines)
    # 表头行不产单元；数据行空单元格跳过
    assert [u.locator for u in units] == ["n_x#r0c0"]


# ── RagFlow 风格行组切片 ──


def test_slice_table_repeats_header_per_slice() -> None:
    lines = ["等级 | 起付"] + [f"等级{i} | {i}00" for i in range(1, 8)]
    slices = slice_table_for_retrieval(lines, rows_per_slice=3)
    assert len(slices) == 3
    for s in slices:
        assert s["header"] == ["等级", "起付"], "每片必须重复表头上下文"
    assert slices[0]["rows"] == [["等级1", "100"], ["等级2", "200"], ["等级3", "300"]]
    assert slices[-1]["row_range"] == [6, 7]


def test_slice_table_carries_source_line_range() -> None:
    slices = slice_table_for_retrieval(TABLE_DOC.split("\n"))
    assert len(slices) == 1
    assert slices[0]["line_range"] == [1, 4]


# ── leaf_match 单元格分层匹配 ──


def _doc_units():
    _root, _by, _all, kept = parse_kept_leaves(TABLE_DOC, "测试政策")
    return kept, collect_cell_units(kept)


def test_combo_tier_locates_row_dimension_plus_value_cell() -> None:
    _kept, units = _doc_units()
    tier, hits = match_cell_units("一级及以下定点医疗机构起付标准为100元", units)
    assert tier == "combo"
    assert hits == [f"{hits[0].split('#')[0]}#r0c1"], "应命中起付标准列的值单元格"


def test_combo_tier_distinguishes_rows() -> None:
    _kept, units = _doc_units()
    tier, hits = match_cell_units("二级及以上定点医疗机构的支付比例为50%", units)
    assert tier == "combo"
    assert hits[0].endswith("#r1c2"), "应命中第二行支付比例单元格"


def test_unrelated_prose_gets_no_cell_match() -> None:
    _kept, units = _doc_units()
    tier, hits = match_cell_units("累计最高支付数额为3000元", units)
    assert tier == ""
    assert hits == []


def test_value_tier_falls_back_for_bare_value_fact() -> None:
    _kept, units = _doc_units()
    tier, hits = match_cell_units("门诊起付标准为550元", units)
    assert tier in ("value", "combo")
    assert hits[0].endswith("#r1c1"), "550 应定位到第二行起付标准单元格"


# ── run_extraction：引用定位到表格单元格 ──


def test_run_extraction_grounds_table_fact_to_cell_locator() -> None:
    """表格事实的 unit_id 应携带 #r{n}c{m} 单元格定位，不再只有条款级。"""
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )
    from src.model_service.models import ModelResponse, TokenUsage

    class _Store:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.document = {
                "doc_id": "doc_tbl_1",
                "title": "测试表格政策",
                "content_text": TABLE_DOC,
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

    def fake_generate(self, messages, model_type, scene, max_tokens=None, model_override=None):  # noqa: ARG001
        return ModelResponse(
            content='[{"fact_text": "一级及以下定点医疗机构起付标准为100元", "rules": []}]',
            model_name="m",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        )

    import src.model_service.gateway as gw

    original = gw.ModelGateway.generate
    gw.ModelGateway.generate = fake_generate  # type: ignore[method-assign]
    try:
        result = orch.run_extraction("doc_tbl_1")
    finally:
        gw.ModelGateway.generate = original  # type: ignore[method-assign]

    assert result["success"] is True
    assert len(store.created) == 1
    unit_id = store.created[0]["unit_id"]
    assert "#r" in unit_id and "c" in unit_id.split("#", 1)[1], (
        f"unit_id 应为单元格定位（#r{{n}}c{{m}}），实际: {unit_id!r}"
    )
    assert unit_id.endswith("#r0c1"), f"应命中第一行起付标准单元格，实际: {unit_id!r}"


def test_run_extraction_keeps_clause_grounding_for_prose_fact() -> None:
    """正文条款事实的 unit_id 保持条款级（无 # 定位符），不被表格值抢占。"""
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )
    from src.model_service.models import ModelResponse, TokenUsage

    class _Store:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.document = {
                "doc_id": "doc_tbl_2",
                "title": "测试表格政策",
                "content_text": TABLE_DOC,
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

    def fake_generate(self, messages, model_type, scene, max_tokens=None, model_override=None):  # noqa: ARG001
        return ModelResponse(
            content='[{"fact_text": "本办法自2026年1月1日起执行", "rules": []}]',
            model_name="m",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        )

    import src.model_service.gateway as gw

    original = gw.ModelGateway.generate
    gw.ModelGateway.generate = fake_generate  # type: ignore[method-assign]
    try:
        orch.run_extraction("doc_tbl_2")
    finally:
        gw.ModelGateway.generate = original  # type: ignore[method-assign]

    unit_id = store.created[0]["unit_id"]
    assert unit_id and "#" not in unit_id, (
        f"正文事实应保持条款级 unit_id，实际: {unit_id!r}"
    )
