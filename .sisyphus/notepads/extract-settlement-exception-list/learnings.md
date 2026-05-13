# Learnings: Extract SettlementExceptionList

## Findings

1. **Component already existed** - `settlement-exception-list.tsx` was already created in a previous session with proper loading/error/empty states and real API integration via `listWorkflows()`.

2. **Pre-existing dependencies**:
   - `types.ts` had `WorkflowItem` and `WorkflowListItem` types available
   - `api-client.ts` already had `listWorkflows()` function with proper error handling
   - `fetchErrorCodes()` was already defined (though imported by dashboard.tsx)

3. **Build fixes needed**:
   - `app/page.tsx` needed `Suspense` boundary for `useSearchParams()` - Next.js 16 enforces this for client components that use search params during static generation

4. **Key patterns used**:
   - `SettlementItemRow` component handles priority indicator, patient info, status badge, and "查看处理步骤" button
   - Navigation to chat uses `router.push('/?prefill=...')` 
   - Three states: Loading (skeleton), Error (with retry), Empty (with guidance message)

5. **Component to page integration**: 
   - `app/settlement/page.tsx` now delegates entirely to `<SettlementExceptionList currentRole={currentRole} />`
   - `app/page.tsx` reads `prefill` from search params and passes to `<SettlementChat>`
