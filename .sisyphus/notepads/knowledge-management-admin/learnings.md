# Learnings: Admin Knowledge Management Components

## Patterns Used
- Components follow same CRUD pattern as skill-management.tsx:
  - `'use client'` directive
  - Table within Card with CardHeader/CardContent
  - Dialog for create/edit with full form
  - Separate confirmation Dialog for delete
  - Error display as red alert box
  - Loading state as centered text
  - Empty state with guidance button

## Type Casting
- API functions return `Record<string, unknown>[]` from `requestJson`
- To cast to specific interfaces, use `as unknown as InterfaceName[]` (two-step cast needed since `Record<string, unknown>` doesn't overlap with specific types)

## UI Components Used
- `@/components/ui/badge` - Badge component from shadcn/ui style
- `@/components/ui/button` - Button with variants (default, outline, ghost, destructive) and sizes (sm, icon-sm)
- `@/components/ui/card` - Card, CardContent, CardHeader, CardTitle
- `@/components/ui/dialog` - Dialog, DialogContent, etc.
- `@/components/ui/input` - Input for text fields
- `@/components/ui/select` - Select from @base-ui/react
- `@/components/ui/textarea` - Textarea for multiline

## Role IDs for Multi-Select
Role IDs matching the codebase: cashier, medical_office, information_department, medical_record_staff, clinician

## Risk Levels
API uses uppercase: LOW, MEDIUM, HIGH (matching backend schema)

## Knowledge Asset Chunk Management
- Click row to expand inline chunk section
- Uses `GET /knowledge/assets/{asset_id}/chunks` for listing
- Uses `POST /knowledge/assets/{asset_id}/chunks` for creating
- Chunks render as cards with chunk_id, section badge, content preview

## Appeal & Prompt Template CRUD
- AppealTemplateCrud and PromptTemplateCrud follow same CRUD table + Dialog pattern
- **AppealTemplate fields**: template_id (PK), template_name, template_type (select), denial_reason_pattern, content (textarea), required_evidence (JSON editor textarea), applicable_scenarios (multi-select buttons)
- **PromptTemplate fields**: template_id (PK), template_name, template_type (select), scenario (select), role (select), system_prompt (textarea), user_prompt_template (textarea), variables (comma-separated tag input), output_format (JSON editor textarea)
- **Render Preview**: Eye icon button on each row opens render dialog; user fills variable values; POST /knowledge/prompt-templates/render returns rendered result
- **Select component** `onValueChange` callback signature is `(value: string | null, eventDetails) => void` — use `(v: string | null) => setState(v ?? '')` type annotation
- **Client-side filtering**: Always fetch all data, filter on client side with `filteredItems` — avoids stale closures from async state
- **shadcn Select has `string | null`** for value in `onValueChange`, not just `string`
