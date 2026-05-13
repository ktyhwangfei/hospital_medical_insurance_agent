# Learnings: Extract SettlementExceptionList + API Integration

## Patterns & Conventions
- Portal's api-client.ts already had `WorkflowListItem` and `WorkflowListResponse` types defined
- `WorkflowItem` is a type alias for `WorkflowListItem` (backward compat)
- Types are in `src/lib/types.ts`, API functions in `src/lib/api-client.ts`
- API functions follow the pattern: `try { return await requestJson<T>(path) } catch { handle error }`

## Decisions
- Reused existing `WorkflowListItem` type instead of creating a new one — added `steps`, `current_step`, and `[key: string]: unknown` for extensibility
- Added `ErrorCodeItem` interface for dashboard error code stats
- Settlements status filter uses `pending,processing` encoding per backend convention
- Mock data kept for types compatibility but components now fetch from API on mount

## Gotchas
- `WorkflowListItem` already existed without `steps` — discharge-qc's type assertion needed `steps` added
- Two `listWorkflows` existed after edit — had to deduplicate (keep the original, remove the new one)
- TypeScript compilation passed but Next.js build fails on pre-existing `useSearchParams()` in root `/` page
