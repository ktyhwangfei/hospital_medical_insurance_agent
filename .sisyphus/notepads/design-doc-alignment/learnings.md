# Design-Doc Alignment Plan - Learnings

## Initial Context (2026-05-12)

### Backend API Status
- 51 endpoints implemented, 17 missing
- Knowledge routes (28 endpoints): All 28 CRUD endpoints confirmed existing and registered
- Model routes (17 endpoints): ModelConfig, ModelRoutes, Fallbacks, Params, Providers
- Schema models: ErrorCodeCreate/Update, RuleCreate/Update, AssetCreate/Update, ChunkCreate, AppealTemplateCreate/Update, PromptTemplateCreate/Update/RenderRequest all defined in schemas.py
- Router registration: `knowledge_router` imported and registered in `app.py` with prefix

### Frontend Status
- Admin app: KnowledgeManagement (missing), ModelManagement (partial), McpManagement (partial)
- Portal app: SettlementChat (complete), other components need API integration
- Embed app: complete for its purpose

### model_routes.py Implementation (2026-05-12)
- Created 17 endpoints: Group A (2 model-config), Group B (9 model-routes), Group C (6 model-providers)
- **Route ordering critical**: `/fallbacks/{name}` and `/params/{name}` MUST be before `/{route_id}` to avoid FastAPI path conflicts
- In-memory dict stores: `_routes_store`, `_fallback_chains`, `_model_params_store`, `_providers_store`
- API key safety: separate `_model_api_key` var, `_mask_api_key()` masks to `prefix****suffix`
- Connectivity test uses `urllib.request` (stdlib) — no extra dependencies
- Lists return `{"items": [...], "total": N}` format
- Registered in app.py as `app.include_router(model_router, prefix='/api/v1/medical-insurance-ai-agent')`

### Key Conventions
- Python: FastAPI routers with prefix `/api/v1/medical-insurance-ai-agent`
- Frontend: Next.js 16 + React 19 + shadcn/ui (base-nova) + Tailwind CSS v4
- Admin UI: Uses Dialog for create/edit, Select for choices, Tabs for sub-navigation
- API prefix import from AGENTS.md

### KnowledgeManagement Implementation (2026-05-12)
- Created `knowledge-management.tsx` with 5-tab layout (错误码管理, 规则解释, 知识资产, 申诉模板, 提示词模板)
- ErrorCodeCrud sub-component: full CRUD with search, create/edit Dialog, delete confirmation Dialog
- Followed skill-management.tsx CRUD pattern (Card header with action buttons, table, Dialog forms)
- No Skeleton UI component available, used inline `animate-pulse` divs instead
- `Button variant="destructive"` is supported for delete confirmation
- `RequestJson` returns `Promise<T>` — void functions use `Promise<void>` with DELETE method
- api-client.ts import needs both `ErrorCode` and `ErrorCodeCreate` types
- The knowledge page uses `useState<RoleId>('cashier')` pattern (same as skills page)
- `knowledge-explorer.tsx` (old mock-data component) kept for reference — not deleted
