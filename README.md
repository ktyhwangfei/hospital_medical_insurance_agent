# hospital-medical-insurance-agent（院端医保智能体系统）

> AI 导办与协同中枢：面向医院医保办/医务科的智能助手平台，提供**政策问答、结算异常导办、出院前质控**等 AI 场景。
>
> **平台定位**：AI 导办与协同中枢，**不替代**医保正式结算、事前审核、DRG 分组、病案修改等既有业务系统。高风险动作一律拦截转人工确认。

---

## 目录

- [功能总览](#功能总览)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [环境要求](#环境要求)
- [快速开始（Windows 推荐）](#快速开始windows-推荐)
- [手动启动（Linux / WSL）](#手动启动linux--wsl)
- [配置说明](#配置说明)
- [API 概览](#api-概览)
- [测试](#测试)
- [部署](#部署)
- [常见问题与陷阱](#常见问题与陷阱)
- [文档导航](#文档导航)

---

## 功能总览

### 业务场景

| 场景 | 说明 | 前端入口 | 后端核心 |
|------|------|----------|----------|
| **政策问答 / 费用解释** | 医保政策流式问答，含费用项目解释（起付线/统筹自付/大额自付等），Skill 驱动 + 结构化政策检索 | `/policy-qa` | `runtime/policy_qa`、`skills/settlement_explain_skill` |
| **结算异常导办** | 医保结算错误码 → AI 分析异常原因 → 给出处理步骤导办卡 | `/settlement` | `business_scenarios/settlement_exception_guide` |
| **出院前质控** | 触发质控 → 风险扫描 → 事前审核 + DRG/DIP 分组分析 | `/qc` | `business_scenarios/pre_discharge_joint_qc` |
| **政策知识治理** | 政策知识库 5 tab 管理（概览/政策/事实/结构化/发现） | `/policy-knowledge` | `runtime/policy_knowledge_routes`、`knowledge_extension/policy_retrieval` |
| **语义层** | 语义指标注册表、领域/对象/映射/指标浏览 | `/semantic-layer` | `semantic_layer/` |
| **技能管理** | Skill 包加载、路由测试、执行测试 | `/skills` | `skill_infra/` |
| **问答历史** | 政策问答历史记录查询 | `/qa-history` | `runtime/policy_qa/history_service` |
| **运营看板** | 运营指标展示 + 工作流监控 | `/dashboard` | `observability/` |

### 核心能力

- **LLM 统一网关**：所有模型调用走 `model_service/gateway`（type + scene 路由、OpenAI 兼容 Provider、SSE 流式、异常分类）
- **LangGraph 图式编排**：结算异常/出院前质控场景图执行，`interrupt()` 支持高风险动作人工确认
- **Skill 驱动架构**：YAML 配置 + Python assembler 声明式业务能力包，通过 `business_action` + `business_object` 挂载
- **政策知识管线**：政策原文 → 语义层契约 → 结构化事实/规则（Milvus 向量检索 + SQL Server 业务数据源）
- **安全围栏**：高风险拦截、AI 输出强制 `citations`/`uncertainties`、敏感数据脱敏、审计日志

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12 · FastAPI · uvicorn · LangGraph · Pydantic v2 |
| 前端 | Next.js 16 · React 19 · Tailwind CSS 4 · Vitest |
| 存储 | PostgreSQL 16（pgvector）· Redis 7.4 · Milvus 2.4（向量库）· SQL Server 2022（业务数据源） |
| 模型 | OpenAI 兼容接口（默认 DeepSeek，可配其他） |
| 依赖管理 | uv（`uv.lock`）· npm |
| 部署 | Docker Compose · Kubernetes（`deploy/`） |

四层架构：**SaaS 应用产品层**（portal）→ **PaaS 平台支撑层**（网关/运行时/模型服务/知识服务/适配器/任务闭环）→ **DaaS 数据与知识服务层**（数据访问/缓存/持久化/向量存储）→ **系统接入与基础设施层**（外部系统防腐层）。

---

## 目录结构

```
hospital_medical_insurance_agent/
├── src/                          # 后端源码
│   ├── runtime/                  # Agent 核心运行时（API/会话/意图/编排/LangGraph/任务闭环）
│   ├── business_scenarios/       # 医保业务场景（结算异常导办、出院前质控）
│   ├── model_service/            # 模型服务网关（路由/Provider/流式/异常）
│   ├── knowledge_extension/      # 知识与扩展（政策检索/MCP 注册/规则解释）
│   ├── adapters/                 # 外部系统防腐层（医保/事前审核/DRG/DIP/HIS/EMR/病案/收费）
│   ├── data_platform/            # DaaS 数据底座（访问/缓存/持久化/存储）
│   ├── domain/                   # 领域模型（患者/医保/费用/审核风险/任务…）
│   ├── security/                 # 安全围栏（权限/脱敏/风控/审计）
│   ├── gateway/                  # 统一接入网关（API 网关/认证/租户/限流/请求安全）
│   ├── interaction/              # 多模态交互层（Chat/文件/语音/消息提醒）
│   ├── config/                   # 全局配置（production.py 统一配置）
│   ├── skill_infra/              # Skill 基础设施（SkillLoader/SkillRouter）
│   ├── semantic_layer/           # 语义层（指标注册表/领域/映射）
│   ├── apps/portal/              # 前端 Next.js 16 应用（业务入口）
│   └── tests/                    # 后端测试（unit/integration/performance/e2e）
├── skills/                       # Skill 包（settlement_explain_skill 等）
├── deploy/                       # 部署（docker-compose/k8s/env）
├── docs/steering/                # 设计文档（架构/接口/数据库/原型/政策管线）
├── start-servers.ps1             # 一键启动脚本（Windows）
├── stop-servers.ps1              # 一键停止脚本（Windows）
├── pyproject.toml + uv.lock      # Python 依赖（uv）
└── AGENTS.md / PROGRESS.md       # 开发规范 / 项目进度
```

---

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 后端运行环境 |
| Node.js | 20+ | 前端构建（Next.js 16） |
| uv | 最新 | Python 依赖管理（推荐） |
| Docker + Docker Compose | 最新 | 一键启动全部基础设施 |
| 模型 API Key | — | OpenAI 兼容（默认 DeepSeek，见 [配置说明](#配置说明)） |

---

## 快速开始（Windows 推荐）

### 第 1 步：启动基础设施（Docker Compose）

一键拉起 PostgreSQL、Redis、Milvus、SQL Server、MinIO、etcd 等：

```powershell
cd deploy/docker
docker compose up -d
```

首次会拉取镜像（约几分钟），之后秒级启动。验证：

```powershell
docker compose ps          # 全部 healthy
```

| 服务 | 容器名 | 端口 | 凭据（见 `deploy/docker/.env`） |
|------|--------|------|------|
| PostgreSQL | medical-postgres | 5432 | `postgres` / 密码见 `deploy/docker/.env`，库 `hospital_mcp` |
| Redis | medical-redis | 6379 | 密码见 `deploy/docker/.env` |
| SQL Server | sql2022 | 1433 | `sa` / 密码见 `deploy/docker/.env` |
| Milvus | milvus-standalone | 19530 | — |
| MinIO | milvus-minio | 9000 / 9001 | `minioadmin` / 密码见 `deploy/docker/.env` |
| Attu（Milvus 管理台） | attu | http://127.0.0.1:8010 | — |
| RedisInsight | redisinsight | http://127.0.0.1:5540 | — |
| Ollama / Open WebUI | ollama | 11434 / 3005 | 可选（本地模型） |

> ⚠️ 若使用 docker-compose 的 Redis（带密码），需在环境变量中设置 `REDIS_PASSWORD`（值见本地 `deploy/docker/.env`，该文件已被 gitignore，不会入库）；未设置时缓存层自动降级为内存实现（`CACHE_FAIL_OPEN=1`），不影响启动。

### 第 2 步：初始化数据库（首次）

```bash
# WSL/Linux 一键初始化 PostgreSQL + SQL Server（导入 schema 与种子数据）
cd deploy/docker
chmod +x init_all.sh
./init_all.sh
```

Windows 下可跳过初始化直接启动——后端会在启动时自动建表/初始化，缺失的数据走降级路径（见 [常见问题](#常见问题与陷阱)）。

### 第 3 步：安装后端依赖

```powershell
# 推荐：uv（自动按 pyproject.toml + uv.lock 安装全部依赖，含 dev 组）
uv sync

# 或传统方式：
# pip install -r requirements.txt
# pip install -e .   # 安装 pyproject.toml 主依赖 + dev 依赖
```

### 第 4 步：配置模型服务（必做）

复制 `.env` 并填入你的模型 Key（默认 DeepSeek，OpenAI 兼容）：

```powershell
# 项目根目录 .env（已被 gitignore，不会入库）
MODEL_BASE_URL=https://api.deepseek.com/v1
MODEL_API_KEY=sk-你的Key
```

> ⛔ **未配置 `MODEL_API_KEY` 时，所有依赖 LLM 的接口不可用**（政策问答降级、模型测试失败等）。

### 第 5 步：安装前端依赖

```powershell
cd src/apps/portal
npm install
```

### 第 6 步：一键启动（推荐）

回到项目根目录，直接运行：

```powershell
.\start-servers.ps1
```

脚本自动完成：清理旧进程 → 校验端口 → 加载 `.env` 与 MSSQL 环境变量 → 启动后端（8000）→ 编译并启动前端（3000）→ 健康检查。

停止：

```powershell
.\stop-servers.ps1
```

> ⛔ **请使用脚本启停，不要手动启动**。脚本处理了端口冲突、uvicorn 孤儿 worker（`--reload` 产生的僵尸进程占用端口）等问题。手动 `uvicorn --reload` 后若强制结束主进程，worker 会变孤儿进程持有端口。

### 第 7 步：验证

| 检查项 | 地址 |
|--------|------|
| 后端健康检查 | http://127.0.0.1:8000/health → `{"status":"ok"}` |
| 后端 API 文档（Swagger） | http://127.0.0.1:8000/docs |
| 前端 Portal | http://localhost:3000 |
| 政策问答（主入口） | http://localhost:3000/policy-qa |

---

## 手动启动（Linux / WSL）

```bash
# 1. 后端（create_app 是工厂函数，必须带 --factory）
cd /path/to/hospital_medical_insurance_agent
export $(grep -v '^#' .env | xargs)          # 加载模型配置
export DATA_SOURCE_MODE=real_db               # 启用真实 SQL Server 数据源（可选）
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory

# 2. 前端（另开终端）
cd src/apps/portal
npm run dev
```

---

## 配置说明

### 后端配置（`src/config/production.py`，全部可用环境变量覆盖）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `POSTGRES_HOST/PORT/USER/PASSWORD/DB` | `127.0.0.1:5432` / `postgres` / `postgres` / `hospital_mcp` | PostgreSQL（**密码是 `postgres`，不是历史文档误记的 `123456`**） |
| `REDIS_HOST/PORT/PASSWORD` | `127.0.0.1:6379` / 空 | Redis（docker-compose 密码见 `deploy/docker/.env`，已被 gitignore） |
| `MILVUS_HOST/PORT` | `127.0.0.1:19530` | Milvus 向量库（**端口是 `19530`，不是历史文档误记的 `19121`**） |
| `SKILLS_DIR` | 项目根 `skills/` | Skill 包目录 |
| `MODEL_BASE_URL` / `MODEL_API_KEY` | — | OpenAI 兼容模型端点与 Key |
| `DATA_SOURCE_MODE` | `mock` | `mock`=内存模拟数据；`real_db`=查询真实 SQL Server 业务库 |
| `USE_MEMORY_STORAGE` | 未设置 | 设为 `1` 时全部存储（skill/tool/task/workflow/audit）回退内存实现（灰度/无 PG 场景） |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `CACHE_ENABLED` / `CACHE_FAIL_OPEN` | `1` / `1` | 缓存开关；Redis 故障自动降级内存缓存 |

### MSSQL（结算业务数据源，`start-servers.ps1` 自动注入）

| 变量 | 默认值 |
|------|--------|
| `MSSQL_HOST/PORT` | `localhost:1433` |
| `MSSQL_DATABASE` | `bjybdb` |
| `MSSQL_USER/PASSWORD` | `sa` / 密码见 `deploy/docker/.env`（已被 gitignore） |
| `MSSQL_DRIVER` | `SQL Server` |

### 前端（`src/apps/portal/next.config.ts`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8000` | 后端地址；`next.config.ts` 已将 `/api/v1/medical-insurance-ai-agent/*` 反代到该地址 |

---

## API 概览

所有接口前缀 `/api/v1/medical-insurance-ai-agent`（除 `/health` 外）。完整清单见 `docs/steering/接口设计文档.md`（40+ 端点）。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/policy-qa/stream` | 政策问答 **SSE 流式**（前端据此持续对话；`done` 事件标志流结束） |
| `POST` | `/policy-qa/test` | 政策问答测试（非流式） |
| `GET` | `/policy-qa/settlement-explanation` | 结算费用解释（Skill 驱动 + 结构化政策检索） |
| `GET` | `/policy-qa/history` | 问答历史（分页） |
| `GET` | `/policy-qa/debug/structured-policy-search` | 结构化政策检索调试 |
| `GET/POST/PUT/DELETE` | `/policy-knowledge/rules`、`/rules/{rule_id}` | 政策规则 CRUD |
| `POST` | `/policy-knowledge/rules/query` | 高级表达式查询 |
| `GET` | `/policy-knowledge/stats` | 规则集合统计 |
| `*` | `/policy-pipeline/*` | 政策知识管线（提取/发布/演化） |
| `*` | `/semantic/*`、`/semantic/alignment/*` | 语义层指标注册表与对齐 |
| `*` | `/policy-workbench/*` | 政策工作台 |
| `*` | `/infra-skills/*` | Skill 基础设施（加载/路由测试/执行测试） |

响应统一 `AgentResponse` 结构（`error_code/message/audit_event`），SSE 流式事件见 `src/runtime/api/streaming.py`。

---

## 测试

验证顺序严格串行：**单元 → 集成(API) → 性能 → E2E**。详见 `src/tests/AGENTS.md` 与 `docs/governance/TEST-VERIFICATION-MATRIX.md`。

```bash
# 后端单元测试（纯逻辑，无需外部服务）
pytest src/tests/unit -q

# 后端集成测试（API 端点 + 业务流程）
pytest src/tests/integration/api -q
pytest src/tests/integration/flow -q

# 后端性能测试（需先启动后端，Locust）
# 见 src/tests/performance/

# 前端单元测试（Vitest）
cd src/apps/portal
npm test

# E2E（Playwright，需启动前后端）
# 见 src/apps/portal/src/tests/e2e/
```

> ⚠️ **已知测试债务**（2026-07-31 基线，与 HEAD 一致、非新改动引入）：单元 26 失败 / 894 通过、API 66 失败 / 43 通过、Flow 42 失败 / 9 通过。主因：chat 端点迁移至 `/policy-qa/stream` 后旧测试仍 POST `/chat`（404）、skill manifest 改名断言未更新等。判断回归以「与基线对比零新增失败」为准。

---

## 部署

### Docker（后端容器）

```bash
cd deploy/docker
docker build -f Dockerfile -t medical-insurance-agent ..
docker run -p 8000:8000 \
  -e MODEL_API_KEY=sk-xxx \
  -e DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/hospital_mcp \
  medical-insurance-agent
```

### Docker Compose（基础设施）

`deploy/docker/docker-compose.yml` 包含全部中间件（SQL Server / PostgreSQL / Redis / Milvus / etcd / MinIO / Attu / Ollama / Open WebUI）。生产凭据请覆盖 `deploy/docker/.env`。

### Kubernetes

`deploy/k8s/` 下按组件提供 K8s 清单；环境变量模板见 `deploy/env/`（`.env.development` / `.env.testing` / `.env.production`）。

---

## 常见问题与陷阱

| 现象 | 原因 / 解决 |
|------|-------------|
| `uvicorn: error: ... create_app` 找不到 | `create_app()` 是**工厂函数**，启动必须带 `--factory`：`uvicorn src.runtime.api.app:create_app --port 8000 --factory` |
| 政策问答没有答案 / 模型接口报错 | 未配置 `MODEL_API_KEY`（.env）。模型调用统一走 `model_service/gateway` |
| 端口 8000 被占用，进程找不到 | uvicorn `--reload` 孤儿 worker 持有端口。用 `.\stop-servers.ps1` 清理；查找用 `netstat -ano | findstr :8000` 反查 PID |
| 前端调后端 404 | 确认后端已启动且 `NEXT_PUBLIC_API_BASE_URL` 指向 8000（next.config.ts 有 rewrites 代理） |
| SSE 流不结束 | `/policy-qa/stream` 的 `done` 事件标志流结束，前端据此关闭 EventSource |
| Milvus 连接失败 | 端口是 `19530`（不是历史文档的 `19121`）；确认 `docker compose ps` 中 milvus healthy |
| PostgreSQL 连接失败 | 密码默认 `postgres`（不是 `123456`）；库名 `hospital_mcp` |
| 结算解释无数据 | 样例数据仅 `P001`/`E001`；`P002` 触发降级路径。需要真实数据请设 `DATA_SOURCE_MODE=real_db` 并初始化 SQL Server |
| 聊天/导办答非所问 | 记忆不沉淀：检查 PostgreSQL 是否可达（POSTGRES_PASSWORD 默认值覆盖后需与 docker-compose 一致） |
| PowerShell 里 `&&`/`||` 无效 | 用 `;` 分隔命令 |
| `domain/tool/`、`data_platform/storage/tool/` 导入报错 | 完全空目录（无 `__init__.py`），**不要使用** |
| `runtime/orchestration/service.py`、`runtime/planning/service.py` | 已 DEPRECATED，使用 `scenario_executor.py` 代替 |

---

## 文档导航

| 文档 | 内容 |
|------|------|
| `AGENTS.md` | 开发规范、架构映射、安全约束、已知陷阱（**改代码前必读**） |
| `PROGRESS.md` | 项目进度追踪（功能单元 / 政策管线 P0-P10 / Runtime 三阶段） |
| `docs/steering/架构设计.md` | 四层体系完整架构 |
| `docs/steering/接口设计文档.md` | 40+ API 端点定义 |
| `docs/steering/数据库设计文档.md` | 18 张表定义 |
| `docs/steering/原型设计文档.md` | 前端组件规范 |
| `docs/steering/政策知识管线设计.md` / `政策知识管线开发计划.md` | 政策知识管线架构与 P0-P10 计划 |
| `src/tests/AGENTS.md` | 测试分层、命令速查、模块↔测试映射 |
| `docs/governance/TEST-VERIFICATION-MATRIX.md` | 风险分级验证矩阵（测试唯一权威参考） |
| `src/domain/AGENTS.md` | 领域通用语言字典（命名统一） |
| `src/apps/portal/AGENTS.md` | 前端开发约定 |

---

*本项目文档与代码注释以中文为主。遇到 Bug 或新需求时，建议先阅读 `AGENTS.md` 与 `PROGRESS.md`，遵守「排障零步骤」与「缺陷驱动测试铁律」。*
