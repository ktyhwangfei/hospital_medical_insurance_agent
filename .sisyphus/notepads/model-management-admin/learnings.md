# ModelManagement Component - Learnings

## Project Patterns
- Admin app uses `@/components/ui/*` (shadcn/ui with @base-ui/react)
- Components follow pattern: imports, constants, interfaces, helpers, then component(s)
- Dialog pattern: `Dialog` > `DialogContent` > `DialogHeader` + fields + `DialogFooter`
- Tabs use `@base-ui/react/tabs`: `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent`
- Select uses guarded `onValueChange`: `onValueChange={(v) => { if (v) setState(v) }}`
- API functions return typed Promises via `requestJson<T>()` (no try/catch in simple getters)
- `ListResponse<T>` pattern: `{ items: T[], total: number }`

## Key Decisions
- ModelConfigPanel: Load config on mount, simple form with 4 fields, saves via PUT
- ModelRouteCrud: CRUD table + Dialog with route fields + fallback chain editing + JSON params
- ProviderCrud: CRUD table + Dialog + per-row connectivity test + delete confirmation
- ModelTest tab keeps full existing functionality by importing ModelTest component
- No toast library used - inline success/error notifications match existing patterns
- `ModelConfig` type needed optional `fallback?: boolean` field like other API responses
