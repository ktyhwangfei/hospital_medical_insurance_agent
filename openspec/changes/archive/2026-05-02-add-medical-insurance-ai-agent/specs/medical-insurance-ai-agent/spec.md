## ADDED Requirements

### Requirement: AI Chat Unified Entry
系统 SHALL 提供医保 AI Chat 统一入口，支持医保办、收费员、信息科、病案室、临床医生、科主任和院领导通过自然语言发起医保业务导办请求。

#### Scenario: 用户发起医保导办请求
- **WHEN** 用户通过医保 AI Chat 输入医保业务问题
- **THEN** 系统 SHALL 接收请求并创建会话上下文
- **AND** 系统 SHALL 记录用户身份、角色、请求内容和请求时间

#### Scenario: 用户请求缺少关键对象
- **WHEN** 用户请求缺少患者、就诊、科室、时间范围或业务对象等必要信息
- **THEN** 系统 SHALL 发起澄清
- **AND** 系统 SHALL 不得编造缺失业务对象

### Requirement: Role Permission and Sensitive Data Protection
系统 SHALL 在处理医保导办请求前校验用户角色权限，并对患者敏感数据进行最小必要展示和脱敏处理。

#### Scenario: 用户具备访问权限
- **WHEN** 用户访问其权限范围内的患者、就诊、费用、审核或结算数据
- **THEN** 系统 SHALL 允许继续构建导办上下文
- **AND** 系统 SHALL 按角色展示最小必要字段

#### Scenario: 用户缺少访问权限
- **WHEN** 用户请求访问超出其权限范围的数据
- **THEN** 系统 SHALL 拒绝访问
- **AND** 系统 SHALL 记录权限校验失败审计事件

### Requirement: Runtime Context Construction
系统 SHALL 基于用户请求、角色权限、患者索引、就诊索引、费用、医嘱、诊断、病案、医保交易和业务系统状态构建运行时上下文。

#### Scenario: 构建患者医保上下文
- **WHEN** 用户请求分析某患者医保风险
- **THEN** 系统 SHALL 构建包含患者、就诊、费用、医保待遇、交易状态、审核结果、DRG/DIP 结果和任务状态的运行时上下文
- **AND** 系统 SHALL 标记每类上下文数据的来源系统和更新时间

#### Scenario: 上下文数据质量不足
- **WHEN** 构建上下文时发现关键数据缺失、过期或不一致
- **THEN** 系统 SHALL 在上下文中标记数据质量问题
- **AND** 系统 SHALL 在导办结果中提示不确定性和补充数据建议

### Requirement: Template-first Task Planning
系统 SHALL 基于场景模板优先生成结构化执行计划，并允许模型辅助补全复杂任务，但所有计划 MUST 经过校验后才能执行。

#### Scenario: 生成医保结算异常导办计划
- **WHEN** 用户询问患者医保结算失败原因
- **THEN** 系统 SHALL 识别为医保结算异常导办场景
- **AND** 系统 SHALL 生成包含医保交易查询、费用上传状态查询、错误码知识检索、收费状态查询、异常归因和处理建议生成的执行计划

#### Scenario: 生成出院前联合质控计划
- **WHEN** 用户请求检查患者出院前医保风险
- **THEN** 系统 SHALL 识别为出院前联合质控场景
- **AND** 系统 SHALL 生成包含费用医嘱查询、医保接口状态查询、事前审核结果查询、DRG/DIP 预分组查询、规则解释检索、风险清单生成和整改任务创建的执行计划

#### Scenario: 执行计划校验失败
- **WHEN** 执行计划缺少必要上下文、适配器能力、权限授权或存在非法高风险动作
- **THEN** 系统 SHALL 阻止计划执行
- **AND** 系统 SHALL 返回失败原因和可修复建议

### Requirement: Orchestration Execution
系统 SHALL 按执行计划调度模型、知识库、规则解释、工具、业务系统适配器和任务闭环服务，并持久化每个步骤的状态和审计信息。

#### Scenario: 成功执行导办计划
- **WHEN** 执行计划通过校验
- **THEN** 系统 SHALL 创建工作流实例
- **AND** 系统 SHALL 按步骤依赖关系执行查询、检索、解释、生成和任务创建动作
- **AND** 系统 SHALL 保存每个步骤的输入引用、输出引用、状态、耗时和调用能力

#### Scenario: 外部系统调用失败
- **WHEN** 业务系统适配器调用超时、失败或返回不可用
- **THEN** 系统 SHALL 根据错误类型进行重试、降级或终止步骤
- **AND** 系统 SHALL 在导办结果中展示受影响的数据来源和不确定性

#### Scenario: 流程需要人工确认
- **WHEN** 执行计划到达人工确认节点
- **THEN** 系统 SHALL 暂停工作流实例
- **AND** 系统 SHALL 保存当前上下文、已完成步骤输出和待确认事项

### Requirement: Data and Knowledge Foundation
系统 SHALL 提供医保数据与知识底座，统一管理结构化数据、向量知识、文件材料、缓存、主数据、患者医保画像、指标和数据质量信息。

#### Scenario: 查询医保业务数据
- **WHEN** 编排执行步骤需要患者、就诊、费用、医嘱、诊断、病案、审核、分组或结算数据
- **THEN** 系统 SHALL 通过统一数据访问服务查询数据
- **AND** 系统 SHALL 返回数据来源、来源记录标识、采集时间和质量状态

#### Scenario: 检索医保知识
- **WHEN** 导办流程需要解释政策、错误码、规则命中或申诉依据
- **THEN** 系统 SHALL 从医保政策知识库、错误码知识库、规则解释库或模板库中检索相关知识
- **AND** 系统 SHALL 返回可展示的知识来源引用

### Requirement: Business System Adapter Abstraction
系统 SHALL 通过适配器抽象访问首信医保接口、东软事前审核、大瑞集思 DRG/DIP、HIS、EMR、病案系统、收费系统和任务系统。

#### Scenario: 调用医保接口适配器
- **WHEN** 导办流程需要查询医保交易流水、费用上传状态、预结算状态或医保错误信息
- **THEN** 系统 SHALL 通过医保接口适配器调用对应能力
- **AND** 系统 SHALL 统一处理认证、超时、重试、错误码归一和审计记录

#### Scenario: 调用事前审核和 DRG/DIP 适配器
- **WHEN** 导办流程需要查询合规审核结果、规则命中、DRG/DIP 预分组、盈亏预测或病案风险
- **THEN** 系统 SHALL 通过对应适配器获取结果
- **AND** 系统 SHALL 明确标记结果来源厂商、来源系统和生成时间

### Requirement: Settlement Exception Guidance
系统 SHALL 支持医保结算异常导办，能够聚合医保交易状态、费用上传状态、错误码知识、收费结算状态和相关审核风险，生成可执行处理建议。

#### Scenario: 生成结算异常处理建议
- **WHEN** 医保交易失败或返回错误码
- **THEN** 系统 SHALL 返回异常类型、错误码解释、可能原因、涉及系统、责任角色、推荐处理步骤、是否需要人工确认和审计记录

#### Scenario: 结算异常原因无法确定
- **WHEN** 当前数据不足以判断结算异常原因
- **THEN** 系统 SHALL 返回已排除原因、待补充数据、建议排查路径和责任角色
- **AND** 系统 SHALL 不得输出确定性根因结论

### Requirement: Pre-discharge Joint Quality Control
系统 SHALL 支持出院前联合质控，能够聚合医保接口、事前审核、DRG/DIP、病案首页、费用明细、医嘱和医保数据中台信息，生成联合质控风险清单。

#### Scenario: 生成出院前联合质控清单
- **WHEN** 用户请求检查患者出院前医保风险
- **THEN** 系统 SHALL 返回结算准备风险、合规拒付风险、DRG/DIP 支付风险、病案首页风险和费用结构风险
- **AND** 系统 SHALL 为每项风险提供来源引用、风险等级、处理建议和责任角色

#### Scenario: 生成整改任务
- **WHEN** 联合质控清单存在需要处理的风险项
- **THEN** 系统 SHALL 支持创建整改待办任务
- **AND** 系统 SHALL 记录任务关联患者、就诊、风险类型、责任角色、处理建议和来源证据

### Requirement: Human Confirmation for High-risk Actions
系统 SHALL 对高风险动作进行人工确认或自动拦截，AI 不得直接执行正式结算、退费、冲正、撤销结算、病案首页修改、费用明细修改或最终申诉结论确认。

#### Scenario: 高风险动作被拦截
- **WHEN** 执行计划包含正式结算、退费、冲正、撤销结算、病案首页修改或费用明细修改动作
- **THEN** 系统 SHALL 阻止自动执行
- **AND** 系统 SHALL 将动作转换为建议、材料草稿或待办任务
- **AND** 系统 SHALL 要求具备权限的人工用户确认

#### Scenario: 用户确认高风险建议
- **WHEN** 人工用户确认某项高风险建议
- **THEN** 系统 SHALL 记录确认人、确认时间、确认内容和确认前后的上下文
- **AND** 系统 SHALL 不得绕过既有业务系统的正式操作流程

### Requirement: Evidence Citation and Auditability
系统 SHALL 对 AI 输出、系统调用、知识检索、模型调用、人工确认和任务闭环保留来源引用和审计记录。

#### Scenario: 用户查看 AI 风险解释来源
- **WHEN** 用户查看 AI 生成的风险解释、异常归因、质控清单或处理建议
- **THEN** 系统 SHALL 展示对应结构化数据、知识片段、规则解释、业务系统记录或任务记录的来源引用

#### Scenario: 审计导办流程
- **WHEN** 管理员或审计人员查看某次导办流程
- **THEN** 系统 SHALL 展示请求用户、执行计划、步骤状态、调用能力、输入输出引用、人工确认、任务闭环和最终结果

### Requirement: Task Closure Tracking
系统 SHALL 支持将导办结果转化为可分派、可跟踪、可关闭的任务，并沉淀任务闭环指标。

#### Scenario: 创建导办任务
- **WHEN** 导办结果包含需要医保办、收费员、信息科、病案室或临床科室处理的事项
- **THEN** 系统 SHALL 支持创建任务
- **AND** 系统 SHALL 记录任务状态、责任角色、优先级、截止时间、证据引用和处理建议

#### Scenario: 关闭导办任务
- **WHEN** 责任人完成整改并提交处理结果
- **THEN** 系统 SHALL 更新任务状态
- **AND** 系统 SHALL 记录闭环结果、处理耗时和复核信息

### Requirement: FastAPI Backend MVP Contract
系统 SHALL 在第一阶段提供 FastAPI 后端 MVP，暴露医保 AI 导办 Chat、患者上下文、流程状态和任务闭环相关 API，并通过 OpenAPI 文档描述接口契约。

#### Scenario: 调用医保 AI Chat API
- **WHEN** 前端、Web SDK、H5 容器或第三方系统调用医保 AI Chat API
- **THEN** 系统 SHALL 接收用户身份、角色、自然语言消息、患者标识、就诊标识和可选业务对象
- **AND** 系统 SHALL 返回场景、状态、结构化结果、来源引用、任务、缺失字段、不确定性、高风险拦截动作和审计摘要

#### Scenario: 查询患者上下文 API
- **WHEN** 前端请求查看某患者某就诊的医保上下文
- **THEN** 系统 SHALL 按用户角色返回最小必要字段
- **AND** 系统 SHALL 对患者敏感信息进行脱敏

#### Scenario: 暴露 OpenAPI 文档
- **WHEN** 开发人员访问 FastAPI OpenAPI 文档
- **THEN** 系统 SHALL 展示 Chat、患者上下文、流程状态和任务闭环相关接口定义

### Requirement: Infrastructure Port Replaceability
系统 SHALL 在第一阶段使用内存实现验证 MVP，并通过端口和适配器抽象预留 PostgreSQL、Redis/Valkey、Milvus、Nginx 和真实医院业务系统的替换边界。

#### Scenario: 使用内存实现运行 MVP
- **WHEN** 系统在本地开发或自动化测试环境启动
- **THEN** 系统 SHALL 能够不依赖 PostgreSQL、Redis/Valkey、Milvus、Nginx 或真实医院系统完成两个 MVP 场景
- **AND** 系统 SHALL 使用内存数据、内存知识库、内存适配器和内存审计记录

#### Scenario: 替换为 PostgreSQL 持久化
- **WHEN** 后续实施需要持久化结构化数据、任务和审计日志
- **THEN** 系统 SHALL 能够通过数据访问端口替换内存仓储为 PostgreSQL 实现
- **AND** 系统 SHALL 不改变上层规划、编排和 API 契约

#### Scenario: 替换为 Redis/Valkey 与 Milvus
- **WHEN** 后续实施需要会话缓存、限流、分布式锁或向量检索
- **THEN** 系统 SHALL 能够通过缓存端口和知识检索端口接入 Redis/Valkey 与 Milvus
- **AND** 系统 SHALL 不改变导办结果响应结构

### Requirement: Automated Verification Coverage
系统 SHALL 为医保 AI 导办后端 MVP 提供自动化测试，覆盖核心业务场景、安全边界、降级行为和审计可追溯性。

#### Scenario: 验证医保结算异常导办
- **WHEN** 自动化测试提交包含交易失败、错误码和费用上传异常的 Chat 请求
- **THEN** 系统 SHALL 返回结算异常类型、错误码解释、可能原因、责任角色、处理步骤、来源引用和审计摘要

#### Scenario: 验证出院前联合质控
- **WHEN** 自动化测试提交出院前风险检查请求
- **THEN** 系统 SHALL 返回合规拒付风险、DRG/DIP 支付风险、病案首页风险、整改任务和来源引用

#### Scenario: 验证安全边界
- **WHEN** 自动化测试提交权限不足请求或高风险动作请求
- **THEN** 系统 SHALL 拒绝越权访问或拦截高风险动作
- **AND** 系统 SHALL 记录审计事件

#### Scenario: 验证降级和不确定性提示
- **WHEN** 自动化测试模拟外部系统调用失败或关键数据缺失
- **THEN** 系统 SHALL 返回降级状态、不确定性提示、受影响数据来源和可解释失败原因
