# Skill 执行隔离设计说明

> 适用范围：`hospital_medical_insurance_agent` 项目  
> 当前状态：v1.0  
> 文档定位：定义 skill 的执行边界、能力约束与隔离策略，是 skill 开发者和 reviewer 的权威参考  
> 配套文档：`AI-CODING-GOVERNANCE.md` §7.3 / `AI-CODING-MODULE-BOUNDARIES.md` §5.9-5.10

---

## 1. 现状诊断

### 1.1 当前架构

```
用户问题
  │
  ▼
skill_router → 关键词/LLM 路由 → skill_id
  │
  ▼
skill_loader → importlib.import_module("skills.xxx.assembler")  ← 同进程直接 import
  │
  ▼
assembler.execute(ctx, evidence, status)
  │
  ▼
Strategy → YAML 配置 + Python 纯逻辑 + Protocol 接口（SQL/Policy/LLM）
```

### 1.2 做得好的（保持）

| 特性 | 现状 | 评价 |
|------|------|------|
| 自包含目录结构 | ⭐ 每个 skill 一个独立目录 | 好 — 易于下线、替换、版本管理 |
| Protocol 接口 | ⭐ 通过 Protocol 声明外部依赖 | 好 — 不硬编码 Agent 实现，可替换 |
| Strategy Pattern | ⭐ 子能力通过策略扩展 | 好 — 新增费用项无需改 assembler |
| 声明式配置 | ⭐ YAML 驱动逻辑，非代码硬编码 | 好 — 非开发人员可审计 |
| 热加载/卸载 | ⭐ `rediscover()` + `unload()` | 好 — 运行时上下线 skill |
| Manifest 约束 | ⭐ 关键词 + 排除词 + MCP 依赖声明 | 好 — 有清单可审计 |

### 1.3 需要加固的（当前隔离缺口）

| 缺口 | 当前状态 | 风险 |
|------|----------|------|
| **进程级隔离** | skill 与主应用**同一进程**内 `importlib.import_module` | skill 异常可拖垮主进程；skill 可访问主应用所有内存 |
| **权限边界** | 无运行时强制 —— 纯靠约定 | skill 可以 `import` 任意模块，包括 `security/`、`data_platform/` |
| **资源限制** | 无 CPU/内存/IO 限制 | 恶意或 buggy skill 可耗尽资源 |
| **文件系统** | 无限制 | skill 可读写任意文件 |
| **网络访问** | 通过 Protocol 声明，但无强制 | skill 可在代码中直接 `requests.get()` |
| **数据库直连** | 通过 Protocol 声明，但无强制 | skill 可直接 `import` 数据库驱动 |
| **审计** | skill 执行无审计事件 | 无法追踪哪个 skill 做了什么 |
| **错误隔离** | `SkillLoader.discover()` 有 try/except | 加载层面有，但执行层面无 —— assembler 异常直接传播 |

**结论**：当前是「约定式隔离」（逻辑隔离），而非「强制式隔离」（物理隔离）。约定对 AI 生成代码约束力不足。

---

## 2. 隔离目标

### 2.1 核心原则

> **Skill 是插件，不是旁路。Skill 的能力边界 = 主应用显式注入的上下文 + Protocol 接口。**

### 2.2 三层隔离目标

| 层级 | 目标 | 优先级 |
|------|------|--------|
| **L1：能力边界约束** | 明确 skill 能做什么、不能做什么，形成可检查的清单 | 🔴 短期 |
| **L2：上下文注入控制** | 控制 skill 接收什么数据、不接收什么数据 | 🔴 短期 |
| **L3：执行环境隔离** | 限制 skill 的进程/资源/网络/文件系统权限 | 🟡 中期 |

---

## 3. L1：Skill 能力边界约束（短期落地）

### 3.1 能力白名单（Skill 可以做什么）

| 允许的行为 | 实现方式 | 审查要点 |
|-----------|----------|----------|
| 读取 YAML 配置（仅自身目录内） | `yaml.safe_load(Path(__file__).parent / "xxx.yaml")` | 路径必须限于 skill 自身目录 |
| 纯 Python 计算逻辑 | 标准库 + skill 自身目录内 import | 不得 import `src.security`、`src.data_platform`、`src.adapters` 等 |
| 通过 Protocol 接口调用外部能力 | `tool_interfaces.py` 定义的 Protocol | Protocol 参数必须符合 schema 契约 |
| 生成解释文本、计算链路 | 模板渲染 + 纯函数 | 文本不能包含伪造的政策依据 |
| 声明 MCP 依赖（manifest） | `skill_manifest.yaml` 的 `mcp_dependencies` | MCP 调用通过基础设施层代理 |
| 抛出约定异常 | 自定义 SkillException | 不得吞掉异常返回伪成功 |

### 3.2 能力黑名单（Skill 绝对不能做什么）

| 禁止的行为 | 违规信号 | 被发现后 |
|-----------|----------|----------|
| **直接 import 数据库驱动** | `import psycopg2`、`import sqlalchemy`、`import aiomysql` | 退回 + 要求通过 Protocol 重构 |
| **直接访问外部 API** | `import requests`、`import httpx`、`import aiohttp` | 退回 + 要求通过 MCP 或适配器 |
| **直接 import 主应用模块** | `from src.security import ...`、`from src.data_platform import ...` | 直接退回 |
| **文件系统越界读写** | `open("/etc/..." )`、`Path("/")`、写 `skills/` 以外目录 | 直接退回 |
| **创建子进程/线程** | `subprocess.run()`、`os.system()`、`threading.Thread()` | 直接退回 |
| **修改全局状态** | `os.environ["KEY"] = ...`、模块级全局变量修改 | 退回 + 要求无状态设计 |
| **重建认证/授权/审计** | 在 skill 内部校验权限、记录审计 | 退回 |
| **输出无来源的确定性结论** | 解释文本无 `citations` 且无 `uncertainties` | 退回 |
| **吞掉异常返回伪成功** | `try: ... except: return {"ok": True}` | 退回 + 要求异常上抛 |

### 3.3 Skill 自身的 import 白名单

skill 代码只能 import 以下来源：

| 来源 | 示例 | 条件 |
|------|------|------|
| Python 标准库 | `json`、`re`、`dataclasses`、`pathlib`、`yaml` | 无条件 |
| 自身目录内模块 | `from .strategies.registry import get_strategy` | 无条件 |
| 自身目录内 `tool_interfaces.py` | `from .tool_interfaces import SqlQueryTool` | 无条件 |
| 公共工具库（白名单内的） | `from src.shared.exceptions import SkillException` | 需审计通过 |

以下来源 **严禁** import：

```
src/security/*           # 权限、鉴权、审计
src/data_platform/*      # 存储、缓存、数据库
src/adapters/*           # 外部系统防腐层
src/runtime/*            # 编排、上下文、任务闭环
src/model_service/*      # 模型网关（通过 Protocol 间接使用）
src/gateway/*            # 接入安全
src/config/*             # 全局配置（通过 manifest 声明）
```

---

## 4. L2：上下文注入控制（短期落地）

### 4.1 当前注入方式

当前 assembler 的 `execute()` 接收三个参数：

```python
assembler.execute(ctx, evidence, status)
```

- `ctx`：患者上下文（PatientContext）
- `evidence`：证据数据（Evidence）
- `status`：状态数据（Status）

这些参数由 `skill_infra` 或编排层在调用 assembler 时传入，但**当前没有规范定义这三个参数的内容边界**。

### 4.2 上下文最小化原则

> Skill 只应接收「完成其业务逻辑所需的最小数据集」。不应将整个患者记录、所有就诊历史、所有费用明细一次性灌入。

| 原则 | 说明 | 反例 |
|------|------|------|
| **最小化** | 只传需要的字段 | 传整个 Patient 对象而非仅费用明细 |
| **脱敏先行** | 传入 skill 的数据在注入前已完成脱敏 | 把原始身份证号、手机号传入 skill |
| **只读传递** | skill 接收的数据应是副本，不是引用 | 传入可变对象引用，skill 修改后影响主流程 |
| **显式声明** | skill 在 manifest 中声明它需要什么数据 | 不声明，靠调用方猜测 |

### 4.3 推荐：引入 SkillExecutionContext

在 manifest 中声明 skill 所需的上下文 Schema：

```yaml
# skill_manifest.yaml（扩展字段）
skill_id: settlement_explain_skill
skill_name: 医保费用解释

# ★ 新增：上下文依赖声明
context_dependencies:
  required:
    - field: patient_settlement         # 患者结算数据
      schema: schemas/input/settlement.json
    - field: applicable_policies        # 适用政策
      schema: schemas/input/policies.json
  optional:
    - field: annual_accumulation        # 年度累计
      schema: schemas/input/annual.json
```

`skill_infra`（或编排层）在注入上下文时，根据声明构造 `SkillExecutionContext`，skill 只能访问声明过的字段。**未声明的字段即使传入也不应被 skill 使用**（通过运行时校验，若 skill 访问未声明字段则告警）。

### 4.4 数据脱敏注入链

```
原始数据（含敏感字段）
  │
  ▼
security/desensitization/  ← 脱敏处理
  │
  ▼
SkillExecutionContext      ← 按 manifest 声明的 schema 裁剪
  │
  ▼
assembler.execute(ctx)     ← skill 只看到脱敏 + 裁剪后的数据
```

---

## 5. L3：执行环境隔离（中期规划）

当前不要求立即实现，但需在架构上预留接口。

### 5.1 目标架构

```
skill_infra/
├── skill_loader.py       ← 保持：动态发现 + 清单解析
├── skill_router.py       ← 保持：关键词/LLM 路由
├── skill_executor.py     ← ★ 新增：隔离执行器
│   ├── validate_imports(skill_dir)     → 静态分析，检查 import 白名单
│   ├── validate_context(declared, actual) → 运行时检查，确认上下文不越界
│   ├── execute_in_subprocess(args)      → 子进程隔离执行（中期）
│   └── execute_in_sandbox(args)         → 沙箱执行（长期）
└── skill_auditor.py      ← ★ 新增：skill 执行审计
    ├── log_execution_start(skill_id, ctx_schema)
    ├── log_execution_end(skill_id, duration, result)
    └── log_execution_error(skill_id, error)
```

### 5.2 分阶段路线

#### 阶段 A：静态检查（可立即落地）

在被 `SkillLoader` 加载时，对 skill 的 `assembler.py` 及所有被 import 的模块做静态 AST 分析，检测违禁 import：

```python
# skill_executor.py（伪代码 — 阶段 A）
FORBIDDEN_IMPORTS = {
    "psycopg2", "sqlalchemy", "aiomysql", "asyncpg",    # 数据库驱动
    "requests", "httpx", "aiohttp", "urllib3",           # HTTP 客户端
    "subprocess", "os.system", "threading",               # 进程/线程
    "src.security", "src.data_platform", "src.adapters",  # 主应用模块
    "src.runtime", "src.model_service", "src.gateway",
}

def validate_skill_imports(skill_dir: Path) -> list[str]:
    """扫描 skill 目录下所有 .py 文件，返回违禁 import 列表。"""
    violations = []
    for py_file in skill_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = _get_module_name(node)
                if _is_forbidden(module_name):
                    violations.append(f"{py_file}:{node.lineno} imports {module_name}")
    return violations
```

若检测到违禁 import，**拒绝加载该 skill**，记录告警日志，返回 `LoadError`。

#### 阶段 B：子进程隔离（中期，1-3 个月）

- skill 在独立子进程中执行（`multiprocessing` 或 `subprocess`）
- 子进程崩溃不影响主进程
- 通过序列化接口传递输入/输出
- 设置 CPU 时间和内存上限
- 可配置超时，超时后 kill 子进程

```python
# skill_executor.py（伪代码 — 阶段 B）
import multiprocessing as mp

def execute_skill_isolated(
    skill_id: str,
    assembler_path: str,
    context: SkillExecutionContext,
    timeout: float = 30.0,
    memory_limit_mb: int = 512,
) -> SkillResult:
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(
        target=_run_skill_in_worker,
        args=(assembler_path, context.to_dict(), queue),
    )
    proc.start()
    proc.join(timeout=timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join()
        raise SkillTimeoutError(skill_id, timeout)
    return SkillResult.from_dict(queue.get())
```

#### 阶段 C：容器/沙箱隔离（长期，3-6 个月）

- skill 在独立容器中执行（Docker / gVisor / Firecracker）
- 网络策略：默认禁止出站，白名单放行
- 文件系统：只读挂载 skill 目录，临时目录隔离
- 资源配额：CPU shares、memory limit、disk quota
- 适用于高风险 skill 或用户上传的第三方 skill

### 5.3 何时触发更高隔离级别

| 场景 | 最低隔离级别 |
|------|-------------|
| 项目内置 skill（如 `settlement_explain_skill`） | L1（静态检查） |
| 项目内置但涉及外部调用的 skill | L2（上下文控制 + 静态检查） |
| 第三方/用户上传的 skill | L3 阶段 B（子进程隔离）起 |
| 涉及高风险动作的 skill | 不允许以 skill 形式存在 —— 必须走主流程 |
| 需要访问患者敏感数据的 skill | L2（脱敏注入链）+ L3 阶段 B（子进程隔离） |

---

## 6. Skill 开发者检查清单

新增或修改 skill 时，开发者必须逐项确认：

### 6.1 结构规范

- [ ] 目录名 = `skill_id`，不含空格和特殊字符
- [ ] 包含 `skill_manifest.yaml`（含 `skill_id`, `skill_name`, `business_action`, `business_object`, `supported_intents`）
  - `business_action` 必须是 `BusinessAction` 七类之一（`explain` / `query` / `guide` / `verify` / `compare` / `evaluate` / `analyze`）
  - `business_object` 必须是 `BusinessObject` 枚举值
  - Action-Object 组合必须在 `src/domain/common/actions.py` 的 `VALID_ACTION_OBJECT_PAIRS` 白名单中
- [ ] 包含 `assembler.py`（含 `load()` 函数，返回 assembler 实例）
- [ ] 包含 `tool_interfaces.py`（声明 Protocol 接口，不实现）

### 6.2 Import 合规

- [ ] **不** import 数据库驱动（`psycopg2`, `sqlalchemy`, `aiomysql` 等）
- [ ] **不** import HTTP 客户端（`requests`, `httpx`, `aiohttp` 等）
- [ ] **不** import 主应用模块（`src.security`, `src.data_platform`, `src.adapters`, `src.runtime`, `src.model_service`, `src.gateway`）
- [ ] **不** 使用 `subprocess`, `os.system`, `threading`
- [ ] **不** 使用 `os.environ` 修改环境变量
- [ ] 外部能力通过 `tool_interfaces.py` 的 Protocol 声明，由基础设施层注入实现

### 6.3 数据与安全

- [ ] 不从环境变量读取密钥/配置（配置通过 manifest 或注入上下文获取）
- [ ] 不读取/写入 `skills/` 之外的文件
- [ ] 不在 skill 内部实现鉴权/授权/审计逻辑
- [ ] 异常上抛，不吞掉返回伪成功
- [ ] 输出包含 `citations`（来源引用）或 `uncertainties`（不确定性声明）

### 6.4 测试

- [ ] 有单元测试（`tests/` 目录）
- [ ] 有边界输入测试（空数据、缺失字段、异常数据）
- [ ] 有 Protocol mock，不依赖真实数据库/外部服务

---

## 7. Reviewer 检查清单

Review skill 相关 PR 时，按以下顺序快速筛查：

| 步骤 | 检查项 | 发现违规后 |
|------|--------|-----------|
| ① | Import 扫描：是否有违禁 import？ | 直接退回 |
| ② | 文件系统：是否在 `skills/<skill_id>/` 之外读写？ | 直接退回 |
| ③ | 外部调用：是否绕过了 Protocol/MCP，直接调 HTTP/DB？ | 直接退回 |
| ④ | 权限：是否在 skill 内实现鉴权/授权？ | 退回 + 说明应由基础设施层负责 |
| ⑤ | 审计：是否有无审计的写操作？ | 退回 + 要求补审计事件 |
| ⑥ | 输出：是否缺少 citations/uncertainties？ | 退回 |
| ⑦ | Manifest：context_dependencies 是否与实际使用的数据一致？ | 退回 + 要求对齐 |

---

## 8. 与项目其他模块的关系

```
                    ┌──────────────┐
                    │  skill_infra │  ← 负责加载/路由/隔离/审计
                    │  (R3 橙区)   │
                    └──────┬───────┘
                           │ 加载 & 注入
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌──────────┐    ┌──────────┐    ┌──────────┐
   │ skill A  │    │ skill B  │    │ skill C  │  ← skills/ (R1 绿区)
   │          │    │          │    │          │     只能通过 Protocol 调用外部能力
   └──────────┘    └──────────┘    └──────────┘
          │                │                │
          │ Protocol       │ Protocol       │ Protocol
          ▼                ▼                ▼
   ┌──────────────────────────────────────────────┐
   │              基础设施层 (R3-R4)               │
   │  adapters / model_service / knowledge_ext     │
   │  security / data_platform / gateway           │
   └──────────────────────────────────────────────┘
```

**关键约束**：skill 不能越过 `skill_infra` 直接接触基础设施层。所有外部调用必须通过 Protocol → 基础设施层代理。

---

## 9. 实施优先级

| 优先级 | 事项 | 产出 | 预计工作量 |
|--------|------|------|-----------|
| 🔴 P0 | 写入本文档 + skill import 白名单/黑名单 | 文档（已完成） | — |
| 🔴 P0 | AST 静态检查（`validate_skill_imports()`） | `src/skill_infra/skill_executor.py` | 1-2 天 |
| 🔴 P0 | Skill 执行审计事件 | `src/skill_infra/skill_auditor.py` | 0.5 天 |
| 🟡 P1 | SkillExecutionContext + manifest context_dependencies | 扩展 manifest schema + 上下文构造器 | 2-3 天 |
| 🟡 P1 | 数据脱敏注入链 | 与 `security/desensitization/` 对接 | 1-2 天 |
| 🟢 P2 | 子进程隔离执行 | `execute_skill_isolated()` | 3-5 天 |
| 🔵 P3 | 容器/沙箱隔离执行 | Docker/gVisor 集成 | 1-2 周 |

---

## 10. 变更记录

| 版本 | 日期 | 作者 | 说明 |
|------|------|------|------|
| v1.0 | 2026-06-29 | — | 初始版本：现状诊断 + L1/L2/L3 三层隔离设计 + 开发者/reviewer 检查清单 |
