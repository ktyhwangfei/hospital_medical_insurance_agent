# Prototype Frontend Static Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将前端入口统一到 [`prototype`](../../../prototype/) 目录，删除旧 [`src/static`](../../../src/static/) 静态前端，并让 FastAPI 后端只保留 API。

**Architecture:** 后端应用 [`create_app()`](../../../src/runtime/api/app.py) 不再注册静态页面路由，只保留健康检查、业务 API 与 MCP API。旧静态 HTML 文件和对应测试整体删除，文档改为指向独立 Next.js 前端目录 [`prototype`](../../../prototype/)。

**Tech Stack:** Python 3、FastAPI、pytest、Next.js、npm、Git。

---

## 文件结构

- Modify: [`src/runtime/api/app.py`](../../../src/runtime/api/app.py) — 移除 `Path`、`FileResponse` 与 `/`、`/mcp-admin`、`/prototype` 静态页面路由。
- Delete: [`src/static/index.html`](../../../src/static/index.html) — 旧根页面。
- Delete: [`src/static/mcp-admin.html`](../../../src/static/mcp-admin.html) — 旧 MCP 管理静态页面。
- Delete: [`src/static/prototype.html`](../../../src/static/prototype.html) — 已弃用原型静态页面。
- Delete: [`src/tests/integration/test_mcp_management_ui.py`](../../../src/tests/integration/test_mcp_management_ui.py) — 旧静态页面文件读取测试。
- Modify: [`AGENTS.md`](../../../AGENTS.md) — 更新前端说明，明确 [`prototype`](../../../prototype/) 是唯一前端目录。
- Optional: [`README.md`](../../../README.md) — 当前文件疑似编码异常，不在本计划中重写，避免无关改动。

## Task 1: 后端移除静态页面路由

**Files:**
- Modify: [`src/runtime/api/app.py`](../../../src/runtime/api/app.py:1)
- Test: [`src/tests/integration/test_openapi_contract.py`](../../../src/tests/integration/test_openapi_contract.py:8)

- [ ] **Step 1: 记录当前健康检查基线**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py::test_health_version_and_openapi_contract -q`

Expected: `1 passed`，证明 FastAPI 应用创建和 `/health` 当前可用。

- [ ] **Step 2: 修改 [`src/runtime/api/app.py`](../../../src/runtime/api/app.py:1)**

将文件内容调整为：

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.runtime.api.mcp_routes import router as mcp_router
from src.runtime.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title='medical-insurance-ai-agent')

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            'http://127.0.0.1:3000',
            'http://localhost:3000',
            'http://127.0.0.1:5173',
            'http://localhost:5173',
        ],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    app.include_router(router, prefix='/api/v1/medical-insurance-ai-agent')
    app.include_router(mcp_router)
    return app
```

- [ ] **Step 3: 验证后端应用仍可创建且健康检查通过**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py::test_health_version_and_openapi_contract -q`

Expected: `1 passed`。

- [ ] **Step 4: 提交后端路由清理**

```bash
git add src/runtime/api/app.py
git commit -m "refactor: remove static page routes"
```

## Task 2: 删除旧静态目录和旧静态页测试

**Files:**
- Delete: [`src/static/index.html`](../../../src/static/index.html)
- Delete: [`src/static/mcp-admin.html`](../../../src/static/mcp-admin.html)
- Delete: [`src/static/prototype.html`](../../../src/static/prototype.html)
- Delete: [`src/tests/integration/test_mcp_management_ui.py`](../../../src/tests/integration/test_mcp_management_ui.py)

- [ ] **Step 1: 删除旧静态文件和对应测试**

Run:

```cmd
del src\static\index.html src\static\mcp-admin.html src\static\prototype.html
rmdir src\static
del src\tests\integration\test_mcp_management_ui.py
```

Expected: 命令完成后 [`src/static`](../../../src/static/) 目录不存在，旧测试文件不存在。

- [ ] **Step 2: 确认 Git 删除状态**

Run: `git status --short src/static src/tests/integration/test_mcp_management_ui.py`

Expected:

```text
 D src/static/index.html
 D src/static/mcp-admin.html
 D src/tests/integration/test_mcp_management_ui.py
```

如果 [`src/static/prototype.html`](../../../src/static/prototype.html) 是未跟踪文件，则不会显示为 `D`；只需确认它已从工作区删除。

- [ ] **Step 3: 运行旧 UI 测试路径确认不再收集**

Run: `python -m pytest src/tests/integration/test_mcp_management_ui.py -q`

Expected: pytest 报告文件不存在或无测试可运行；这是预期，因为该测试文件已经删除。

- [ ] **Step 4: 提交静态目录清理**

```bash
git add -A src/static src/tests/integration/test_mcp_management_ui.py
git commit -m "refactor: remove deprecated static frontend"
```

## Task 3: 更新项目说明

**Files:**
- Modify: [`AGENTS.md`](../../../AGENTS.md:85)

- [ ] **Step 1: 修改 [`AGENTS.md`](../../../AGENTS.md:85) 前端说明**

将原有“前端演示页”说明替换为：

```markdown
前端原型目录: `prototype/`，基于 Next.js 独立运行；FastAPI 后端只提供 API，不再从 `src/static/` 返回静态页面。
```

- [ ] **Step 2: 搜索运行时代码中的旧目录引用**

Run: `python -c "from pathlib import Path; paths=[p for p in Path('src').rglob('*') if p.is_file() and p.suffix in {'.py','.html','.md','.txt'}]; hits=[str(p) for p in paths if 'src/static' in p.read_text(encoding='utf-8', errors='ignore') or 'static/index.html' in p.read_text(encoding='utf-8', errors='ignore')]; print('\n'.join(hits))"`

Expected: 无输出，或只输出已删除路径之外的历史缓存文件；不得出现 [`src/runtime`](../../../src/runtime/)、[`src/tests`](../../../src/tests/) 运行时代码对 [`src/static`](../../../src/static/) 的引用。

- [ ] **Step 3: 提交文档更新**

```bash
git add AGENTS.md
git commit -m "docs: document prototype frontend entry"
```

## Task 4: 全量验证

**Files:**
- Verify: [`src/tests`](../../../src/tests/)
- Verify: [`prototype/package.json`](../../../prototype/package.json)

- [ ] **Step 1: 运行后端测试**

Run: `python -m pytest src/tests -q`

Expected: 全部测试通过，无失败。

- [ ] **Step 2: 运行前端构建**

Run: `npm run build`

Working directory: [`prototype`](../../../prototype/)

Expected: 构建成功，命令退出码为 `0`。

- [ ] **Step 3: 确认 worktree 状态**

Run: `git status --short --branch`

Expected: 只包含本任务产生的已提交记录之外的既有未提交变更；不得再出现 [`src/static`](../../../src/static/) 未跟踪文件。

- [ ] **Step 4: 汇总结果**

记录以下验证证据：

```text
python -m pytest src/tests -q
npm run build，cwd=prototype
git status --short --branch
```

## 自检

- 设计文档中的删除旧静态目录、删除静态路由、删除旧测试、更新文档、后端与前端验证均已有对应任务。
- 计划没有未决占位项；[`README.md`](../../../README.md) 因编码异常被明确排除，不影响本次目标。
- 后端 API 保留范围和用户确认的“后端只保留 API”一致。
