"""黄金问答用例灌入：手工 3 条 + 每篇政策文档自动生成 2 条（precise 模式）。

需求：所有政策文档都应配几条黄金问答（发布门禁的回归护栏）。
自动生成策略：从 active release 按 doc_id 取该文档的比例规则，优先选维度齐全
（人群+医疗类别+医院等级+金额区间）的单元格，生成 precise 用例并用
search_precise 实测能命中才入库。

用法（项目根目录）：
    uv run python scripts/seed_golden_test_cases.py
"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg
from pymilvus import MilvusClient

from src.config.production import DATABASE_URL, MILVUS_HOST, MILVUS_PORT
from src.data_platform.storage.postgresql.policy_quality_store import (
    PostgresPolicyQualityStore,
)
from src.knowledge_extension.rule_explanation.quality_models import PolicyQATestCase
from src.knowledge_extension.rule_explanation.quality_store import DEFAULT_TEST_CASES
from src.knowledge_extension.rule_explanation.release_resolver import get_active_release
from src.knowledge_extension.rule_explanation.rules_search_service import (
    RulesSearchService,
)
from src.runtime.policy_qa.policy_rules_search import unpack_detail


def _doc_titles() -> dict[str, str]:
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute("SELECT doc_id, title FROM policy_documents WHERE status = 'extracted'")
        return {doc_id: title for doc_id, title in cur.fetchall()}


def _generate_doc_cases(
    release, searcher: RulesSearchService, doc_id: str, title: str, max_cases: int = 2
) -> list[PolicyQATestCase]:
    """为一篇文档生成黄金用例：维度齐全的比例规则优先，实测命中才产出。"""
    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    rows = client.query(
        collection_name=release.rules_collection,
        filter=f'doc_id == "{doc_id}"',
        output_fields=[
            "rule_id", "psn_type", "med_type", "hosp_lv",
            "amount_band", "payment_ratio", "rule_type",
        ],
        limit=200,
    )
    rules = []
    for row in rows:
        unpack_detail(row)
        if str(row.get("payment_ratio") or "").strip():
            rules.append(row)

    # 维度齐全度排序：非空维度越多越好
    def _dim_count(rule: dict) -> int:
        return sum(
            1
            for key in ("psn_type", "med_type", "hosp_lv", "amount_band")
            if str(rule.get(key) or "").strip()
        )

    rules.sort(key=_dim_count, reverse=True)
    cases: list[PolicyQATestCase] = []
    used_keys: set[tuple] = set()
    for rule in rules:
        if len(cases) >= max_cases:
            break
        dims = {
            key: str(rule.get(key) or "").strip()
            for key in ("psn_type", "med_type", "hosp_lv", "amount_band")
        }
        key = tuple(dims.values())
        if not dims["psn_type"] or not dims["med_type"] or key in used_keys:
            continue
        filters = {k: v for k, v in dims.items() if v}
        filters["doc_id"] = doc_id  # 关联所属文档：前端按此分组，检索更精确
        # 实测：search_precise 必须能命中该规则，否则用例无意义
        groups = searcher.search_precise(filters)
        result_ids = {
            str(r.get("rule_id")) for g in groups for r in g.get("rules", [])
        }
        if rule["rule_id"] not in result_ids:
            continue
        used_keys.add(key)
        dim_text = "".join(
            part for part in (dims["psn_type"], dims["med_type"], dims["hosp_lv"], dims["amount_band"])
            if part
        )
        cases.append(PolicyQATestCase(
            case_id=f"golden_doc_{doc_id.removeprefix('doc_')}_{len(cases) + 1}",
            name=f"黄金·{title[:12]}·{dim_text}",
            query=f"{dim_text}的统筹基金支付比例是多少",
            mode="precise",
            expected_knowledge_ids=[rule["rule_id"]],
            filters=filters,
            required=True,
            case_set_version=0,
        ))
    return cases


def main() -> int:
    store = PostgresPolicyQualityStore()
    golden = [c for c in DEFAULT_TEST_CASES if c.case_id.startswith("golden_")]
    for case in golden:
        store.save_test_case(case)
        print(f"upserted {case.case_id}")
    # 停用语义模式的宽泛黄金用例（rule_id 语义检索不保证命中，改为 precise 维度断言）
    store.save_test_case(PolicyQATestCase(
        case_id="golden_broad_outpatient_fund_ratio",
        name="黄金·门诊统筹基金支付比例（宽泛问法，已停用）",
        query="门诊统筹基金支付比例是多少",
        mode="semantic",
        active=False,
    ))

    release = get_active_release()
    if release is None:
        print("没有 active release，跳过文档级黄金用例生成")
        return 0
    searcher = RulesSearchService(
        rules_col_name=release.rules_collection,
        facts_col_name=release.facts_collection,
    )
    generated = 0
    for doc_id, title in _doc_titles().items():
        cases = _generate_doc_cases(release, searcher, doc_id, title)
        for case in cases:
            store.save_test_case(case)
            generated += 1
        print(f"  {title[:30]} → {len(cases)} 条")
    print(f"手工 {len(golden)} 条 + 文档级生成 {generated} 条，完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
