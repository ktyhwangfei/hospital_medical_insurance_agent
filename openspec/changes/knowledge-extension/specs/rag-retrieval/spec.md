## ADDED Requirements

### Requirement: RAG retrieval must support hybrid retrieval
系统 MUST 提供面向医保业务的 RAG 检索能力，支持语义检索、关键词检索或两者组合，并返回结构化检索结果。检索请求 MUST 支持查询文本、业务场景、角色、租户、院区、知识类型、有效日期、最大召回数量、上下文预算和追踪标识。

#### Scenario: Retrieve policy evidence for settlement exception
- **WHEN** 运行时针对医保结算异常发起知识检索
- **THEN** RAG 服务 MUST 返回与错误码、政策规则或处理建议相关的检索结果
- **AND** 每条结果 MUST 包含来源资产、切片标识、分数和检索时间

#### Scenario: Retrieve with filters
- **WHEN** 检索请求包含场景、知识类型、有效日期或角色范围过滤条件
- **THEN** RAG 服务 MUST 仅返回满足过滤条件且当前用户可见的结果

#### Scenario: Retrieve respects effective date
- **WHEN** 检索请求指定业务发生日期或政策适用日期
- **THEN** RAG 服务 MUST 优先返回该日期范围内有效的知识切片
- **AND** 过期或尚未生效的切片 MUST NOT 作为默认确定性依据

### Requirement: RAG retrieval must rerank and assemble context
系统 MUST 支持对召回结果进行重排，并将结果组装为可供模型或确定性响应使用的上下文包。

#### Scenario: Assemble model context
- **WHEN** 运行时需要模型生成医保规则说明
- **THEN** RAG 服务 MUST 返回上下文包
- **AND** 上下文包 MUST 包含候选切片、引用清单、上下文文本和裁剪说明

#### Scenario: Context budget exceeded
- **WHEN** 检索结果超过上下文预算
- **THEN** RAG 服务 MUST 按分数、业务优先级和来源可信度裁剪上下文
- **AND** 上下文包 MUST 记录被裁剪结果数量

#### Scenario: Reranking tie is deterministic
- **WHEN** 多条检索结果具有相同或近似分数
- **THEN** RAG 服务 MUST 使用来源可信度、生效日期、资产类型优先级和切片标识进行稳定排序
- **AND** 相同输入 MUST 产生可重复的上下文顺序

### Requirement: RAG retrieval must produce traceable citations
系统 MUST 将检索结果转换为可用于 API 响应的引用来源，引用 MUST 包含来源标题、来源类型、版本、章节或切片标识、有效日期、检索分数区间、检索时间和检索依据。

#### Scenario: Chat response uses retrieved citations
- **WHEN** Chat 响应使用 RAG 检索结果生成导办说明
- **THEN** 响应 MUST 包含由检索结果生成的 citations
- **AND** citations MUST 能追溯到知识资产和知识切片

#### Scenario: Citation hides restricted internals
- **WHEN** 检索命中的知识来源包含内部文件路径、文件指纹或受限审计字段
- **THEN** 面向用户的 citations MUST 只展示可公开的标题、类型、版本、章节和依据摘要
- **AND** 内部定位信息 MUST 仅进入审计记录

### Requirement: RAG retrieval failures must degrade safely
系统 MUST 在知识索引不可用、检索超时、无命中或重排失败时返回结构化降级结果，而不是编造知识依据。

#### Scenario: No retrieval hits
- **WHEN** RAG 检索没有命中可用知识
- **THEN** RAG 服务 MUST 返回无命中状态
- **AND** 最终导办响应 MUST 包含不确定性提示或建议人工复核

#### Scenario: Retrieval source unavailable
- **WHEN** 向量存储或知识索引不可用
- **THEN** RAG 服务 MUST 返回可审计失败结果
- **AND** 运行时 MUST 将知识服务不可用纳入 workflow 降级状态

#### Scenario: Partial retrieval failure
- **WHEN** 关键词召回成功但语义召回、重排或上下文组装失败
- **THEN** RAG 服务 MUST 返回部分成功状态
- **AND** 结果 MUST 携带可用 citations 和对应 uncertainties
