# knowledge_extension/ — 知识与扩展服务

## 概述

错误码知识库（PostgreSQL CRUD）、RAG 检索（Milvus 向量）、规则解释（CRUD）、提示模板（含渲染引擎，CRUD）、知识资产（含切片管理→向量化，CRUD）、申诉模板（CRUD）、MCP 注册中心。

## 结构

```
knowledge_extension/
├── knowledge/            # 错误码知识库（postgres.py CRUD + in_memory 内存字典）
├── knowledge/appeal_postgres.py  # 申诉模板 CRUD
├── rag/                  # RAG 管道 + 向量检索
│   ├── pipeline.py       # RAGPipeline 主入口
│   ├── in_memory.py      # InMemoryHybridRetriever（关键词匹配）
│   └── milvus/           # Milvus 向量存储实现
├── rule_explanation/     # 规则解释服务（postgres.py CRUD）
├── prompt_templates/     # 提示模板管理（postgres.py CRUD + render）
├── assets/               # 知识资产（postgres.py CRUD）
├── extension_registry/   # 扩展注册表
├── mcp_registry/         # MCP 注册中心
│   ├── models.py         # McpServer, McpCapability, McpRiskLevel
│   ├── discovery.py      # 服务发现
│   ├── transport/        # stdio/SSE 传输层
│   ├── client_gateway.py # MCP 客户端网关
│   ├── config_import.py  # 配置导入
│   ├── demo_tools.py     # 演示工具
│   └── storage/          # PostgreSQL/Redis 存储
└── common/               # 共享模型（AuditSummary, VisibilityScope）
```

## 关键约定

- `McpRiskLevel` (HIGH/MEDIUM/LOW) 在 `mcp_registry/models.py` 定义，被 `domain/skill` 引用
- 知识资产使用 `VisibilityScope` 控制可见性（角色 + 租户 + 院区）
- MCP 工具调用需通过安全边界校验（风险等级 + 角色权限）
- RAG 检索支持关键词匹配（in_memory）和向量检索（Milvus）
- PostgreSQL CRUD: error_code_knowledge, rule_explanations, knowledge_assets, knowledge_chunks, appeal_templates, prompt_templates 六张表

## 注意事项

- `knowledge/in_memory.py` 中 `ERROR_CODE_KNOWLEDGE` 是硬编码字典，仅含 `E-UPLOAD-001`
- `assets/in_memory.py` 中 `build_default_asset_repository()` 提供初始知识资产
- MCP 注册中心 stdio 传输已实现，SSE 传输待完善
- 各 CRUD 端点定义见 `docs/steering/接口设计文档.md` §10 知识管理
