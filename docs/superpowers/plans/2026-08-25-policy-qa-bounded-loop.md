# Policy QA 有界 Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现行 Policy QA 真实结算链路中补齐 Gather → Act → Verify → Repeat，并保证瞬时故障最多重试一次、确定性缺证据不重试。

**Architecture:** 不创建通用 Loop 框架。`policy_qa_routes.py` 在现有流式管线内执行最多两轮完整尝试；真实结算 Provider 和结构化政策检索器只把明确的数据源不可用异常标记为可重试，现有 `_build_public_result` 继续作为唯一确定性验证器。

**Tech Stack:** Python 3、FastAPI SSE、pytest、SQL Server/pyodbc、Milvus/pymilvus、现有 Skill assembler

---

### Task 1: 同步 Issue #21 研究依据

**Files:**
- Create: `docs/research/LoopEngineering.md`

- [ ] **Step 1: 从 main 同步原文**

将 main 中的 `docs/research/LoopEngineering.md` 原样加入当前分支，不修改标题、结构或结论。

- [ ] **Step 2: 校验关键工程约束存在**

Run: `rg -n "Gather|Act|Verify|Repeat|最大迭代|停滞|恢复" docs/research/LoopEngineering.md`

Expected: 命中闭环、停止条件和恢复策略章节。

- [ ] **Step 3: 提交研究文档**

```bash
git add docs/research/LoopEngineering.md
git commit -m "docs: 同步 loop engineering 研究依据"
```

### Task 2: 用失败测试区分瞬时故障与确定性失败

**Files:**
- Create: `src/tests/unit/runtime/policy_qa/test_loop_recovery.py`
- Modify: `src/runtime/policy_qa/settlement_data_provider.py`
- Modify: `src/runtime/policy_qa/structured_policy_retriever.py`

- [ ] **Step 1: 编写结算数据异常分类测试**

```python
import pytest

from src.runtime.policy_qa.settlement_data_provider import (
    RealDbSettlementDataProvider,
    SettlementDataUnavailableError,
    SettlementNotFoundError,
)


@pytest.mark.asyncio
async def test_provider_maps_missing_settlement_to_non_retryable_error(monkeypatch):
    provider = object.__new__(RealDbSettlementDataProvider)
    provider.client = type("Client", (), {
        "get_case_context_raw": lambda self, settlement_id: (_ for _ in ()).throw(
            ValueError(f"未查询到结算记录 djh={settlement_id}")
        )
    })()
    with pytest.raises(SettlementNotFoundError):
        await provider.get_settlement_context("missing")


@pytest.mark.asyncio
async def test_provider_maps_connection_failure_to_retryable_error():
    provider = object.__new__(RealDbSettlementDataProvider)
    provider.client = type("Client", (), {
        "get_case_context_raw": lambda self, settlement_id: (_ for _ in ()).throw(
            ConnectionError("sql unavailable")
        )
    })()
    with pytest.raises(SettlementDataUnavailableError):
        await provider.get_settlement_context("S1")
```

- [ ] **Step 2: 编写政策检索故障不伪装成零命中测试**

```python
def test_structured_retriever_exposes_source_failure():
    from src.runtime.policy_qa.structured_policy_retriever import (
        PolicyRetrievalUnavailableError,
        StructuredPolicyQuery,
        StructuredPolicyRuleRetriever,
    )

    retriever = object.__new__(StructuredPolicyRuleRetriever)
    retriever.collection_name = "policy_rules_v2"
    retriever.client = type("Client", (), {
        "query": lambda self, **kwargs: (_ for _ in ()).throw(ConnectionError("milvus unavailable"))
    })()
    with pytest.raises(PolicyRetrievalUnavailableError):
        retriever.execute_query(StructuredPolicyQuery(query_name="required"))
```

- [ ] **Step 3: 运行测试并确认红灯**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_loop_recovery.py -q`

Expected: FAIL，两个新的数据源异常类型尚不存在，检索器仍吞掉异常。

- [ ] **Step 4: 实现最小异常分类**

`settlement_data_provider.py`：

```python
class SettlementDataUnavailableError(Exception):
    """真实结算数据源发生可恢复的连接或超时故障。"""


try:
    raw_context = await loop.run_in_executor(
        None,
        lambda: self.client.get_case_context_raw(settlement_id=settlement_id),
    )
except ValueError as exc:
    if "未查询到结算记录" in str(exc):
        raise SettlementNotFoundError(
            f"未查询到真实结算数据: settlement_id={settlement_id}"
        ) from exc
    raise
except (ConnectionError, TimeoutError) as exc:
    raise SettlementDataUnavailableError("真实结算数据源暂时不可用") from exc
```

同时捕获 `pyodbc.Error`，但不把 `ValueError`、`KeyError`、`FileNotFoundError` 或配置 `RuntimeError` 标记为可重试。

`structured_policy_retriever.py`：

```python
class PolicyRetrievalUnavailableError(Exception):
    """政策规则数据源不可用，调用方可执行有界重试。"""


try:
    raw_results = self.client.query(
        collection_name=self.collection_name,
        filter=expr,
        output_fields=OUTPUT_FIELDS,
        limit=top_k,
    )
except Exception as exc:
    logger.warning("Structured policy query unavailable", exc_info=True)
    raise PolicyRetrievalUnavailableError("政策规则数据源暂时不可用") from exc
```

- [ ] **Step 5: 运行测试并确认绿灯**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_loop_recovery.py -q`

Expected: PASS。

- [ ] **Step 6: 提交异常分类**

```bash
git add src/runtime/policy_qa/settlement_data_provider.py src/runtime/policy_qa/structured_policy_retriever.py src/tests/unit/runtime/policy_qa/test_loop_recovery.py
git commit -m "fix: 区分 policy-qa 可重试数据源故障"
```

### Task 3: 用 API 测试固定两轮 Loop 和停止条件

**Files:**
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`

- [ ] **Step 1: 添加首轮瞬时失败、第二轮成功测试**

```python
def test_stream_retries_transient_settlement_failure_once(
    client, safe_policy_qa_dependencies, monkeypatch,
):
    from src.runtime.api import policy_qa_routes
    from src.runtime.policy_qa.settlement_data_provider import (
        SettlementContext,
        SettlementDataUnavailableError,
    )

    calls = 0

    class FlakyProvider:
        async def get_settlement_context(self, settlement_id: str):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise SettlementDataUnavailableError("temporary")
            return SettlementContext(
                settlement_id=settlement_id,
                total_amount=100.0,
                basic_pooling_self_pay=10.0,
            )

    monkeypatch.setattr(policy_qa_routes, "create_settlement_data_provider", FlakyProvider)
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "统筹自付为什么是这些？", "settlement_id": "S1"},
    )
    events = _sse_events(response.text)
    assert calls == 2
    assert any(name == "step" and data.get("step") == "recovery" for name, data in events)
    assert next(data for name, data in events if name == "done")["success"] is True
```

- [ ] **Step 2: 添加非重试错误和停滞测试**

```python
def test_stream_does_not_retry_missing_settlement(
    client, safe_policy_qa_dependencies, monkeypatch,
):
    from src.runtime.api import policy_qa_routes
    from src.runtime.policy_qa.settlement_data_provider import SettlementNotFoundError

    calls = 0

    class MissingProvider:
        async def get_settlement_context(self, settlement_id: str):
            nonlocal calls
            calls += 1
            raise SettlementNotFoundError(settlement_id)

    monkeypatch.setattr(policy_qa_routes, "create_settlement_data_provider", MissingProvider)
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "统筹自付为什么是这些？", "settlement_id": "missing"},
    )
    events = _sse_events(response.text)
    assert calls == 1
    assert next(data for name, data in events if name == "done")["success"] is False


def test_stream_stops_after_two_identical_transient_failures(
    client, safe_policy_qa_dependencies, monkeypatch,
):
    from src.runtime.api import policy_qa_routes
    from src.runtime.policy_qa.settlement_data_provider import SettlementDataUnavailableError

    calls = 0

    class UnavailableProvider:
        async def get_settlement_context(self, settlement_id: str):
            nonlocal calls
            calls += 1
            raise SettlementDataUnavailableError("temporary")

    monkeypatch.setattr(policy_qa_routes, "create_settlement_data_provider", UnavailableProvider)
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "统筹自付为什么是这些？", "settlement_id": "S1"},
    )
    events = _sse_events(response.text)
    assert calls == 2
    assert any(name == "error" for name, _data in events)
    assert next(data for name, data in events if name == "done")["success"] is False
```

- [ ] **Step 3: 添加确定性部分回答不重试测试**

```python
def test_stream_does_not_repeat_deterministic_partial_result(
    client, safe_policy_qa_dependencies, monkeypatch,
):
    from types import SimpleNamespace
    from src.runtime.api import policy_qa_routes

    retrieval_calls = 0

    def no_evidence(**_kwargs):
        nonlocal retrieval_calls
        retrieval_calls += 1
        return SimpleNamespace(selected_evidence=[], missing_required_rules=["required"])

    monkeypatch.setattr(policy_qa_routes, "retrieve_policy_evidence", no_evidence)
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "统筹自付为什么是这些？", "settlement_id": "S1"},
    )
    events = _sse_events(response.text)
    result = next(data for name, data in events if name == "result")["result"]
    assert retrieval_calls == 1
    assert result["answer_status"] in {"partial", "unavailable"}
    assert next(data for name, data in events if name == "done")["success"] is True
```

- [ ] **Step 4: 运行测试并确认红灯**

Run: `python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q -k "retries_transient or does_not_retry or stops_after_two or deterministic_partial"`

Expected: FAIL；当前流式管线第一次异常即结束。

### Task 4: 在现行 SSE 管线实现最小有界 Loop

**Files:**
- Modify: `src/runtime/api/policy_qa_routes.py`

- [ ] **Step 1: 导入可重试异常并定义固定上限**

```python
from src.runtime.policy_qa.settlement_data_provider import (
    SettlementDataUnavailableError,
    SettlementNotFoundError,
    create_settlement_data_provider,
)
from src.runtime.policy_qa.structured_policy_retriever import (
    PolicyRetrievalUnavailableError,
    retrieve_policy_evidence,
)

_MAX_POLICY_QA_ATTEMPTS = 2
_RETRYABLE_POLICY_QA_ERRORS = (
    SettlementDataUnavailableError,
    PolicyRetrievalUnavailableError,
)
```

- [ ] **Step 2: 用两轮 `for` 包住现有 Gather → Act → Verify**

在 `_policy_qa_stream` 中保持 `_yield_step`、持久化和最终 SSE 发送位置不变，把 intent detection 至 `_build_public_result` 放入：

```python
attempt_count = 0
halt_reason = "non_retryable_failure"
previous_failure: str | None = None

for attempt_count in range(1, _MAX_POLICY_QA_ATTEMPTS + 1):
    try:
        provider = create_settlement_data_provider()
        public_result = _build_public_result(
            answer=result_answer,
            can_answer=trace_can_answer,
            partial_answer=trace_partial_answer,
            policy_status=policy_status,
            policy_evidence=result_policy_evidence,
            calculation_steps=_calc_steps,
            definition=_definition,
            warnings=_warnings,
            case_context=_case_context,
            is_overview=_is_overview,
        )
    except _RETRYABLE_POLICY_QA_ERRORS as exc:
        fingerprint = f"{type(exc).__module__}.{type(exc).__qualname__}"
        if attempt_count >= _MAX_POLICY_QA_ATTEMPTS or fingerprint == previous_failure:
            halt_reason = (
                "stagnated" if fingerprint == previous_failure else "attempt_limit"
            )
            raise
        previous_failure = fingerprint
        async for event in _yield_step(
            "recovery",
            "done",
            "数据源短暂不可用，正在执行最后一次恢复尝试…",
        ):
            yield event
        continue

    halt_reason = (
        "verified" if public_result.answer_status == "complete" else "degraded"
    )
    async for event in _yield_step(
        "verification",
        "done",
        public_result.verification_summary.message,
    ):
        yield event
    break
```

具体编辑方式：把当前 `intent_detection` 开始至上述 `_build_public_result` 调用结束的完整代码块整体缩进到 `try` 内，代码内容和执行顺序保持不变；只把原来位于循环外的 `provider = create_settlement_data_provider()` 移入每轮开头。

不捕获 `SettlementNotFoundError`、配置/输入错误或安全错误；它们继续进入现有外层异常处理且只执行一次。

- [ ] **Step 3: 持久化尝试次数和停止原因**

成功任务 `output` 增加：

```python
"attempt_count": attempt_count,
"halt_reason": halt_reason,
```

失败任务 `output` 使用同样字段；不持久化异常正文、SQL 或内部检索载荷。

- [ ] **Step 4: 保持公开契约和停止语义**

- `complete`：`done.success=true`，`halt_reason=verified`。
- `partial/unavailable` 安全结果：`done.success=true`，`halt_reason=degraded`，不重复。
- 两轮瞬时故障：现有 `error` + `done.success=false`。
- 不新增模型调用、配置项或第二套结果 DTO。

- [ ] **Step 5: 运行 API Loop 测试并确认绿灯**

Run: `python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q -k "retries_transient or does_not_retry or stops_after_two or deterministic_partial"`

Expected: PASS。

- [ ] **Step 6: 提交 Loop**

```bash
git add src/runtime/api/policy_qa_routes.py src/tests/integration/api/test_policy_qa_routes.py
git commit -m "feat: 为 policy-qa 增加有界执行 loop"
```

### Task 5: 补齐 Flow 验证和 PROGRESS 记录

**Files:**
- Modify: `src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 添加 Flow 级恢复与确定性停止测试**

在文件顶部增加可复用的真实 App client 与既有确定性依赖 fixture：

```python
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.tests.integration.api.test_policy_qa_routes import (
    _sse_events,
    safe_policy_qa_dependencies,
)


@pytest.fixture
def client():
    return TestClient(create_app())
```

```python
def test_policy_qa_flow_retries_transient_source_once(
    client, safe_policy_qa_dependencies, monkeypatch,
):
    from src.runtime.api import policy_qa_routes
    from src.runtime.policy_qa.settlement_data_provider import (
        SettlementContext,
        SettlementDataUnavailableError,
    )

    calls = 0

    class FlakyProvider:
        async def get_settlement_context(self, settlement_id: str):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise SettlementDataUnavailableError("temporary")
            return SettlementContext(
                settlement_id=settlement_id,
                total_amount=100.0,
                basic_pooling_self_pay=10.0,
            )

    monkeypatch.setattr(policy_qa_routes, "create_settlement_data_provider", FlakyProvider)
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "统筹自付为什么是这些？", "settlement_id": "S1"},
    )
    events = _sse_events(response.text)
    assert calls == 2
    assert any(name == "step" and data.get("step") == "recovery" for name, data in events)
    assert next(data for name, data in events if name == "done")["success"] is True


def test_policy_qa_flow_does_not_retry_missing_policy_evidence(
    client, safe_policy_qa_dependencies, monkeypatch,
):
    from types import SimpleNamespace
    from src.runtime.api import policy_qa_routes

    calls = 0

    def no_evidence(**_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(selected_evidence=[], missing_required_rules=["required"])

    monkeypatch.setattr(policy_qa_routes, "retrieve_policy_evidence", no_evidence)
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "统筹自付为什么是这些？", "settlement_id": "S1"},
    )
    events = _sse_events(response.text)
    result = next(data for name, data in events if name == "result")["result"]
    assert calls == 1
    assert result["uncertainties"]
```

- [ ] **Step 2: 运行 Flow 测试**

Run: `python -m pytest src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py -q`

Expected: PASS。

- [ ] **Step 3: 更新 `PROGRESS.md` Issue #21 状态**

新增 Policy QA 单元 1.7：

```markdown
| 1.7 | Policy QA 有界 Loop：真实结算与政策证据 Gather → Skill Act → 确定性 Verify；瞬时故障最多两轮，证据不足立即安全停止 | B+S | — | `policy_qa_routes.py` → `_build_public_result` | SQL Server + Milvus | verified |
```

同时更新：

- §0 当前焦点和阶段为 Issue #21 已完成验证。
- §1 Policy QA 单元数、verified/impl_done 和总计。
- §4 写入本次 T1/T2a/T2b/Portal/T3/T4 的真实数量。
- §6 变更日志记录旧场景退役、两轮上限、停止条件及无模型切换。
- 明确 `policy-qa + 真实结算单 + settlement_explain_skill` 是唯一业务主链。

- [ ] **Step 4: 提交 Flow 与进度**

```bash
git add src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py PROGRESS.md
git commit -m "test: 验证 policy-qa loop 完整闭环"
```

### Task 6: 严格执行 R4 最终验证

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: T1 单元测试**

Run: `python -m pytest src/tests/unit -q`

Expected: PASS。

- [ ] **Step 2: T2a API 测试**

Run: `python -m pytest src/tests/integration/api -q`

Expected: PASS。

- [ ] **Step 3: T2b Flow 测试**

Run: `python -m pytest src/tests/integration/flow -q`

Expected: PASS。

- [ ] **Step 4: T3 Policy QA 性能场景**

先通过中央脚本启动当前工作区：

```powershell
..\ws.ps1 up issue21
```

再运行仅 Policy QA 标签的 Locust：

```powershell
python -m locust -f src/tests/performance/locustfile.py --headless -u 5 -r 1 -t 30s --host <ws.ps1 输出的后端 URL> --tags policy-qa
```

Expected: 0 个未预期失败；每次 SSE 都出现 `done`，无第三次数据源调用。

- [ ] **Step 5: Portal T4 验证**

```bash
cd src/apps/portal
npm test
npx tsc --noEmit
npm run lint
npm run build
```

然后运行现行 Policy QA E2E 和 Portal smoke；旧 `/settlement`、`/qc`、`/dashboard` 必须为 404。

- [ ] **Step 6: LSP/编译诊断**

Run: `python -m compileall -q src`

Expected: 退出码 0；无已删除模块 import 错误。

- [ ] **Step 7: 将最终真实数字写入 `PROGRESS.md` 并提交**

```bash
git add PROGRESS.md
git commit -m "docs: 记录 issue 21 最终验证证据"
```

- [ ] **Step 8: 停止当前工作区服务**

Run: `..\ws.ps1 down issue21`

Expected: 当前工作区后端与 Portal 均停止。
