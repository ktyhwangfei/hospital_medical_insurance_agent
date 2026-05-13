# runtime/ — Agent 核心运行时

## 概述

Agent 的"大脑"：API 入口、意图识别、LangGraph 编排、技能执行、任务闭环。

## 结构

```
runtime/
├── api/                  # FastAPI 路由 + SSE 流式
│   ├── app.py            # create_app() 工厂（uvicorn 入口）
│   ├── routes.py         # /chat, /tasks, /workflows, /patient-context
│   ├── knowledge_routes.py # /knowledge/* 知识管理 CRUD（481行）
│   ├── model_routes.py   # /model-test, /model-config, /model-routes, /model-providers（353行）
│   ├── skill_routes.py   # /skills, /tools CRUD
│   ├── mcp_routes.py     # /mcp/servers, /mcp/storage/health
│   ├── schemas.py        # AgentResponse, ChatRequest 等 Pydantic 模型
│   └── streaming.py      # SSE 事件格式化
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
  → routes.py: detect_intent_smart()        # 意图识别
  → orchestrator.py: RuntimeOrchestrator     # 流程控制
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
- `knowledge_routes.py`（481行）和 `model_routes.py`（353行）是最大的两个路由文件
- `intent/graph/` 是 LangGraph 图式意图识别（5 节点 DAG），与关键词解析器是双路径关系
