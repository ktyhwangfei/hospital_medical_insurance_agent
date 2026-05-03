## 1. Project-root 工程骨架与配置基线

- [x] 1.1 创建 `runtime/`、`business_scenarios/`、`domain/`、`adapters/`、`data_platform/`、`knowledge_extension/`、`security/`、`shared/`、`config/`、`tests/` 后端 MVP 目录结构
- [x] 1.2 在 `runtime/api/` 创建 FastAPI 应用入口、路由注册、版本信息和健康检查接口
- [x] 1.3 在 `shared/exceptions/` 添加统一异常模型和 HTTP 错误映射
- [x] 1.4 在 `shared/schemas/` 添加统一响应结构，覆盖 scenario、status、result、citations、tasks、missing_fields、uncertainties、blocked_actions 和 audit
- [x] 1.5 在 `config/security_policy/` 定义医保办、收费员、信息科、病案室、临床医生、科主任和院领导角色及权限边界
- [x] 1.6 在 `config/security_policy/` 定义各角色最小必要字段展示规则、患者敏感数据脱敏规则和高风险动作黑名单
- [ ] 1.7 在 `config/agent_orchestration/` 定义医保结算异常导办、出院前联合质控和高风险动作请求的场景流程配置
- [ ] 1.8 在 `config/adapter/` 定义第一阶段内存适配器启用配置和未来真实系统适配器替换点
- [ ] 1.9 在 `tests/` 下创建 unit、integration、e2e、adapter_contract、rag_evaluation、security 测试目录和 pytest 基础配置

## 2. domain 领域模型层

- [ ] 2.1 在 `domain/common/` 设计 Citation、DataReference、DataQuality、AuditRef、RiskLevel、WorkflowStatus 和通用错误码模型
- [ ] 2.2 在 `domain/patient/` 设计患者、就诊、住院、门诊和患者索引模型
- [ ] 2.3 在 `domain/insurance/` 设计医保待遇、医保交易、结算状态、费用上传状态、医保错误码和医保目录相关模型
- [ ] 2.4 在 `domain/order_fee/` 设计医嘱、费用明细、药品、耗材和诊疗项目模型
- [ ] 2.5 在 `domain/audit_risk/` 设计事前审核结果、规则命中、违规金额和风险摘要模型
- [ ] 2.6 在 `domain/drg_dip/` 设计 DRG/DIP 预分组、盈亏预测、费用结构和病组风险模型
- [ ] 2.7 在 `domain/medical_record/` 设计病案首页、诊断、手术、编码、病案质控和病历证据模型
- [ ] 2.8 在 `domain/task/` 设计任务、待办、人工确认、处理记录和闭环状态模型

## 3. data_platform 数据与知识底座

- [x] 3.1 在 `data_platform/data_access/` 定义统一数据访问端口，返回数据内容、来源系统、来源记录标识、采集时间和质量状态
- [ ] 3.2 在 `data_platform/storage/relational/` 定义结构化存储端口，第一阶段提供内存实现承载患者、就诊、费用、医嘱、病案、结算和审核样例数据
- [x] 3.3 在 `data_platform/storage/cache/` 定义会话缓存、限流计数和分布式锁端口，第一阶段提供内存实现
- [x] 3.4 在 `data_platform/storage/vector/` 定义向量检索端口，第一阶段提供内存知识检索实现
- [ ] 3.5 在 `data_platform/patient_profile/` 建立患者医保画像基础版，聚合医保待遇、费用上传、结算状态、审核风险、DRG/DIP 结果和任务状态
- [ ] 3.6 在 `data_platform/master_data/` 建立医保主数据基础模型，覆盖药品、项目、耗材、科室、医生、病种和规则主数据
- [ ] 3.7 在 `data_platform/data_quality/` 实现数据质量提示机制，标记缺失、过期、不一致和来源不可追溯的数据
- [ ] 3.8 在 `data_platform/data_access/` 实现内存样例数据装载，覆盖两类 MVP 场景所需患者、就诊、费用、审核结果、DRG/DIP 结果和结算异常数据

## 4. knowledge_extension 知识与扩展服务

- [x] 4.1 在 `knowledge_extension/knowledge/` 建立内存错误码知识库，支持错误码、错误描述、可能原因、处理建议和责任角色查询
- [ ] 4.2 在 `knowledge_extension/knowledge/` 建立内存医保政策知识库，支持政策条款、适用范围、来源文件和生效时间检索
- [ ] 4.3 在 `knowledge_extension/rule_explanation/` 建立规则解释库，支持事前审核规则命中原因和医保目录限制条件解释
- [ ] 4.4 在 `knowledge_extension/rag/` 实现知识检索结果的来源引用结构，支持在 AI 输出中展示政策、错误码、规则或模板来源
- [ ] 4.5 在 `knowledge_extension/prompt_templates/` 定义结算异常导办、出院前联合质控和高风险动作确认的确定性输出模板
- [ ] 4.6 在 `knowledge_extension/rag/` 预留 Milvus 向量检索替换端口，第一阶段由内存知识检索实现承载

## 5. adapters 业务系统适配器层

- [ ] 5.1 在 `adapters/base/` 定义适配器基类、认证占位、重试策略、异常模型、日志模型、脱敏钩子和权限映射钩子
- [x] 5.2 在 `adapters/insurance_interface/` 定义并实现内存医保接口适配器，支持交易流水、费用上传状态、预结算状态、结算状态和错误信息查询
- [x] 5.3 在 `adapters/billing/` 定义并实现内存收费系统适配器，支持收费结算状态、费用明细和结算失败记录查询
- [x] 5.4 在 `adapters/pre_audit/` 定义并实现内存事前审核适配器，支持审核结果、规则命中、违规金额和规则解释查询
- [x] 5.5 在 `adapters/drg_dip/` 定义并实现内存 DRG/DIP 适配器，支持预分组、盈亏预测、费用结构和病案风险查询
- [x] 5.6 在 `adapters/his/` 定义并实现内存 HIS 适配器，支持患者、就诊、住院、费用和医嘱查询
- [x] 5.7 在 `adapters/emr/` 定义并实现内存 EMR 适配器，支持病历、诊断、手术、病程和出院记录查询
- [x] 5.8 在 `adapters/medical_record/` 定义并实现内存病案系统适配器，支持病案首页、编码和病案质控结果查询
- [ ] 5.9 在 `adapters/base/` 实现适配器调用审计，记录调用时间、调用能力、输入摘要、输出摘要、来源系统和操作用户

## 6. security 安全围栏

- [x] 6.1 在 `security/authorization/` 实现角色权限校验，限制用户访问超出权限范围的患者、费用、审核、病案和结算数据
- [x] 6.2 在 `security/desensitization/` 实现患者姓名、证件号、联系方式等敏感数据脱敏和最小必要展示策略
- [x] 6.3 在 `security/risk_control/` 实现高风险动作识别，覆盖正式结算、退费、冲正、撤销结算、病案首页修改、费用明细修改和最终申诉结论确认
- [x] 6.4 在 `security/risk_control/` 实现高风险动作拦截结果，将禁止自动执行的动作转换为建议、草稿或待办任务
- [x] 6.5 在 `security/audit/` 实现审计记录端口和内存审计日志，覆盖请求、响应、适配器调用、规划、编排、人工确认和任务闭环
- [ ] 6.6 在 `security/audit/` 实现导办流程审计视图，展示请求用户、执行计划、步骤状态、调用能力、输入输出引用、人工确认和最终结果

## 7. runtime AI 导办运行时

- [ ] 7.1 在 `runtime/session/` 实现会话生命周期、会话状态和会话恢复的内存模型
- [ ] 7.2 在 `runtime/api/` 实现医保 AI Chat API，记录用户身份、角色、请求内容和请求时间
- [x] 7.3 在 `runtime/api/` 实现患者上下文查询 API，支持按角色返回最小必要字段
- [x] 7.4 在 `runtime/intent/` 实现医保业务意图识别，至少识别医保结算异常导办、出院前联合质控和高风险动作请求
- [x] 7.5 在 `runtime/clarification/` 实现缺失关键对象的多轮澄清响应，阻止系统编造缺失业务对象
- [ ] 7.6 在 `runtime/context/` 实现运行时上下文构建服务，聚合用户、角色、患者、就诊、业务数据、知识引用和数据质量状态
- [ ] 7.7 在 `runtime/planning/` 定义 ExecutionPlan 数据结构，包括目标、场景、步骤、依赖、风险等级、人工确认标记、输出要求和审计信息
- [ ] 7.8 在 `runtime/planning/` 定义计划步骤类型，包括系统查询、知识检索、规则解释、模型调用、证据抽取、文档生成、任务创建、人工确认和结果返回
- [ ] 7.9 在 `runtime/planning/` 实现医保结算异常导办、出院前联合质控和高风险动作请求规划模板
- [ ] 7.10 在 `runtime/planning/` 实现计划校验和计划解释能力，覆盖权限、上下文完整性、适配器可用性、高风险动作、循环依赖和输出格式
- [x] 7.11 在 `runtime/runtime_state/` 定义 WorkflowInstance 和 StepState 数据结构，记录流程实例、当前步骤、步骤状态、输入输出引用和审计引用
- [ ] 7.12 在 `runtime/orchestration/` 实现顺序执行和基础 DAG 调度能力
- [ ] 7.13 在 `runtime/orchestration/` 实现业务系统适配器调用、知识检索、规则解释、模板生成和任务创建步骤执行器
- [x] 7.14 在 `runtime/scheduling/` 实现失败重试、超时处理、降级返回和终止策略
- [x] 7.15 在 `runtime/task_closure/` 实现人工确认暂停、恢复、任务创建、任务更新、任务关闭和任务状态流转
- [x] 7.16 在 `runtime/response/` 实现 Web SDK 友好的统一响应组装，包含 scenario、status、result、citations、tasks、missing_fields、uncertainties、blocked_actions 和 audit

## 8. business_scenarios 医保业务场景

- [x] 8.1 在 `business_scenarios/settlement_exception_guide/` 固化医保结算异常导办输入问题样例、输出字段、数据来源、责任角色和人工确认点
- [x] 8.2 在 `business_scenarios/settlement_exception_guide/` 实现医保结算异常导办端到端链路：交易查询、费用上传查询、错误码检索、收费状态查询、异常归因和处理建议生成
- [x] 8.3 在 `business_scenarios/settlement_exception_guide/` 实现结算异常导办结果结构，包含异常类型、错误码解释、可能原因、涉及系统、责任角色、推荐步骤、人工确认要求和审计记录
- [x] 8.4 在 `business_scenarios/pre_discharge_joint_qc/` 固化出院前联合质控输入问题样例、输出字段、数据来源、责任角色和人工确认点
- [x] 8.5 在 `business_scenarios/pre_discharge_joint_qc/` 实现出院前联合质控端到端链路：费用医嘱查询、医保接口状态查询、事前审核查询、DRG/DIP 查询、规则解释检索和风险清单生成
- [x] 8.6 在 `business_scenarios/pre_discharge_joint_qc/` 实现联合质控风险清单结构，包含结算准备风险、合规拒付风险、DRG/DIP 支付风险、病案首页风险、费用结构风险、来源引用和处理建议
- [x] 8.7 在 `business_scenarios/pre_discharge_joint_qc/` 实现整改任务创建能力，将风险项转化为关联患者、就诊、风险类型、责任角色、证据引用和处理建议的待办任务

## 9. observability 与基础设施替换边界

- [x] 9.1 在 `observability/logging/` 预留结构化日志接口，第一阶段可由标准日志或内存记录实现
- [x] 9.2 在 `observability/metrics/` 预留任务完成率、平均处理时长、风险发现数量和结算异常处理时长指标定义
- [x] 9.3 在 `data_platform/storage/relational/` 预留 PostgreSQL 结构化数据、任务和审计日志持久化替换端口
- [x] 9.4 在 `data_platform/storage/cache/` 预留 Redis/Valkey 会话缓存、限流和分布式锁替换端口
- [x] 9.5 在 `data_platform/storage/vector/` 预留 Milvus 向量检索替换端口
- [x] 9.6 在 `runtime/api/` 确保 OpenAPI 文档暴露 Chat、患者上下文、流程状态和任务闭环相关接口

## 10. tests 验证与验收

- [x] 10.1 在 `tests/e2e/` 使用 pytest 和 FastAPI TestClient 验证医保结算异常导办在交易失败、错误码存在、费用上传异常和数据不足情况下的输出完整性
- [x] 10.2 在 `tests/e2e/` 使用 pytest 和 FastAPI TestClient 验证出院前联合质控在存在合规风险、DRG/DIP 风险、病案风险和数据缺失情况下的风险清单准确性
- [x] 10.3 在 `tests/security/` 验证权限不足用户无法访问超范围患者、费用、审核、病案和结算数据
- [x] 10.4 在 `tests/security/` 验证高风险动作不会被 AI 自动执行，并会转换为建议、草稿或待办任务
- [x] 10.5 在 `tests/integration/` 验证所有 AI 输出均包含来源引用或明确的不确定性提示
- [x] 10.6 在 `tests/adapter_contract/` 验证外部系统调用失败时系统能够重试、降级或返回可解释失败原因
- [x] 10.7 在 `tests/integration/` 验证审计记录可还原一次导办流程的用户、计划、步骤、调用、确认和结果
- [x] 10.8 在 `tests/integration/` 验证 OpenAPI 文档能够暴露 Chat、患者上下文、流程状态和任务闭环相关接口
