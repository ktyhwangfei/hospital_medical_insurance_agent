# AGENTS.md - 院端医保智能体系统

## 验证命令

```bash
# 运行全部测试（工作目录为项目根目录）
python -m pytest src/tests -v

# 运行单个测试文件
python -m pytest src/tests/e2e/test_settlement_exception.py -v

# 启动开发服务器（--factory 必须指定，因为 create_app 是工厂函数）
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload

# OpenSpec 验证
npx openspec validate "add-medical-insurance-ai-agent" --strict
npx openspec status --change "<name>" --json
npx openspec list --json
```

## 项目状态

- **当前阶段**: MVP 已完成，所有核心模块使用内存实现
- **已归档变更**: `openspec/changes/archive/2026-05-02-add-medical-insurance-ai-agent/`
- **基础设施**: PostgreSQL、Redis/Valkey、Milvus 仅定义端口（Protocol），不作为运行依赖

## 架构

完整架构定义见 `docs/steering/架构设计.md`，采用四层体系：SaaS 应用产品层 → PaaS 平台支撑层 → DaaS 数据与知识服务层 → 系统接入与基础设施层。

PaaS 层七个服务域是系统的核心能力分解：接入安全（gateway）、会话上下文（runtime/session+context）、智能编排（runtime/intent+planning+orchestration）、模型服务（model_service）、知识服务（knowledge_extension）、业务适配（adapters）、任务闭环（runtime/task_closure）。

当前 MVP 只实现了后端核心子集（`src/` 下），暂缓目录：`apps/`、`interaction/`、`gateway/`、`model_service/`、`deploy/`。

### 目录职责映射

Agent 编码时根据以下映射定位代码位置：

| 目录 | 职责 | 当前状态 |
|------|------|----------|
| `runtime/` | Agent 核心运行时：API 入口、会话、意图、澄清、编排、调度、响应、任务闭环 | 部分实现（api/clarification/scheduling/task_closure/runtime_state） |
| `runtime/intent/` | 意图识别：LLM 解析 + 关键词降级 + 注册表 | 已实现（intent-parsing, intent-routing） |
| `business_scenarios/` | 医保业务场景：结算异常导办、出院前联合质控 | 两个场景已实现 |
| `knowledge_extension/` | 知识与扩展：错误码知识库、RAG、规则解释、提示模板 | 仅 knowledge 实现 |
| `adapters/` | 外部系统防腐层：医保接口、事前审核、DRG/DIP、HIS、EMR、病案、收费 | 7 个内存适配器已实现，base 基类未实现 |
| `data_platform/` | DaaS 数据底座：数据访问、存储端口、患者画像、主数据、数据质量 | 仅 data_access 和 storage 端口实现 |
| `domain/` | 领域模型：患者、医保、费用、审核风险、DRG/DIP、病案、任务 | 仅 patient/insurance/task/common 实现 |
| `security/` | 安全围栏：权限、脱敏、风险控制、审计 | authorization/desensitization/risk_control/audit 实现 |
| `config/` | 全局配置：角色权限、场景流程、适配器配置 | 仅 security_policy 实现 |

### 业务流向

```
runtime/api (FastAPI 路由)
  → runtime/intent (意图识别)
  → security/risk_control (高风险拦截)
  → security/authorization (权限校验)
  → business_scenarios/{settlement_exception_guide, pre_discharge_joint_qc}
  → adapters/* (外部系统防腐层，当前均为内存实现)
  → knowledge_extension/knowledge (错误码/政策知识库)
  → 返回 AgentResponse 结构
```

### 核心约定

- **平台定位**: AI 导办与协同中枢，不替代医保正式结算/事前审核/DRG分组/病案修改等既有业务系统
- **解耦纪律**: 业务逻辑严禁耦合外部系统接口，必须通过 `adapters/` 封装调用；替换真实系统时只需实现对应 Protocol 接口
- **高风险动作**: 必须拦截转为 `waiting_human_confirmation`，由人工在既有业务系统执行
- **来源可追溯**: AI 输出必须携带 `citations` 或声明 `uncertainties`，禁止无来源的确定性结论
- **OpenSpec 即实源**: 所有功能变更必须先在 `openspec/` 查看或生成提案

### API

路由前缀: `/api/v1/medical-insurance-ai-agent`

| 端点 | 说明 |
|------|------|
| `POST /chat` | 统一导办入口（意图识别 → 场景路由 → 结果返回） |
| `GET /patient-context/{patient_id}/{encounter_id}` | 按角色返回最小必要字段 |
| `POST /tasks/confirm` | 人工确认/拒绝高风险动作 |
| `GET /workflows/{workflow_id}` | 流程状态查询 |
| `GET /tasks/{task_id}` | 任务状态查询 |
| `GET /version` | 版本信息 |

前端演示页: `src/static/index.html`，根路径 `/` 直接返回。

### MVP 场景与适配器

| 场景 | business_scenarios/ | 涉及适配器 |
|------|---------------------|-----------|
| 医保结算异常导办 | `settlement_exception_guide/` | insurance_interface, billing |
| 出院前联合质控 | `pre_discharge_joint_qc/` | pre_audit, drg_dip, his, emr, medical_record |

适配器当前均为内存实现（`in_memory.py`）。

后续规划场景：拒付申诉助手、DRG/DIP 运营助手、病案首页风险导办、科室整改闭环、医保运营驾驶舱、政策规则解释。适配器规划：insurance_data_platform、lis、pacs、finance、integration_platform、external_agent。

## 编码规范

- **import 路径**: 所有 Python 模块使用 `src.` 前缀（如 `from src.runtime.api.app import create_app`）
- **每个目录**: 必须包含 `__init__.py`（可为空文件），否则 pytest 无法导入
- **类型安全**: 禁止裸 `dict` 作为返回类型，使用 Pydantic BaseModel；API 响应统一使用 `AgentResponse` 结构
- **异常标准**: `{ error_code, message, audit_event }`，通过 `shared.schemas.responses.error_detail()` 生成
- **文件命名**: `snake_case`（后端）；类名 `PascalCase`；常量 `UPPER_SNAKE_CASE`
- **无注释**: 代码不加注释，除非明确要求

### MVP 阶段的技术债务

以下已知妥协与编码规范矛盾，后续迭代需修正：

- `routes.py` 的 `chat()` 返回裸 `dict` 而非 `AgentResponse` Pydantic 实例
- `pre_discharge_joint_qc/service.py` 硬编码风险数据，未调用适配器（违反解耦纪律）
- `build_human_confirmation_response()` 中 `task_id` 硬编码为 `task-human-confirm-001`

## 安全约束（硬性）

- 高风险动作（退费/冲正/正式结算/病案修改等）必须在 `security/risk_control/` 拦截，转为 `waiting_human_confirmation`
- 任何 AI 输出必须携带 `citations` 来源引用，或声明 `uncertainties`
- 敏感数据通过 `security/desensitization/` 脱敏处理后输出

## OpenSpec 工作流

- 变更提案必须先在 `openspec/` 生成（proposal → design → specs → tasks）
- 归档目录: `openspec/changes/archive/YYYY-MM-DD-<name>/`
- 实现计划参考: `docs/superpowers/plans/2026-04-30-medical-insurance-ai-agent.md`

## Git 提交规范

Angular 格式：`feat: | fix: | refactor: | docs: | test: | chore: <描述>`

## 已知陷阱

- `create_app()` 是工厂函数，启动 uvicorn 必须加 `--factory`
- 样例数据仅包含 `P001/E001`，`P002` 触发降级路径
- 测试中 `HIGH_RISK_ACTIONS` 是 `set`，`detect_blocked_actions` 返回顺序不稳定，断言应使用 `set()` 比较
- PowerShell 中 `&&` 和 `||` 无效，用 `;` 分隔命令
