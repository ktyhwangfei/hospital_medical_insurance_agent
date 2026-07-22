# 定期架构熵增巡检模板

> 适用范围：`hospital_medical_insurance_agent` 项目  
> 当前状态：v1.0  
> 文档定位：每个里程碑结束时执行的架构健康检查清单，防止 AI 长期迭代导致的架构退化  
> 配套文档：`AI-CODING-GOVERNANCE.md` §7.5 / `AI-CODING-MODULE-BOUNDARIES.md`

---

## 1. 巡检目的

AI Coding 的长期风险不是某一次改动出错，而是**慢性架构熵增**：

- 同一逻辑在多个文件中重复实现，收口越来越难。
- 新旧两套实现并存，调用方不知道该用哪个。
- 目录职责逐步漂移，模块边界文档与实际代码脱节。
- 为了修局部 bug 引入跨层快捷调用，绕过防腐层。

本模板用于每个里程碑（或每 2-4 周）执行一次架构体检，以**可复现的检查项**替代"凭感觉觉得不太对"。

---

## 2. 巡检频率与触发条件

| 触发条件 | 最低频率 |
|----------|---------|
| 每个里程碑结束 | 必须执行 |
| 累计 AI 改动超过 20 个 PR | 必须执行 |
| 新增 skill 超过 3 个 | 必须执行（重点查 skill 隔离） |
| 修改了 R3/R4 目录超过 5 次 | 必须执行 |
| 感觉"系统越来越难改" | 随时执行 |

---

## 3. 巡检清单

### 3.1 重复路径检测

> 目标：发现同一功能的多套实现。

**检查方法**：

```bash
# 搜索可能的重复实现信号
# 1. 同名函数在不同文件中定义
# 2. 相似的 import 链出现在不该出现的地方
# 3. 同一类名/模块名在多个目录出现
```

| 检查项 | 方法 | 通过标准 |
|--------|------|----------|
| **重复的场景执行入口** | 搜索 `scenario_executor` 的使用，确认只有 `runtime/orchestration/` 中有定义 | 仅一处定义 |
| **重复的知识检索逻辑** | 搜索 `from src.knowledge_extension` 的 import，确认不在 `runtime/` 或 `adapters/` 中重复实现检索 | 仅 knowledge_extension 内部实现 |
| **重复的模型调用** | 搜索 `openai.`、`httpx.post`、`aiohttp` 等直接 HTTP 调用，确认所有 LLM 调用都走 `model_service/gateway` | 业务模块中无直接 HTTP 调用 |
| **重复的权限校验** | 搜索 `if role`、`check_permission` 的自定义实现，确认权限统一走 `security/authorization/` | 业务模块中无自建权限校验 |
| **重复的错误码/错误信息** | 搜索相似的 `error_code` 字符串，确认同一类错误有统一定义 | 无散落的硬编码错误码 |

**典型问题示例**：

```
# ❌ 在 runtime/ 中直接调模型（绕过了 model_service/gateway）
# src/runtime/some_module.py
response = openai.ChatCompletion.create(...)

# ❌ 在业务场景中自建权限校验（绕过了 security/authorization）
# src/business_scenarios/settlement.py
if user.role != "doctor":
    raise PermissionError(...)
```

### 3.2 新旧路径并存检测

> 目标：发现已被替代但未清理的旧代码。

| 检查项 | 检查方法 | 通过标准 |
|--------|----------|----------|
| **DEPRECATED 模块仍被引用** | 搜索 `deprecated`、`DEPRECATED` 注释标记的模块/函数，检查是否仍有 import | 已废弃的无外部引用 |
| **旧版路由/端点未下线** | 对比 `routes.py` 中的路由列表与设计文档，确认是否有标记为"待删除"的端点仍存活 | 无僵尸端点 |
| **两套编排引擎并存** | 搜索 `orchestration/service.py` 和 `planning/service.py`（已 DEPRECATED）是否仍被 import | 无对已废弃模块的引用 |
| **两套路由逻辑并存** | 确认 `skill_router.py` 的旧版 `route_question()` 是否仍有调用方使用非统一入口 | 全部走 unified_router |
| **两套前端组件并存** | 搜索同名组件的多个版本（如 `chat.tsx` vs `chat-v2.tsx`），确认旧版是否已下线 | 无 `-v2`/`-old`/`-new` 命名的并存文件 |

**典型问题示例**：

```
# ❌ 已废弃的模块仍被引用
# src/runtime/some_module.py
from src.runtime.orchestration.service import ScenarioOrchestrator  # 已废弃！

# ❌ 并存组件
src/apps/portal/components/chat.tsx
src/apps/portal/components/chat-v2.tsx      # ← 应该只有一个是活的
```

### 3.3 目录职责漂移检测

> 目标：发现模块承担了不属于其职责范围的功能。

| 检查项 | 检查方法 | 通过标准 |
|--------|----------|----------|
| **adapters/ 中混入业务逻辑** | 抽样读取 `src/adapters/` 下的文件，确认只做协议翻译和数据转换，不包含 `if ... else ...` 的业务判断 | 适配器只"翻译"不"决策" |
| **domain/ 中混入流程逻辑** | 检查 `src/domain/` 是否有 import `runtime/`、`model_service/` 等上层模块 | domain/ 不依赖上层 |
| **skill 中混入基础设施能力** | 检查 `skills/` 下的 import，确认不包含 §3.3 的黑名单模块 | skill 不越界 |
| **前端组件中混入后端逻辑** | 检查 `src/apps/` 下是否有直接数据库操作、模型调用、权限判断 | 前端只做展示和交互 |
| **config/ 中混入业务规则** | 检查 `src/config/` 是否在定义医保业务规则（如"起付线=800"），而非配置项 | config 只做配置，不定义业务规则 |
| **model_service/ 中混入业务路由** | 检查 `src/model_service/` 是否包含场景判断（如"如果是结算异常则用模型A"） | model_service 只做模型路由，不做场景路由 |

**典型问题示例**：

```
# ❌ adapter 里做业务判断
# src/adapters/his_adapter.py
def get_patient(patient_id):
    data = self._fetch(patient_id)
    if data["age"] > 60:           # ← 业务逻辑！
        data["insurance_type"] = "退休"
    return data
```

### 3.4 跨层调用检测

> 目标：发现绕过既定分层和防腐层的快捷调用。

| 检查项 | 检查方法 | 通过标准 |
|--------|----------|----------|
| **业务层直接调外部系统** | 搜索 `requests.`、`httpx.`、`aiohttp.` 在 `runtime/`、`business_scenarios/` 中的使用 | 无直接外部调用 |
| **业务层直接调数据库** | 搜索 `psycopg2`、`sqlalchemy`、`asyncpg`、`aiomysql` 在 `runtime/` 和 `skills/` 中的 import | 无直接数据库访问 |
| **skills/ 绕过安全层** | 检查 skill 执行路径是否都经过了 `security/risk_control/` | 所有 skill 执行前有风险检查 |
| **前端直接调模型** | 检查 `src/apps/` 中是否有直接调用 OpenAI/模型 API 的代码 | 模型调用全走后端 |
| **降级路径跳过审计** | 抽样检查 `except` 分支是否记录了审计事件 | 降级路径不可吞审计 |

**典型问题示例**：

```
# ❌ 业务场景直接调 HTTP（应通过 adapters/）
# src/business_scenarios/settlement.py
import requests
response = requests.get(f"http://his-server/patient/{pid}")

# ❌ 前端直接调模型（应通过后端 /chat 端点）
# src/apps/portal/utils/ai.ts
const response = await fetch("https://api.openai.com/v1/chat/completions", ...)
```

### 3.5 接口契约漂移检测

> 目标：发现 API 响应格式、事件结构、Protocol 签名的隐性变化。

| 检查项 | 检查方法 | 通过标准 |
|--------|----------|----------|
| **AgentResponse 结构变化** | 对比 `src/shared/schemas/` 的当前定义与 OpenAPI 契约测试（`test_openapi_contract.py`） | 契约测试通过 |
| **SSE 事件格式变化** | 检查 SSE 流式端点返回的事件类型是否与前端期望一致 | 事件类型未增删未经声明 |
| **Protocol 接口签名变化** | 检查 `tool_interfaces.py` 的 Protocol 定义是否与注入实现一致 | 签名一致 |
| **API 端点前缀/路径变化** | 检查所有路由是否仍以 `/api/v1/medical-insurance-ai-agent` 为前缀 | 无旁路入口 |
| **领域模型字段语义变化** | 检查 `src/domain/` 中的字段是否新增了与旧语义冲突的含义 | 无概念混名 |

### 3.6 测试覆盖退化检测

> 目标：发现随着迭代增长，测试覆盖率下降的信号。

| 检查项 | 方法 | 通过标准 |
|--------|------|----------|
| **跳过的测试数量增长** | 搜索 `@pytest.mark.skip`、`# noqa` 的数量 | 不应比上次巡检显著增长 |
| **新增模块无测试** | 列出最近新增的 `.py` 文件，逐一确认是否有对应测试 | 每个新模块有至少一个测试 |
| **高风险路径测试缺失** | 检查 `flow/test_high_risk_and_permission.py` 是否覆盖了最近新增的高风险场景 | 高风险场景有 flow 覆盖 |
| **异常分支测试缺失** | 抽查最近 5 个 PR 新增的异常处理代码，是否有对应测试 | 异常分支有测试 |

---

## 4. 巡检执行流程

### 4.1 执行步骤

```
Step 1: 确定巡检范围
  ├─ 本次里程碑改了哪些目录？
  ├─ 涉及哪些风险等级？
  └─ 标记为重点检查的目录

Step 2: 执行检查项
  ├─ 按 §3 清单逐项执行
  ├─ 记录发现的问题（文件路径 + 问题描述 + 严重程度）
  └─ 对不确定的项不做主观判断，标记"需人工确认"

Step 3: 出具巡检报告
  ├─ 严重问题（🔴）：必须本里程碑修复
  ├─ 一般问题（🟡）：下个里程碑修复
  └─ 观察项（🔵）：持续关注，下个里程碑复检
```

### 4.2 报告模板

```markdown
## 架构熵增巡检报告 — M{里程碑号}

**巡检日期**：YYYY-MM-DD
**巡检范围**：{改动涉及的目录列表}
**执行人**：{姓名/Agent}

### 检查摘要

| 类别 | 检查项数 | 通过 | 发现问题 |
|------|---------|------|---------|
| 重复路径 | N | N | N |
| 新旧并存 | N | N | N |
| 目录漂移 | N | N | N |
| 跨层调用 | N | N | N |
| 契约漂移 | N | N | N |
| 测试退化 | N | N | N |

### 严重问题（必须本里程碑修复）

| # | 类别 | 文件 | 问题描述 | 修复建议 |
|---|------|------|---------|---------|
| 1 | | | | |

### 一般问题（下个里程碑修复）

| # | 类别 | 文件 | 问题描述 | 修复建议 |
|---|------|------|---------|---------|
| 1 | | | | |

### 观察项（持续关注）

| # | 类别 | 文件 | 描述 |
|---|------|------|------|
| 1 | | | |

### 与前次巡检对比

- 上次尚存问题修复情况：N / M
- 新增问题趋势：上升 / 持平 / 下降
```

---

## 5. 自动化辅助

以下脚本可辅助快速扫描（非替代人工判断）：

```bash
# 检查业务模块是否直接 import 外部调用库（绕过 adapters/）
python -c "
import ast, pathlib
for f in pathlib.Path('src/runtime').rglob('*.py'):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ('requests', 'httpx', 'aiohttp', 'psycopg2'):
                    print(f'[CROSS-LAYER] {f} imports {alias.name}')
"

# 检查 skills/ 是否 import 了黑名单模块
python -c "
import ast, pathlib
BLACKLIST = {'psycopg2','sqlalchemy','requests','httpx','aiohttp',
             'src.security','src.data_platform','src.adapters','src.runtime'}
for f in pathlib.Path('skills').rglob('*.py'):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and any(node.module.startswith(b) or node.module == b for b in BLACKLIST):
                print(f'[SKILL-VIOLATION] {f} imports {node.module}')
"

# 统计 @pytest.mark.skip 数量趋势
grep -r "@pytest.mark.skip" src/tests/ | wc -l
```

---

## 6. 巡检后的修复优先级

| 问题类别 | 严重程度 | 修复窗口 |
|----------|----------|---------|
| 跨层调用（绕过 adapters/risk_control/model_service） | 🔴 严重 | 立即修复，阻塞后续开发 |
| 高风险路径无 flow 测试 | 🔴 严重 | 本里程碑必须补齐 |
| skill import 黑名单模块 | 🔴 严重 | 立即修复或下线该 skill |
| 新旧路径并存（DEPRECATED 仍被引用） | 🟡 一般 | 下个里程碑清理 |
| 目录职责轻度漂移 | 🟡 一般 | 下个里程碑重构 |
| 测试 skip 数量增长 | 🟡 一般 | 下个里程碑逐步清理 |
| 弱信号（需持续观察） | 🔵 观察 | 下个里程碑复检 |

---

## 7. 变更记录

| 版本 | 日期 | 作者 | 说明 |
|------|------|------|------|
| v1.0 | 2026-06-29 | — | 初始版本：6 大类检查项 + 执行流程 + 报告模板 + 自动化辅助脚本 |
