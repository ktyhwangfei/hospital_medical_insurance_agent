# rule_explanation/ — 规则解释服务

## 概述

医保规则解释子系统：管理 rule_explanations 表的 CRUD 操作，并提供基于 Milvus 的政策检索、语义映射、规则重排序、解释规划等下层能力。

## 结构

```
rule_explanation/
├── service.py                          # RuleExplanationService（CRUD 主入口）
├── postgres.py                         # PostgreSQL 存储（rule_explanations 表）
├── models.py                           # Pydantic 请求/响应模型
├── ports.py                            # 存储端口抽象
├── in_memory.py                        # 内存存储（开发/测试用）
├── policy_retrieval/                   # 政策检索子系统
│   ├── milvus_retriever.py             # MilvusPolicyRetriever（向量+标量搜索）
│   ├── policy_rules_schema.py          # Milvus collection schema（policy_rules，19字段）
│   ├── data_model1_loader.py           # Excel → Milvus 加载（24条规则）
│   ├── milvus_ingest.py                # 批量/增量写入
│   ├── mcp_result_normalizer.py        # MCP 查询结果归一化 → Milvus 过滤
│   ├── query_understanding.py          # QueryUnderstandingService（意图识别+实体抽取）
│   ├── semantic_mapping.py             # SemanticMapper（口语→系统术语映射）
│   ├── reranker.py                     # RuleBasedReranker（规则重排序）
│   ├── explanation_planner.py          # ExplanationPlanner（解释结构规划）
│   ├── sqlserver_business_data_client.py  # SqlServerBusinessDataClient（SQL Server 实时数据）
│   ├── embedding_provider.py           # 向量化提供方
│   ├── embedding_text_builder.py       # 嵌入文本组装
│   ├── question_rewriter.py            # 问题改写
│   ├── contextual_policy_qa.py         # 上下文政策问答
│   ├── context_requirement.py          # 上下文需求
│   ├── case_context.py                 # 案例上下文
│   ├── claim_explain_tree.py           # 结算解释树
│   ├── explanation_trace.py            # 解释链路追踪
│   ├── excel_loader.py                 # Excel 数据加载基类
│   ├── utils.py                        # 工具函数
│   ├── models.py                       # 检索相关 Pydantic 模型
│   ├── business_data_client.py         # 业务数据客户端抽象
│   ├── config/
│   │   └── business_sql.yaml           # SQL 查询配置（SQL Server 用）
│   └── test_*.py                       # 各模块测试
├── crawl/                              # 政策爬虫
├── policy_extract/                     # 政策提取
├── policy_fact/                        # 政策事实
├── policy_node/                        # 政策节点
└── policy_struct/                      # 政策结构化
```

## 关键约定

- `rule_explanations` 表主键 `rule_explanation_id`，定义在 `postgres.py` 中
- policy_rules 的 Milvus collection 字段名遵循原始 Excel 列名：`insu_type`、`med_type`、`hosp_lv`、`person_type`、`deductible_line` 等（19 字段，详见 `policy_rules_schema.py`）
- 语义映射由 `semantic_mapping.py` 完成：用户口语（如"三甲"）→ 系统标准值（如 `hosp_lv=3`）
- Milvus 端口：开发环境 19530，生产环境 19121
- SQL Server 端口 1433，查询语句统一配置在 `config/business_sql.yaml` 中
- `SqlServerBusinessDataClient` 需先调用 `check_connection()` 验证连通性

## 注意事项

- `policy_retrieval/` 下仅 `milvus_retriever.py`、`reranker.py`、`query_understanding.py`、`semantic_mapping.py`、`explanation_planner.py`、`sqlserver_business_data_client.py` 为核心检索管线组件，其余为辅助/测试模块
- `policy_extract/`、`policy_fact/`、`policy_node/`、`policy_struct/`、`crawl/` 为独立子领域，有各自的入口和逻辑
- 24 条初始规则从 `policy_active_rules.xlsx` 加载，由 `data_model1_loader.py` 写入 Milvus
- MCP 查询结果需经 `mcp_result_normalizer.py` 归一化后方可进行 Milvus 过滤
