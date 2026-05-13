# Decisions

## 2026-05-08
- Tool is NEW domain model, NOT extending McpCapability
- Skill is NEW domain model with steps list + execution strategy
- ToolOwner enum: CASHIER, MEDICAL_OFFICE, INFORMATION_DEPARTMENT, MEDICAL_RECORD_STAFF
- ExecutionStrategy: SEQUENTIAL, PARALLEL, CONDITIONAL
- Skill = single owner, cross-dept via multiple skills
- @-mention: regex `@([a-z0-9_]+(?:-[a-z0-9_]+)*)` pattern
- Storage: follow MCP dual-mode factory (PostgreSQL + in-memory)
- Backward compat: existing scenario routing preserved as fallback
