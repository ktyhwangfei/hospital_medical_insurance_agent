# gateway/ — 统一接入网关

## OVERVIEW

请求入口的七层防线：渠道识别 → 认证鉴权 → 租户隔离 → 限流熔断 → 安全校验 → 审计日志 → 访问日志，全在 WSGI 中间件链上串行执行。

## STRUCTURE

```
gateway/
├── api_gateway/audit_middleware.py  # GatewayAuditMiddleware — 活跃的审计方案
├── channel/          # 渠道识别：web / mobile / api，依据 User-Agent + x-channel
├── auth/             # JWT / Token 认证中间件
├── tenant/           # 多租户隔离，从 JWT claims 提取 tenant_id 注入请求上下文
├── rate_limiter/     # 令牌桶限流 + 熔断器（模块存根，基础实现）
├── request_guard/    # 请求安全校验：SQL 注入探测 / 路径穿越拦截
└── access_log/       # 请求→响应日志，含耗时 / 状态码 / 客户端 IP
```

## KEY CONVENTIONS

- **GatewayAuditMiddleware 是唯一活跃审计**：`security/audit/service.py` 已废弃，不要再改它。所有审计走 gateway 中间件。
- **中间件注册顺序不可调换**：`create_app()` 中 `add_middleware()` 的调用顺序即执行顺序。GatewayAuditMiddleware 必须第一个注册，确保所有请求均被审计。
- **CORS 白名单**：`127.0.0.1:3000/5173`、`localhost:3000/5173`。新增域名必须同步更新 `origins` 列表，否则前端跨域报错。
- **无独立单元测试**：gateway 模块不设单独测试文件，全量验证通过集成 Flow 测试覆盖（`src/tests/integration/flow/`）。修改后运行全量 Flow 测试确认无回归。
- **channel / auth / tenant 模块当前为 __init__.py 存根**：仅包含模块级入口函数签名。扩展时保持中间件接口一致：`__call__(request, call_next)`。
- **rate_limiter 熔断器**：当前为简单计数式，后续对接 Redis 实现分布式限流时保持 `RateLimiter.check(key) → bool` 接口不变。

## ANTI-PATTERNS

- 不要在 gateway 中间件中引入业务逻辑（结算异常、DRG 分组等）。它是防线，不是业务编排层。
- 不要跳过 GatewayAuditMiddleware 直接调用 `security/audit/` 的旧审计接口——会产生双写和混乱。
- 不要在中间件内做 HTTP 调用（模型推理、外部 API 查询）。中间件应同步、轻量、无副作用。
- 不要修改 `request.state` 中由上游中间件写入的字段（如 `tenant_id`、`user_id`）。每个中间件只写自己负责的字段。
