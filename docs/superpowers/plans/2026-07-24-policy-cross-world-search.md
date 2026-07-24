# 政策管线 P6-跨世界：target=database / both Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**对整个目标的价值**（补全 M4 检索能力的"跨世界"半边）:

- 让政策知识**能联查业务数据**——`target=database` 经指标 `source_field` 映射查 SQLServer 业务库；`target=both` 同时返回政策规则 + 业务实际值（"政策规定报多少" vs "这个患者实际报多少"），这是政策问答增强的核心场景。
- **可行性已验证**：`SemanticDataSource.query(["djxx.fund_type"], {"djh": <真登记号>})` 端到端返回 `{'城镇职工'}`——PG registry 有 seed metric、SQLServer(bjybdb, 361 表) 可用、resolve_metric 正确。P6 跨世界本质是它的**薄封装**。
- **source_field 三段式推迟到 P7**：调研发现解析点有 **3 处**（semantic_routes / semantic_source / data_query 全是 `split(".", 1)`），升级是 breaking change；且 **P6 只有一个数据源**（bjybdb），三段式的 `ds` 段无用。三段式真正有意义在 P7（§7.6 datasource 多源注册表）——届时再统一升级，避免现在做无用的 breaking 改动。
- **核心维度→业务列映射（§4.3 "同一条件打两库"）推迟**：那需要 insu_type/hosp_lv → 业务表列的语义映射（独立大块，依赖业务表语义）。P6 跨世界用现有成熟模式：政策按核心维度过滤、业务按登记号(djh)取值——这是 `SemanticDataSource` 已验证的模式，覆盖"政策↔业务联查"核心价值。
- 风险：R2（新检索代码 + 依赖 PG/SQLServer）。**只读**业务库 + 新 collection，不改旧路径。测试用 skip 兜底（PG/SQLServer 不可用则 skip）。

**依据:** `docs/steering/政策知识管线设计文档.md` §4.3（跨世界查找）/ §7.5（target 字段）。已验证：`SemanticDataSource`（`src/runtime/discovery/semantic_source.py`）两段式 source_field + 按 djh 取值，端到端可用。

---

## Goal

给 `RulesSearchService` 加 `search_database`（封装 `SemanticDataSource.query`），扩展 `POST /rules/search` 支持 `target=database|both`。

## Architecture

- `search_database(metric_codes, context)` → `SemanticDataSource().query(metric_codes, context)` → `{metric_code: value}`（经指标 source_field 映射查 SQLServer）。
- API `target` 字段：
  - `policy`（默认）：现有三模式（precise/semantic/hybrid）→ `groups`。
  - `database`：`search_database` → `database_values`。
  - `both`：policy 三模式 + database → 同时填 `groups` + `database_values`。
- 返回结构统一为 `{mode, target, groups, total_groups, database_values}`——`target=policy` 时 `database_values={}`，向后兼容。

**Tech Stack:** SemanticDataSource（pymilvus + pyodbc + PG registry）· FastAPI · pytest

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `src/knowledge_extension/rule_explanation/rules_search_service.py` | 加 `search_database` 方法 | 改 |
| `src/runtime/api/policy_pipeline_routes.py` | `/rules/search` 加 `target` 分支 | 改 |
| `src/tests/integration/flow/test_rules_search_service.py` | 加 `search_database` 集成测试 | 改 |

---

## Task 1: search_database + 集成测试

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/rules_search_service.py`
- Test: `src/tests/integration/flow/test_rules_search_service.py`

- [ ] **Step 1: 写失败测试（search_database 经 source_field 映射查业务库）**

在 `test_rules_search_service.py` **末尾追加**（独立函数，skip 兜底 PG/SQLServer）：

```python
def _db_ready() -> bool:
    """PG(registry) + SQLServer(业务库) 都可用才跑跨世界测试。"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        import pyodbc
        from src.config.production import SQLSERVER_HOST  # noqa: F401
        conn = pyodbc.connect(
            "DRIVER={SQL Server};SERVER=127.0.0.1,1433;DATABASE=bjybdb;"
            "UID=sa;PWD=REDACTED", timeout=2)
        conn.close()
        return True
    except Exception:
        return False


def test_search_database_via_semantic_source():
    """target=database：经指标 source_field 映射查业务库（SemanticDataSource 封装）。"""
    from dotenv import load_dotenv
    load_dotenv()
    import pyodbc
    from src.knowledge_extension.rule_explanation.rules_search_service import RulesSearchService
    # 取真实登记号（yb_brdjxx 是 seed 里 source_field 指向的真实表）
    conn = pyodbc.connect(
        "DRIVER={SQL Server};SERVER=127.0.0.1,1433;DATABASE=bjybdb;"
        "UID=sa;PWD=REDACTED", timeout=3)
    cur = conn.cursor()
    cur.execute("SELECT TOP 1 djh FROM yb_brdjxx")
    row = cur.fetchone()
    conn.close()
    assert row is not None, "yb_brdjxx 无数据"
    djh = row[0]

    svc = RulesSearchService()
    # djxx.fund_type 的 source_field=yb_brdjxx.FUND_TYPE（seed 验证过）
    result = svc.search_database(["djxx.fund_type", "djxx.yllb"], {"djh": djh})
    assert "djxx.fund_type" in result
    assert result["djxx.fund_type"] is not None, "业务取值应非空（如 '城镇职工'）"
    assert result["djxx.yllb"] is not None
```

并**在文件顶部 pytestmark 下方追加** skip 标记给此测试（避免 PG/SQLServer 不可用时硬失败）：

```python
db_test = pytest.mark.skipif(not _db_ready(), reason="PG/SQLServer 业务库不可用")
```
（在 `test_search_database_via_semantic_source` 定义上加装饰器 `@db_test`，并把 `_db_ready` 定义移到 `pytestmark` 之后）

- [ ] **Step 2: 运行，确认失败（`search_database` 不存在）**

```bash
python -m pytest src/tests/integration/flow/test_rules_search_service.py::test_search_database_via_semantic_source -v
```

- [ ] **Step 3: 实现 `search_database`（薄封装 SemanticDataSource）**

在 `rules_search_service.py` 的 `RulesSearchService` 类**末尾**（`_group_by_fact` 之后）追加：

```python
    def search_database(
        self, metric_codes: list[str], context: dict[str, Any]
    ) -> dict[str, Any]:
        """target=database：经指标 source_field 映射查业务库（SQLServer）。

        复用 SemanticDataSource.query（两段式 source_field + 按 context[filter_key] 过滤）。
        [来源: §4.3 跨世界查找；SemanticDataSource 已验证端到端可用]
        """
        from src.runtime.discovery.semantic_source import SemanticDataSource
        return SemanticDataSource().query(metric_codes, context)
```

- [ ] **Step 4: 运行通过 → 提交**

```bash
python -m pytest src/tests/integration/flow/test_rules_search_service.py -v
git add src/knowledge_extension/rule_explanation/rules_search_service.py src/tests/integration/flow/test_rules_search_service.py
git commit -m "feat: RulesSearchService.search_database cross-world lookup (P6, §4.3)"
```

---

## Task 2: API target=database/both 扩展 + 端到端

**Files:**
- Modify: `src/runtime/api/policy_pipeline_routes.py`

- [ ] **Step 1: 改 `/rules/search` 端点加 target 分支**

将现有 `search_rules` 函数体替换为（保留三模式，加 target 分支 + 统一返回）：

```python
@router.post("/rules/search")
async def search_rules(request: Request):
    """政策规则混合检索（P6，基于 policy_rules_v2 + 业务库）。

    body: {mode, query?, filters?, target, metric_codes?, context?, top_k?}
    - mode: precise|semantic|hybrid（target=policy/both 时生效）
    - target: policy(默认)|database|both
      - policy: 查政策规则（三模式）
      - database: 查业务数据（经 source_field 映射查 SQLServer，需 metric_codes+context）
      - both: 政策规则 + 业务数据
    """
    from src.knowledge_extension.rule_explanation.rules_search_service import RulesSearchService
    body = await request.json()
    mode = body.get("mode", "precise")
    target = body.get("target", "policy")
    top_k = int(body.get("top_k", 20))
    svc = RulesSearchService()

    groups: list = []
    if target in ("policy", "both"):
        if mode == "precise":
            groups = svc.search_precise(body.get("filters", {}), top_k=top_k)
        elif mode == "semantic":
            groups = svc.search_semantic(body["query"], top_k=top_k)
        elif mode == "hybrid":
            groups = svc.search_hybrid(body["query"], body.get("filters", {}), top_k=top_k)
        else:
            raise HTTPException(status_code=400, detail=error_detail(
                "INVALID_MODE", f"mode 必须是 precise/semantic/hybrid，实际={mode}", {}))

    database_values: dict = {}
    if target in ("database", "both"):
        metric_codes = body.get("metric_codes", [])
        if not metric_codes:
            raise HTTPException(status_code=400, detail=error_detail(
                "NO_METRICS", "target=database/both 必须提供 metric_codes", {}))
        database_values = svc.search_database(metric_codes, body.get("context", {}))

    return {
        "mode": mode, "target": target,
        "groups": groups, "total_groups": len(groups),
        "database_values": database_values,
    }
```

- [ ] **Step 2: import smoke + 回归 + 端到端验证 → 提交**

```bash
# import smoke
python -c "from src.runtime.api.policy_pipeline_routes import router; print('routes OK')"
# 回归（P6 三模式 + 跨世界 + P3 + P0 基线）
python -m pytest src/tests/integration/flow/test_rules_search_service.py src/tests/integration/flow/test_policy_facts_write.py src/tests/integration/flow/test_policy_rules_v2_write.py src/tests/integration/flow/test_policy_qa_vector_retrieval_baseline.py src/tests/unit/rule_explanation/ -q
# 端到端：target=database + both（用真登记号）
python -c "
from dotenv import load_dotenv; load_dotenv()
import pyodbc
conn = pyodbc.connect('DRIVER={SQL Server};SERVER=127.0.0.1,1433;DATABASE=bjybdb;UID=sa;PWD=REDACTED',timeout=3)
djh = conn.cursor(); djh.execute('SELECT TOP 1 djh FROM yb_brdjxx'); d = djh.fetchone()[0]; conn.close()
from src.runtime.api.app import create_app
from fastapi.testclient import TestClient
c = TestClient(create_app())
B='/api/v1/medical-insurance-ai-agent/policy-pipeline'
for body in [
  {'target':'database','metric_codes':['djxx.fund_type'],'context':{'djh':d}},
  {'target':'both','mode':'precise','filters':{'insu_type':'城镇职工基本医疗保险'},'metric_codes':['djxx.fund_type'],'context':{'djh':d}},
]:
    r=c.post(B+'/rules/search',json=body); j=r.json()
    print(body['target'].ljust(8),r.status_code,'db=',j.get('database_values'),'groups=',j.get('total_groups'))
"
git add src/runtime/api/policy_pipeline_routes.py
git commit -m "feat: /rules/search target=database|both cross-world (P6, §4.3/§7.5)"
```

---

## 收口标准

- [ ] `search_database(metric_codes, context)` 经 SemanticDataSource 查业务库（集成测试绿，返回真实值）。
- [ ] `/rules/search` 支持 `target=policy|database|both`，返回统一含 `groups` + `database_values`。
- [ ] `target=policy`（默认）向后兼容（现有调用不变，`database_values={}`）。
- [ ] 端到端：`target=database` 返回业务值；`target=both` 同时返回政策规则 + 业务值。

## 本计划交付后的事实 + 后续去向

- M4 跨世界**核心价值达成**：政策规则 ↔ 业务数据联查可用（`target=database/both`）。
- **source_field 仍两段式**（不改，向后兼容）；三段式升级推迟 P7（多源注册表，那时才需要 `ds` 段）。
- **§4.3 "同一条件打两库"未完整实现**：政策按核心维度、业务按登记号（djw），非"同一条件"。完整的维度→业务列映射是独立大块，后续单独阶段。
- M4 状态可更新为「**三模式 + 跨世界(经登记号) 达成；同条件联查 + 三段式 推迟 P7+**」。
