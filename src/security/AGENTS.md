# security — 安全围栏

## 概述

三层防线：授权鉴权 → 数据脱敏 → 高风险拦截。全链路审计覆盖。
详细安全约束（高风险拦截、脱敏、citation 要求、MCP 安全边界）见根目录 AGENTS.md 安全约束章节。

## 结构

- `authorization/service.py` — `visible_fields_for(role)` / `is_allowed(role, scenario)`。
  基于 role 的可见字段和场景权限校验。5 角色：CASHIER / MEDICAL_OFFICE / INFORMATION_DEPARTMENT / MEDICAL_RECORD_STAFF / CLINICIAN。编排层先调此模块，无权限直接拒绝。
- `desensitization/service.py` — `mask_name()`。PII 脱敏（患者姓名/身份证/手机号/地址/医保卡号/银行卡号）。AI 输出组装前必须调，原始敏感数据不准离开此层。
- `risk_control/service.py` — `detect_blocked_actions()` 检测高风险动作 + `build_human_confirmation_response()` 构建拦截响应。
  HIGH_RISK_ACTIONS 定义在 `config/security_policy/rules.py`。命中 → status=waiting_human_confirmation。
  DB 规则（risk_control_rules 表）优先，不可用时回退硬编码 HIGH_RISK_ACTIONS 兜底。
- `risk_control/storage/postgres.py` — `PostgresRiskControlStorage`。操作 risk_control_rules / risk_control_events 两张表。
- `risk_control/postgres_event_store.py` — ⚠️ DEPRECATED。被 storage/postgres.py 替代，禁止 import。
- `audit/service.py` — ⚠️ 部分 DEPRECATED。审计日志迁移至 `runtime/api/middleware.py` 的 `GatewayAuditMiddleware`（全自动记录请求/响应）。
  保留的 `record_audit_event()` 仅供 workflow 层回调使用。
- `audit/postgresql_store.py` — `PostgresAuditStore`。审计日志 PostgreSQL 持久化。记录每次 AI 交互的请求来源/操作/模型输出/风险结果。
- `audit/in_memory.py` — 内存审计存储。测试环境或 `USE_MEMORY_STORAGE=1` 时回退。

## 关键约定

- **高风险必须拦截**: HIGH_RISK_ACTIONS 包含退费/冲正/正式结算/病案修改/删除结算记录/修改费率等。严禁 AI 代执行。
- **脱敏是最后关口**: AI 输出组装完 → 调 desensitization → 再进响应体。
- **HIGH_RISK_ACTIONS 是 set**: `detect_blocked_actions` 返回顺序不固定。断言必须用 `set()` 比较。
- **鉴权链**: 请求 → 提取角色 → 校验 resource:action → 通过放行，否则返回权限拒绝。
- **存储多态**: 审计/风险存储遵循 ports/adapter 模式。PostgreSQL 为默认，`USE_MEMORY_STORAGE=1` 回退内存。
- **全链路审计**: 所有 AI 交互（请求来源/操作内容/模型输出/风险判断）均需落审计日志。GatewayAuditMiddleware 自动完成。

## 注意事项

- ❌ 业务代码自行判断"是否高风险" — 必须走 `risk_control/service.py`
- ❌ 断言 `HIGH_RISK_ACTIONS` 的元素顺序 — set 无稳定顺序
- ❌ import `postgres_event_store.py` — 标记 DEPRECATED
- ❌ 脱敏前将原始数据写入审计日志 — 先脱敏再落库
- ❌ 跳过 authorization 直接执行业务 — 编排层必须先过权限校验
- ❌ 使用旧的 `audit/service.py` 做请求级审计 — 已迁移到 GatewayAuditMiddleware
