"""Issue #19：单元医疗类别确定性分类 + 规则继承。

验证：
- classify_med_type：长别名优先、单元原文优先于祖先语境、无命中回退「通用」
- normalize_med_type_value：别名归一到政策标准值，未知名原样返回
- apply_unit_med_type：规则空值继承单元分类、已有值归一不覆盖
- 提取 intake（extract_document / extract_single）：规则 med_type 回填 +
  单元分类落 extracted_fields.unit_med_type，S5 快照可按医疗类别分组
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.knowledge_extension.rule_explanation.policy_extract.med_type_classifier import (
    FALLBACK_MED_TYPE,
    apply_unit_med_type,
    classify_med_type,
    normalize_med_type_value,
)


# ── 纯函数分类器 ──────────────────────────────────────────────

def test_classify_longest_alias_wins():
    assert classify_med_type("急诊留观费用按规定报销") == "急诊留观"
    assert classify_med_type("门特待遇标准如下") == "门诊特殊病"


def test_classify_unit_text_precedes_ancestor_context():
    # 单元原文说门诊，上级章节说住院 → 门诊（就近原则）
    assert classify_med_type("门诊起付标准为1800元", "第三章 住院治疗管理") == "门诊"


def test_classify_falls_back_to_general():
    assert classify_med_type("基本医疗保险费的征缴") == FALLBACK_MED_TYPE
    assert classify_med_type("", "") == FALLBACK_MED_TYPE


def test_normalize_med_type_value():
    assert normalize_med_type_value("门特") == "门诊特殊病"
    assert normalize_med_type_value(" 住院 ") == "住院"
    assert normalize_med_type_value("住院-普通住院") == "住院-普通住院"  # 未知名原样
    assert normalize_med_type_value("") == ""


def test_apply_unit_med_type_backfills_empty_and_keeps_existing():
    rules = [
        {"med_type": ""},                      # 空 → 继承单元分类
        {"med_type": "门特"},                  # 已有别名 → 归一
        {"med_type": "急诊抢救"},              # 已有标准值 → 不被单元值覆盖
        {"confidence": 0.9},                   # 无键 → 补单元分类
        "not-a-dict",                          # 非法项跳过
    ]
    apply_unit_med_type(rules, "住院")
    assert rules[0]["med_type"] == "住院"
    assert rules[1]["med_type"] == "门诊特殊病"
    assert rules[2]["med_type"] == "急诊抢救"
    assert rules[3]["med_type"] == "住院"
    assert rules[4] == "not-a-dict"


# ── 提取 intake 集成 ─────────────────────────────────────────

class _Store:
    """最小 PipelineStore 桩（沿用 test_pipeline_unknown_concepts 模式）。"""

    def __init__(self, content_text: str):
        self.doc = {
            "doc_id": "doc_1",
            "title": "医保政策",
            "content_text": content_text,
        }
        self.extractions: dict[str, dict] = {}
        self._lock = threading.RLock()

    def get_document(self, doc_id):
        return self.doc if doc_id == "doc_1" else None

    def claim_extraction_run(self, doc_id, run_token):
        self.doc.update({"status": "processing", "extraction_run_token": run_token})
        return True

    @contextmanager
    def commit_extraction_run(self, doc_id, run_token):
        yield self.doc.get("extraction_run_token") == run_token

    def is_extraction_run_current(self, doc_id, run_token):
        return self.doc.get("extraction_run_token") == run_token

    def finish_extraction_run(self, doc_id, run_token, data):
        if self.doc.get("extraction_run_token") != run_token:
            return False
        self.doc.update(data)
        return True

    def list_extractions(self, page=1, page_size=20, doc_id="", status=""):
        items = [
            item for item in self.extractions.values()
            if (not doc_id or item["doc_id"] == doc_id)
            and (item["status"] == status if status else item["status"] != "archived")
        ]
        return {"items": items, "total": len(items), "page": page, "page_size": page_size}

    def batch_create_extractions(self, items):
        for item in items:
            self.extractions[item["extraction_id"]] = {**item, "status": "draft"}
        return len(items)

    def reconcile_extractions(self, doc_id, items, run_token=None):
        if run_token and self.doc.get("extraction_run_token") != run_token:
            return None
        self.batch_create_extractions(items)
        return len(items)


class _Alignment:
    """S5 对齐桩：捕获冲突报告即可。"""

    def __init__(self):
        self.reports = []

    def intake_signal(self, signal):
        pass

    def intake_conflict_report(self, report, **context):
        self.reports.append(report)


def test_extract_document_backfills_med_type_from_unit(monkeypatch):
    """全文提取：规则 med_type 为空时继承单元医疗类别，并落 unit_med_type。"""
    content = "第一条 住院报销比例为85%。"
    store = _Store(content)
    alignment = _Alignment()
    orch = PipelineOrchestrator(store=store, alignment_service=alignment)
    monkeypatch.setattr(
        orch,
        "_extract_policy_facts",
        lambda *a, **k: [{
            "fact_text": "住院报销比例为85%。",
            "rules": [{"confidence": 0.9, "payment_ratio": "85%"}],
        }],
    )
    result = orch.run_extraction("doc_1")
    assert result["success"] is True

    items = store.list_extractions(doc_id="doc_1")["items"]
    assert len(items) == 1
    fields = items[0]["extracted_fields"]
    assert fields["unit_med_type"] == "住院"
    assert fields["rules"][0]["med_type"] == "住院"


def test_extract_document_keeps_and_normalizes_existing_med_type(monkeypatch):
    """全文提取：规则已有 med_type 仅归一，不被单元分类覆盖。"""
    content = "第一条 住院报销比例为85%，急诊抢救费用另行规定。"
    store = _Store(content)
    orch = PipelineOrchestrator(store=store, alignment_service=_Alignment())
    monkeypatch.setattr(
        orch,
        "_extract_policy_facts",
        lambda *a, **k: [{
            "fact_text": "住院报销比例为85%，急诊抢救费用另行规定。",
            "rules": [
                {"confidence": 0.9, "med_type": "急诊抢救"},
                {"confidence": 0.8, "med_type": " 门特 "},
            ],
        }],
    )
    assert orch.run_extraction("doc_1")["success"] is True
    rules = store.list_extractions(doc_id="doc_1")["items"][0]["extracted_fields"]["rules"]
    assert rules[0]["med_type"] == "急诊抢救"   # 保留
    assert rules[1]["med_type"] == "门诊特殊病"  # 归一


def test_extract_single_backfills_med_type(monkeypatch):
    """单单元提取：无语境信号回退「通用」，规则同样继承。"""
    store = _Store("第一条 大额互助起付标准为650元。")
    orch = PipelineOrchestrator(store=store, alignment_service=_Alignment())
    monkeypatch.setattr(
        orch,
        "_extract_policy_facts",
        lambda *a, **k: [{
            "fact_text": "大额互助起付标准为650元。",
            "rules": [{"confidence": 0.9}],
        }],
    )
    result = orch.extract_single("doc_1", "大额互助起付标准为650元。", unit_id="unit_x")
    assert result["success"] is True
    items = store.list_extractions(doc_id="doc_1")["items"]
    fields = items[0]["extracted_fields"]
    assert fields["unit_med_type"] == FALLBACK_MED_TYPE
    assert fields["rules"][0]["med_type"] == FALLBACK_MED_TYPE
