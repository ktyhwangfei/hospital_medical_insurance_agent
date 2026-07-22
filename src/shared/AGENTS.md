# shared/ — 共享基础：异常、Schema 契约、技能模型

## OVERVIEW

三层基础设施：异常层次定义 API 错误语义 → Schema 契约保证响应结构一致 → 技能引擎提供 YAML 驱动的可插拔工具。

## STRUCTURE

```
shared/
├── exceptions/models.py    # 异常基类体系：BaseAppError → NotFoundError / ValidationError / AuthError 等
├── schemas/
│   ├── contracts.py        # Schema 契约：Citation、AdapterCallResult、ConfidenceLevel 等纯数据模型
│   └── responses.py        # AgentResponse、ChatRequest、ErrorDetail + error_detail() 工厂
└── skills/
    ├── loader.py            # YAML 技能文件解析器
    ├── models.py            # Skill、SkillStep、SkillMetadata（Pydantic 模型）
    ├── registry.py          # SkillRegistry — 内存技能查找，技能启动时加载
    └── SKILL.md             # 技能文件格式文档，写新技能前先读
```

## KEY CONVENTIONS

- **错误响应格式**：`{ error_code: str, message: str, audit_event: dict | None }`，统一用 `error_detail()` 构造。禁止手写 `{"error": ...}`。
- **AgentResponse.result 类型债务**：当前为 `dict[str, Any]`。新增场景时优先在 result 中放结构化 dict，后续逐步 Pydantic-ization。禁止往 result 里塞原始 LLM 文本。
- **技能加载时机**：`SkillRegistry.load_all()` 在应用启动时调用，扫描 `skills/` 目录下所有 `.yaml`/`.yml` 文件。增量更新技能后需重启应用。
- **Skill.skill_id 命名**：必须使用 `kebab-case` 或 `snake_case`，禁止大写或空格（如 `"calc_drg"` 或 `"calc-drg"` 正确，`"CalcDRG"` 错误）。
- **Schema 契约不可变**：`contracts.py` 中已定义的模型（Citation、AdapterCallResult 等）不可修改字段名或类型。新增场景需要新契约时追加新模型。
- **测试映射**：`src/tests/unit/shared/skills/` 下有 3 个测试文件，覆盖 loader / models / registry。修改技能相关代码后必须运行该目录全量测试。

## ANTI-PATTERNS

- 不要在 shared 层引入外部系统依赖（HTTP 客户端、数据库驱动）。shared 是整个项目的零依赖基石。
- 不要修改 `error_detail()` 返回结构——前端和监控系统依赖 `error_code` / `message` / `audit_event` 这三个顶层键。
- 不要用 `Optional` 或 `Union` 污染 AgentResponse 的结构字段。response 字段应始终非空，不确定内容放入 `uncertainties`。
- 不要在技能加载时做网络 I/O。loader 是纯 YAML 解析，技能所需的远程资源在 `execute()` 阶段获取。
