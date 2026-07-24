# 政策管线 P6：混合检索（三模式 + 按 fact 分组）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**对整个目标的价值**（见路线图 §0 价值地图；P6 属 **M4 检索能力完整**）:

- 让新 collection 的结构化知识**能被查**——M2 只是"存"（写入），P6 是"查"（检索）。这是政策知识从"落库"到"可用"的关键一跃。
- 三种检索模式覆盖不同查询场景：
  - **precise**（精准标量）：如「查城镇职工、三级医院、起付线」——核心维度精确过滤。
  - **semantic**（语义）：如自然语言「住院报销比例多少」——向量召回。
  - **hybrid**（混合）：标量过滤 + 向量排序，兼顾精准与语义。
- **按 fact_id 分组返回**：一条政策事实的多条规则聚合呈现（`{fact_id, fact_text, rules:[...]}`），符合政策问答的展示逻辑。
- 是 **P10（生产切换）的硬前置**：政策问答切到新 collection 前必须有可用的检索能力。
- **target=database（跨世界查找）推迟**：依赖 semantic_layer `source_field` 从两段式（`table.column`）升级为三段式（`ds.table.column`，§4.3），是独立前置块，放 P6 之后。
- 风险：R2（新检索代码），但**只读新 collection**（不改旧 `policy_rules` 检索）、P0 基线保护 → 生产零影响。

---

## Goal

新建 `RulesSearchService`，基于 `policy_rules_v2`（自带 vector 复用 + 核心维度）实现三模式检索，按 fact_id 分组并 join `policy_facts.fact_text`。新增 `POST /policy-pipeline/rules/search` 端点。

## Architecture

**关键简化**：`policy_rules_v2` 自带 `vector`（复用 fact 向量）+ 核心维度字段，所以三模式统一在 policy_rules_v2 上，无需跨 collection 召回：
- **precise**：`MilvusClient.query(filter=核心维度expr)`。
- **semantic**：`MilvusClient.search(data=[query_vec], anns_field="vector")`。
- **hybrid**：`MilvusClient.search(data=[query_vec], filter=核心维度expr)`。

分组：Python 端按 `fact_id` 聚合 rules，再 `policy_facts.query(fact_id)` 取 fact_text。

**Tech Stack:** pymilvus MilvusClient · SentenceTransformerEmbeddingProvider（P0-b）· FastAPI · pytest

**依据:** `docs/steering/政策知识管线设计文档.md` §4.2（三种检索）/ §4.1（rules 复用 fact 向量，使三模式可在 rules 上统一）。对应路线图 Phase 6（6.1/6.3/6.4；6.2 跨世界推迟）。

## 范围边界

- ✅ 做：RulesSearchService（三模式 + 分组）、`POST /rules/search` 端点（target=policy）。
- ❌ 不做：target=database 跨世界查找（source_field 三段式未升级，推迟）、改旧 `policy_rules` 检索、改政策问答读入口（P10）。
- ❌ 不碰：旧 `policy_rules` collection、`PolicyRulesSearchEngine`（P0-b 修的向量检索）。

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `src/knowledge_extension/rule_explanation/rules_search_service.py` | `RulesSearchService`：三模式检索 + 按 fact 分组 | 新建 |
| `src/runtime/api/policy_pipeline_routes.py` | 加 `POST /policy-pipeline/rules/search` 端点 | 改 |
| `src/tests/integration/flow/test_rules_search_service.py` | 三模式集成测试（临时 collection + 测试数据） | 新建 |

---

## Task 1: RulesSearchService + search_precise + 按 fact 分组

**Files:**
- Create: `src/knowledge_extension/rule_explanation/rules_search_service.py`
- Test: `src/tests/integration/flow/test_rules_search_service.py`

- [ ] **Step 1: 写失败测试（precise 标量过滤 + 分组 join fact_text）**

Create `src/tests/integration/flow/test_rules_search_service.py`:

```python
"""RulesSearchService 集成测试（P6）。依赖 Milvus，不可用则 skip。用临时 collection。"""
import pytest

MILVUS_URI = "http://127.0.0.1:19530"


def _milvus_ready() -> bool:
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI, timeout=2); c.close(); return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _milvus_ready(), reason="Milvus 不可用")


def _seed_test_data(svc_rules_col: str, svc_facts_col: str):
    """写入测试数据：2 facts + 4 rules（不同险种/规则类型）。占位向量（precise 不需要真实向量）。"""
    from pymilvus import connections
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
        create_policy_facts_collection, upsert_facts,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection, rule_to_entity, upsert_rules,
    )
    connections.connect(alias="default", host="127.0.0.1", port="19530")
    facts_col = create_policy_facts_collection(collection_name=svc_facts_col, drop_existing=True)
    rules_col = create_policy_rules_v2_collection(collection_name=svc_rules_col, drop_existing=True)
    # fact1: 城镇职工住院起付
    upsert_facts(facts_col, [{"fact_id": "f_test_1", "doc_id": "d_test",
                              "fact_text": "城镇职工住院起付标准1300元", "vector": [0.1] * 768,
                              "created_at": "2026-07-24"}])
    # fact2: 城乡居民门诊报销
    upsert_facts(facts_col, [{"fact_id": "f_test_2", "doc_id": "d_test",
                              "fact_text": "城乡居民门诊统筹支付50%", "vector": [0.2] * 768,
                              "created_at": "2026-07-24"}])
    rules = [
        rule_to_entity({"rule_id": "r1", "fact_id": "f_test_1", "rule_type": "起付线",
                        "insu_type": "城镇职工基本医疗保险", "hosp_lv": "三级医院",
                        "deductible_amount": "1300元"}, vector=[0.1] * 768, extracted_at="t"),
        rule_to_entity({"rule_id": "r2", "fact_id": "f_test_1", "rule_type": "支付比例",
                        "insu_type": "城镇职工基本医疗保险", "hosp_lv": "三级医院",
                        "payment_ratio": "85%"}, vector=[0.1] * 768, extracted_at="t"),
        rule_to_entity({"rule_id": "r3", "fact_id": "f_test_2", "rule_type": "支付比例",
                        "insu_type": "城乡居民基本医疗保险", "hosp_lv": "一级医院",
                        "payment_ratio": "50%"}, vector=[0.2] * 768, extracted_at="t"),
    ]
    for r in rules:
        r["doc_id"] = "d_test"
    upsert_rules(rules_col, rules)


def test_search_precise_filters_and_groups():
    from pymilvus import connections, utility
    from src.knowledge_extension.rule_explanation.rules_search_service import RulesSearchService
    connections.connect(alias="default", host="127.0.0.1", port="19530")
    rcol, fcol = "_test_rules_search_r", "_test_rules_search_f"
    try:
        _seed_test_data(rcol, fcol)
        svc = RulesSearchService(rules_col_name=rcol, facts_col_name=fcol)
        groups = svc.search_precise({"insu_type": "城镇职工基本医疗保险"}, top_k=20)
        # 只命中 fact_test_1 的 2 条规则，聚合为 1 个 group
        assert len(groups) == 1
        g = groups[0]
        assert g["fact_id"] == "f_test_1"
        assert g["fact_text"] == "城镇职工住院起付标准1300元"  # join 了 fact_text
        assert len(g["rules"]) == 2
        types = {r["rule_type"] for r in g["rules"]}
        assert types == {"起付线", "支付比例"}
    finally:
        for n in (rcol, fcol):
            if utility.has_collection(n):
                utility.drop_collection(n)
```

- [ ] **Step 2: 运行，确认失败（模块不存在）**

```bash
python -m pytest src/tests/integration/flow/test_rules_search_service.py -v
```

- [ ] **Step 3: 实现 `RulesSearchService`（precise + 分组）**

Create `src/knowledge_extension/rule_explanation/rules_search_service.py`:

```python
"""政策规则混合检索服务（设计文档 §4.2）。

基于 policy_rules_v2（自带 vector 复用 + 核心维度）实现三模式检索，
按 fact_id 分组并 join policy_facts.fact_text。

三模式统一在 policy_rules_v2 上（无需跨 collection 召回）：
- precise: MilvusClient.query(filter=核心维度)
- semantic: MilvusClient.search(data=[query_vec])
- hybrid: MilvusClient.search(data=[query_vec], filter=核心维度)

[来源: docs/steering/政策知识管线设计文档.md §4.1 / §4.2]
"""
from __future__ import annotations

from typing import Any

from pymilvus import MilvusClient

# 核心维度（可做标量过滤）
CORE_DIMS = ("rule_type", "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type")

# rules 输出字段（核心维度 + 关键详情字段）
RULE_OUTPUT_FIELDS = [
    "rule_id", "fact_id", "doc_id", "rule_type", "insu_type", "med_type",
    "hosp_lv", "psn_type", "setl_type", "schema_version",
    "payment_ratio", "deductible_amount", "cap_amount", "amount_band",
    "rule_value", "source_text",
]


class RulesSearchService:
    """政策规则三模式检索 + 按 fact 分组。"""

    def __init__(
        self,
        uri: str = "http://127.0.0.1:19530",
        rules_col_name: str = "policy_rules_v2",
        facts_col_name: str = "policy_facts",
    ):
        self._client = MilvusClient(uri=uri, timeout=10)
        self._rules_col = rules_col_name
        self._facts_col = facts_col_name

    @staticmethod
    def _build_filter(filters: dict[str, str]) -> str:
        """核心维度 dict → Milvus filter 表达式。空 filters → 空串（不过滤）。"""
        parts = [f'{d} == "{filters[d]}"' for d in CORE_DIMS if filters.get(d)]
        return " and ".join(parts)

    def search_precise(self, filters: dict[str, str], top_k: int = 20) -> list[dict[str, Any]]:
        """精准标量检索：按核心维度过滤 policy_rules_v2。"""
        flt = self._build_filter(filters)
        rules = self._client.query(
            collection_name=self._rules_col,
            filter=flt or "",  # 空串 = 不过滤
            output_fields=RULE_OUTPUT_FIELDS,
            limit=top_k,
        )
        return self._group_by_fact(rules)

    def _group_by_fact(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按 fact_id 聚合 rules，join policy_facts.fact_text。"""
        by_fact: dict[str, list[dict]] = {}
        for r in rules:
            by_fact.setdefault(r.get("fact_id", ""), []).append(r)
        groups: list[dict[str, Any]] = []
        for fid, rs in by_fact.items():
            fact_text = ""
            if fid:
                fr = self._client.query(
                    collection_name=self._facts_col,
                    filter=f'fact_id == "{fid}"',
                    output_fields=["fact_text"], limit=1,
                )
                if fr:
                    fact_text = fr[0].get("fact_text", "")
            groups.append({"fact_id": fid, "fact_text": fact_text, "rules": rs})
        return groups
```

- [ ] **Step 4: 运行通过 → 提交**

```bash
python -m pytest src/tests/integration/flow/test_rules_search_service.py -v
git add src/knowledge_extension/rule_explanation/rules_search_service.py src/tests/integration/flow/test_rules_search_service.py
git commit -m "feat: RulesSearchService precise search + group-by-fact (P6, §4.2)"
```

---

## Task 2: search_semantic + search_hybrid（向量检索）

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/rules_search_service.py`
- Test: `src/tests/integration/flow/test_rules_search_service.py`（追加测试）

- [ ] **Step 1: 追加失败测试（semantic + hybrid，需真实向量化）**

在 `test_rules_search_service.py` **末尾追加**：

```python
def test_search_semantic_and_hybrid():
    """semantic 向量召回 + hybrid 标量过滤+向量。需真实向量化（加载模型）。"""
    from pymilvus import connections, utility
    from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
        get_embedding_provider,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
        create_policy_facts_collection, upsert_facts,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection, rule_to_entity, upsert_rules,
    )
    from src.knowledge_extension.rule_explanation.rules_search_service import RulesSearchService

    connections.connect(alias="default", host="127.0.0.1", port="19530")
    rcol, fcol = "_test_rules_sem_r", "_test_rules_sem_f"
    try:
        provider = get_embedding_provider()
        # 真实向量化 fact_text
        v1 = provider.encode(["城镇职工住院起付标准1300元"])[0]
        v2 = provider.encode(["城乡居民门诊统筹支付50%"])[0]
        facts_col = create_policy_facts_collection(collection_name=fcol, drop_existing=True)
        rules_col = create_policy_rules_v2_collection(collection_name=rcol, drop_existing=True)
        upsert_facts(facts_col, [
            {"fact_id": "f_sem_1", "doc_id": "d_sem", "fact_text": "城镇职工住院起付标准1300元",
             "vector": v1, "created_at": "t"},
            {"fact_id": "f_sem_2", "doc_id": "d_sem", "fact_text": "城乡居民门诊统筹支付50%",
             "vector": v2, "created_at": "t"},
        ])
        rules = [
            rule_to_entity({"rule_id": "rs1", "fact_id": "f_sem_1", "rule_type": "起付线",
                            "insu_type": "城镇职工基本医疗保险", "deductible_amount": "1300元"},
                           vector=v1, extracted_at="t"),
            rule_to_entity({"rule_id": "rs2", "fact_id": "f_sem_2", "rule_type": "支付比例",
                            "insu_type": "城乡居民基本医疗保险", "payment_ratio": "50%"},
                           vector=v2, extracted_at="t"),
        ]
        for r in rules:
            r["doc_id"] = "d_sem"
        upsert_rules(rules_col, rules)

        svc = RulesSearchService(rules_col_name=rcol, facts_col_name=fcol)

        # semantic：语义查询"职工住院起付"应召回 f_sem_1（城镇职工起付）
        sem_groups = svc.search_semantic("职工住院起付标准", top_k=5)
        assert len(sem_groups) >= 1
        top_fact = sem_groups[0]["fact_id"]
        assert top_fact == "f_sem_1", f"语义召回应首选城镇职工起付，实际={top_fact}"
        assert sem_groups[0]["rules"][0]["score"] > 0  # 带 score

        # hybrid：向量 + insu_type 过滤
        hyb_groups = svc.search_hybrid("住院", {"insu_type": "城镇职工基本医疗保险"}, top_k=5)
        for g in hyb_groups:
            for r in g["rules"]:
                assert r["insu_type"] == "城镇职工基本医疗保险"
    finally:
        for n in (rcol, fcol):
            if utility.has_collection(n):
                utility.drop_collection(n)
```

- [ ] **Step 2: 运行，确认失败（`search_semantic` 不存在）**

- [ ] **Step 3: 实现 `search_semantic` + `search_hybrid`**

在 `rules_search_service.py` 的 `RulesSearchService` 类**末尾追加**：

```python
    def search_semantic(self, query_text: str, top_k: int = 20) -> list[dict[str, Any]]:
        """语义检索：query 向量化 → policy_rules_v2 向量搜索（复用 fact 向量）。"""
        from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
            get_embedding_provider,
        )
        vec = get_embedding_provider().encode([query_text])[0]
        results = self._client.search(
            collection_name=self._rules_col,
            data=[vec],
            anns_field="vector",
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            output_fields=RULE_OUTPUT_FIELDS,
        )
        rules = []
        for hit in results[0]:
            e = dict(hit["entity"])
            e["score"] = float(hit["distance"])
            rules.append(e)
        return self._group_by_fact(rules)

    def search_hybrid(
        self, query_text: str, filters: dict[str, str], top_k: int = 20
    ) -> list[dict[str, Any]]:
        """混合检索：向量召回 + 核心维度标量过滤。"""
        from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
            get_embedding_provider,
        )
        vec = get_embedding_provider().encode([query_text])[0]
        flt = self._build_filter(filters)
        results = self._client.search(
            collection_name=self._rules_col,
            data=[vec],
            anns_field="vector",
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            filter=flt or "",
            limit=top_k,
            output_fields=RULE_OUTPUT_FIELDS,
        )
        rules = []
        for hit in results[0]:
            e = dict(hit["entity"])
            e["score"] = float(hit["distance"])
            rules.append(e)
        return self._group_by_fact(rules)
```

- [ ] **Step 4: 运行通过（semantic 测试需加载模型，较慢）→ 提交**

```bash
python -m pytest src/tests/integration/flow/test_rules_search_service.py -v
git add src/knowledge_extension/rule_explanation/rules_search_service.py src/tests/integration/flow/test_rules_search_service.py
git commit -m "feat: RulesSearchService semantic + hybrid search (P6, §4.2)"
```

---

## Task 3: POST /rules/search API 端点

**Files:**
- Modify: `src/runtime/api/policy_pipeline_routes.py`

- [ ] **Step 1: 加 API 端点（无独立测试，靠 import smoke + 手动验证）**

在 `policy_pipeline_routes.py` 的 `list_unpublished_rules` 端点**之前**插入：

```python
@router.post("/rules/search")
async def search_rules(request: Request):
    """政策规则混合检索（P6，基于 policy_rules_v2）。

    body: {mode: "precise"|"semantic"|"hybrid", query?, filters?, top_k?}
    - precise: filters 必填（核心维度）
    - semantic: query 必填（自然语言）
    - hybrid: query + filters 都填
    """
    from src.knowledge_extension.rule_explanation.rules_search_service import RulesSearchService
    body = await request.json()
    mode = body.get("mode", "precise")
    top_k = int(body.get("top_k", 20))
    svc = RulesSearchService()
    if mode == "precise":
        groups = svc.search_precise(body.get("filters", {}), top_k=top_k)
    elif mode == "semantic":
        groups = svc.search_semantic(body["query"], top_k=top_k)
    elif mode == "hybrid":
        groups = svc.search_hybrid(body["query"], body.get("filters", {}), top_k=top_k)
    else:
        raise HTTPException(status_code=400, detail=error_detail(
            "INVALID_MODE", f"mode 必须是 precise/semantic/hybrid，实际={mode}", {}))
    return {"mode": mode, "groups": groups, "total_groups": len(groups)}
```

- [ ] **Step 2: import smoke + 全量回归 → 提交**

```bash
python -c "from src.runtime.api.policy_pipeline_routes import router; print('routes OK')"
python -m pytest src/tests/integration/flow/test_rules_search_service.py src/tests/integration/flow/test_policy_facts_write.py src/tests/integration/flow/test_policy_rules_v2_write.py src/tests/integration/flow/test_policy_qa_scalar_retrieval_baseline.py src/tests/integration/flow/test_policy_qa_vector_retrieval_baseline.py src/tests/unit/rule_explanation/ src/tests/unit/semantic_layer/ -q
git add src/runtime/api/policy_pipeline_routes.py
git commit -m "feat: POST /rules/search hybrid retrieval endpoint (P6, §7.5)"
```

---

## 收口标准

- [ ] `search_precise` 按核心维度过滤 + 按 fact 分组 + join fact_text（集成测试绿）。
- [ ] `search_semantic` 向量召回（带 score）+ `search_hybrid` 向量+标量（集成测试绿）。
- [ ] `POST /rules/search` 端点支持三模式（import smoke + 手动 curl 验证）。
- [ ] **未触碰**旧 `policy_rules` / `PolicyRulesSearchEngine`（P0 基线无回归）。

## 手动验证（收口后，可选）

用 M2 demo 写入的数据 curl 验证：
```bash
# precise
curl -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-pipeline/rules/search \
  -H "Content-Type: application/json" \
  -d '{"mode":"precise","filters":{"insu_type":"城镇职工基本医疗保险"}}'
# semantic
curl ... -d '{"mode":"semantic","query":"住院起付标准"}'
# hybrid
curl ... -d '{"mode":"hybrid","query":"住院","filters":{"insu_type":"城镇职工基本医疗保险"}}'
```

## 本计划交付后的事实 + 跨世界去向

- 新 collection 的结构化知识**可被三模式检索**（M4 主体达成）。
- 生产政策问答仍读旧路径（P10 切换）。
- **target=database（跨世界）推迟**：需先把 semantic_layer `source_field` 从两段式升三段式（§4.3，`datasource.table.column`），作为 P6 后的独立前置块。届时 `search_database` 经 source_field 映射查 SQLServer，`target=both` 合并两边结果。
