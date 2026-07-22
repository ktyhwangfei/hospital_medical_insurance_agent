# runtime/ — Agent 核心运行时

## 概述

Agent 的"大脑"：API 入口、意图识别、LangGraph 编排、技能执行、任务闭环。

## 结构

```
runtime/
├── api/                  # FastAPI 路由 + SSE 流式
│   ├── app.py            # create_app() 工厂（uvicorn 入口），注册 5 个路由模块
│   ├── policy_qa_routes.py     # /policy-qa/stream, /settlement-explanation, /history（920 行）
│   ├── policy_knowledge_routes.py # /policy-knowledge/rules/* Milvus CRUD（285 行）
│   ├── model_routes.py   # /model-config, /model-routes, /model-providers（434 行，17 端点）
│   ├── mcp_routes.py     # /mcp/servers, /mcp/capabilities, /mcp/storage/health（81 行，9 端点）
│   ├── infra_skill_routes.py  # /infra-skills/*（148 行，4 端点）
│   ├── skill_routes.py   # ⚠️ 未注册（导入不存在模块，死代码）
│   ├── policy_qa/        # 政策问答核心（已迁移到 skills/settlement_explain_skill）
│   │   ├── orchestrator.py   # 旧编排器（DEPRECATED — 使用 SkillRouter + assembler）
│   │   └── structured_policy_retriever.py # Milvus 结构化策略检索
│   ├── schemas.py        # AgentResponse, ChatRequest 等 Pydantic 模型
│   ├── streaming.py      # SSE 事件格式化
│   └── streaming_emitter.py  # SSE 流式发射器
├── intent/               # 意图识别
│   ├── parser.py         # LLM 解析（降级到关键词）
│   ├── registry.py       # 意图注册表
│   ├── service.py        # detect_intent_smart()
│   ├── skill_matcher.py  # 技能匹配
│   ├── knowledge.py      # 知识型意图
│   └── graph/            # LangGraph 图式意图识别
│       ├── graph.py      #   IntentGraph 定义
│       ├── state.py      #   图状态
│       ├── config.py     #   图配置
│       └── nodes/        #   图节点（candidate_retrieval/discrimination/decision/validation）
├── langgraph/            # LangGraph 编排
│   ├── settlement_exception.py  # 结算异常图
│   ├── pre_discharge_qc.py      # 出院前质控图
│   ├── checkpoint.py     # _checkpoint_registry（task_id→graph映射）
│   ├── postgresql_checkpointer.py # PostgreSQL 检查点持久化
│   ├── graph_builder.py  # 通用图构建器
│   ├── base_state.py     # 基础状态
│   └── nodes.py          # 共享节点
├── orchestrator.py       # RuntimeOrchestrator（核心调度）
├── scenario_executor.py  # UnifiedScenarioExecutor（场景分发）★ 推荐使用
├── dependencies.py       # FastAPI 依赖注入（适配器单例）
├── orchestration/        # 编排子模块
│   └── mcp_integration.py # MCP 工具集成
├── skill_registry/       # 技能/工具执行引擎
│   ├── engine.py         #   SkillExecutionEngine
│   ├── parser.py         #   技能解析器
│   └── skill_service.py  #   Skill CRUD 服务
├── policy_qa/            # 政策问答（已迁移到 skills/settlement_explain_skill）
│   ├── orchestrator.py   #   旧编排器（DEPRECATED — 使用 SkillRouter + assembler）
│   └── structured_policy_retriever.py # Milvus 结构化策略检索（支持 custom_queries）
├── task_closure/         # 任务闭环 + PostgreSQL 存储
├── runtime_state/        # 工作流状态 + PostgreSQL 存储
├── context/              # RuntimeContext 模型
├── planning/             # 步骤规划
├── clarification/        # 缺失上下文澄清
├── event_log/            # 事件日志
├── capability_nodes/     # 可执行能力节点
└── scheduling/           # 调度服务
```

## 关键流程

```
POST /chat
  → intent/service.py: detect_intent_smart()   # 意图识别
  → orchestrator.py: RuntimeOrchestrator        # 流程控制
      ├─ security/risk_control               # 高风险检测
      ├─ scenario_executor.py                # 场景分发
      │   ├─ langgraph/*                     # LangGraph 图执行
      │   └─ skill_registry/engine           # 技能执行
      └─ model_service/gateway               # LLM 调用（如需要）
  → AgentResponse                            # 结构化结果
```

## 注意事项

- `create_app()` 是工厂函数，启动 uvicorn 必须加 `--factory`
- `_checkpoint_registry` 维护 task_id → (graph, thread_id) 映射，用于 LangGraph 人工确认恢复
- `dependencies.py` 中适配器是单例懒加载，当前只处理 `"memory"` 实现
- SSE 流式端点的 `done` 事件标志流结束
- 样例数据仅包含 `P001/E001`，`P002` 触发降级路径
- `orchestration/service.py` 和 `planning/service.py` 已 DEPRECATED — 用 `scenario_executor.py`
- `policy_qa_routes.py`（920 行）和 `model_routes.py`（434 行）是最大的两个路由文件
- `intent/graph/` 是 LangGraph 图式意图识别（5 节点 DAG），与关键词解析器是双路径关系

## 流式接口排障铁律

> **⛔ SSE / 流式接口出问题时，严格按此顺序排障，禁止跳步。**

**诊断顺序（自底向上，前一步确认正常才能进入下一步）：**

**第一步：验证数据是否真的在流式到达**

```bash
# 直接 curl 看 SSE 原始输出 — 事件是逐条返回还是等半天一次性返回？
curl -N -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"患者P001结算失败","role":"cashier","user_id":"demo","patient_id":"P001"}'
```

- 如果事件逐条到达（间隔明显）→ 后端流式正常，问题在前端
- 如果等很久然后一次性吐出一大段 → **后端流式是假的，先修后端**

**第二步：如果后端是假流式，查生成器**

- 同步生成器（`def events() -> Iterator`）：检查是否有同步阻塞调用（如 `executor.execute()`）阻塞了 `yield`
- 异步生成器（`async def events()`）：检查 `yield` 语句是否在 `await` 之前，`await` 是否耗时过长
- 关键信号：`yield from buffer` 是否在阻塞调用**之后**才执行 → 这就是根因

**第三步：确认后端流式正常后，再看前端**

- 前端 SSE 解析见 `src/apps/portal/AGENTS.md`
- 如果后端逐条发送但前端一次性渲染：查 `readSseStream` 的同步 for 循环 + React 18 批处理
- 修复：在 `onEvent(event)` 后加 `await new Promise(r => setTimeout(r, 0))` 出让渲染周期

**硬性约束：**
- 严禁在未确认后端流式正常前修改前端 UI 组件
- 严禁用 `asyncio.sleep()` 制造"假实时感" — 流式应该靠真实的事件推送，不靠人为延迟
- 任何流式端点的新增或修改，必须在 PR 描述中附上 curl 验证结果

### 快速诊断命令

```bash
# 一键检查 SSE 端点是否真正流式（前 5 秒内应看到多条 event: 行）
timeout 5 curl -N -s -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"统筹自付是什么意思","settlement_id":"1671213","session_id":"diag"}' \
  | grep "^event:" | head -20
```
