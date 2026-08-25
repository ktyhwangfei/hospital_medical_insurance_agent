# knowledge_extension/ — 知识与扩展服务

## 概述

MCP 注册中心、规则解释服务（含 Milvus 政策检索、SQL Server 业务数据）、扩展注册表、共享模型（状态、引用溯源、可见性范围）。

**已移除模块**：原 knowledge/（错误码知识库 CRUD）、assets/（知识资产+切片管理+向量化 CRUD）、rag/（RAG 管道+向量检索）、prompt_templates/（提示模板 CRUD+渲染引擎）、申诉模板 CRUD 均已删除；`service.py` 仅保留最小兼容接口。

## 结构

```
knowledge_extension/
├── common/               # 共享模型
│   └── models.py         # KnowledgeExtensionStatus, VisibilityScope, Citation, Degradation, AuditSummary
├── extension_registry/   # 扩展注册表
│   ├── models.py         # ExtensionType, ExtensionRiskLevel, ExtensionCapability, ExtensionSelectionRequest/Result
│   ├── ports.py          # ExtensionRegistry Protocol（select 接口）
│   └── in_memory.py      # 内存实现
├── mcp_registry/         # MCP 注册中心
│   ├── __init__.py       # 导出 McpServer, McpCapability, McpRiskLevel, McpRegistryService 等
│   ├── models.py         # McpServer, McpCapability, McpRiskLevel (HIGH/MEDIUM/LOW), McpCapabilityType, McpTransportType
│   ├── service.py        # McpRegistryService（注册+安全校验：风险等级+角色权限）
│   ├── storage_provider.py  # 存储 Provider（PostgreSQL/内存）
│   ├── ports.py          # 端口抽象
│   ├── discovery.py      # 服务发现
│   ├── transport.py      # 传输层抽象（stdio/SSE）
│   ├── stdio_client.py   # stdio 传输客户端
│   ├── client_gateway.py # MCP 客户端网关
│   ├── config_import.py  # mcp_config.yaml 导入
│   └── demo_tools.py     # 演示工具
├── rule_explanation/     # 规则解释服务（详见 rule_explanation/AGENTS.md）
│   ├── service.py        # RuleExplanationService（CRUD 主入口）
│   ├── postgres.py       # PostgreSQL 存储（rule_explanations 表）
│   ├── in_memory.py      # 内存存储（开发/测试用）
│   ├── models.py         # Pydantic 请求/响应模型
│   ├── ports.py          # 存储端口抽象
│   ├── policy_retrieval/ # 政策检索子系统（Milvus 向量检索 + SQL Server 实时数据）
│   │   ├── milvus_retriever.py, reranker.py, query_understanding.py,
│   │   ├── semantic_mapping.py, explanation_planner.py,
│   │   ├── sqlserver_business_data_client.py, data_model1_loader.py,
│   │   ├── milvus_ingest.py, policy_rules_schema.py, embedding_provider.py,
│   │   ├── mcp_result_normalizer.py, question_rewriter.py, contextual_policy_qa.py,
│   │   ├── context_requirement.py, case_context.py, claim_explain_tree.py,
│   │   ├── explanation_trace.py, excel_loader.py, utils.py, models.py,
│   │   ├── business_data_client.py, embedding_text_builder.py,
│   │   └── config/business_sql.yaml  # SQL 查询配置
│   ├── crawl/            # 政策爬虫
│   ├── policy_extract/   # 政策提取
│   ├── policy_fact/      # 政策事实
│   ├── policy_node/      # 政策节点
│   └── policy_struct/    # 政策结构化
└── service.py            # ★ 知识扩展服务 stub（原 assets/rag/prompt_templates 已删除）
```

## 关键约定

- `McpRiskLevel` (HIGH/MEDIUM/LOW) 在 `mcp_registry/models.py` 定义，被 `domain/skill` 引用
- 知识资产使用 `VisibilityScope` 控制可见性（角色 + 租户 + 院区）
- MCP 工具调用需通过安全边界校验（风险等级 + 角色权限）
- MCP 注册中心 stdio 传输已实现，SSE 传输待完善
- rule_explanations 表主键 `rule_explanation_id`，定义在 `rule_explanation/postgres.py`
- policy_rules Milvus collection 字段名遵循原始 Excel 列名（19 字段，详见 `policy_rules_schema.py`）
- 语义映射由 `rule_explanation/policy_retrieval/semantic_mapping.py` 完成：用户口语→系统标准值

## 注意事项

- `service.py` 为兼容 stub，所有方法返回空值/NO_HIT——原模块已整体移除
- MCP 注册中心端点定义见 `src/runtime/api/mcp_routes.py`（9 端点）
- 政策知识 CRUD 端点定义见 `src/runtime/api/policy_knowledge_routes.py`（7 端点）
- 政策问答 SSE 端点定义见 `src/runtime/api/policy_qa_routes.py`（5 端点）
- `knowledge/in_memory.py`、`assets/in_memory.py`、`rag/`、`prompt_templates/` 等文件已不在代码库中
