# Design-Doc Alignment Plan - Issues

## Pending Issues

1. **Knowledge routes backend stores**: Need to verify all store implementations have the required CRUD methods matching API design doc specs
2. **Model routes**: ModelRouter API surface needs verification - may need wrapper methods for fallback chains and params
3. **Admin page.tsx**: Current admin home page has inline top nav - may need refactoring to support sidebar
4. **SettlementExceptionList**: Current inline implementation uses mock data and hardcoded CSS - extraction needs to preserve visual style

### 2026-05-12: Knowledge Routes Implementation (28 endpoints)

1. **28 endpoints across 5 groups**: Error Codes (5), Rules (5), Assets (7), Appeal Templates (5), Prompt Templates (6).

2. **Store limitations**: Some stores lack full CRUD (e.g., `PostgresAppealTemplateStore` only has `list_templates`). Used direct `PostgreSQLClient` with raw SQL for missing operations (create/update/delete on appeal/prompt templates, delete on rules, get_asset, delete_asset cascade).

3. **Routing approach**: Uses `APIRouter()` without prefix (same as `skill_routes.py`), registered in `app.py` with `prefix='/api/v1/medical-insurance-ai-agent'`.

4. **Schema models**: Added 13 new Pydantic models to `schemas.py` for request validation (ErrorCodeCreate/Update, RuleCreate/Update, AssetCreate/Update, ChunkCreate, AppealTemplateCreate/Update, PromptTemplateCreate/Update, PromptTemplateRenderRequest).

5. **In-memory filtering**: Error codes filter by `error_code`/`description` in-memory since store doesn't support SQL-level filtering. Assets filter by `status` in-memory. Appeal templates filter by `type` in-memory.

6. **Cascade delete**: Asset DELETE manually deletes from both `knowledge_chunks` and `knowledge_assets` tables (DB-level FK enforcement not available).

## Resolved Issues

### 2026-05-12: Model Routes Implementation (17 endpoints)

1. **Path prefix strategy**: `model_routes.py` uses `APIRouter(prefix="/api/v1/medical-insurance-ai-agent")` with relative paths. Registered without additional prefix in `app.py` (same pattern as `mcp_router`).

2. **Route ordering**: Static sub-paths (`/model-routes/fallbacks/{name}`, `/model-routes/params/{name}`) defined BEFORE `/{route_id}` to avoid FastAPI path conflicts.

3. **In-memory backend**: `ModelRouter` is read-only, `ModelServiceConfig` uses pydantic-settings. All mutable state uses in-memory dicts initialized from config files.

4. **API key masking**: Provider responses mask api_key (first 4 + last 4 chars).

5. **Provider test**: Uses `OpenAICompatibleProvider` with minimal test request.

6. **Pre-existing test failures** (unrelated): `test_mcp_discovery.py` (broken import), `test_intent_routing` (McpRiskLevel enum mismatch in seed data).
