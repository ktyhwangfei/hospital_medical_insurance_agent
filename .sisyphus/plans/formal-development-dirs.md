# 工作计划：正式开发 apps/ interaction/ gateway/ deploy/ 目录

## 概述

根据架构设计文档，正式开发以下4个目录：
- `apps/` - SaaS应用入口层
- `interaction/` - 多模态交互层
- `gateway/` - 统一接入网关
- `deploy/` - 部署配置增强

## 架构约束

- 四层架构：SaaS → PaaS → DaaS → 基础设施
- 解耦纪律：业务逻辑严禁耦合外部系统接口
- 高风险动作：必须拦截转为waiting_human_confirmation
- 来源可追溯：AI输出必须携带citations
- 模型调用统一：所有LLM调用必须通过model_service/gateway

## 任务分解

### Wave 1: gateway/ - 统一接入网关（基础设施层）

**任务1.1: api_gateway模块**
- 创建 `src/gateway/api_gateway/__init__.py`
- 实现ApiGatewayMiddleware中间件
- 实现RequestAggregator请求聚合器
- 集成到FastAPI应用

**任务1.2: channel渠道识别**
- 创建 `src/gateway/channel/__init__.py`
- 实现ChannelDetector渠道检测器
- 支持portal/embedded/mobile/admin/api五种渠道

**任务1.3: auth认证鉴权**
- 创建 `src/gateway/auth/__init__.py`
- 实现Authenticator认证器
- 实现Token验证和权限检查

**任务1.4: tenant租户隔离**
- 创建 `src/gateway/tenant/__init__.py`
- 实现TenantContext租户上下文
- 支持医院/院区/科室/系统来源隔离

**任务1.5: rate_limiter限流熔断**
- 创建 `src/gateway/rate_limiter/__init__.py`
- 实现RateLimiter限流器
- 支持令牌桶算法

**任务1.6: request_guard请求安全校验**
- 创建 `src/gateway/request_guard/__init__.py`
- 实现RequestGuard请求守卫
- 参数校验、敏感动作拦截

**任务1.7: access_log接入日志**
- 创建 `src/gateway/access_log/__init__.py`
- 实现AccessLogger访问日志
- 记录请求/响应/审计信息

### Wave 2: interaction/ - 多模态交互层

**任务2.1: chat聊天模块**
- 创建 `src/interaction/chat/__init__.py`
- 实现ChatSession会话管理
- 实现MessageHandler消息处理
- 支持多轮对话和卡片消息

**任务2.2: file文件上传**
- 创建 `src/interaction/file/__init__.py`
- 实现FileUploader文件上传器
- 支持文件选择、上传状态、预览

**任务2.3: voice语音交互**
- 创建 `src/interaction/voice/__init__.py`
- 实现VoiceProcessor语音处理器
- 支持语音采集、播放、转写

**任务2.4: page_context页面上下文**
- 创建 `src/interaction/page_context/__init__.py`
- 实现PageContextManager上下文管理器
- 支持患者、住院号、页面来源

**任务2.5: notification消息提醒**
- 创建 `src/interaction/notification/__init__.py`
- 实现NotificationService通知服务
- 支持待办提醒、风险提醒

**任务2.6: knowledge_upload知识上传**
- 创建 `src/interaction/knowledge_upload/__init__.py`
- 实现KnowledgeUploader知识上传器
- 支持政策、制度、规则导入

### Wave 3: apps/ - SaaS应用入口层

**任务3.1: portal统一门户**
- 创建 `src/apps/portal/__init__.py`
- 实现PortalApp门户应用
- 统一入口、角色路由

**任务3.2: embedded_widgets嵌入式组件**
- 创建 `src/apps/embedded_widgets/__init__.py`
- 实现WidgetManager组件管理器
- 支持HIS/EMR/医生站嵌入

**任务3.3: admin_console管理后台**
- 创建 `src/apps/admin_console/__init__.py`
- 实现AdminConsole管理控制台
- 智能体配置、知识管理、用户管理

### Wave 4: deploy/ - 部署配置增强

**任务4.1: Docker配置**
- 创建 `deploy/docker/Dockerfile`
- 创建 `deploy/docker/docker-compose.yml`
- 创建 `deploy/docker/.env.example`

**任务4.2: 环境变量模板**
- 创建 `deploy/env/.env.production`
- 创建 `deploy/env/.env.development`
- 创建 `deploy/env/.env.testing`

## 依赖关系

```
Wave 1 (gateway/) ← Wave 2 (interaction/) ← Wave 3 (apps/)
                                    ↑
                            Wave 4 (deploy/) - 独立
```

## 测试策略

每个模块需要：
1. 单元测试：测试核心逻辑
2. 集成测试：测试与现有代码的集成
3. API测试：测试端点功能

## 验证命令

```bash
# 运行全部测试
python -m pytest src/tests -v

# 运行单个模块测试
python -m pytest src/tests/gateway -v
python -m pytest src/tests/interaction -v
python -m pytest src/tests/apps -v

# 启动开发服务器
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload
```
