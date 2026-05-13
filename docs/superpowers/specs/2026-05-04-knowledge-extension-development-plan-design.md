# Knowledge Extension 模块开发计划设计

## 背景

`knowledge-extension` OpenSpec 变更已经定义知识资产、RAG 检索、规则解释、提示词模板、扩展注册、运行时执行闭环和安全契约。本开发计划设计用于把 OpenSpec 规范转化为可执行实施计划，完整覆盖 `openspec/changes/knowledge-extension/tasks.md` 中 8 个任务组。

当前代码中 `src/knowledge_extension/` 只有 `knowledge/` 内存错误码知识库。后续实现必须在保持现有 Chat API、医保结算异常导办、出院前联合质控和安全契约兼容的前提下，新增知识与扩展服务能力。

## 目标

- 完整覆盖资产、RAG、规则解释、模板、扩展注册、门面、运行时集成、API/安全验证 8 个任务组。
- 同时提供高层阶段设计和可进一步展开为逐文件实施任务的开发计划基础。
- 优先建立 Pydantic 模型、Protocol 端口、内存实现和测试闭环，不接入真实向量库、知识管理后台或远程扩展执行沙箱。
- 保证知识服务与业务适配器、模型服务、运行时编排解耦。
- 保证所有用户可见 AI 输出满足 citations 或 uncertainties。

## 非目标

- 不实现知识管理后台 UI。
- 不新增真实 Milvus、Elasticsearch、对象存储或关系数据库依赖。
- 不实现真实 MCP Server、A2A 协议或远程 Tool 沙箱。
- 不让知识服务直接访问 HIS、EMR、医保接口、收费、事前审核、DRG/DIP 或病案系统。
- 不替代医保正式结算、事前审核裁决、DRG/DIP 正式分组、病案修改或申诉最终结论。

## 开发计划组织方式

采用推荐混合方案：核心契约先行、子能力纵向实现、门面聚合、运行时/API 集成。

### 备选方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 横向分层 | 模型与端口统一，边界一致 | 前期很久没有业务闭环 | 不采用 |
| 纵向切片 | 每个能力可以独立验证 | 公共模型和引用合并容易反复调整 | 不采用 |
| 混合方案 | 控制返工，逐步形成测试闭环，贴合 OpenSpec 任务组 | 初始契约设计需要更严谨 | 采用 |

## 高层里程碑

### 里程碑 1：基础契约与共享模型

建立知识与扩展能力共同使用的引用、降级、审计、可见范围、脱敏摘要和状态模型。该阶段为后续资产、RAG、规则解释、模板和扩展注册提供一致返回语义。

验收重点：模型类型明确；返回类型禁止裸 `dict`；状态枚举覆盖成功、无命中、部分降级、权限拒绝、不可用、版本不匹配、证据冲突、模板缺失和高风险拦截。

### 里程碑 2：知识资产与 RAG 检索

先实现资产、切片、索引状态和可见范围过滤，再实现内存混合检索、有效期过滤、确定性重排、上下文预算裁剪和 API citations 映射。

验收重点：内存资产仓储不泄露可变内部状态；检索结果可追溯到资产与切片；无命中和部分失败进入结构化降级；面向用户 citations 不暴露内部路径、文件指纹和受限审计字段。

### 里程碑 3：规则解释、模板和扩展注册

实现确定性规则解释、模板选择/渲染安全和扩展目录/权限/高风险拦截。三个子能力分别单测闭环，并复用共享引用、降级和审计模型。

验收重点：规则解释不输出正式裁决；模板变量不能覆盖系统级安全约束；扩展选择执行角色、场景、健康状态和风险校验；高风险扩展不自动执行。

### 里程碑 4：知识与扩展服务门面

新增运行时唯一入口，组合资产、RAG、规则解释、模板和扩展注册能力。门面负责 citations 去重、uncertainties 合并、审计事件合并、内部证据到 API 响应字段映射。

验收重点：运行时和业务场景不直接依赖各子模块内存实现；重复引用能稳定去重；无证据时输出 uncertainties；内部敏感字段不进入 API 响应。

### 里程碑 5：运行时与场景集成

在医保结算异常导办和出院前联合质控中接入知识增强步骤。workflow 状态记录知识与扩展步骤输入输出引用、最终响应引用映射、降级状态和审计事件。

验收重点：现有主流程兼容；知识增强失败不破坏业务响应；workflow 审计视图可还原知识检索、规则解释、模板选择、扩展选择和知识降级事件。

### 里程碑 6：API、前端与安全验证

保持 `AgentResponse` 兼容，新增知识增强信息进入 `result`、`citations`、`uncertainties` 和 `audit` 子字段。更新前端引用展示和知识降级提示，补齐 OpenAPI、安全边界和全量测试。

验收重点：OpenAPI 不出现破坏性变更；所有最终响应满足 citations 或 uncertainties；敏感字段不泄露；高风险动作仍转人工确认。

## 组件与目录设计

### `src/knowledge_extension/common/`

存放共享枚举、引用、降级、审计摘要、可见范围、脱敏摘要模型。该目录只承载知识扩展域内部共享模型，不替代 `src/domain/common/`。

### `src/knowledge_extension/assets/`

存放知识资产、知识切片、索引状态、查询过滤条件、资产仓储 Protocol、切片仓储 Protocol、索引器 Protocol 和内存实现。

### `src/knowledge_extension/rag/`

存放检索请求、过滤条件、召回结果、重排结果、上下文包、检索引用、检索器 Protocol、重排器 Protocol、上下文组装器 Protocol 和内存实现。

### `src/knowledge_extension/rule_explanation/`

存放规则解释请求、规则证据、解释结果、适用条件、限制说明、人工复核提示、规则解释器 Protocol 和内存实现。该模块兼容 `src/knowledge_extension/knowledge/in_memory.py` 的现有错误码知识。

### `src/knowledge_extension/prompt_templates/`

存放提示词模板、模板类型、模板状态、变量 schema、输出安全约束、模板仓储、模板选择器、模板渲染器和内存模板。

### `src/knowledge_extension/extension_registry/`

存放扩展能力、扩展类型、输入输出 schema、风险等级、权限要求、场景范围、超时策略、重试策略、健康状态、审计策略、扩展注册表、扩展选择器、健康检查和内存注册表。

### `src/knowledge_extension/service.py`

存放知识与扩展服务门面。运行时通过该门面获取知识增强、规则增强、模板选择和扩展选择结果，不直接依赖各子模块具体实现。

### 测试目录

- `src/tests/knowledge_extension/`：新增知识扩展单元测试目录。
- `src/tests/integration/`：扩展运行时和业务场景集成测试。
- `src/tests/security/`：扩展安全边界测试。

## 数据流设计

Chat 请求仍沿用现有业务主流程：`runtime/api` → `runtime/intent` → `security/risk_control` → `security/authorization` → 业务场景服务。知识增强不改变主流程，只在业务场景内部或运行时计划步骤中通过 `knowledge_extension/service.py` 门面调用。

核心数据流：

1. 业务场景根据意图、患者/就诊摘要、角色和场景构造知识增强请求。
2. 门面先执行模板选择和知识范围过滤，再调用 RAG 检索与规则解释。
3. 子能力返回内部证据、引用、不确定性和审计摘要。
4. 门面统一去重 citations、合并 uncertainties、脱敏审计摘要，并返回给业务场景。
5. 业务场景将知识增强结果合并到现有 `AgentResponse` 的 `result`、`citations`、`uncertainties`、`audit` 字段。
6. workflow 状态记录每个知识步骤的输入输出引用、降级原因和最终响应引用映射。

## 边界约束

- 知识服务不得直接调用 HIS、EMR、医保接口、收费、事前审核、DRG/DIP 或病案适配器。
- 业务系统数据仍由业务场景通过 adapters 获取，再以最小必要摘要传入知识门面。
- 高风险动作仍由 `security/risk_control` 和任务闭环处理。
- 扩展注册本阶段只做元数据注册、选择和风控，不执行真实远程能力调用。

## 错误处理与降级设计

子能力不向上抛出业务可恢复异常，而是返回结构化状态。不可恢复的编程错误仍通过测试暴露，不吞异常。

结构化状态包括：成功、无命中、部分降级、权限拒绝、不可用、版本不匹配、证据冲突、模板缺失、高风险拦截。

降级策略：

- RAG 无命中：返回无命中状态，最终响应带人工复核或知识不足不确定性。
- 模板缺失：回退确定性业务响应，不让模型自由生成无约束内容。
- 规则未知、证据不足或证据冲突：不生成正式结论，只返回不确定性与人工复核建议。
- 扩展不可用或权限拒绝：不调用能力，记录审计事件，必要时返回降级说明。

## 安全设计

- 知识范围过滤在召回、解释、模板选择、扩展选择前执行。
- 面向 API 的 citations 不暴露内部路径、文件指纹、Token、完整敏感原文。
- 高风险动作即使出现在知识、规则或模板中，也不能绕过风控，必须转人工确认。
- 任何最终 AI 导办输出必须有 citations 或 uncertainties。
- 扩展输入摘要和输出摘要必须脱敏后进入审计事件。

## 测试设计

### 单元测试

新增 `src/tests/knowledge_extension/`，分别覆盖资产、RAG、规则解释、模板、扩展注册、门面的模型校验、内存实现、边界条件和降级状态。

### 集成测试

扩展 `src/tests/integration/`，覆盖结算异常导办知识增强、出院前联合质控规则解释、模板缺失降级、扩展权限拒绝、重复 citations 合并、workflow 审计记录。

### 安全测试

扩展 `src/tests/security/`，覆盖高风险扩展不自动执行、知识内容不绕过风控、敏感字段不进入 citations 或扩展审计摘要。

### API 与 OpenAPI 测试

确保 `AgentResponse` 兼容，不新增破坏性字段。新增信息进入 `citations`、`uncertainties`、`audit`、`result` 子字段。

### 前端冒烟

更新 `src/static/index.html` 引用来源与知识降级提示展示逻辑后，通过现有测试和页面结构检查确认不破坏根页面。

## 可执行任务清单轮廓

后续实施计划应按以下顺序展开为逐文件任务：

1. 新增 `src/knowledge_extension/common/` 共享模型与测试。
2. 新增 `src/knowledge_extension/assets/` 模型、端口、内存实现、样例数据与测试。
3. 新增 `src/knowledge_extension/rag/` 模型、端口、内存检索、重排、上下文组装、citations 映射与测试。
4. 新增 `src/knowledge_extension/rule_explanation/` 模型、端口、内存解释器、错误码兼容适配与测试。
5. 新增 `src/knowledge_extension/prompt_templates/` 模型、端口、内存模板仓储、选择、渲染与测试。
6. 新增 `src/knowledge_extension/extension_registry/` 模型、端口、内存注册表、选择校验、高风险拦截与测试。
7. 新增 `src/knowledge_extension/service.py` 门面和门面测试。
8. 扩展运行时计划模型与 workflow 状态模型。
9. 接入医保结算异常导办知识增强。
10. 接入出院前联合质控规则解释增强。
11. 扩展审计视图和 workflow 查询结果。
12. 更新 Chat、流式 Chat、OpenAPI 和前端兼容展示。
13. 补齐安全边界测试、集成测试和全量回归。
14. 执行验收命令并修复失败。

## 验收命令

```bash
python -m pytest src/tests -v
npx openspec validate "knowledge-extension" --strict
```

## 验收标准

- 所有测试通过。
- OpenSpec 严格校验通过。
- 医保结算异常导办和出院前联合质控主流程仍兼容。
- 知识增强失败时不会编造依据。
- 所有最终响应满足 citations 或 uncertainties。
- 高风险动作不被知识、规则、模板或扩展能力绕过。
- API citations 不泄露内部路径、文件指纹、Token、完整敏感原文。

## 后续计划生成要求

用户审阅本设计后，应进入 writing-plans 流程生成详细实施计划。实施计划必须按小步提交组织，每一步包含目标文件、测试文件、实现要点、边界条件和验收命令。
