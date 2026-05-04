## ADDED Requirements

### Requirement: Knowledge assets must be versioned and traceable
系统 MUST 为医保政策、院内制度、错误码、审核规则、申诉模板和业务说明材料建立统一知识资产模型，模型 MUST 包含资产标识、类型、标题、摘要、来源系统或来源文件、来源 URL 或文件指纹、版本、生效状态、生效日期、失效日期、导入时间、可见范围、数据质量状态和审计事件。

#### Scenario: Import policy knowledge asset
- **WHEN** 运维人员或初始化程序导入医保政策知识
- **THEN** 系统 MUST 创建知识资产记录
- **AND** 知识资产 MUST 包含来源、版本、状态和审计事件

#### Scenario: Query inactive knowledge asset
- **WHEN** 运行时检索知识时命中过期或未发布资产
- **THEN** 系统 MUST NOT 将该资产作为默认可用依据返回
- **AND** 系统 MUST 在审计事件中记录被过滤的资产状态

#### Scenario: Import duplicate knowledge version
- **WHEN** 系统导入同一资产标识和版本的知识资产
- **THEN** 系统 MUST 拒绝覆盖已发布资产或创建可审计的新修订记录
- **AND** 审计事件 MUST 记录重复版本处理结果

### Requirement: Knowledge assets must be chunked for retrieval
系统 MUST 将可检索知识资产拆分为知识切片，切片 MUST 保留资产标识、资产版本、切片标识、章节、段落定位、原文摘要、结构化标签、可检索文本、来源定位信息、可见范围和索引状态。

#### Scenario: Chunk policy document
- **WHEN** 系统接入一份可检索政策文档
- **THEN** 系统 MUST 生成一个或多个知识切片
- **AND** 每个切片 MUST 能追溯到原始知识资产和原文位置

#### Scenario: Chunk carries business tags
- **WHEN** 知识切片与结算异常、出院质控、拒付申诉或 DRG/DIP 运营场景相关
- **THEN** 切片 MUST 支持记录业务场景、规则类别、适用人群或适用病种等标签

#### Scenario: Chunk omits sensitive raw fields
- **WHEN** 知识切片包含患者示例、费用明细样例或院内敏感运营信息
- **THEN** 系统 MUST 在切片入库前脱敏或标记为受限可见
- **AND** 默认检索结果 MUST NOT 向无权角色返回敏感原文

### Requirement: Knowledge asset access must respect permissions and scope
系统 MUST 在知识资产查询和检索前执行角色权限、租户范围、院区范围和知识可见性过滤。

#### Scenario: Role cannot access internal policy
- **WHEN** 用户角色无权访问内部院内制度知识
- **THEN** 系统 MUST NOT 返回该知识资产或其切片内容
- **AND** 系统 MUST 记录权限过滤审计事件

#### Scenario: Tenant scoped knowledge retrieval
- **WHEN** 多医院或多院区上下文请求知识检索
- **THEN** 系统 MUST 仅返回当前上下文允许范围内的知识资产

#### Scenario: Filtered asset remains auditable
- **WHEN** 知识资产因权限、租户、院区或可见性范围被过滤
- **THEN** 系统 MUST 记录过滤原因和资产标识摘要
- **AND** 系统 MUST NOT 在普通用户响应中泄露被过滤资产的正文

### Requirement: Knowledge asset indexing must expose status
系统 MUST 跟踪知识资产的索引状态，覆盖未索引、索引中、已索引、索引失败和需重建索引等状态。

#### Scenario: Asset index succeeds
- **WHEN** 知识资产完成切片并写入可检索索引
- **THEN** 系统 MUST 将索引状态更新为已索引
- **AND** 系统 MUST 记录索引时间和索引审计事件

#### Scenario: Asset index fails
- **WHEN** 知识资产切片或索引写入失败
- **THEN** 系统 MUST 将索引状态更新为索引失败
- **AND** 失败状态 MUST 包含可审计错误类型和用户可读原因

#### Scenario: Asset content changes after indexing
- **WHEN** 知识资产版本、正文、可见范围或切片策略发生变化
- **THEN** 系统 MUST 将索引状态标记为需重建索引
- **AND** 运行时检索 MUST NOT 默认使用已失配的旧索引作为确定性依据
