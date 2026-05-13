# Admin Sidebar + Capabilities CRUD - Learnings

## Summary
Added collapsible sidebar navigation to Admin app (port 3001) and capabilities CRUD to MCP management page.

## Key Changes

### Files Created
- `src/apps/admin/src/components/admin-sidebar.tsx` — New collapsible sidebar component
  - NAV_SECTIONS data-driven with "业务应用" and "平台管理" sections
  - 232px expanded (w-58), 56px collapsed (w-14)
  - `transition-all duration-300`
  - Icons: Puzzle (skills), Cpu (MCP), BookOpen (knowledge), Bot (model)
  - Active route highlighting via `usePathname()`
  - Collapse toggle button at bottom

### Files Modified
- `src/apps/admin/src/app/layout.tsx` — Added AdminShell wrapper with sidebar + header
- `src/apps/admin/src/app/page.tsx` — Removed inline header/nav (moved to layout)
- `src/apps/admin/src/lib/types.ts` — Added `McpCapability` and `McpCapabilityCreate` interfaces
- `src/apps/admin/src/lib/api-client.ts` — Added `listCapabilities`, `createCapability`, `deleteCapability`
- `src/apps/admin/src/components/mcp-management.tsx` — Added capabilities CRUD section

## Patterns Used
- Portal layout.tsx sidebar pattern adapted for admin (same collapsible pattern, different sections)
- Dialog component from @base-ui/react for capability registration form
- Select for server filter dropdown
- IIFE pattern for conditional table rendering inside JSX

## Issues Encountered
- File corruption from multiple write operations — had to rewrite entire sections
- Dialog component uses `render` prop (base-ui pattern) not `asChild` (Radix pattern)
- CardTitle is a self-closing `<div>` component that accepts children via `{...props}` spread
