# medical-insurance-ai-agent 开发计划设计

## 1. 背景与目标

本开发计划基于 OpenSpec 变更 `add-medical-insurance-ai-agent` 生成，目标是把医保 AI 导办智能体从规范推进到可编码、可测试、可演示的后端 MVP。

相关 OpenSpec 产物：

- `openspec/changes/add-medical-insurance-ai-agent/proposal.md`
- `openspec/changes/add-medical-insurance-ai-agent/design.md`
- `openspec/changes/add-medical-insurance-ai-agent/specs/medical-insurance-ai-agent/spec.md`
- `openspec/changes/add-medical-insurance-ai-agent/tasks.md`

第一阶段实现目标：

1. 建立 `FastAPI` 后端 MVP 工程骨架。
2. 使用内存数据、内存知识库、内存适配器和内存审计记录打通核心业务链路。
3. 实现医保结算异常导办和出院前联合质控两个端到端 MVP 场景。
4. 固化 `Chat API`、患者上下文 API、统一响应结构和 OpenAPI 契约。
5. 通过 `pytest` 与 `FastAPI TestClient` 覆盖关键验收场景。
6. 通过端口与适配器预留 `PostgreSQL`、`Redis/Valkey`、`Milvus` 和真实医院系统替换边界。

第一阶段不做：

1. 不接入真实 `PostgreSQL`、`Redis/Valkey`、`Milvus`、`Nginx`。
2. 不接入真实首信、东软、大瑞集思、HIS、EMR、病案和收费系统。
3. 不创建完整 `Vue 3` 前端工程。
4. 不实现自动结算、自动退费冲正、自动修改病案首页或自动修改费用明细。
5. 不实现多智能体自由自治执行。

## 2. 开发计划组织方式

采用“端到端薄切片优先”的方式，而不是按模块孤立开发。每个切片都必须形成一个可运行、可测试、可验收的小闭环。

总体节奏：

```text
切片 0：工程骨架与测试基线
  ↓
切片 1：医保结算异常导办最小闭环
  ↓
切片 2：权限、脱敏、澄清与高风险拦截
  ↓
切片 3：出院前联合质控最小闭环
  ↓
切片 4：编排、审计、任务闭环增强
  ↓
切片 5：基础设施替换端口与 OpenAPI 契约固化
  ↓
切片 6：验收测试、质量门禁和交付准备
```

每个切片包含：

1. 对应 OpenSpec 任务编号。
2. 目标行为。
3. 代码交付物。
4. 测试用例。
5. 验收标准。
6. 明确不做事项。

## 3. 目标工程架构与 MVP 落点

用户确认的长期工程架构采用 `Project-root/` 分层目录，覆盖多入口应用、交互层、网关、运行时、业务场景、知识扩展、业务适配器、模型服务、数据平台、领域模型、配置、安全、可观测性、共享基础库、部署与测试。

长期结构如下：

```text
Project-root/
├── apps/
├── interaction/
├── gateway/
├── runtime/
├── business_scenarios/
├── knowledge_extension/
├── adapters/
├── model_service/
├── data_platform/
├── domain/
├── config/
├── security/
├── observability/
├── shared/
├── docs/
├── scripts/
├── deploy/
└── tests/
```

第一阶段 MVP 不把所有目录都做成完整子系统，而是在长期架构下实现最小可运行后端闭环。

| 长期目录 | MVP 落点 | 第一阶段说明 |
|---|---|---|
| `runtime/` | 主要实现目录 | 承载 FastAPI 入口、会话、上下文、意图、澄清、规划、编排、响应、任务闭环和运行态状态 |
| `business_scenarios/` | 主要实现目录 | 实现医保结算异常导办和出院前联合质控两个场景 |
| `domain/` | 主要实现目录 | 沉淀患者、医保、费用、审核风险、DRG/DIP、病案、任务和通用值对象 |
| `adapters/` | 主要实现目录 | 定义适配器协议并提供内存适配器，真实系统后置 |
| `data_platform/` | 主要实现目录 | 提供内存数据访问、患者画像、知识数据、数据质量与来源引用 |
| `knowledge_extension/` | MVP 子集 | 只做知识检索、RAG 引用、规则解释和提示模板的内存实现 |
| `security/` | MVP 子集 | 只做权限、脱敏、高风险动作拦截和审计 |
| `shared/` | MVP 子集 | 放通用异常、Schema、常量、工具和事件对象 |
| `config/` | MVP 子集 | 放角色权限、场景流程、高风险动作、模型降级和适配器配置 |
| `observability/` | MVP 子集 | 只做结构化日志与审计指标占位 |
| `apps/` | 暂缓 | 不实现完整门户和前端入口，只在 API 契约上支撑后续入口 |
| `interaction/` | 暂缓 | 不实现文件、语音、通知和知识上传，只保留 Chat 请求模型 |
| `gateway/` | 暂缓 | 不实现 API 网关、SSO、租户隔离和限流熔断真实能力，仅预留接口边界 |
| `model_service/` | 暂缓 | 不接真实大模型，第一阶段用确定性模板替代模型结果 |
| `deploy/` | 暂缓 | 不做生产部署，仅保留后续部署目录规划 |

## 4. MVP 建议工程结构

第一阶段直接采用长期目录的后端子集，避免先创建临时目录后再大规模迁移。

```text
runtime/
├── api/
│   ├── app.py
│   ├── routes.py
│   └── schemas.py
├── session/
├── context/
├── intent/
├── clarification/
├── planning/
├── orchestration/
├── scheduling/
├── response/
├── task_closure/
└── runtime_state/
business_scenarios/
├── settlement_exception_guide/
└── pre_discharge_joint_qc/
knowledge_extension/
├── knowledge/
├── rag/
├── rule_explanation/
└── prompt_templates/
adapters/
├── base/
├── insurance_interface/
├── pre_audit/
├── drg_dip/
├── his/
├── emr/
├── billing/
└── medical_record/
data_platform/
├── data_access/
├── patient_profile/
├── data_quality/
├── master_data/
└── storage/
    ├── relational/
    ├── vector/
    ├── object/
    └── cache/
domain/
├── patient/
├── insurance/
├── order_fee/
├── audit_risk/
├── drg_dip/
├── medical_record/
├── task/
└── common/
config/
├── agent_orchestration/
├── adapter/
├── knowledge/
└── security_policy/
security/
├── authorization/
├── desensitization/
├── risk_control/
└── audit/
shared/
├── constants/
├── exceptions/
├── schemas/
├── utils/
└── events/
tests/
├── unit/
├── integration/
├── e2e/
├── adapter_contract/
├── rag_evaluation/
└── security/
```

结构原则：

1. `domain/` 只放领域对象和值对象，不依赖 FastAPI、数据库或外部系统。
2. `runtime/` 承载 Agent 核心运行时，负责上下文、意图、规划、编排、响应和任务闭环。
3. `business_scenarios/` 承载医保业务场景编排模板和场景结果构建，不直接访问真实系统。
4. `adapters/` 定义外部系统适配器协议和第一阶段内存适配器。
5. `data_platform/` 提供数据访问、患者画像、数据质量、知识数据和存储端口。
6. `knowledge_extension/` 提供知识检索、规则解释、RAG 引用和模板能力。
7. `security/` 提供权限、脱敏、高风险动作拦截和审计能力。
8. `shared/` 放通用 Schema、异常、事件、常量和工具，避免各层重复定义。
9. `runtime/api/` 只负责 HTTP 请求响应转换、依赖组装和错误映射。
10. 第一阶段内存实现应放在对应模块内部的 `memory` 或 `in_memory` 文件中，后续再替换为真实基础设施实现。

## 4. 切片 0：工程骨架与测试基线

### 对应 OpenSpec 任务

- 2.1 创建 Python 后端项目结构。
- 2.2 添加 FastAPI 应用入口和 uvicorn 启动入口。
- 2.3 添加健康检查 API 和版本信息 API。
- 2.4 建立依赖注入容器。
- 2.5 添加基础异常模型和统一错误响应结构。
- 2.6 添加 pytest 测试配置和 FastAPI TestClient 测试夹具。
- 10.8 验证 OpenAPI 文档能够暴露相关接口。

### 目标行为

后端应用可以通过 `create_app()` 创建 FastAPI 实例，健康检查、版本信息和 OpenAPI 文档可访问。测试环境可以通过内存容器启动应用。

### 代码交付物

1. `runtime/api/app.py`
2. `runtime/api/routes.py`
3. `runtime/api/schemas.py`
4. `shared/exceptions/`
5. `shared/schemas/`
6. `tests/conftest.py`
7. 基础测试文件

### 测试用例

1. `GET /health` 返回健康状态。
2. `GET /api/v1/medical-insurance-ai-agent/version` 返回模块版本和 MVP 模式。
3. `GET /openapi.json` 包含 Chat、患者上下文、流程状态和任务相关路径占位。

### 验收标准

1. `pytest` 可以运行。
2. FastAPI 应用可通过 TestClient 创建。
3. OpenAPI 文档可生成。
4. 未引入真实数据库、缓存、向量库依赖作为启动前置条件。

### 不做事项

1. 不实现具体医保业务逻辑。
2. 不连接外部基础设施。

## 5. 切片 1：医保结算异常导办最小闭环

### 对应 OpenSpec 任务

- 1.3 固化医保结算异常导办样例。
- 1.6 准备内存样例数据。
- 3.1 至 3.10 数据与知识底座基础能力。
- 4.1、4.2、4.7 至 4.9 业务系统适配基础能力。
- 5.1、5.3、5.4、5.8 Chat、意图识别、对象抽取和上下文构建。
- 6.1 至 6.3、6.6、6.8 规划能力。
- 7.1 至 7.6 编排基础能力。
- 8.1、8.2、8.6、8.7 MVP 输出。
- 10.1、10.5、10.6、10.7 验收测试。

### 目标行为

用户请求“患者医保结算失败原因”时，系统可以识别为医保结算异常导办，查询内存医保交易、费用上传状态、错误码知识和收费状态，返回可追溯的处理建议。

### 代码交付物

1. 结算异常场景样例数据。
2. `runtime/intent` 意图识别服务。
3. `runtime/context` 上下文构建服务。
4. `runtime/planning` 的结算异常模板。
5. `runtime/orchestration` 的顺序执行能力。
6. `adapters/insurance_interface`、`adapters/billing` 内存适配器。
7. `knowledge_extension/rule_explanation` 错误码知识库。
8. `business_scenarios/settlement_exception_guide` 结果构建器。

### 测试用例

1. 输入患者和就诊后返回 `scenario=settlement_exception_guidance`。
2. 返回异常类型、错误码解释、可能原因、涉及系统、责任角色、推荐步骤。
3. 返回 `citations`，至少包含医保交易和错误码知识来源。
4. 外部适配器失败时返回 `status=degraded` 和不确定性提示。
5. 审计摘要包含 workflow_id 和步骤记录。

### 验收标准

1. 结算异常导办端到端测试通过。
2. 所有结论均有来源引用或不确定性提示。
3. 适配器失败不会导致未解释的 500 错误。

### 不做事项

1. 不调用真实医保接口。
2. 不执行正式结算、退费或冲正。

## 6. 切片 2：权限、脱敏、澄清与高风险拦截

### 对应 OpenSpec 任务

- 1.1 定义角色及权限边界。
- 1.2 定义最小必要字段和脱敏规则。
- 1.5 固化高风险动作黑名单。
- 5.2 患者上下文查询 API。
- 5.5 缺失关键对象澄清。
- 5.6 权限校验。
- 5.7 脱敏策略。
- 6.5 高风险动作规划模板。
- 6.7 高风险动作识别。
- 9.1、9.2 高风险动作和人工确认。
- 10.3、10.4 安全边界验收。

### 目标行为

系统可以按角色控制数据访问与展示，缺少关键上下文时返回澄清，识别退费、冲正等高风险动作并转为人工确认待办。

### 代码交付物

1. `config/security_policy` 角色权限配置。
2. `config/security_policy` 字段可见性配置。
3. `config/security_policy` 高风险动作黑名单。
4. `security/authorization` 权限服务。
5. `security/desensitization` 脱敏服务。
6. `runtime/clarification` 澄清响应模型。
7. `security/risk_control` 高风险动作识别。
8. `runtime/task_closure` 人工确认待办创建逻辑。

### 测试用例

1. 缺少 patient_id 和 encounter_id 时返回 `needs_clarification`。
2. 临床医生访问结算异常导办时返回 403 和权限审计事件。
3. 收费员和医保办查询患者上下文时看到不同字段集合。
4. 患者姓名脱敏为类似“张**”。
5. “直接退费冲正”请求返回 `waiting_human_confirmation`，并创建人工确认待办。

### 验收标准

1. 越权请求不会泄露患者或结算明细。
2. 高风险动作不进入自动执行步骤。
3. 澄清响应不会编造患者、就诊或业务对象。

### 不做事项

1. 不实现真实身份认证。
2. 不绕过既有业务系统执行高风险动作。

## 7. 切片 3：出院前联合质控最小闭环

### 对应 OpenSpec 任务

- 1.4 固化出院前联合质控样例。
- 3.4、3.5、3.8、3.9 患者画像、规则解释和来源引用。
- 4.3 至 4.6、4.7 事前审核、DRG/DIP、HIS/EMR/病案和任务适配器。
- 5.3 意图识别。
- 6.4 出院前联合质控规划模板。
- 8.3 至 8.7 联合质控、任务创建和统一响应结构。
- 10.2、10.5、10.7 验收测试。

### 目标行为

用户请求“检查患者出院前医保风险”时，系统聚合费用、医嘱、病案、事前审核、DRG/DIP 和医保接口状态，返回联合质控风险清单并生成整改待办。

### 代码交付物

1. 出院前联合质控样例数据。
2. `adapters/pre_audit` 内存事前审核适配器。
3. `adapters/drg_dip` 内存 DRG/DIP 适配器。
4. `adapters/his`、`adapters/emr`、`adapters/medical_record` 内存适配器。
5. `knowledge_extension/rule_explanation` 规则解释知识库。
6. `business_scenarios/pre_discharge_joint_qc` 联合质控风险清单构建器。
7. `runtime/task_closure` 内存任务系统能力。

### 测试用例

1. 返回 `scenario=pre_discharge_quality_control`。
2. 风险清单包含合规拒付风险、DRG/DIP 支付风险、病案首页风险。
3. 每项风险包含风险等级、责任角色、处理建议和来源引用。
4. 风险项可生成待办任务，任务状态为 `pending`。
5. 审计记录可追溯查询、规则解释和任务创建步骤。

### 验收标准

1. 联合质控端到端测试通过。
2. 任务创建与风险项、患者、就诊和证据引用关联。
3. 数据缺失时返回不确定性提示，而不是确定性结论。

### 不做事项

1. 不修改病案首页。
2. 不修改费用明细。
3. 不替代正式 DRG/DIP 分组结果。

## 8. 切片 4：编排、审计、任务闭环增强

### 对应 OpenSpec 任务

- 7.1 至 7.9 编排执行。
- 9.2 至 9.5 人工确认、审计视图、任务状态和指标。
- 10.6、10.7 验收测试。

### 目标行为

编排引擎支持工作流实例、步骤状态、失败重试、降级、人工确认暂停恢复、状态查询和审计还原。任务闭环支持状态流转和基础指标。

### 代码交付物

1. `domain/common`、`runtime/runtime_state` 中的 `WorkflowInstance` 和 `StepState`。
2. `runtime/runtime_state` 工作流状态存储。
3. `runtime/orchestration` 步骤执行器注册机制。
4. `runtime/scheduling` 重试与降级策略。
5. `runtime/task_closure` 人工确认暂停和恢复接口。
6. `security/audit` 审计查询服务。
7. `domain/task` 与 `runtime/task_closure` 任务状态流转和指标服务。

### 测试用例

1. 工作流步骤按依赖顺序执行。
2. 某个适配器失败后按策略重试或降级。
3. 人工确认节点将工作流置为 `WAITING_CONFIRM`。
4. 恢复人工确认后工作流继续执行。
5. 审计视图可以还原用户、计划、步骤、调用、确认和结果。
6. 任务从 `pending` 到 `in_progress`、`completed`、`closed` 的流转受控。

### 验收标准

1. 工作流状态可查询。
2. 步骤输入输出引用可追溯。
3. 失败、降级和人工确认均有审计记录。

### 不做事项

1. 不引入复杂第三方工作流引擎。
2. 不实现分布式执行。

## 9. 切片 5：基础设施替换端口与 OpenAPI 契约固化

### 对应 OpenSpec 任务

- 2.4 依赖注入容器。
- 9.6 PostgreSQL 审计日志仓储端口。
- 9.7 Redis/Valkey 会话缓存、限流和分布式锁端口。
- 9.8 Milvus 向量检索端口。
- 8.7 Web SDK 友好的统一响应结构。
- 10.8 OpenAPI 验证。

### 目标行为

在不接真实基础设施的前提下，完成端口定义、内存实现、依赖注入和 API 契约固化，保证后续替换不影响上层业务逻辑。

### 代码交付物

1. `data_platform/data_access` 数据访问端口。
2. `security/audit` 审计日志端口。
3. `data_platform/storage/cache` 缓存端口。
4. `knowledge_extension/rag` 知识检索端口。
5. `runtime/task_closure` 任务存储端口。
6. 各端口内存实现。
7. `runtime/api/schemas.py` OpenAPI schema 示例。
8. `shared/schemas` 统一响应模型。

### 测试用例

1. 替换容器中的端口实现时，上层服务测试无需修改。
2. OpenAPI 中存在 Chat 和患者上下文路径。
3. Chat 响应结构包含 `scenario`、`status`、`result`、`citations`、`tasks`、`missing_fields`、`uncertainties`、`blocked_actions`、`audit`。

### 验收标准

1. 所有基础设施通过端口访问。
2. `services/` 不直接依赖具体内存实现。
3. API 响应契约稳定。

### 不做事项

1. 不实现真实 PostgreSQL schema migration。
2. 不实现真实 Redis/Valkey 连接。
3. 不实现真实 Milvus embedding 与向量写入。

## 10. 切片 6：验收测试、质量门禁和交付准备

### 对应 OpenSpec 任务

- 10.1 至 10.8 全部验证任务。

### 目标行为

形成可重复运行的自动化测试套件，覆盖两个 MVP 场景、安全边界、降级行为、来源引用、审计还原和 OpenAPI 契约。

### 代码交付物

1. `tests/unit` 单元测试套件。
2. `tests/integration` 集成测试套件。
3. `tests/e2e` 端到端测试套件。
4. `tests/adapter_contract` 适配器契约测试。
5. `tests/security` 权限与安全测试。
6. 测试夹具与样例数据构建器。
7. README 或开发运行说明。
8. 本地启动命令说明。
9. 后续真实基础设施接入清单。

### 测试用例

1. 医保结算异常导办完整输出。
2. 出院前联合质控完整输出。
3. 权限不足拦截。
4. 高风险动作拦截。
5. 所有 AI 输出具备来源引用或不确定性提示。
6. 外部系统失败降级。
7. 审计记录还原。
8. OpenAPI 文档接口暴露。

### 验收标准

1. 所有测试通过。
2. 测试输出无未解释错误和警告。
3. 开发者可按文档在本地启动后端 MVP。
4. OpenSpec 任务可按完成情况逐项勾选。

### 不做事项

1. 不进行生产部署。
2. 不承诺性能压测结果。

## 11. 长期目录与 MVP 分阶段启用策略

第一阶段必须坚持“长期架构对齐、MVP 子集实现”。目录启用策略如下：

1. 必须启用：`runtime/`、`business_scenarios/`、`domain/`、`adapters/`、`data_platform/`、`knowledge_extension/`、`security/`、`shared/`、`config/`、`tests/`。
2. 部分启用：`observability/` 只启用日志、审计和指标占位。
3. 暂缓启用：`apps/`、`interaction/`、`gateway/`、`model_service/`、`deploy/`。
4. 暂缓目录可以先不创建，避免空目录膨胀；如需表达长期架构，可在文档中保留。
5. MVP 代码不得为了满足长期目录而拆得过碎；单个文件过大或职责变多时再拆分。

## 12. TDD 执行策略

每个切片按 TDD 执行：

```text
写失败测试
  ↓
运行并确认 RED
  ↓
写最小实现
  ↓
运行并确认 GREEN
  ↓
重构和补充边界测试
  ↓
更新 OpenSpec tasks.md 勾选项
```

测试优先级：

1. API 行为测试优先，保证外部契约稳定。
2. 服务层单元测试补充复杂分支。
3. 端口替换测试保证基础设施可替换。
4. 审计和安全边界测试必须覆盖失败路径。

## 13. 里程碑与交付物

| 里程碑 | 范围 | 主要交付物 | 验收方式 |
|---|---|---|---|
| M0 | 工程骨架 | FastAPI 应用、健康检查、测试基线 | OpenAPI 与 pytest 可运行 |
| M1 | 结算异常导办 | 结算异常端到端闭环 | API 测试通过 |
| M2 | 安全边界 | 权限、脱敏、澄清、高风险拦截 | 安全边界测试通过 |
| M3 | 出院前质控 | 联合质控与整改任务 | 场景测试通过 |
| M4 | 编排审计 | 工作流、审计、任务闭环增强 | 审计还原测试通过 |
| M5 | 契约固化 | 端口、统一响应、OpenAPI | 契约测试通过 |
| M6 | MVP 交付 | 文档、测试、任务勾选 | 全量验收通过 |

## 14. 风险与控制

| 风险 | 控制措施 |
|---|---|
| MVP 内存实现与生产差距过大 | 所有基础设施访问必须通过端口，禁止服务层直接依赖内存实现 |
| 业务场景被实现成不可追溯问答 | 所有结果必须包含 Citation 或 uncertainty |
| 高风险动作误执行 | 规划与编排双层拦截，测试覆盖退费、冲正、病案修改等动作 |
| 任务过多导致开发失焦 | 以端到端切片推进，每个切片只完成当前闭环最小能力 |
| API 不适合前端复用 | 响应结构固定为 Web SDK 友好模型，并通过 OpenAPI 验证 |
| 缺少真实系统导致逻辑失真 | 样例数据覆盖医保交易、费用上传、审核、DRG/DIP、病案风险和失败降级 |
| 长期目录过大导致 MVP 复杂化 | MVP 只启用长期架构中的后端核心子集，未启用目录保持占位或延后创建 |

## 15. 开发计划验收定义

开发计划完成后，应满足：

1. 可以直接转化为逐步编码实施计划。
2. 每个切片都能映射到 OpenSpec 任务编号。
3. 每个切片都有测试、交付物和验收标准。
4. 第一阶段范围清晰，不混入真实基础设施和完整前端工程。
5. 后续从内存 MVP 演进到 PostgreSQL、Redis/Valkey、Milvus 和真实系统接入时，不需要推翻核心架构。

## 16. 建议下一步

在本设计获得确认后，进入 implementation plan 阶段，生成可执行编码计划。编码计划应进一步细化为：

1. 每次提交的文件列表。
2. 每个测试的名称和预期失败原因。
3. 每个实现步骤的最小代码范围。
4. 每个切片完成后需要勾选的 OpenSpec 任务项。
5. 每个阶段的验证命令。
