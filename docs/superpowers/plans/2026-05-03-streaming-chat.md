# Streaming Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留现有非流式接口的前提下，为演示页面新增流式/非流式开关，实现 LLM 基础调用逐字/分片流式显示，业务导办按步骤事件流式展示并最终渲染结构化卡片。

**Architecture:** 后端新增 SSE 风格的 `POST /chat/stream` 与 `POST /model-test/stream`，使用 `StreamingResponse` 输出 `text/event-stream` 事件；现有 `POST /chat` 与 `POST /model-test` 保持不变。前端新增流式模式开关，开启时用 `fetch()` + `ReadableStream` 解析事件流，关闭时继续走现有 JSON 接口。

**Tech Stack:** Python, FastAPI, StreamingResponse, pytest, 原生 HTML/JavaScript, Fetch ReadableStream, SSE event format

---

### Task 1: 新增 SSE 事件格式化工具与单元测试

**Files:**
- Create: `src/runtime/api/streaming.py`
- Create: `src/tests/unit/test_streaming_events.py`
- Test: `src/tests/unit/test_streaming_events.py`

- [ ] **Step 1: 写失败测试**

创建 [`src/tests/unit/test_streaming_events.py`](src/tests/unit/test_streaming_events.py)：

```python
import json

from src.runtime.api.streaming import sse_event


def test_sse_event_formats_json_payload():
    raw = sse_event('step', {'step': 'intent_detection', 'message': '正在识别意图'})

    assert raw.startswith('event: step\n')
    assert raw.endswith('\n\n')
    data_line = raw.split('\n')[1]
    assert data_line.startswith('data: ')
    assert json.loads(data_line.removeprefix('data: ')) == {
        'step': 'intent_detection',
        'message': '正在识别意图',
    }
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `python -m pytest src/tests/unit/test_streaming_events.py -v`

Expected: FAIL，失败原因为 [`src.runtime.api.streaming`](src/runtime/api/streaming.py) 尚不存在。

- [ ] **Step 3: 实现最小工具函数**

创建 [`src/runtime/api/streaming.py`](src/runtime/api/streaming.py)：

```python
import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f'event: {event}\ndata: {payload}\n\n'
```

- [ ] **Step 4: 运行测试确认绿灯**

Run: `python -m pytest src/tests/unit/test_streaming_events.py -v`

Expected: PASS。

### Task 2: 抽取 chat 共享处理函数，保持非流式接口兼容

**Files:**
- Modify: `src/runtime/api/routes.py`
- Test: `src/tests/unit/test_tech_debt_fixes.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: 运行现有非流式测试作为基线**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_chat_returns_agent_response_instance src/tests/unit/test_tech_debt_fixes.py::test_chat_missing_context_returns_agent_response -v`

Expected: PASS。

- [ ] **Step 2: 抽取共享处理函数**

在 [`src/runtime/api/routes.py`](src/runtime/api/routes.py) 中将 [`chat()`](src/runtime/api/routes.py:28) 的主体抽为 `process_chat_request()`，并让 [`chat()`](src/runtime/api/routes.py:28) 调用该函数：

```python
def process_chat_request(request: ChatRequest) -> AgentResponse:
    missing = missing_context_fields(request.patient_id, request.encounter_id)
    if missing:
        return AgentResponse(status='needs_clarification', missing_fields=missing)
    blocked = detect_blocked_actions(request.message)
    if blocked:
        return build_human_confirmation_response(blocked)
    scenario = detect_intent(request.message)
    if scenario == 'settlement_exception_guidance':
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        return guide_settlement_exception(request.patient_id, request.encounter_id)
    if scenario == 'pre_discharge_quality_control':
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        return run_pre_discharge_qc(request.patient_id, request.encounter_id)
    return AgentResponse(status='not_implemented')


@router.post('/chat')
def chat(request: ChatRequest) -> AgentResponse:
    return process_chat_request(request)
```

- [ ] **Step 3: 运行回归测试**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_chat_returns_agent_response_instance src/tests/unit/test_tech_debt_fixes.py::test_chat_missing_context_returns_agent_response src/tests/integration/test_openapi_contract.py -v`

Expected: PASS，说明非流式 [`/chat`](src/runtime/api/routes.py:28) 未被破坏。

### Task 3: 新增 chat 步骤事件流接口

**Files:**
- Modify: `src/runtime/api/routes.py`
- Modify: `src/tests/integration/test_openapi_contract.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: 写失败测试**

在 [`src/tests/integration/test_openapi_contract.py`](src/tests/integration/test_openapi_contract.py) 添加：

```python
def test_chat_stream_returns_step_final_and_done_events():
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/chat/stream',
        json={
            'user_id': 'u-demo-001',
            'role': 'medical_office',
            'message': '患者 P001 本次医保结算失败，帮我看一下原因',
            'patient_id': 'P001',
            'encounter_id': 'E001',
        },
    )

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    text = response.text
    assert 'event: step' in text
    assert 'intent_detection' in text
    assert 'risk_control' in text
    assert 'scenario_processing' in text
    assert 'event: final' in text
    assert 'settlement_exception_guidance' in text
    assert 'event: done' in text
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py::test_chat_stream_returns_step_final_and_done_events -v`

Expected: FAIL，状态码 `404`。

- [ ] **Step 3: 实现 [`/chat/stream`](src/runtime/api/routes.py:28)**

在 [`src/runtime/api/routes.py`](src/runtime/api/routes.py) 导入：

```python
from collections.abc import Iterator

from fastapi.responses import StreamingResponse

from src.runtime.api.streaming import sse_event
```

新增路由：

```python
@router.post('/chat/stream')
def chat_stream(request: ChatRequest) -> StreamingResponse:
    def events() -> Iterator[str]:
        try:
            yield sse_event('step', {'step': 'intent_detection', 'message': '正在识别意图'})
            yield sse_event('step', {'step': 'risk_control', 'message': '正在检查高风险动作'})
            yield sse_event('step', {'step': 'authorization', 'message': '正在校验角色权限'})
            yield sse_event('step', {'step': 'scenario_processing', 'message': '正在执行场景导办'})
            result = process_chat_request(request)
            yield sse_event('step', {'step': 'response_rendering', 'message': '正在生成结构化结果'})
            yield sse_event('final', result.model_dump())
        except HTTPException as exc:
            yield sse_event('error', {'status_code': exc.status_code, 'detail': exc.detail})
        except Exception as exc:
            yield sse_event('error', {'error_code': 'STREAM_ERROR', 'message': str(exc)})
        yield sse_event('done', {})

    return StreamingResponse(events(), media_type='text/event-stream')
```

- [ ] **Step 4: 运行测试确认绿灯**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py::test_chat_stream_returns_step_final_and_done_events -v`

Expected: PASS。

### Task 4: 新增 model-test 流式接口

**Files:**
- Modify: `src/runtime/api/routes.py`
- Modify: `src/tests/integration/test_openapi_contract.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: 写失败测试**

在 [`src/tests/integration/test_openapi_contract.py`](src/tests/integration/test_openapi_contract.py) 添加：

```python
def test_model_test_stream_returns_delta_final_and_done_events(monkeypatch):
    from src.model_service.models import StreamChunk, TokenUsage
    from src.runtime.api import routes

    def fake_generate_stream(self, messages, model_type, scene):
        yield StreamChunk(content='你', finish_reason=None, usage=None)
        yield StreamChunk(content='好', finish_reason='stop', usage=TokenUsage(prompt_tokens=1, completion_tokens=2))

    monkeypatch.setattr(routes.ModelGateway, 'generate_stream', fake_generate_stream)
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/model-test/stream',
        json={'message': '你好', 'scene': 'default'},
    )

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    text = response.text
    assert 'event: start' in text
    assert 'event: delta' in text
    assert '你' in text
    assert '好' in text
    assert 'event: final' in text
    assert 'event: done' in text
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py::test_model_test_stream_returns_delta_final_and_done_events -v`

Expected: FAIL，状态码 `404`。

- [ ] **Step 3: 实现 [`/model-test/stream`](src/runtime/api/routes.py:94)**

在 [`src/runtime/api/routes.py`](src/runtime/api/routes.py) 新增路由：

```python
@router.post('/model-test/stream')
def model_test_stream(request: ModelTestRequest) -> StreamingResponse:
    def events() -> Iterator[str]:
        gateway = ModelGateway()
        messages = [Message(role='user', content=request.message)]
        yield sse_event('start', {'scene': request.scene})
        completion_tokens = 0
        prompt_tokens = 0
        finish_reason = None
        try:
            for chunk in gateway.generate_stream(messages=messages, model_type='llm', scene=request.scene):
                if chunk.content:
                    yield sse_event('delta', {'content': chunk.content})
                if chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
            yield sse_event('final', {
                'scene': request.scene,
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'finish_reason': finish_reason or 'stop',
            })
        except Exception as exc:
            yield sse_event('error', {'error_code': 'MODEL_STREAM_ERROR', 'message': str(exc)})
        yield sse_event('done', {})

    return StreamingResponse(events(), media_type='text/event-stream')
```

- [ ] **Step 4: 运行测试确认绿灯**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py::test_model_test_stream_returns_delta_final_and_done_events -v`

Expected: PASS。

### Task 5: 前端新增流式模式开关与通用 SSE parser

**Files:**
- Modify: `src/static/index.html`
- Manual: `src/static/index.html`

- [ ] **Step 1: 添加流式模式开关 UI**

在 [`src/static/index.html`](src/static/index.html) 侧边栏角色/患者信息附近增加：

```html
  <div class="form-group">
    <label>响应模式</label>
    <select id="streamMode">
      <option value="stream" selected>流式模式</option>
      <option value="normal">非流式模式</option>
    </select>
  </div>
```

- [ ] **Step 2: 添加模式读取函数**

```javascript
function isStreamMode() { return document.getElementById('streamMode').value === 'stream'; }
```

- [ ] **Step 3: 添加可更新消息气泡函数**

```javascript
function addStreamingMsg(title) {
  const el = document.getElementById('emptyState');
  if (el) el.remove();
  const messages = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = '<div class="bubble"><h3>' + escapeHtml(title) + '</h3><div class="stream-content"></div></div>';
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div.querySelector('.stream-content');
}
```

- [ ] **Step 4: 添加 SSE 解析函数**

```javascript
function parseSseBlock(block) {
  const lines = block.split('\n');
  let event = 'message';
  let data = '';
  lines.forEach(function(line) {
    if (line.startsWith('event: ')) event = line.slice(7).trim();
    if (line.startsWith('data: ')) data += line.slice(6);
  });
  return { event: event, data: data ? JSON.parse(data) : {} };
}

async function readSse(resp, onEvent) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    buffer += decoder.decode(result.value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    parts.forEach(function(part) {
      if (part.trim()) onEvent(parseSseBlock(part));
    });
  }
  if (buffer.trim()) onEvent(parseSseBlock(buffer));
}
```

### Task 6: 前端业务导办接入 chat/stream 并保留非流式回退

**Files:**
- Modify: `src/static/index.html`
- Manual: `src/static/index.html`

- [ ] **Step 1: 修改 [`callChat()`](src/static/index.html:239) 分流**

```javascript
async function callChat(msg) {
  if (isStreamMode()) {
    await callChatStream(msg);
    return;
  }
  await callChatNormal(msg);
}
```

- [ ] **Step 2: 将现有 [`callChat()`](src/static/index.html:239) 改名为 `callChatNormal()`**

保留现有非流式逻辑，只改函数名：

```javascript
async function callChatNormal(msg) {
  const body = {
    user_id: userId,
    role: getRole(),
    message: msg,
    patient_id: getPatientId() || null,
    encounter_id: getEncounterId() || null,
  };
  try {
    const resp = await fetch(API + '/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await resp.json();
    if (!resp.ok) {
      const detail = data.detail || {};
      addMsg('bot', '<span style="color:#f53f3f">' + escapeHtml(detail.error_code || 'ERROR') + '：' + escapeHtml(detail.message || resp.statusText) + '</span>');
      return;
    }
    addMsg('bot', renderResult(data));
  } catch (e) {
    addMsg('bot', '<span style="color:#f53f3f">请求失败：' + escapeHtml(e.message) + '</span>');
  }
}
```

- [ ] **Step 3: 新增 `callChatStream()`**

```javascript
async function callChatStream(msg) {
  const body = {
    user_id: userId,
    role: getRole(),
    message: msg,
    patient_id: getPatientId() || null,
    encounter_id: getEncounterId() || null,
  };
  const area = addStreamingMsg('业务导办流式执行');
  try {
    const resp = await fetch(API + '/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!resp.ok || !resp.body) {
      area.innerHTML += '<div style="color:#f53f3f">流式请求失败，切换为非流式重试中...</div>';
      await callChatNormal(msg);
      return;
    }
    await readSse(resp, function(evt) {
      if (evt.event === 'step') {
        area.innerHTML += '<div class="task-item">' + escapeHtml(evt.data.message || evt.data.step) + '</div>';
      }
      if (evt.event === 'final') {
        area.innerHTML += renderResult(evt.data);
      }
      if (evt.event === 'error') {
        area.innerHTML += '<div style="color:#f53f3f">' + escapeHtml(evt.data.message || '流式执行失败') + '</div>';
      }
    });
  } catch (e) {
    area.innerHTML += '<div style="color:#f53f3f">流式请求失败：' + escapeHtml(e.message) + '</div>';
  }
}
```

### Task 7: 前端模型测试接入 model-test/stream 并保留非流式回退

**Files:**
- Modify: `src/static/index.html`
- Manual: `src/static/index.html`

- [ ] **Step 1: 修改 [`testModel()`](src/static/index.html:276) 分流**

```javascript
async function testModel(msg) {
  if (isStreamMode()) {
    await testModelStream(msg);
    return;
  }
  await testModelNormal(msg);
}
```

- [ ] **Step 2: 将现有 [`testModel()`](src/static/index.html:276) 改名为 `testModelNormal()`**

保留现有非流式容错逻辑，只改函数名。

- [ ] **Step 3: 新增 `testModelStream()`**

```javascript
async function testModelStream(msg) {
  addMsg('user', '[模型测试] ' + escapeHtml(msg));
  const area = addStreamingMsg('模型服务流式测试');
  let text = '';
  try {
    const resp = await fetch(API + '/model-test/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, scene: 'default' }),
    });
    if (!resp.ok || !resp.body) {
      area.innerHTML += '<div style="color:#f53f3f">流式请求失败，切换为非流式重试中...</div>';
      await testModelNormal(msg);
      return;
    }
    await readSse(resp, function(evt) {
      if (evt.event === 'delta') {
        text += evt.data.content || '';
        area.innerHTML = '<div style="white-space:pre-wrap">' + escapeHtml(text) + '</div>';
      }
      if (evt.event === 'final') {
        area.innerHTML += '<div class="citation">完成：' + escapeHtml(evt.data.finish_reason || 'stop') + '</div>';
      }
      if (evt.event === 'error') {
        area.innerHTML += '<div style="color:#f53f3f">' + escapeHtml(evt.data.message || '模型流式调用失败') + '</div>';
      }
    });
  } catch (e) {
    area.innerHTML += '<div style="color:#f53f3f">流式请求失败：' + escapeHtml(e.message) + '</div>';
  }
}
```

### Task 8: 完整验证与页面手工验收

**Files:**
- Test: `src/tests`
- Manual: `src/static/index.html`

- [ ] **Step 1: 运行流式相关测试**

Run: `python -m pytest src/tests/unit/test_streaming_events.py src/tests/integration/test_openapi_contract.py -v`

Expected: PASS。

- [ ] **Step 2: 运行完整测试**

Run: `python -m pytest src/tests -v`

Expected: PASS。

- [ ] **Step 3: 重启页面服务**

Run: `uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 18080 --factory`

Expected: 服务启动在 [`http://127.0.0.1:18080/`](src/runtime/api/app.py:17)。

- [ ] **Step 4: 页面验证流式模式**

打开 [`http://127.0.0.1:18080/`](src/runtime/api/app.py:17)，选择“流式模式”：

- 点击 [`LLM 基础调用`](src/static/index.html:94)：文本分片追加
- 点击 [`结算异常导办`](src/static/index.html:87)：先展示步骤事件，再展示结构化结果卡片

- [ ] **Step 5: 页面验证非流式模式**

切换到“非流式模式”：

- 点击 [`LLM 基础调用`](src/static/index.html:94)：保持一次性 JSON 渲染
- 点击 [`结算异常导办`](src/static/index.html:87)：保持现有一次性结构化卡片

## 自检结果

- 规格覆盖：已覆盖保留非流式接口、新增两个流式接口、业务步骤事件、模型 delta 分片、前端开关、失败回退、测试与页面验收。
- 占位符扫描：未保留 `TBD`、`TODO` 或缺少具体代码的步骤。
- 类型一致性：计划中使用的 [`ChatRequest`](src/runtime/api/schemas.py:6)、[`ModelTestRequest`](src/runtime/api/schemas.py:60)、[`AgentResponse`](src/runtime/api/schemas.py:14)、[`StreamChunk`](src/model_service/models.py) 均为现有类型。
